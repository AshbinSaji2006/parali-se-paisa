"""Build the blind human-review reference-label package from the committed label-tool chips.

The Sentinel-2 chips (true colour and SWIR, three dates per field-season, field outline) were
rendered by ``scripts/build_label_tool.py`` from the raw district stacks and are stored in the
internal chip store ``reports/research/label_tool/chips_<year>.json``. This script reuses those real chips
(no re-rendering, no new imagery), attaches ancillary context that the reviewer can only open
after recording a first decision, and writes:

* ``reports/research/label_tool/label_reference_<year>.html``: the review interface;
* ``reports/research/label_tool/reference_package_<year>.json``: the package manifest.

Nothing here produces a label. Labels come only from a person using the interface and are
imported with ``scripts/import_reference_labels.py``.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.provenance import content_available  # noqa: E402
from src.features.fire_context import firms_context, modis_burned_area_context  # noqa: E402

TOOL = ROOT / "reports" / "research" / "label_tool"
REAL = ROOT / "data" / "real"
PACKAGE_VERSION = "reference-v2"
ITEMS_RE = re.compile(r"const ITEMS = (\[.*?\]);\s*\n", re.S)


def load_items(year: int) -> list[dict]:
    store = TOOL / f"chips_{year}.json"
    if store.exists():
        return json.loads(store.read_text(encoding="utf-8"))["items"]
    html = (ROOT / "reports" / "research" / "internal_do_not_share" / "legacy-reviewer-artifacts" / f"label_burns_{year}.html").read_text(encoding="utf-8")  # legacy chip source
    match = ITEMS_RE.search(html)
    if not match:
        raise ValueError(f"label_burns_{year}.html does not contain an ITEMS array")
    return json.loads(match.group(1))


def _round(value, digits=3):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def ancillary_context(items: list[dict], year: int) -> dict[str, dict]:
    """Context shown only after a first decision. Burn-tier rule outputs are never included."""
    frame = pd.DataFrame([{"field_id": i["field_id"], "centroid_lat": i["lat"], "centroid_lon": i["lon"],
                           # End of the candidate day: detections on that day are visible in the after chip.
                           "observation_datetime": pd.Timestamp(i["candidate_date"], tz="UTC") + pd.Timedelta(hours=23, minutes=59)}
                          for i in items])
    fires = firms_context(frame, pd.read_parquet(REAL / "firms" / "active_fire_unified.parquet"))
    burned = modis_burned_area_context(frame, pd.read_parquet(REAL / "burned_area" / "mcd64a1_burn_pixels.parquet"),
                                       pd.read_parquet(REAL / "burned_area" / "mcd64a1_muktsar.parquet"))
    events = pd.read_parquet(REAL / "derived" / "timeseries" / f"events_{year}.parquet",
                             columns=["field_id", "n_usable", "peak_ndvi", "peak_date", "harvest_date", "last_green_date",
                                      "harvest_window_days", "last_date"]).set_index("field_id")
    radar_path = REAL / "derived" / "research" / f"paddy_mask_s1_{year}.parquet"
    radar = pd.read_parquet(radar_path).set_index("field_id") if content_available(radar_path) else None
    out = {}
    for k, item in enumerate(items):
        fid = item["field_id"]
        e = events.loc[fid] if fid in events.index else None
        day = lambda v: None if v is None or pd.isna(v) else pd.Timestamp(v).date().isoformat()
        ctx = {
            "dense_series": None if e is None else {
                "usable_observations": int(e.n_usable), "peak_ndvi": _round(e.peak_ndvi), "peak_date": day(e.peak_date),
                "first_harvested_observation": day(e.harvest_date), "last_green_observation": day(e.last_green_date),
                "last_observation": day(e.last_date)},
            "firms_30d_1km": {"viirs": fires.iloc[k].firms_viirs_detections_near_field, "modis": fires.iloc[k].firms_modis_detections_near_field,
                               "nearest_km": _round(fires.iloc[k].firms_nearest_detection_km, 2),
                               "coverage": fires.iloc[k].firms_coverage_status},
            "mcd64a1_30d_500m": {"burned_pixels": burned.iloc[k].modis_ba_burned_pixels_near_field,
                                 "coverage": burned.iloc[k].modis_ba_coverage_status},
            "sentinel1_vh_season": None,
        }
        if radar is not None and fid in radar.index and pd.notna(radar.loc[fid, "vh_canopy_db"]):
            r = radar.loc[fid]
            ctx["sentinel1_vh_season"] = {"vh_min_transplant_db": _round(r.vh_min_transplant_db, 2),
                                          "vh_canopy_db": _round(r.vh_canopy_db, 2), "vh_rise_db": _round(r.vh_rise_db, 2),
                                          "flooded_paddy_signature": bool(r.paddy_s1)}
        for key in ("viirs", "modis", "burned_pixels"):
            for block in ("firms_30d_1km", "mcd64a1_30d_500m"):
                if key in ctx[block] and ctx[block][key] is not None and not pd.isna(ctx[block][key]):
                    ctx[block][key] = int(ctx[block][key])
                elif key in ctx[block]:
                    ctx[block][key] = None
        out[fid] = ctx
    return out


def build(year: int) -> dict:
    items = load_items(year)
    context = ancillary_context(items, year)
    review_items = []
    manifest_items = []
    for item in items:
        item_id = f"{year}:{item['field_id']}"
        frames = item["frames"]
        review_items.append({"item_id": item_id, "field_id": item["field_id"], "year": year,
                             "candidate_date": item["candidate_date"], "lon": item["lon"], "lat": item["lat"],
                             "frames": frames, "context": context[item["field_id"]]})
        # The stratum is the detector's own output: it stays in the manifest for design-based
        # estimation but is never placed in the reviewer interface.
        manifest_items.append({"item_id": item_id, "field_id": item["field_id"], "year": year, "stratum": item["stratum"],
                               "candidate_date": item["candidate_date"], "frame_dates": [f["date"] for f in frames]})
    design = json.loads((TOOL / f"sample_design_{year}.json").read_text(encoding="utf-8"))
    manifest = {"package_version": PACKAGE_VERSION, "year": year, "generated_at": datetime.now(timezone.utc).isoformat(),
                "items": manifest_items, "item_count": len(manifest_items), "sample_design": design,
                "source_chips": f"reports/research/label_tool/chips_{year}.json (internal; Sentinel-2 L2A, harmonised BOA offset, 20 m)",
                "blinding": "Detector stratum and burn tiers are withheld from the interface; ancillary context opens only after a first decision.",
                "label_policy": "Human multi-date visual review (Tier B). No label is generated by this package."}
    (TOOL / f"reference_package_{year}.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    html = (ROOT / "scripts" / "reference_label_template.html").read_text(encoding="utf-8")
    html = (html.replace("__PACKAGE__", f"{PACKAGE_VERSION}-{year}").replace("__YEAR__", str(year))
                .replace("__ITEMS__", json.dumps(review_items, separators=(",", ":"))))
    (TOOL / f"label_reference_{year}.html").write_text(html, encoding="utf-8")
    return {"year": year, "items": len(review_items)}


if __name__ == "__main__":
    print(json.dumps([build(y) for y in (2023, 2025)], indent=1))
