"""Download Sentinel-1 RTC (gamma0) VV/VH for the summer season onto the Sentinel-2 20 m district grid.

Used for a radar paddy mask: transplanted paddy is flooded (very low VH backscatter) in June-July, then
VH rises strongly as the canopy grows; cotton and other dry-land crops never flood. One relative orbit
is used for consistent geometry. Values are stored as int16 dB x 100 (nodata -32768).
"""
from __future__ import annotations

import os

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("VSI_CACHE", "TRUE")

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import planetary_computer as pc
import rasterio
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "real" / "s1_stack"
NODATA = -32768


def target_grid():
    ref = next((ROOT / "data" / "real" / "s2_stack" / "2025").glob("*.tif"))
    with rasterio.open(ref) as src:
        return src.crs, src.transform, src.width, src.height


def read_db(href, crs, transform, w, h):
    """Decimated window read on the shared EPSG:32643 grid (RTC COGs carry 2x overviews)."""
    from rasterio.windows import from_bounds
    left, top = transform.c, transform.f
    bounds = (left, top - h * transform.e * -1, left + w * transform.a, top)
    last = None
    for k in range(4):
        try:
            with rasterio.open(href) as src:
                if src.crs != crs:
                    with WarpedVRT(src, crs=crs, transform=transform, width=w, height=h, resampling=Resampling.average) as vrt:
                        lin = vrt.read(1).astype(np.float32)
                else:
                    win = from_bounds(*bounds, transform=src.transform)
                    lin = src.read(1, window=win, out_shape=(h, w), resampling=Resampling.average,
                                   boundless=True, fill_value=src.nodata if src.nodata is not None else 0).astype(np.float32)
                nod = src.nodata
            db = np.full(lin.shape, NODATA, dtype=np.int16)
            ok = (lin > 0) & np.isfinite(lin) & ((lin != nod) if nod is not None else True)
            db[ok] = np.clip(np.round(1000 * np.log10(lin[ok])), -6000, 3000).astype(np.int16)  # dB x 100
            return db
        except Exception as exc:  # transient remote read failures
            last = exc
            time.sleep(3 * (k + 1))
    raise RuntimeError(last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--orbit", type=int, default=34)
    ap.add_argument("--start", default="05-20")
    ap.add_argument("--end", default="09-30")
    a = ap.parse_args()
    crs, transform, w, h = target_grid()
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    items = list(cat.search(collections=["sentinel-1-rtc"], bbox=[74.25, 29.90, 74.83, 30.67],
                            datetime=f"{a.year}-{a.start}/{a.year}-{a.end}").items())
    items = [i for i in items if i.properties.get("sat:relative_orbit") == a.orbit]
    by_day = {}
    for it in sorted(items, key=lambda i: i.id):
        by_day.setdefault(it.datetime.strftime("%Y%m%d"), []).append(it)
    out_dir = OUT / str(a.year)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(items)} items on {len(by_day)} days, orbit {a.orbit}", flush=True)
    pool = ThreadPoolExecutor(max_workers=8)

    def do_day(day, its):
        path = out_dir / f"S1_{day}_o{a.orbit}.tif"
        if path.exists():
            return f"exists {path.name}"
        t0 = time.time()
        stack = np.full((2, h, w), NODATA, dtype=np.int16)
        for it in its:  # adjacent slices of the same pass are mosaicked
            s = pc.sign(it)
            for b, band in enumerate(["vv", "vh"]):
                db = read_db(s.assets[band].href, crs, transform, w, h)
                fill = (stack[b] == NODATA) & (db != NODATA)
                stack[b][fill] = db[fill]
        prof = dict(driver="GTiff", width=w, height=h, count=2, dtype="int16", crs=crs, transform=transform, nodata=NODATA,
                    tiled=True, blockxsize=512, blockysize=512, compress="deflate", predictor=2)
        with rasterio.open(path, "w", **prof) as dst:
            dst.write(stack)
            dst.set_band_description(1, "VV_dB_x100")
            dst.set_band_description(2, "VH_dB_x100")
            dst.update_tags(items=",".join(i.id for i in its), source="Microsoft Planetary Computer sentinel-1-rtc (gamma0)",
                            real_or_synthetic="REAL")
        cover = float((stack[1] != NODATA).mean())
        path.with_suffix(".json").write_text(json.dumps({"day": day, "items": [i.id for i in its], "orbit": a.orbit,
                                                         "coverage": cover, "seconds": round(time.time() - t0, 1)}), encoding="utf-8")
        return f"wrote {path.name} coverage={cover:.2f} {time.time()-t0:.0f}s"

    with ThreadPoolExecutor(max_workers=4) as days:
        for r in days.map(lambda kv: do_day(*kv), sorted(by_day.items())):
            print(r, flush=True)
    pool.shutdown()


if __name__ == "__main__":
    main()
