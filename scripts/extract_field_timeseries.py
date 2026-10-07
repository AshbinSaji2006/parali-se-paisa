"""Zonal Sentinel-2 statistics for every research field on every downloaded date.

Reads the local 20 m stacks written by download_s2_stack.py, rasterises all Fields of The
World polygons once on the same grid, and writes one Parquet per season with per-field
band means over usable pixels plus pixel-level quality and char fractions.

Usable pixels are SCL 2 (dark area), 4 (vegetation), 5 (bare soil), 6 (water) and
7 (unclassified). Class 2 is kept on purpose: fresh crop-residue char is very dark and an
SCL-4/5/6-only mask risks discarding the very signal we want. Clouds/shadows (3, 8, 9, 10)
are counted, not averaged. Haze is not flagged by SCL and is handled downstream.
"""
from __future__ import annotations

import argparse
import glob
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "data" / "real" / "s2_stack"
OUT = ROOT / "data" / "real" / "derived" / "timeseries"
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
USABLE_SCL = [2, 4, 5, 6, 7]
CLOUD_SCL = [3, 8, 9, 10]


def field_zones(transform, width, height):
    cache = OUT / "field_zones.npy"
    ids_path = OUT / "field_zone_ids.parquet"
    if cache.exists() and ids_path.exists():
        return np.load(cache), pd.read_parquet(ids_path)
    fields = gpd.read_parquet(ROOT / "data" / "real" / "fields" / "fields_of_the_world_muktsar.parquet")
    fields = fields[["field_id", "area_ha", "centroid_lon", "centroid_lat", "geometry"]].to_crs("EPSG:32643").reset_index(drop=True)
    fields["zone"] = np.arange(1, len(fields) + 1, dtype=np.int32)
    zones = rasterize(((g, int(z)) for g, z in zip(fields.geometry, fields.zone)), out_shape=(height, width),
                      transform=transform, fill=0, dtype="int32", all_touched=False)
    OUT.mkdir(parents=True, exist_ok=True)
    np.save(cache, zones)
    ids = pd.DataFrame(fields.drop(columns="geometry"))
    ids["n_px"] = np.bincount(zones.ravel(), minlength=len(fields) + 1)[1:]
    ids.to_parquet(ids_path)
    return zones, ids


def process(path: Path, zones_flat: np.ndarray, nz: int, keep: np.ndarray) -> pd.DataFrame:
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    with rasterio.open(path) as src:
        arr = src.read()
    scl = arr[-1].ravel()
    refl = arr[:-1].reshape(len(BANDS), -1)
    usable = np.isin(scl, USABLE_SCL) & (refl[2] != -32768) & (zones_flat > 0)
    cloud = np.isin(scl, CLOUD_SCL) & (zones_flat > 0)
    z = zones_flat[usable]
    n_valid = np.bincount(z, minlength=nz)
    n_cloud = np.bincount(zones_flat[cloud], minlength=nz)
    n_dark2 = np.bincount(zones_flat[(scl == 2) & (zones_flat > 0)], minlength=nz)
    out = {"n_valid": n_valid, "n_cloud": n_cloud, "n_scl2": n_dark2}
    vals = {}
    for i, b in enumerate(BANDS):
        v = refl[i][usable].astype(np.float32) / 1e4
        vals[b] = v
        out[b] = np.divide(np.bincount(z, weights=v, minlength=nz), n_valid,
                           out=np.full(nz, np.nan), where=n_valid > 0).astype(np.float32)
    # Pixel-level fractions: fresh char is dark in NIR and SWIR with negative NBR.
    nbr = (vals["B8A"] - vals["B12"]) / np.maximum(vals["B8A"] + vals["B12"], 1e-4)
    char = (vals["B8A"] < 0.12) & (vals["B12"] < 0.14) & (nbr < 0.0)
    green = ((vals["B08"] - vals["B04"]) / np.maximum(vals["B08"] + vals["B04"], 1e-4)) > 0.5
    for name, flag in [("char_frac", char), ("green_frac", green)]:
        out[name] = np.divide(np.bincount(z[flag], minlength=nz), n_valid, out=np.full(nz, np.nan),
                              where=n_valid > 0).astype(np.float32)
    df = pd.DataFrame({k: v[1:] for k, v in out.items()})
    df.insert(0, "zone", np.arange(1, nz, dtype=np.int32))
    df = df[keep]
    df.insert(1, "date", pd.Timestamp(meta["datetime"]).tz_convert("UTC").normalize().tz_localize(None))
    df.insert(2, "item_id", meta["item_id"])
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=[2023, 2024, 2025, 2026])
    args = ap.parse_args()
    first = sorted(glob.glob(str(STACK / "*" / "*.tif")))[0]
    with rasterio.open(first) as src:
        transform, width, height = src.transform, src.width, src.height
    t0 = time.time()
    zones, ids = field_zones(transform, width, height)
    print(f"zones ready {time.time()-t0:.0f}s fields={len(ids)} with>=3px={(ids.n_px>=3).sum()}", flush=True)
    nz = len(ids) + 1
    keep = (ids.n_px.values >= 3)
    zones_flat = zones.ravel()
    for year in args.years:
        files = sorted(Path(p) for p in glob.glob(str(STACK / str(year) / "S2_*_43RDP.tif")) if not p.endswith(".tmp.tif"))
        files = [f for f in files if f.with_suffix(".json").exists()]
        if not files:
            continue
        parts = []
        for f in files:
            t1 = time.time()
            parts.append(process(f, zones_flat, nz, keep))
            print(f"{year} {f.name} {time.time()-t1:.1f}s", flush=True)
        df = pd.concat(parts, ignore_index=True)
        df = df.merge(ids[["zone", "field_id"]], on="zone", how="left")
        df["year"] = year
        df["real_or_synthetic"] = "REAL"
        df.to_parquet(OUT / f"field_timeseries_{year}.parquet", index=False)
        print(f"WROTE {year} rows={len(df)} dates={len(files)}", flush=True)


if __name__ == "__main__":
    main()
