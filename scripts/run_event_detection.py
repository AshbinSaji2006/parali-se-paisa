"""Run field-level harvest/burn event detection for every extracted season."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research.events import detect_events  # noqa: E402

TS = ROOT / "data" / "real" / "derived" / "timeseries"

if __name__ == "__main__":
    years = [int(a) for a in sys.argv[1:]] or [2023, 2024, 2025, 2026]
    ids = pd.read_parquet(TS / "field_zone_ids.parquet")
    for y in years:
        p = TS / f"field_timeseries_{y}.parquet"
        if not p.exists():
            continue
        e = detect_events(pd.read_parquet(p)).merge(ids[["field_id", "n_px", "centroid_lon", "centroid_lat"]], on="field_id")
        e["pixel_area_ha"] = e.n_px * 0.04
        e["year"] = y
        e["label_source"] = "RULE_CANDIDATE_S2"
        e["real_or_synthetic"] = "REAL"
        e.to_parquet(TS / f"events_{y}.parquet", index=False)
        crop = e[e.peak_ndvi >= 0.6]
        print(y, "fields", len(e), "crop", len(crop), "harvested", round(crop.harvested.mean(), 3),
              "burned_loose", round(crop.burned.mean(), 3), "burned_strict", round(crop.burned_strict.mean(), 3),
              "burned_strict_ha", round(crop[crop.burned_strict].pixel_area_ha.sum()))
