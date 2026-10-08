"""Field-level candidate event tables (one row per crop field-season with a candidate event).

Row types:
- STRICT_BURN_CANDIDATE / LOOSE_BURN_CANDIDATE: label "RULE-BASED BURN CANDIDATE" at the first strict
  observation (or the first loose one when no strict observation exists);
- HARVESTED_NO_BURN_CANDIDATE: label "RULE-BASED HARVEST CANDIDATE (NO BURN SIGNAL)" at the first
  harvested observation of fields without any burn-candidate observation.
Pre/post are the neighbouring usable observations of the same field. FIRMS proximity is descriptive
thermal context only (not used by the tiers, not a field-level confirmation): VIIRS/MODIS
vegetation-fire detections within FIRMS_RADIUS_KM of the field centroid during the evidence window,
with archive-coverage status. Uncovered windows keep null counts. Areas: ``pixel_area_ha`` is the
non-overlapping 20 m pixel area; ``polygon_area_ha`` is the (overlapping) Fields of The World area.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

from src.features.fire_context import _coverage_status, _covered_days, firms_coverage_intervals
from src.research.events import LOOSE, RULE_VERSION, STRICT, bais2

FIRMS_RADIUS_KM = 1.0
FIRMS_CORROBORATION_KM = 0.5
FIRMS_TOLERANCE_DAYS = 1
HARVEST_NO_BURN = "HARVESTED_NO_BURN_CANDIDATE"
LABEL_BURN = "RULE-BASED BURN CANDIDATE"
LABEL_HARVEST = "RULE-BASED HARVEST CANDIDATE (NO BURN SIGNAL)"
_tr = Transformer.from_crs(4326, 32643, always_xy=True)


def _evidence_and_caution(r) -> tuple[str, str]:
    ev, cau = [], []
    if r.candidate_type in (STRICT, LOOSE):
        if r.nbr_event < 0.03 and r.b8a_event < 0.15 and r.b12_event < 0.17:
            ev.append("char-dark NIR and SWIR-2 with NBR < 0.03")
        if r.nir_drop > 0.06:
            ev.append(f"NIR (B8A) collapse {r.nir_drop:.3f}")
        if r.swir2_drop > 0.03:
            ev.append(f"SWIR-2 (B12) drop {r.swir2_drop:.3f}")
        if pd.notna(r.dnbr):
            ev.append(f"dNBR {r.dnbr:.3f}")
        if r.char_frac_event >= 0.25:
            ev.append(f"{100 * r.char_frac_event:.0f}% char-like pixels")
        if r.candidate_type == STRICT:
            ev.append("clear pre-event image; post-event NBR stays low")
        else:
            if r.haze_flag_pre != "CLEAR":
                cau.append("pre-event image haze-downgraded (strict tier needs a clear reference)")
            if pd.isna(r.post_event_date):
                cau.append("no later usable image to check temporal consistency")
            cau.append("exploratory loose tier: not a confirmed burn")
    else:
        ev.append(f"NBR fell below 0.30 after peak (harvest); no char-like darkening in {int(r.n_post_harvest_obs)} later usable images")
        if r.n_post_harvest_obs < 2:
            cau.append("few post-harvest images: a short-lived burn could be missed")
    if r.haze_flag_event == "HAZE_DOWNGRADED":
        cau.append("event image haze-downgraded")
    if pd.notna(r.event_window_days) and r.event_window_days > 10:
        cau.append(f"{int(r.event_window_days)}-day gap between pre and event images")
    if r.pixel_area_ha < 0.5:
        cau.append("small field (< 0.5 ha of 20 m pixels)")
    if r.firms_coverage_status == "NOT_COVERED":
        cau.append("no active-fire archive coverage for the window (fire counts unknown, left null)")
    elif r.firms_coverage_status == "PARTIAL":
        cau.append("active-fire archive covers only part of the window; zero counts refer to the covered days")
    cau.append("rule output, not ground truth")
    return "; ".join(ev), "; ".join(cau)


def build_event_table(u: pd.DataFrame, events: pd.DataFrame, ids: pd.DataFrame, firms: pd.DataFrame, year: int) -> pd.DataFrame:
    """``u``: annotate_observations output; ``events``: detect_events output; ``ids``: field_zone_ids."""
    crop = events[events.peak_ndvi >= 0.6]
    keyed = u.set_index(["field_id", "date"])
    rows = []
    burn = crop[crop.burned]
    harvest_only = crop[crop.harvested & ~crop.burned]
    sel = pd.concat([
        pd.DataFrame({"field_id": burn.field_id.values, "date": burn.burn_date.values, "candidate_type": burn.burn_tier.values}),
        pd.DataFrame({"field_id": harvest_only.field_id.values, "date": harvest_only.harvest_date.values, "candidate_type": HARVEST_NO_BURN})])
    obs = keyed.loc[list(zip(sel.field_id, sel.date))].reset_index()
    obs["candidate_type"] = sel.candidate_type.values
    post_counts = u[u.post_harvest].groupby("field_id").size()
    e = crop.set_index("field_id")
    t = pd.DataFrame({
        "field_id": obs.field_id, "season": year, "candidate_type": obs.candidate_type,
        "strict_or_loose_tier": obs.candidate_type.map({STRICT: "STRICT", LOOSE: "LOOSE"}),
        "label": np.where(obs.candidate_type.eq(HARVEST_NO_BURN), LABEL_HARVEST, LABEL_BURN),
        "candidate_event_date": obs.date, "pre_event_date": obs.prev_date, "post_event_date": obs.next_date,
        "event_window_days": (obs.date - obs.prev_date).dt.days,
        "harvest_date": obs.field_id.map(e.harvest_date), "last_green_date": obs.field_id.map(e.last_green_date),
        "season_last_image": obs.field_id.map(e.last_date),
        "ndvi_pre": obs.prev_ndvi, "ndvi_event": obs.ndvi, "ndvi_post": obs.next_ndvi,
        "nbr_pre": obs.prev_nbr, "nbr_event": obs.nbr, "nbr_post": obs.next_nbr, "dnbr": obs.dnbr,
        "bais2_pre": bais2(obs.prev_B04, obs.prev_B06, obs.prev_B07, obs.prev_B8A, obs.prev_B12),
        "bais2_event": bais2(obs.B04, obs.B06, obs.B07, obs.B8A, obs.B12),
        "b8a_pre": obs.prev_B8A, "b8a_event": obs.B8A, "b11_pre": obs.prev_B11, "b11_event": obs.B11,
        "b12_pre": obs.prev_B12, "b12_event": obs.B12, "nir_drop": obs.nir_drop, "swir2_drop": obs.swir2_drop,
        "char_frac_event": obs.char_frac, "char_frac_post": obs.next_char_frac,
        "haze_flag_pre": obs.prev_haze_class, "haze_flag_event": obs.haze_class, "haze_flag_post": obs.next_haze_class,
        "b02_pre": obs.prev_B02, "b02_event": obs.B02,
        "valid_frac_pre": obs.prev_valid_frac, "valid_frac_event": obs.valid_frac, "valid_frac_post": obs.next_valid_frac,
        "valid_pixels_event": obs.n_valid, "n_post_harvest_obs": obs.field_id.map(post_counts).fillna(0).astype(int),
        "strict_blocked_by_haze": obs.field_id.map(e.strict_blocked_by_haze).fillna(False).astype(bool),
    })
    t["observation_quality"] = np.select(
        [t.haze_flag_pre.eq("CLEAR") & t.haze_flag_event.eq("CLEAR") & t.post_event_date.notna() & (t.valid_frac_event >= 0.9),
         t.haze_flag_pre.eq("HAZE_DOWNGRADED") | t.haze_flag_event.eq("HAZE_DOWNGRADED"), t.post_event_date.isna()],
        ["GOOD", "HAZE_DOWNGRADED", "NO_POST_IMAGE"], "FAIR")
    meta = ids.set_index("field_id")
    t["pixel_area_ha"] = t.field_id.map(meta.n_px) * 0.04
    t["polygon_area_ha"] = t.field_id.map(meta.area_ha)
    t["centroid_lon"] = t.field_id.map(meta.centroid_lon)
    t["centroid_lat"] = t.field_id.map(meta.centroid_lat)
    t = t.join(firms_proximity(t, firms))
    reasons = [_evidence_and_caution(r) for r in t.itertuples()]
    t["evidence_reasons"] = [a for a, _ in reasons]
    t["uncertainty_caution"] = [b for _, b in reasons]
    t["rule_version"] = RULE_VERSION
    t["label_source"] = "RULE_CANDIDATE_S2_HARVEST_AWARE"
    t["is_ground_truth"] = False
    t["real_or_synthetic"] = "REAL"
    return t.sort_values(["candidate_type", "field_id"]).reset_index(drop=True)


def firms_proximity(t: pd.DataFrame, firms: pd.DataFrame) -> pd.DataFrame:
    """Thermal context per event row. Window: burn rows [pre - 1 d, event + 1 d]; harvest rows
    [last green - 1 d, last usable image of the season + 1 d] (post-harvest period)."""
    f = firms[firms["type"].fillna(0).eq(0)].copy()
    out = pd.DataFrame(index=t.index, columns=["firms_window_start", "firms_window_end", "firms_coverage_status",
                                               "firms_viirs_1km", "firms_modis_1km", "firms_any_within_500m",
                                               "firms_nearest_km", "firms_nearest_sensor", "firms_nearest_date",
                                               "firms_time_diff_days"], dtype=object)
    intervals = firms_coverage_intervals(firms)
    burn = t.candidate_type.ne(HARVEST_NO_BURN).values
    tol = np.timedelta64(FIRMS_TOLERANCE_DAYS, "D")
    pre = t.pre_event_date.fillna(t.candidate_event_date).values.astype("datetime64[ns]")
    green = t.last_green_date.fillna(t.pre_event_date).fillna(t.candidate_event_date).values.astype("datetime64[ns]")
    event = t.candidate_event_date.values.astype("datetime64[ns]")
    last = t.season_last_image.fillna(t.candidate_event_date).values.astype("datetime64[ns]")
    start = np.where(burn, pre, green) - tol
    end = np.where(burn, event, last) + tol
    out["firms_window_start"], out["firms_window_end"] = start, end
    tz = lambda s: pd.Timestamp(s).tz_localize("UTC")
    out["firms_coverage_status"] = [_coverage_status(_covered_days(intervals, tz(a), tz(b)), (pd.Timestamp(b) - pd.Timestamp(a)).days)
                                    for a, b in zip(start, end)]
    x, y = _tr.transform(t.centroid_lon.values, t.centroid_lat.values)
    fx, fy = _tr.transform(f.longitude.values, f.latitude.values)
    tree = cKDTree(np.c_[fx, fy])
    hits = tree.query_ball_point(np.c_[x, y], r=FIRMS_RADIUS_KM * 1000)
    fdates = f.acq_date.values.astype("datetime64[ns]")
    sensors = f.sensor.values
    for i, h in enumerate(hits):
        if out.at[t.index[i], "firms_coverage_status"] == "NOT_COVERED":
            continue  # unknown, not zero
        idx = t.index[i]
        h = np.asarray(h, dtype=int)
        if h.size:
            inwin = (fdates[h] >= start[i]) & (fdates[h] <= end[i])
            h = h[inwin]
        out.at[idx, "firms_viirs_1km"] = int(sum(str(sensors[j]).startswith("VIIRS") for j in h))
        out.at[idx, "firms_modis_1km"] = int(sum(sensors[j] == "MODIS" for j in h))
        if h.size:
            dist = np.hypot(fx[h] - x[i], fy[h] - y[i]) / 1000
            k = int(np.argmin(dist))
            out.at[idx, "firms_nearest_km"] = round(float(dist[k]), 3)
            out.at[idx, "firms_nearest_sensor"] = str(sensors[h[k]])
            out.at[idx, "firms_nearest_date"] = pd.Timestamp(fdates[h[k]])
            out.at[idx, "firms_time_diff_days"] = int((pd.Timestamp(fdates[h[k]]) - pd.Timestamp(event[i])).days)
            out.at[idx, "firms_any_within_500m"] = bool((dist <= FIRMS_CORROBORATION_KM).any())
        else:
            out.at[idx, "firms_any_within_500m"] = False
    for c in ("firms_viirs_1km", "firms_modis_1km", "firms_time_diff_days"):
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
    out["firms_nearest_km"] = pd.to_numeric(out.firms_nearest_km, errors="coerce")
    out["firms_any_within_500m"] = out.firms_any_within_500m.astype("boolean")
    out["firms_window_start"] = pd.to_datetime(out.firms_window_start)
    out["firms_window_end"] = pd.to_datetime(out.firms_window_end)
    out["firms_nearest_date"] = pd.to_datetime(out.firms_nearest_date)
    out["firms_role"] = "THERMAL CONTEXT ONLY: not a field-level confirmation"
    return out
