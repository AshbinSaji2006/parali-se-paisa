"""Sentinel-1 radar paddy mask per field (flooded transplanting signature), and burn statistics by crop.

For each field: VH (dB, field mean) minimum over the transplanting window (25 May - 31 Jul) and mean
over the canopy window (15 Aug - 30 Sep). Paddy is flooded at transplanting (VH very low) and then
develops a dense canopy (VH rises strongly); cotton and other dry-land crops are never flooded.
Rule (documented in docs/RESEARCH_METHODS.md): paddy if min VH < -20 dB and canopy rise >= 4 dB.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TS = ROOT / "data" / "real" / "derived" / "timeseries"
REP = ROOT / "reports" / "research"
FLOOD_DB, RISE_DB = -20.0, 4.0


def field_means(path: Path, zones: np.ndarray, nz: int) -> np.ndarray:
    with rasterio.open(path) as src:
        vh = src.read(2)
    ok = (vh != -32768) & (zones > 0)
    z = zones[ok]
    lin = 10 ** (vh[ok].astype(np.float32) / 1000.0)  # dB x 100 -> linear power
    n = np.bincount(z, minlength=nz)
    s = np.bincount(z, weights=lin, minlength=nz)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n >= 3, 10 * np.log10(s / np.maximum(n, 1)), np.nan)


def main(year: int = 2025) -> None:
    zones = np.load(TS / "field_zones.npy")
    ids = pd.read_parquet(TS / "field_zone_ids.parquet")
    nz = int(ids.zone.max()) + 1
    files = sorted(Path(p) for p in glob.glob(str(ROOT / "data" / "real" / "s1_stack" / str(year) / "S1_*.tif")))
    days = [pd.Timestamp(f.name[3:11]) for f in files]
    flood = [f for f, d in zip(files, days) if pd.Timestamp(f"{year}-05-25") <= d <= pd.Timestamp(f"{year}-07-31")]
    canopy = [f for f, d in zip(files, days) if pd.Timestamp(f"{year}-08-15") <= d <= pd.Timestamp(f"{year}-09-30")]
    print(f"S1 passes: {len(files)}; flood window {len(flood)}; canopy window {len(canopy)}", flush=True)
    fmin = np.nanmin(np.vstack([field_means(f, zones, nz) for f in flood]), axis=0)
    fcan = np.nanmean(np.vstack([field_means(f, zones, nz) for f in canopy]), axis=0)
    out = ids[["field_id", "zone", "n_px", "centroid_lon", "centroid_lat"]].copy()
    out["vh_min_transplant_db"] = fmin[out.zone]
    out["vh_canopy_db"] = fcan[out.zone]
    out["vh_rise_db"] = out.vh_canopy_db - out.vh_min_transplant_db
    out["paddy_s1"] = (out.vh_min_transplant_db < FLOOD_DB) & (out.vh_rise_db >= RISE_DB)
    out["pixel_area_ha"] = out.n_px * 0.04
    out["year"] = year
    out["real_or_synthetic"] = "REAL"
    PROD = ROOT / "data" / "real" / "derived" / "research"
    PROD.mkdir(parents=True, exist_ok=True)
    out.drop(columns="zone").to_parquet(PROD / f"paddy_mask_s1_{year}.parquet", index=False)
    ev = pd.read_parquet(TS / f"events_{year}.parquet")[["field_id", "peak_ndvi", "harvested", "burned", "burned_strict", "harvest_date"]]
    m = out.merge(ev, on="field_id")
    crop = m[m.peak_ndvi >= 0.6]
    res = {"year": year, "s1_passes": len(files), "flood_window_passes": len(flood), "canopy_window_passes": len(canopy),
           "rule": f"paddy if min VH (25 May-31 Jul) < {FLOOD_DB} dB and canopy (15 Aug-30 Sep) rise >= {RISE_DB} dB",
           "crop_fields": int(len(crop)), "paddy_fields": int(crop.paddy_s1.sum()),
           "paddy_ha": round(float(crop[crop.paddy_s1].pixel_area_ha.sum())), "non_paddy_crop_ha": round(float(crop[~crop.paddy_s1].pixel_area_ha.sum())),
           "burn_loose_share_paddy": round(float(crop[crop.paddy_s1].burned.mean()), 4),
           "burn_loose_share_non_paddy": round(float(crop[~crop.paddy_s1].burned.mean()), 4),
           "burn_strict_share_paddy": round(float(crop[crop.paddy_s1].burned_strict.mean()), 4),
           "burn_strict_share_non_paddy": round(float(crop[~crop.paddy_s1].burned_strict.mean()), 4),
           "median_harvest_doy_paddy": float(crop[crop.paddy_s1 & crop.harvested].harvest_date.dt.dayofyear.median()),
           "median_harvest_doy_non_paddy": float(crop[~crop.paddy_s1 & crop.harvested].harvest_date.dt.dayofyear.median()),
           "south_of_30_15N_paddy_share": round(float(crop[crop.centroid_lat < 30.15].paddy_s1.mean()), 4),
           "north_of_30_15N_paddy_share": round(float(crop[crop.centroid_lat >= 30.15].paddy_s1.mean()), 4)}
    REP.mkdir(parents=True, exist_ok=True)
    (REP / f"paddy_mask_s1_{year}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2025)
