"""Download dense Sentinel-2 L2A stacks for Sri Muktsar Sahib on one 20 m UTM grid.

Every acquisition of MGRS tile 43RDP (which fully contains the district) is cropped to a
fixed EPSG:32643 20 m grid, harmonised to baseline-independent reflectance (DN - 1000 for
processing baseline >= 04.00, i.e. BOA_ADD_OFFSET) and written as a local int16 GeoTIFF
with the SCL band. Local stacks let pixel burn maps, field zonal statistics and labelling
chips be rebuilt offline without repeating remote reads.

Reflectance = value / 10000. Nodata = -32768 (SCL nodata = 0).
"""
from __future__ import annotations

import os

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("GDAL_CACHEMAX", "512")

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import planetary_computer as pc
import rasterio
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "real" / "s2_stack"
LOG = ROOT / "logs" / "s2_stack_download.log"
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
RES = 20
NODATA = -32768
TILE = "43RDP"
CRS = "EPSG:32643"
# Priority order: latest complete season, live season, then history.
SEASONS = {
    2025: ("2025-09-01", "2025-12-20"),
    2026: ("2026-09-01", "2026-10-31"),
    2024: ("2024-09-01", "2024-12-20"),
    2023: ("2023-09-01", "2023-12-20"),
}
MAX_TILE_CLOUD = 90.0


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def district_grid():
    d = gpd.read_file(ROOT / "data" / "real" / "boundaries" / "sri_muktsar_sahib_adm2.geojson").to_crs(CRS)
    b = d.total_bounds
    x0 = math.floor((b[0] - 600) / RES) * RES
    y0 = math.floor((b[1] - 600) / RES) * RES
    x1 = math.ceil((b[2] + 600) / RES) * RES
    y1 = math.ceil((b[3] + 600) / RES) * RES
    w, h = int((x1 - x0) / RES), int((y1 - y0) / RES)
    transform = from_origin(x0, y1, RES, RES)
    inside = ~geometry_mask(d.buffer(600).geometry, out_shape=(h, w), transform=transform)
    return (x0, y0, x1, y1), transform, w, h, inside


def search_items(year: int):
    start, end = SEASONS[year]
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    items = list(cat.search(collections=["sentinel-2-l2a"], bbox=[74.25, 29.90, 74.83, 30.67],
                            datetime=f"{start}/{end}", query={"s2:mgrs_tile": {"eq": TILE}}).items())
    # Duplicate reprocessings share the sensing time; keep the most recent processing.
    by_time: dict[str, object] = {}
    for it in sorted(items, key=lambda i: i.id):
        by_time[it.datetime.strftime("%Y%m%dT%H%M%S")] = it
    keep = [it for it in by_time.values() if (it.properties.get("eo:cloud_cover") or 0) <= MAX_TILE_CLOUD]
    return sorted(keep, key=lambda i: i.datetime)


def read_band(href: str, bounds, h: int, w: int, categorical: bool, attempts: int = 4) -> np.ndarray:
    last = None
    for k in range(attempts):
        try:
            with rasterio.open(href) as src:
                win = from_bounds(*bounds, transform=src.transform)
                return src.read(1, window=win, out_shape=(h, w), boundless=False,
                                resampling=Resampling.nearest if categorical else Resampling.average)
        except Exception as exc:  # network hiccups on remote COG reads
            last = exc
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"read failed after {attempts} attempts: {last}")


def process_item(item, bounds, transform, w, h, inside, pool: ThreadPoolExecutor) -> dict:
    stamp = item.datetime.strftime("%Y%m%dT%H%M%S")
    year = item.datetime.year
    out_dir = OUT / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tif = out_dir / f"S2_{stamp}_{TILE}.tif"
    out_json = out_tif.with_suffix(".json")
    if out_tif.exists() and out_json.exists():
        return {"status": "exists", "path": str(out_tif)}
    t0 = time.time()
    signed = pc.sign(item)
    baseline = float(item.properties.get("s2:processing_baseline", "0") or 0)
    offset = 1000 if baseline >= 4.0 else 0
    futures = {b: pool.submit(read_band, signed.assets[b].href, bounds, h, w, False) for b in BANDS}
    futures["SCL"] = pool.submit(read_band, signed.assets["SCL"].href, bounds, h, w, True)
    arrays = {b: f.result() for b, f in futures.items()}
    stack = np.empty((len(BANDS) + 1, h, w), dtype=np.int16)
    for i, b in enumerate(BANDS):
        a = arrays[b].astype(np.int32)
        nod = (a == 0) | ~inside
        a = np.clip(a - offset, -32767, 32767)
        a[nod] = NODATA
        stack[i] = a.astype(np.int16)
    scl = arrays["SCL"].astype(np.int16)
    scl[~inside] = 0
    stack[-1] = scl
    profile = dict(driver="GTiff", width=w, height=h, count=len(BANDS) + 1, dtype="int16", crs=CRS,
                   transform=transform, nodata=NODATA, tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate", predictor=2, zlevel=6, BIGTIFF="IF_SAFER")
    tmp = out_tif.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(stack)
        for i, b in enumerate(BANDS + ["SCL"], start=1):
            dst.set_band_description(i, b)
        dst.update_tags(source_item=item.id, processing_baseline=str(baseline), harmonised_offset=str(offset),
                        reflectance_scale="0.0001", provider="Microsoft Planetary Computer",
                        real_or_synthetic="REAL")
    os.replace(tmp, out_tif)
    scl_in = scl[inside]
    hist = {int(k): int(v) for k, v in zip(*np.unique(scl_in, return_counts=True))}
    meta = {
        "item_id": item.id, "datetime": item.datetime.isoformat(), "year": year, "tile": TILE,
        "platform": item.properties.get("platform"), "relative_orbit": item.properties.get("sat:relative_orbit"),
        "tile_cloud_cover": item.properties.get("eo:cloud_cover"), "processing_baseline": baseline,
        "harmonised_offset_dn": offset, "reflectance_scale": 1e-4, "nodata": NODATA, "bands": BANDS + ["SCL"],
        "grid": {"crs": CRS, "res_m": RES, "width": w, "height": h, "transform": list(transform)[:6]},
        "district_pixels": int(inside.sum()), "district_nodata_fraction": float((scl_in == 0).mean()),
        "district_scl_histogram": hist,
        "source_item_url": f"https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/{item.id}",
        "source_asset_urls": {b: item.assets[b].href for b in BANDS + ["SCL"]},
        "download_seconds": round(time.time() - t0, 1), "real_or_synthetic": "REAL",
    }
    out_json.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"status": "written", "path": str(out_tif), "seconds": meta["download_seconds"],
            "mb": round(out_tif.stat().st_size / 1e6, 1), "nodata": meta["district_nodata_fraction"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=list(SEASONS))
    ap.add_argument("--limit", type=int, default=0, help="process at most N new items (benchmarking)")
    ap.add_argument("--item-workers", type=int, default=2)
    args = ap.parse_args()
    bounds, transform, w, h, inside = district_grid()
    log(f"GRID {CRS} {RES}m {w}x{h} bounds={bounds} district_px={int(inside.sum())}")
    items = []
    for y in args.years:
        found = search_items(y)
        log(f"SEARCH year={y} items={len(found)}")
        items.extend(found)
    pending = [it for it in items if not (OUT / str(it.datetime.year) / f"S2_{it.datetime.strftime('%Y%m%dT%H%M%S')}_{TILE}.json").exists()]
    if args.limit:
        pending = pending[: args.limit]
    log(f"PENDING {len(pending)} of {len(items)}")
    band_pool = ThreadPoolExecutor(max_workers=12 * args.item_workers)
    with ThreadPoolExecutor(max_workers=args.item_workers) as item_pool:
        futs = {item_pool.submit(process_item, it, bounds, transform, w, h, inside, band_pool): it for it in pending}
        for f in futs:
            it = futs[f]
            try:
                r = f.result()
                log(f"ITEM {it.id} {r}")
            except Exception as exc:
                log(f"ITEM_FAILED {it.id} {type(exc).__name__}: {exc}")
    band_pool.shutdown()
    log("DONE")


if __name__ == "__main__":
    main()
