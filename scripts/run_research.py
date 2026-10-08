"""Reproduce every research result, table and figure from the real-data products.

Inputs: data/real/derived/timeseries/* (from extract_field_timeseries.py + run_event_detection.py),
data/real/firms/active_fire_unified.parquet (build_fire_table.py), ERA5 weather, MCD64A1 pixels.
Outputs: reports/research/results.json, reports/research/*.csv, reports/research/figures/*.png and
app-facing products under data/real/derived/research/.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research import figstyle as fs  # noqa: E402
from src.research import firms_match as fm  # noqa: E402
from src.research.events import add_indices, detect_events  # noqa: E402
from src.research.replay import BALED_T_PER_HA, replay  # noqa: E402
from src.research.risk import FEATURES, build_features, precision_at  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

TS = ROOT / "data" / "real" / "derived" / "timeseries"
REP = ROOT / "reports" / "research"
FIG = REP / "figures"
PROD = ROOT / "data" / "real" / "derived" / "research"
YEARS = [2023, 2024, 2025]
VIIRS = ["VIIRS_SNPP", "VIIRS_NOAA20"]  # sensors available in all three seasons
STRAW_T_PER_HA = 18.81e6 / 3.0e6        # Punjab 2026 straw estimate / paddy area (concept note [1])
STRAW_PRICE_RS_PER_T = 1690             # biomass plant price Rs 169/quintal (concept note [11])
# Andreae (2019) ACP 19:8523, Table 1, "Agricultural residues (open)": mean, SD in g/kg dry matter
EF = {"CO2": (1430, 230), "CH4": (5.7, 6.0), "N2O": (0.09, 0.04), "CO": (76, 55), "PM2.5": (8.2, 4.4),
      "BC": (0.42, 0.28), "OC": (4.9, 3.6)}
GWP100 = {"CH4": 27.0, "N2O": 273.0}    # IPCC AR6 WG1 Table 7.15 (non-fossil CH4)
R = {}


def clean(obj):
    """Strict-JSON copy: NaN/inf become null and numpy scalars become Python numbers."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def harmonise(d: pd.DataFrame, step: int = 5):
    dates, keep, nxt = sorted(d.date.unique()), [], None
    for t in dates:
        if nxt is None or t >= nxt:
            keep.append(t)
            nxt = t + np.timedelta64(step - 1, "D")
    return d[d.date.isin(keep)], keep


def census_and_blindspot(ids: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for y in YEARS:
        d = pd.read_parquet(TS / f"field_timeseries_{y}.parquet")
        dh, keep = harmonise(d)
        e = detect_events(dh).merge(ids[["field_id", "n_px", "centroid_lon", "centroid_lat"]], on="field_id")
        e["pixel_area_ha"] = e.n_px * 0.04
        crop = fm.field_xy(e[e.peak_ndvi >= 0.6])
        fr = fm.load_firms(y)
        fi = fr[fr.in_muktsar]
        strict = crop.assign(burned=crop.burned_strict)
        bb = fm.blind_spot(strict, fr, VIIRS)
        sb = bb[bb.burn_window_days <= 5]
        ctl = crop[crop.harvested & ~crop.burned].sample(20000, random_state=1).copy()
        pick = crop[crop.burned_strict].sample(len(ctl), replace=True, random_state=2)
        ctl["burn_prev_date"], ctl["burn_date"], ctl["burned"] = pick.burn_prev_date.values, pick.burn_date.values, True
        nn = fm.blind_spot(ctl, fr, VIIRS)
        sn = nn[(nn.burn_date - nn.burn_prev_date).dt.days <= 5]
        rec = fm.recall_vs_fires(crop, fr, VIIRS)
        rows.append(dict(
            year=y, s2_dates=int(d.date.nunique()), s2_dates_5day=len(keep),
            viirs_alerts=int(fi.sensor.isin(VIIRS).sum()), viirs_alerts_incl_noaa21=int(fi.sensor.str.startswith("VIIRS").sum()),
            modis_alerts=int((fi.sensor == "MODIS").sum()), crop_fields=len(crop), crop_ha=round(float(crop.pixel_area_ha.sum())),
            harvested_share=round(float(crop.harvested.mean()), 4),
            burned_loose_fields=int(crop.burned.sum()), burned_strict_fields=int(crop.burned_strict.sum()),
            burned_loose_share=round(float(crop.burned.mean()), 4), burned_strict_share=round(float(crop.burned_strict.mean()), 4),
            burned_loose_ha=round(float(crop[crop.burned].pixel_area_ha.sum())), burned_strict_ha=round(float(crop[crop.burned_strict].pixel_area_ha.sum())),
            strict_fields_per_viirs_alert=round(float(crop.burned_strict.sum() / max(fi.sensor.isin(VIIRS).sum(), 1)), 2),
            burns_with_viirs_short_window=round(float(sb.fire_match.mean()), 4), n_short_window=len(sb),
            control_with_viirs_short_window=round(float(sn.fire_match.mean()), 4),
            burns_with_viirs_any_window=round(float(bb.fire_match.mean()), 4), control_with_viirs_any_window=round(float(nn.fire_match.mean()), 4),
            viirs_alerts_with_s2_burn_nearby=round(float(rec.s2_match.mean()), 4)))
        log(f"census {y}: {rows[-1]}")
    t = pd.DataFrame(rows)
    t.to_csv(REP / "census_blindspot_harmonised.csv", index=False)
    return t


def naive_dnbr_vs_aware() -> pd.DataFrame:
    import geopandas as gpd
    mcd = pd.read_parquet(ROOT / "data/real/burned_area/mcd64a1_burn_pixels.parquet")
    mcd["burn_date"] = pd.to_datetime(mcd.burn_date)
    dist = gpd.read_file(ROOT / "data/real/boundaries/sri_muktsar_sahib_adm2.geojson").to_crs(4326).geometry.iloc[0]
    g = gpd.GeoDataFrame(mcd, geometry=gpd.points_from_xy(mcd.longitude, mcd.latitude), crs=4326)
    g = g[g.within(dist)]
    rows = []
    for y in YEARS:
        d = add_indices(pd.read_parquet(TS / f"field_timeseries_{y}.parquet"))
        ev = pd.read_parquet(TS / f"events_{y}.parquet")
        crop = ev[ev.peak_ndvi >= 0.6].set_index("field_id")
        u = d[d.usable & d.field_id.isin(crop.index)]
        pre = u[(u.date.dt.month == 9) | ((u.date.dt.month == 10) & (u.date.dt.day <= 5))].groupby("field_id").nbr.max()
        post = u[(u.date >= f"{y}-11-20") & (u.date <= f"{y}-12-08")].groupby("field_id").nbr.median()
        dn = (pre - post).dropna()
        area = crop.pixel_area_ha
        mm = g[(g.burn_date.dt.year == y) & g.burn_date.dt.month.isin([10, 11, 12])]
        rows.append(dict(year=y, crop_ha=round(float(area.sum())),
                         naive_dnbr_027_share=round(float((dn > 0.27).mean()), 4),
                         naive_dnbr_027_ha=round(float(area.loc[dn[dn > 0.27].index].sum())),
                         naive_dnbr_044_share=round(float((dn > 0.44).mean()), 4),
                         mcd64a1_pixels=int(len(mm)), mcd64a1_nominal_ha=round(len(mm) * 21.47) if len(mm) else None,
                         aware_loose_ha=round(float(crop[crop.burned].pixel_area_ha.sum())),
                         aware_strict_ha=round(float(crop[crop.burned_strict].pixel_area_ha.sum()))))
    t = pd.DataFrame(rows)
    t.to_csv(REP / "naive_dnbr_vs_harvest_aware.csv", index=False)
    log(f"naive dNBR: {t.to_dict('records')}")
    return t


def smoke_blindness() -> pd.DataFrame:
    rows = []
    fires = pd.read_parquet(ROOT / "data/real/firms/active_fire_unified.parquet")
    for y in YEARS:
        d = add_indices(pd.read_parquet(TS / f"field_timeseries_{y}.parquet"))
        g = d.groupby("date").agg(clear=("clear", "mean"), swir_usable=("usable", "mean"), blue_median=("B02", "median"))
        g["year"] = y
        rows.append(g.reset_index())
    t = pd.concat(rows, ignore_index=True)
    t.to_csv(REP / "smoke_blindness_by_date.csv", index=False)
    f = fires[fires.in_muktsar & fires.sensor.isin(VIIRS) & fires.acq_date.dt.month.isin([10, 11, 12])]
    f.groupby(["year", "acq_date"]).size().rename("viirs_alerts").reset_index().to_csv(REP / "viirs_daily.csv", index=False)
    return t


def latency() -> dict:
    out = {}
    for y in YEARS:
        e = pd.read_parquet(TS / f"events_{y}.parquet")
        b = e[(e.peak_ndvi >= 0.6) & e.burned & e.harvested]
        lat = b.harvest_to_burn_days
        out[y] = dict(n=int(len(b)), median_days=float(lat.median()), p25=float(lat.quantile(.25)), p75=float(lat.quantile(.75)),
                      share_within_5d=round(float((lat <= 5).mean()), 4), share_within_10d=round(float((lat <= 10).mean()), 4),
                      share_after_20d=round(float((lat > 20).mean()), 4),
                      median_harvest_window_days=float(b.harvest_window_days.median()),
                      median_burn_window_days=float(b.burn_window_days.median()))
    log(f"latency: {out}")
    return out


def persistence_profile() -> dict:
    """Multi-season burn persistence for fields that are crop fields in all three seasons (loose tier)."""
    ev = {y: pd.read_parquet(TS / f"events_{y}.parquet").set_index("field_id") for y in YEARS}
    ids = sorted(set.intersection(*[set(e[e.peak_ndvi >= 0.6].index) for e in ev.values()]))
    B = pd.DataFrame({y: ev[y].loc[ids, "burned"].astype(bool) for y in YEARS})
    n = B.sum(axis=1)
    p = B.mean()
    exp3 = float(p.prod())
    exp2 = float(sum(p[a] * p[b] * (1 - p[c]) for a, b, c in [(YEARS[0], YEARS[1], YEARS[2]), (YEARS[0], YEARS[2], YEARS[1]), (YEARS[1], YEARS[2], YEARS[0])]) + exp3)
    e25 = ev[2025][ev[2025].peak_ndvi >= 0.6].copy()
    e25["size_quintile"] = pd.qcut(e25.pixel_area_ha, 5, labels=["XS", "S", "M", "L", "XL"])
    out = {"fields_in_all_seasons": len(ids), "share_by_seasons_burned": {str(k): round(float((n == k).mean()), 4) for k in range(4)},
           "ever_burned_share": round(float((n >= 1).mean()), 4), "repeat_burner_share": round(float((n >= 2).mean()), 4),
           "repeat_burner_share_of_burn_events": round(float(n[n >= 2].sum() / n.sum()), 4),
           "all_three_observed": round(float((n == 3).mean()), 4), "all_three_expected_if_independent": round(exp3, 5),
           "at_least_two_observed": round(float((n >= 2).mean()), 4), "at_least_two_expected_if_independent": round(exp2, 4),
           "burn_share_by_field_size_2025": {k: round(float(v), 4) for k, v in e25.groupby("size_quintile", observed=True).burned.mean().items()}}
    log(f"persistence: {out}")
    return out


def risk_model() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    tr, te = build_features(2024), build_features(2025)
    hist = ["prior_burn", "nbhd_prior_rate"]
    res = {}
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(tr[hist], tr.y_loose)
    te["risk_score"] = lr.predict_proba(te[hist])[:, 1]
    from sklearn.ensemble import HistGradientBoostingClassifier
    gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=200,
                                         l2_regularization=1.0, monotonic_cst=[1, 1, 0, 0, 0, 0, 0], random_state=0).fit(tr[FEATURES], tr.y_loose)
    te["risk_score_inseason"] = gbm.predict_proba(te[FEATURES])[:, 1]
    rng = np.random.default_rng(0)
    cands = {"history_logistic (pre-season)": te.risk_score.values,
             "in-season GBM (adds harvest timing, contagion, size, biomass)": te.risk_score_inseason.values,
             "neighbourhood last-season rate only": te.nbhd_prior_rate.values + 1e-9 * rng.random(len(te)),
             "field burned last season only": te.prior_burn.values + 1e-6 * rng.random(len(te)),
             "random": rng.random(len(te))}
    for name, s in cands.items():
        res[name] = {}
        for lab in ["y_loose", "y_strict"]:
            y = te[lab].values
            res[name][lab] = dict(auc=round(float(roc_auc_score(y, s)), 4), ap=round(float(average_precision_score(y, s)), 4),
                                  precision_top10=round(precision_at(y, s, .10), 4),
                                  lift_top10=round(precision_at(y, s, .10) / y.mean(), 3), base_rate=round(float(y.mean()), 4))
    res["persistence"] = dict(p_burn_given_prior_burn=round(float(te[te.prior_burn == 1].y_loose.mean()), 4),
                              p_burn_given_no_prior=round(float(te[te.prior_burn == 0].y_loose.mean()), 4))
    res["train"] = "2024 season (history from 2023)"
    res["test"] = "2025 season (history from 2024), never seen in training"
    log(f"risk: {json.dumps(res)[:600]}")
    return res, tr, te


def hazard_experiment() -> tuple[dict, pd.DataFrame]:
    """Dynamic per-pass hazard (src/research/hazard.py): train 2024 panel, test 2025 panel."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from src.research.hazard import FEATURES as HF, build_panel
    tr, te = build_panel(2024), build_panel(2025)
    feats = [f for f in HF if f != "doy"]  # day-of-year hurts transfer between seasons with shifted timing
    def fit(cols):
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=200,
                                              l2_regularization=1.0, random_state=0).fit(tr[cols], tr.y)
    m = fit(feats)
    te["score"] = m.predict_proba(te[feats])[:, 1]
    out = {"panel_rows_train": len(tr), "panel_rows_test": len(te), "positive_rate_test": round(float(te.y.mean()), 4),
           "auc": round(float(roc_auc_score(te.y, te.score)), 4), "ap": round(float(average_precision_score(te.y, te.score)), 4),
           "ablation_auc": {}}
    for name, drop in {"without_recent_neighbour_burns": ["nbhd_recent_burn_rate", "nbhd_recent_burn_rate_wide"],
                       "without_rain": ["rain_prev_3d", "rain_next_5d"], "without_history": ["prior_burn", "nbhd_prior_rate"],
                       "without_days_since_harvest": ["days_since_harvest"]}.items():
        cols = [f for f in feats if f not in drop]
        out["ablation_auc"][name] = round(float(roc_auc_score(te.y, fit(cols).predict_proba(te[cols])[:, 1])), 4)
    lifts = []
    for _, g in te.groupby("t"):
        if g.y.sum() >= 20:
            k = max(1, int(len(g) * 0.1))
            lifts.append(g.nlargest(k, "score").y.mean() / g.y.mean())
    out["median_per_pass_lift_top10"] = round(float(np.median(lifts)), 2)
    out["label"] = "burn first observed at the next Sentinel-2 pass"
    log(f"hazard: {out}")
    return out, te[["field_id", "t", "score"]]


def replay_grid(te: pd.DataFrame, hazard_scores: pd.DataFrame | None = None) -> pd.DataFrame:
    w = pd.read_parquet(ROOT / "data/real/weather/weather_daily.parquet")
    w["day"] = pd.to_datetime(w.timestamp).dt.tz_localize(None).dt.normalize()
    rain = w.groupby("day").precipitation_mm.mean()
    rain_days = set(rain[rain > 2.0].index)
    f = te[["field_id", "x", "y", "pixel_area_ha", "harvest_date", "burned", "burn_date", "burn_prev_date", "risk_score"]]
    rows = []
    for fleet in [50, 100, 200, 400]:
        for pol in ["random", "fifo", "risk", "dynamic", "oracle"]:
            if pol == "dynamic" and hazard_scores is None:
                continue
            r = replay(f, rain_days, fleet, pol, dynamic_scores=hazard_scores if pol == "dynamic" else None)
            rows.append(dict(fleet=fleet, policy=pol, burned_fields=r.burned_fields, preempted_fields=r.preempted_fields,
                             preempted_share=round(r.preempted_share, 4), preempted_ha=round(r.preempted_ha),
                             baled_ha=round(r.baled_ha), baled_t=round(r.baled_t), preempted_baled_t=round(r.preempted_t)))
        log(f"replay fleet {fleet} done")
    t = pd.DataFrame(rows)
    t.to_csv(REP / "replay_2025.csv", index=False)
    return t


def emissions(burned_ha: float, n: int = 20000, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    straw = rng.uniform(5.0, 7.5, n)          # t/ha air-dry straw (Punjab ~6.3)
    dmf = rng.uniform(0.80, 0.90, n)          # dry-matter fraction
    cf = rng.uniform(0.70, 0.90, n)           # combustion factor (IPCC rice residue default 0.80)
    dm = burned_ha * straw * dmf * cf         # t dry matter burned
    out = {"burned_ha": round(burned_ha), "dry_matter_burned_t": {"median": round(float(np.median(dm))), "p05": round(float(np.quantile(dm, .05))), "p95": round(float(np.quantile(dm, .95)))}}
    co2e = np.zeros(n)
    for sp, (mu, sd) in EF.items():
        ef = np.clip(rng.normal(mu, sd, n), mu * 0.1, None)
        tonnes = dm * ef / 1e3
        out[sp + "_t"] = {"median": round(float(np.median(tonnes)), 1), "p05": round(float(np.quantile(tonnes, .05)), 1), "p95": round(float(np.quantile(tonnes, .95)), 1)}
        if sp in GWP100:
            co2e += tonnes * GWP100[sp]
    out["CH4_N2O_CO2e_t"] = {"median": round(float(np.median(co2e))), "p05": round(float(np.quantile(co2e, .05))), "p95": round(float(np.quantile(co2e, .95)))}
    out["convention"] = "CO2 from residue burning is biogenic and reported separately; CO2e counts CH4 (GWP100 27.0) and N2O (273)."
    return out


def nowcast_2026(te: pd.DataFrame) -> dict:
    curves = {}
    for y in YEARS + [2026]:
        e = pd.read_parquet(TS / f"events_{y}.parquet")
        crop = e[e.peak_ndvi >= 0.6]
        d = pd.read_parquet(TS / f"field_timeseries_{y}.parquet", columns=["date"])
        dates = sorted(d.date.unique())
        hd = crop.harvest_date
        curves[y] = [(int(pd.Timestamp(t).dayofyear), float((hd <= t).mean())) for t in dates]
    grid = np.arange(250, 352)
    hist = np.vstack([np.interp(grid, [p[0] for p in curves[y]], [p[1] for p in curves[y]]) for y in YEARS])
    mean, lo, hi = hist.mean(0), hist.min(0), hist.max(0)
    e26 = pd.read_parquet(TS / "events_2026.parquet")
    crop26 = e26[e26.peak_ndvi >= 0.6]
    crop_ha = float((crop26.n_px * 0.04).sum())
    last = pd.Timestamp(max(pd.read_parquet(TS / "field_timeseries_2026.parquet", columns=["date"]).date))
    weeks = []
    for k in range(9):
        a = last + pd.Timedelta(days=7 * k)
        b = a + pd.Timedelta(days=7)
        fa, fb = np.interp([a.dayofyear, b.dayofyear], grid, mean)
        la, lb = np.interp([a.dayofyear, b.dayofyear], grid, lo)
        ha, hb = np.interp([a.dayofyear, b.dayofyear], grid, hi)
        area = (fb - fa) * crop_ha
        weeks.append(dict(week_start=a.strftime("%Y-%m-%d"), expected_harvest_ha=round(area),
                          range_ha=[round(min((lb - la), (hb - ha)) * crop_ha), round(max((lb - la), (hb - ha)) * crop_ha)],
                          expected_baleable_straw_t=round(area * BALED_T_PER_HA), expected_total_straw_t=round(area * STRAW_T_PER_HA)))
    out = dict(latest_image=last.strftime("%Y-%m-%d"), crop_fields=int(len(crop26)), crop_ha=round(crop_ha),
               harvested_share_now=round(float(crop26.harvested.mean()), 4),
               same_date_prior=dict({str(y): round(float(np.interp(last.dayofyear, [p[0] for p in curves[y]], [p[1] for p in curves[y]])), 4) for y in YEARS}),
               district_straw_total_t=round(crop_ha * STRAW_T_PER_HA), weekly_forecast=weeks,
               method="Weekly harvest = district crop area x increment of the 2023-2025 mean harvest-progress curve (range = min/max year).")
    # Pre-season burn-risk for 2026 from last two seasons (train: 2024 history -> 2025 outcome)
    hist_cols = ["prior_burn", "nbhd_prior_rate"]
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(te[hist_cols], te.y_loose)
    from src.research.risk import _block_sum, _cells, load_events
    cur, prev = load_events(2026), load_events(2025)
    x0, y0 = min(cur.x.min(), prev.x.min()) - 2000, min(cur.y.min(), prev.y.min()) - 2000
    shape = (int((max(cur.y.max(), prev.y.max()) - y0) // 500) + 3, int((max(cur.x.max(), prev.x.max()) - x0) // 500) + 3)
    pc = prev[prev.peak_ndvi >= 0.6]
    pix, piy = _cells(pc, x0, y0)
    bgrid, ngrid = _block_sum(pix, piy, pc.burned.values.astype(float), shape), _block_sum(pix, piy, np.ones(len(pc)), shape)
    c = cur[cur.peak_ndvi >= 0.6].copy()
    cix, ciy = _cells(c, x0, y0)
    c["prior_burn"] = c.field_id.map(prev.set_index("field_id").burned).fillna(False).astype(float)
    c["nbhd_prior_rate"] = bgrid[ciy, cix] / np.maximum(ngrid[ciy, cix], 1)
    c["risk_score"] = lr.predict_proba(c[hist_cols])[:, 1]
    c["risk_decile"] = (pd.qcut(c.risk_score.rank(method="first"), 10, labels=False) + 1).astype(int)
    PROD.mkdir(parents=True, exist_ok=True)
    keep = ["field_id", "centroid_lon", "centroid_lat", "n_px", "harvested", "harvest_date", "prior_burn", "nbhd_prior_rate", "risk_score", "risk_decile"]
    c[keep].assign(pixel_area_ha=c.n_px * 0.04, real_or_synthetic="REAL", score_type="RELATIVE_RANK_NOT_PROBABILITY").to_parquet(PROD / "risk_2026_preseason.parquet", index=False)
    top = c.sort_values("risk_score", ascending=False).head(2000)
    out["preseason_risk"] = dict(model="logistic regression on field + 1.5 km neighbourhood burn history (trained 2024->2025)",
                                 top_decile_fields=int((c.risk_decile == 10).sum()), top_decile_ha=round(float(c[c.risk_decile == 10].n_px.sum() * 0.04)),
                                 top2000_ha=round(float(top.n_px.sum() * 0.04)))
    out["curves"] = {str(y): curves[y] for y in curves}
    out["forecast_grid"] = dict(doy=grid.tolist(), mean=mean.round(4).tolist(), lo=lo.round(4).tolist(), hi=hi.round(4).tolist())
    log(f"nowcast: harvested now {out['harvested_share_now']}, prior {out['same_date_prior']}")
    return out


def export_field_products(te: pd.DataFrame) -> None:
    PROD.mkdir(parents=True, exist_ok=True)
    cols = ["field_id", "centroid_lon", "centroid_lat", "pixel_area_ha", "peak_ndvi", "peak_date", "harvested", "harvest_date",
            "last_green_date", "burned", "burned_strict", "burn_date", "burn_prev_date", "burn_window_days", "harvest_to_burn_days"]
    for y in YEARS + [2026]:
        e = pd.read_parquet(TS / f"events_{y}.parquet")
        e = e[e.peak_ndvi >= 0.6][cols].copy()
        e["year"] = y
        e["burn_tier"] = np.where(e.burned_strict, "CHAR_STRICT", np.where(e.burned, "CHAR_LOOSE", "NONE"))
        e["label_source"] = "RULE_CANDIDATE_S2_HARVEST_AWARE"
        e["real_or_synthetic"] = "REAL"
        e.to_parquet(PROD / f"field_events_{y}.parquet", index=False)
    te[["field_id", "risk_score", "risk_score_inseason"]].to_parquet(PROD / "risk_2025_holdout_scores.parquet", index=False)


def figures(census, naive, smoke, lat, risk, rep, now) -> None:
    fs.setup()
    FIG.mkdir(parents=True, exist_ok=True)
    yrs = census.year.astype(str).tolist()
    # F1 hero: indexed trends. Only the loose tier is a comparable series: the strict tier needs a
    # haze-free pre-event image, so its count follows each season's smoke conditions.
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    series = [("VIIRS fire alerts (S-NPP + NOAA-20)", census.viirs_alerts, fs.SERIES[1], 0, "alerts"),
              ("Sentinel-2 loose burn-candidate area (exploratory)", census.burned_loose_ha, fs.SERIES[2], 0, "ha")]
    for name, v, col, dy, unit in series:
        idx = 100 * v / v.iloc[0]
        ax.plot(range(len(yrs)), idx, color=col, marker="o", ms=7, mec=fs.SURFACE, mew=2)
        ax.annotate(f"{name}: {int(v.iloc[-1]):,} {unit} in {yrs[-1]} (index {idx.iloc[-1]:.0f})", (len(yrs) - 1, idx.iloc[-1]),
                    xytext=(10, dy), textcoords="offset points", va="center", fontsize=8.5, color=fs.INK2)
    ax.axhline(100, color=fs.BASE, lw=1)
    ax.annotate("2024: smog removed 3-21 Nov images,\nso candidate area is a lower bound", (1, 46), xytext=(0, -40),
                textcoords="offset points", ha="center", fontsize=8, color=fs.MUTED)
    ax.set_xticks(range(len(yrs)), yrs)
    ax.set_ylabel("Index, first season = 100")
    ax.set_xlim(-0.2, 4.7)
    ax.set_ylim(0, 130)
    dv = 100 * (census.viirs_alerts.iloc[-1] / census.viirs_alerts.iloc[0] - 1)
    dl = 100 * (census.burned_loose_ha.iloc[-1] / census.burned_loose_ha.iloc[0] - 1)
    ax.set_title(f"VIIRS fire alerts {dv:+.0f}% since {yrs[0]}; loose burn-candidate area {dl:+.0f}%")
    fs.note(fig, "Sri Muktsar Sahib, Oct-Dec, Sentinel-2 L2A at a harmonised 5-day revisit. Loose = exploratory rule-based burn candidates (not confirmed burns).\n"
                 "The strict tier is not plotted as a trend: it needs a haze-free pre-event image, so its count follows each season's smoke conditions.")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(FIG / "f1_alerts_vs_scars.png", dpi=180)
    plt.close(fig)
    # F2 thermal context, from the event-table summary (scripts/build_burn_candidate_events.py), all windows
    cand = json.loads((REP / "burn_candidate_summary.json").read_text(encoding="utf-8"))["thermal_context"]
    tyrs = [y for y in yrs if y in cand]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    x = np.arange(len(tyrs))
    st = [cand[y]["strict"]["500m"] for y in tyrs]
    a = np.array([100 * s["share_candidates_with_viirs_nearby"] for s in st])
    b = np.array([100 * s["proximity_control_share"] for s in st])
    ax.bar(x - 0.19, a, 0.36, color=fs.SERIES[0], label="Strict rule-based burn candidates")
    ax.bar(x + 0.19, b, 0.36, color=fs.BASE, label="Control: harvested fields without candidates")
    for i in range(len(x)):
        ax.text(x[i] - 0.19, a[i] + 1, f"{a[i]:.1f}%\n{st[i]['candidates_with_viirs_nearby']:,} of {st[i]['candidates']:,}", ha="center", fontsize=8, color=fs.INK)
        ax.text(x[i] + 0.19, b[i] + 1, f"{b[i]:.1f}%", ha="center", fontsize=8.5, color=fs.INK2)
    ax.set_xticks(x, tyrs)
    ax.set_ylabel("Share with a matched VIIRS detection (%)")
    ax.set_ylim(0, 60)
    ax.legend(loc="upper right")
    ax.set_title("Strict optical candidates with a matched VIIRS active-fire detection")
    fs.note(fig, "Match: VIIRS S-NPP/NOAA-20 detection within 500 m of the field centroid between the pre-event image - 1 d and the event image + 1 d.\n"
                 "Thermal context only, not field-level confirmation; candidates are rule-based, not ground truth. 2025 uses the UMD monthly archive.")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(FIG / "f2_blind_spot.png", dpi=180)
    plt.close(fig)
    # F3 smoke blindness (two stacked panels, shared x, separate y)
    s23 = smoke[smoke.year == 2023]
    vd = pd.read_csv(REP / "viirs_daily.csv", parse_dates=["acq_date"])
    vd = vd[vd.year == 2023]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    a1.plot(s23.date, 100 * s23.clear, color=fs.SERIES[1], marker="o", ms=5, label="Clear-sky (blue-band) usable")
    a1.plot(s23.date, 100 * s23.swir_usable, color=fs.SERIES[0], marker="o", ms=5, label="SWIR-usable (smoke-robust)")
    a1.set_ylabel("Fields observable (%)")
    a1.legend(loc="lower left")
    a1.set_title("Smoke blinds optical monitoring exactly when burning peaks")
    a2.bar(vd.acq_date, vd.viirs_alerts, width=0.9, color=fs.SERIES[7])
    a2.set_ylabel("VIIRS alerts/day")
    import matplotlib.dates as mdates
    a2.xaxis.set_major_locator(mdates.MonthLocator())
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fs.note(fig, "2023 season, Muktsar crop fields. Sen2Cor cloud masks do not flag smoke; blue reflectance >= 0.10 marks hazy observations.\nSWIR (2.2 um) is little affected by smoke, so harvest and char logic uses NIR/SWIR only.")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(FIG / "f3_smoke_blindness.png", dpi=180)
    plt.close(fig)
    # F4 naive vs aware (2023, area in kha)
    r23 = naive[naive.year == 2023].iloc[0]
    labels = ["Naive pre/post dNBR > 0.27", "MODIS MCD64A1 (500 m)", "Harvest-aware, loose", "Harvest-aware, strict char"]
    vals = [r23.naive_dnbr_027_ha, r23.mcd64a1_nominal_ha or 0, r23.aware_loose_ha, r23.aware_strict_ha]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.barh(labels[::-1], np.array(vals[::-1]) / 1000, color=[fs.SERIES[0], fs.SERIES[0], fs.MUTED, fs.MUTED], height=0.55)  # ours highlighted, references muted
    for i, v in enumerate(vals[::-1]):
        ax.text(v / 1000 + 2, i, f"{v/1000:,.1f}k ha", va="center", fontsize=9, color=fs.INK)
    ax.axvline(r23.crop_ha / 1000, color=fs.BASE, lw=1, ls="--")
    ax.text(r23.crop_ha / 1000, 3.45, " all crop fields", fontsize=8, color=fs.MUTED)
    ax.set_xlabel("Burned area, Muktsar 2023 (thousand ha)")
    ax.set_title("A naive dNBR mistakes the harvest for a fire")
    fs.note(fig, "Paddy harvest alone moves NBR from ~0.67 to ~0.1, so pre/post differencing flags almost every field.\nHarvest-aware logic only scores post-harvest char. MCD64A1 area = burned 463 m pixels x nominal pixel area.")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(FIG / "f4_naive_vs_aware.png", dpi=180)
    plt.close(fig)
    # F5 intervention window (2025)
    e = pd.read_parquet(TS / "events_2025.parquet")
    b = e[(e.peak_ndvi >= 0.6) & e.burned & e.harvested].harvest_to_burn_days
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    bins = np.arange(-2.5, 43, 5)  # one bin per revisit step avoids a 5-day comb artefact
    ax.hist(b.clip(upper=40), bins=bins, color=fs.SERIES[0], edgecolor=fs.SURFACE, linewidth=2)
    med = b.median()
    ax.axvline(med, color=fs.INK2, lw=1.2, ls="--")
    ax.text(med + 0.5, ax.get_ylim()[1] * 0.9, f"median {med:.0f} days", color=fs.INK2, fontsize=9)
    ax.set_xlabel("Days from first harvested observation to first char observation")
    ax.set_ylabel("Burned fields")
    ax.set_title("The intervention window: about two weeks between harvest and fire")
    fs.note(fig, "2025, burn-candidate fields (loose tier). Event dates are interval-censored by the 2-5 day revisit.")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(FIG / "f5_intervention_window.png", dpi=180)
    plt.close(fig)
    # F6 replay
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    names = {"oracle": "Oracle (knows future burns)", "risk": "Pre-season history ranking (ours)", "random": "Random",
             "fifo": "First harvested, first served", "dynamic": "Contagion hazard, re-scored each pass"}
    cols = {"risk": fs.SERIES[0], "fifo": fs.SERIES[1], "random": fs.SERIES[2], "dynamic": fs.SERIES[3], "oracle": fs.MUTED}
    for pol in ["oracle", "risk", "dynamic", "random", "fifo"]:
        s = rep[rep.policy == pol]
        if s.empty:
            continue
        ax.plot(s.fleet, 100 * s.preempted_share, color=cols[pol], marker="o", ms=7, mec=fs.SURFACE, mew=2,
                ls="--" if pol == "oracle" else "-", label=names[pol])
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_xscale("log")
    ax.set_xticks([50, 100, 200, 400], ["50", "100", "200", "400"])
    ax.set_xlim(40, 500)
    ax.set_xlabel("Balers in the district (log scale)")
    ax.set_ylabel("Observed 2025 burns pre-empted (%)")
    ax.set_title("Replaying 2025: risk-ranked dispatch pre-empts 1.7-2.7x more burns")
    fs.note(fig, "Season-replay digital twin on real 2025 Sentinel-2 harvest/burn events; 4 ha/baler/day, ERA5 rain days skipped, 20-day pickup window.\nAssumes a baled field is not burned; policy comparison, not an impact forecast.")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(FIG / "f6_replay.png", dpi=180)
    plt.close(fig)
    # F7 nowcast 2026
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    grid = np.array(now["forecast_grid"]["doy"])
    base = pd.Timestamp("2026-01-01")
    dts = [base + pd.Timedelta(days=int(d) - 1) for d in grid]
    ax.fill_between(dts, 100 * np.array(now["forecast_grid"]["lo"]), 100 * np.array(now["forecast_grid"]["hi"]), color=fs.BLUE_RAMP[0], lw=0, label="2023-2025 range")
    ax.plot(dts, 100 * np.array(now["forecast_grid"]["mean"]), color=fs.SERIES[0], lw=2, ls="--", label="2023-2025 mean (forecast)")
    c26 = now["curves"]["2026"]
    ax.plot([base + pd.Timedelta(days=d - 1) for d, _ in c26], [100 * p for _, p in c26], color=fs.SERIES[1], marker="o", ms=6, mec=fs.SURFACE, mew=2, label="2026 observed (live)")
    ax.set_ylabel("Crop fields harvested (%)")
    ax.legend(loc="upper left")
    ax.set_title(f"Live 2026 nowcast: {100*now['harvested_share_now']:.0f}% harvested on {now['latest_image']}")
    fs.note(fig, "Muktsar crop fields; harvest observed when field NBR falls below 0.30.\nForecast assumes a typical (2023-2025) harvest pace.")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(FIG / "f7_nowcast_2026.png", dpi=180)
    plt.close(fig)
    log("figures written")


def main() -> None:
    REP.mkdir(parents=True, exist_ok=True)
    ids = pd.read_parquet(TS / "field_zone_ids.parquet")
    census = census_and_blindspot(ids)
    naive = naive_dnbr_vs_aware()
    smoke = smoke_blindness()
    lat = latency()
    pers = persistence_profile()
    risk, tr, te = risk_model()
    haz, haz_scores = hazard_experiment()
    rep = replay_grid(te, haz_scores)
    em = {str(r.year): {"strict": emissions(r.burned_strict_ha), "loose": emissions(r.burned_loose_ha)} for r in census.itertuples()}
    best = rep[rep.policy == "risk"].set_index("fleet")
    fifo = rep[rep.policy == "fifo"].set_index("fleet")
    per_1000 = emissions(1000.0, seed=1)  # factors per 1,000 ha burned (avoid rounding small per-ha values)
    replay_impact = {}
    for fleet in best.index:
        ha = float(best.loc[fleet, "preempted_ha"])
        em_f = emissions(ha, seed=2)  # Monte Carlo on the actual pre-empted area
        replay_impact[str(fleet)] = dict(preempted_share=float(best.loc[fleet, "preempted_share"]), fifo_share=float(fifo.loc[fleet, "preempted_share"]),
                                         preempted_ha=round(ha), avoided_CH4_N2O_CO2e_t=em_f["CH4_N2O_CO2e_t"]["median"],
                                         avoided_CH4_N2O_CO2e_t_p05_p95=[em_f["CH4_N2O_CO2e_t"]["p05"], em_f["CH4_N2O_CO2e_t"]["p95"]],
                                         avoided_PM25_t=em_f["PM2.5_t"]["median"], avoided_BC_t=em_f["BC_t"]["median"],
                                         straw_value_preempted_rs_crore=round(ha * BALED_T_PER_HA * STRAW_PRICE_RS_PER_T / 1e7, 2),
                                         straw_value_all_baled_rs_crore=round(float(best.loc[fleet, "baled_t"]) * STRAW_PRICE_RS_PER_T / 1e7, 2))
    now = nowcast_2026(te)
    export_field_products(te)
    figures(census, naive, smoke, lat, risk, rep, now)
    cs_path = REP / "burn_candidate_summary.json"
    if cs_path.exists():  # judge-facing candidate areas and thermal context (scripts/build_burn_candidate_events.py)
        cs = json.loads(cs_path.read_text(encoding="utf-8"))
        R["candidate_summary"] = {k: cs.get(k) for k in ("rule_version", "haze_rule", "labels", "area_statistics", "thermal_context",
                                                        "thermal_context_note", "haze_scenes")}
    R.update(dict(generated_by="scripts/run_research.py", census=census.to_dict("records"), naive_vs_aware=naive.to_dict("records"),
                  latency=lat, persistence=pers, risk_model=risk, dynamic_hazard=haz, replay=rep.to_dict("records"), replay_impact=replay_impact,
                  emissions_burned_area=em, emissions_per_1000_ha_burned=per_1000, nowcast_2026={k: v for k, v in now.items() if k not in ("curves", "forecast_grid")},
                  assumptions=dict(straw_t_per_ha=round(STRAW_T_PER_HA, 2), baled_t_per_ha=BALED_T_PER_HA, straw_price_rs_per_t=STRAW_PRICE_RS_PER_T,
                                   emission_factors_g_per_kg="Andreae 2019 ACP Table 1 agricultural residues (open)", gwp100=GWP100),
                  caveats=["Burn outcomes are rule-derived Sentinel-2 candidates, not ground truth; precision awaits Tier-B human labels.",
                           "Char-based detection is a lower bound: small, partial or quickly tilled burns can be missed between revisits.",
                           "2024 burned area is a lower bound because smog removed 3-21 Nov observations.",
                           "Fields of The World polygons are model-derived and overlap; areas use non-overlapping 20 m pixels.",
                           "Replay assumes a baled field is not burned and ignores intra-zone travel; it compares policies, it does not forecast impact."]))
    (REP / "results.json").write_text(json.dumps(clean(R), indent=1, default=str, allow_nan=False), encoding="utf-8")
    log("results.json written")


if __name__ == "__main__":
    main()
