"""Rule-based burn-candidate events, haze audit, overlap-safe areas and thermal context.

For each season (2023-2026) this script:
1. flags every field-date observation with the haze class (src/research/events.py) and writes a
   per-scene haze audit (no scene is dropped as a whole);
2. detects harvest and STRICT/LOOSE rule-based burn candidates and writes
   data/real/derived/timeseries/events_<year>.parquet (used by the research pipeline);
3. writes the field-level event table data/real/derived/research/burn_candidate_events_<year>.parquet;
4. reports polygon counts, overlapping polygon area and non-overlapping 20 m pixel area;
5. compares candidates with VIIRS/MODIS active fires as independent thermal CONTEXT (2023-2024
   primary; 2025 secondary). This is corroboration, not validation accuracy.
Outputs: reports/research/{haze_quality_by_scene.csv, burn_candidate_summary.json}.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research import firms_match as fm  # noqa: E402
from src.research.event_table import HARVEST_NO_BURN, build_event_table  # noqa: E402
from src.research.events import (CLEAR_B02, HAZE_METRIC, LOOSE, MIN_VALID_FRAC, RULE_VERSION, STRICT,  # noqa: E402
                                 THICK_SMOKE_B02, add_indices, annotate_observations, detect_events)

TS = ROOT / "data" / "real" / "derived" / "timeseries"
PROD = ROOT / "data" / "real" / "derived" / "research"
REP = ROOT / "reports" / "research"
YEARS = [2023, 2024, 2025, 2026]
VIIRS = ["VIIRS_SNPP", "VIIRS_NOAA20"]  # available in every season; NOAA-21 only from 2025


def haze_audit(d: pd.DataFrame, year: int) -> pd.DataFrame:
    rows = []
    for (date, item), g in d.groupby(["date", "item_id"]):
        vc = g.haze_class.value_counts()
        valid = g[g.valid_frac >= MIN_VALID_FRAC]
        n = len(g)
        rows.append({"season": year, "date": pd.Timestamp(date).date().isoformat(), "item_id": item, "field_observations": n,
                     "haze_metric": HAZE_METRIC, "median_b02_valid_fields": round(float(valid.B02.median()), 4) if len(valid) else None,
                     "p90_b02_valid_fields": round(float(valid.B02.quantile(0.9)), 4) if len(valid) else None,
                     **{f"n_{c.lower()}": int(vc.get(c, 0)) for c in ("CLEAR", "HAZE_DOWNGRADED", "THICK_SMOKE_EXCLUDED", "CLOUD_EXCLUDED", "NO_DATA_EXCLUDED")},
                     "share_haze_downgraded": round(float(vc.get("HAZE_DOWNGRADED", 0) / n), 4),
                     "share_thick_smoke_excluded": round(float(vc.get("THICK_SMOKE_EXCLUDED", 0) / n), 4),
                     "share_cloud_excluded": round(float(vc.get("CLOUD_EXCLUDED", 0) / n), 4)})
    return scene_status(pd.DataFrame(rows))


def scene_status(t: pd.DataFrame) -> pd.DataFrame:
    """Scene roll-up of the per-observation flags (cloud with no valid pixels counts as excluded)."""
    t = t.copy()
    n = t.field_observations.clip(lower=1)
    t["share_no_data_excluded"] = (t.n_no_data_excluded / n).round(4)
    excluded = (t.n_thick_smoke_excluded + t.n_cloud_excluded + t.n_no_data_excluded) / n
    t["share_excluded_total"] = excluded.round(4)
    t["scene_status"] = np.select([excluded >= 0.5, t.share_haze_downgraded >= 0.5],
                                  ["MOSTLY_EXCLUDED_OBSERVATIONS", "MOSTLY_HAZE_DOWNGRADED"], "MOSTLY_USABLE")
    t["scene_handling"] = "scene retained; each field observation flagged (excluded or downgraded), never silently dropped"
    return t


def haze_summary(hz: pd.DataFrame) -> dict:
    return {str(y): {"scenes": int(len(g)), "mostly_usable": int((g.scene_status == "MOSTLY_USABLE").sum()),
                     "mostly_haze_downgraded": int((g.scene_status == "MOSTLY_HAZE_DOWNGRADED").sum()),
                     "mostly_excluded": int((g.scene_status == "MOSTLY_EXCLUDED_OBSERVATIONS").sum()),
                     "observations_haze_downgraded": int(g.n_haze_downgraded.sum()),
                     "observations_thick_smoke_excluded": int(g.n_thick_smoke_excluded.sum()),
                     "observations_cloud_or_no_data_excluded": int(g.n_cloud_excluded.sum() + g.n_no_data_excluded.sum())}
            for y, g in hz.groupby("season")}


def thermal_context(ev: pd.DataFrame, year: int) -> dict:
    fires = fm.load_firms(year)
    crop = fm.field_xy(ev[ev.peak_ndvi >= 0.6])
    out = {"sensors": VIIRS, "temporal_tolerance_days": fm.TOL_DAYS,
           "window": "candidate evidence window [pre-event image - 1 d, event image + 1 d]",
           "viirs_detections_in_district_sep_dec": int(fires[fires.in_muktsar & fires.sensor.isin(VIIRS)].shape[0])}
    for tier, col in (("strict", "burned_strict"), ("loose", "burned")):
        res = {}
        for radius in (375, 500, 1000):
            fm.RADIUS_M = float(radius)
            cand = crop.assign(burned=crop[col])
            b = fm.blind_spot(cand, fires, VIIRS)
            ctl = crop[crop.harvested & ~crop.burned].sample(min(20000, int((crop.harvested & ~crop.burned).sum())), random_state=1).copy()
            pick = crop[crop[col]].sample(len(ctl), replace=True, random_state=2) if crop[col].any() else None
            if pick is not None:
                ctl["burn_prev_date"], ctl["burn_date"], ctl["burned"] = pick.burn_prev_date.values, pick.burn_date.values, True
                n_ctl = fm.blind_spot(ctl, fires, VIIRS)
            r = fm.recall_vs_fires(cand, fires, VIIRS)
            short = b[b.burn_window_days <= 5]
            res[f"{radius}m"] = {
                "candidates": int(len(b)),
                "candidates_with_viirs_nearby": int(b.fire_match.sum()),
                "share_candidates_with_viirs_nearby": round(float(b.fire_match.mean()), 4) if len(b) else None,
                "share_short_window_candidates_with_viirs_nearby": round(float(short.fire_match.mean()), 4) if len(short) else None,
                "short_window_candidates": int(len(short)),
                "proximity_control_share": round(float(n_ctl.fire_match.mean()), 4) if pick is not None else None,
                "viirs_detections_with_optical_candidate_nearby": int(r.s2_match.sum()),
                "share_viirs_detections_with_optical_candidate_nearby": round(float(r.s2_match.mean()), 4) if len(r) else None}
        out[tier] = res
    fm.RADIUS_M = 500.0
    return out


def area_statistics(ids: pd.DataFrame, events: dict[int, pd.DataFrame]) -> dict:
    out = {"polygons_total": int(len(ids)), "polygon_area_sum_ha_overlapping": round(float(ids.area_ha.sum())),
           "polygons_with_ge3_pixels": int((ids.n_px >= 3).sum()), "polygons_without_any_pixel": int((ids.n_px == 0).sum()),
           "non_overlapping_pixel_area_ha_all_fields": round(float(ids.n_px.sum() * 0.04)),
           "method": "Each 20 m pixel is assigned to exactly one field when polygons are rasterised, so pixel areas never double count. "
                     "Polygon areas overlap and are never summed for district totals.",
           "seasons": {}}
    for y, ev in events.items():
        crop = ev[ev.peak_ndvi >= 0.6]
        s = {"crop_fields": int(len(crop)), "crop_pixel_area_ha": round(float(crop.pixel_area_ha.sum())),
             "crop_polygon_area_ha_overlapping": round(float(crop.area_ha.sum()))}
        for name, m in (("strict", crop.burned_strict), ("loose_any", crop.burned), ("loose_only", crop.burned & ~crop.burned_strict),
                        ("harvested_no_burn", crop.harvested & ~crop.burned), ("no_harvest_observed", ~crop.harvested)):
            s[f"{name}_fields"] = int(m.sum())
            s[f"{name}_field_share"] = round(float(m.mean()), 4)
            s[f"{name}_pixel_area_ha"] = round(float(crop.loc[m, "pixel_area_ha"].sum()))
            s[f"{name}_pixel_area_share"] = round(float(crop.loc[m, "pixel_area_ha"].sum() / crop.pixel_area_ha.sum()), 4)
            s[f"{name}_polygon_area_ha_overlapping"] = round(float(crop.loc[m, "area_ha"].sum()))
        out["seasons"][str(y)] = s
    return out


def main() -> None:
    ids = pd.read_parquet(TS / "field_zone_ids.parquet")
    firms = pd.read_parquet(ROOT / "data" / "real" / "firms" / "active_fire_unified.parquet")
    PROD.mkdir(parents=True, exist_ok=True)
    REP.mkdir(parents=True, exist_ok=True)
    haze, events, tables, summary = [], {}, {}, {"rule_version": RULE_VERSION,
               "haze_rule": {"metric": HAZE_METRIC, "clear_below": CLEAR_B02, "thick_smoke_from": THICK_SMOKE_B02,
                             "cloud_excluded_below_valid_fraction": MIN_VALID_FRAC,
                             "downgraded_meaning": "kept for NIR/SWIR change logic; cannot be the pre-event reference of a strict candidate"},
               "labels": {"burn": "RULE-BASED BURN CANDIDATE", "never": "CONFIRMED BURN"}, "seasons": {}}
    for y in YEARS:
        d = pd.read_parquet(TS / f"field_timeseries_{y}.parquet")
        haze.append(haze_audit(add_indices(d), y))
        u = annotate_observations(d)
        ev = detect_events(d, u).merge(ids[["field_id", "n_px", "area_ha", "centroid_lon", "centroid_lat"]], on="field_id")
        ev["pixel_area_ha"] = ev.n_px * 0.04
        ev["year"] = y
        ev["label_source"] = "RULE_CANDIDATE_S2_HARVEST_AWARE"
        ev["real_or_synthetic"] = "REAL"
        ev.drop(columns=["area_ha"]).to_parquet(TS / f"events_{y}.parquet", index=False)
        events[y] = ev
        t = build_event_table(u, ev, ids, firms, y)
        t.to_parquet(PROD / f"burn_candidate_events_{y}.parquet", index=False)
        tables[y] = t
        usable = u.shape[0]
        per_fs = u[u.field_id.isin(ev[ev.peak_ndvi >= 0.6].field_id)].groupby("field_id").size()
        summary["seasons"][str(y)] = {
            "scenes": int(d.date.nunique()), "field_time_rows": int(len(d)), "usable_field_time_rows": int(usable),
            "median_usable_obs_per_crop_field_season": float(per_fs.median()) if len(per_fs) else None,
            "event_table_rows": int(len(t)), "event_rows_by_type": t.candidate_type.value_counts().to_dict(),
            "strict_blocked_by_haze_fields": int(ev[(ev.peak_ndvi >= 0.6) & ev.burned & ~ev.burned_strict].strict_blocked_by_haze.sum()),
            "firms_coverage_by_type": {k: g.firms_coverage_status.value_counts().to_dict() for k, g in t.groupby("candidate_type")}}
        print(y, json.dumps(summary["seasons"][str(y)])[:400], flush=True)
        del d, u
    hz = pd.concat(haze, ignore_index=True)
    hz.to_csv(REP / "haze_quality_by_scene.csv", index=False)
    summary["haze_scenes"] = haze_summary(hz)
    summary["area_statistics"] = area_statistics(ids, events)
    summary["thermal_context"] = {str(y): thermal_context(events[y], y) for y in (2023, 2024, 2025)}
    summary["thermal_context_note"] = ("Active fires are thermal context: polar-orbit overpasses (~01:30/13:30 local) miss fires lit "
                                       "later in the day, fires under smoke or cloud, and short-lived small fires; VIIRS pixels are 375 m "
                                       "and a detection near a field is not a field-level confirmation. 2023-2024 are the primary "
                                       "comparison; 2025 uses the UMD monthly archive (Sep-Dec).")
    (REP / "burn_candidate_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print("wrote", REP / "burn_candidate_summary.json", flush=True)


if __name__ == "__main__":
    main()
