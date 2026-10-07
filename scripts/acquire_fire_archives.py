"""Download monthly active-fire location products (VIIRS 375 m C2 and MODIS C6.1) for Muktsar.

Source: University of Maryland fire archive (sftp://fuoco.geog.umd.edu, public guest account
documented in the MODIS C6.1 / VIIRS C2 active fire user guides). Products: VNP14IMGML (S-NPP),
VJ114IMGML (NOAA-20), VJ214IMGML (NOAA-21), MCD14ML (Terra+Aqua MODIS). Global monthly files are
streamed, filtered to a Punjab box and stored as one Parquet; the raw files are not kept.
"""
from __future__ import annotations

import gzip
import io
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "real" / "firms"
BASE = "sftp://fuoco.geog.umd.edu/data"
PRODUCTS = {"VNP14IMGML": ("VIIRS/C2/VNP14IMGML", "VIIRS_SNPP"),
            "VJ114IMGML": ("VIIRS/C2/VJ114IMGML", "VIIRS_NOAA20"),
            "VJ214IMGML": ("VIIRS/C2/VJ214IMGML", "VIIRS_NOAA21"),
            "MCD14ML": ("MODIS/C61/MCD14ML", "MODIS")}
MONTHS = [f"{y}{m:02d}" for y in (2023, 2024, 2025) for m in (9, 10, 11, 12)]
BOX = dict(lat=(29.5, 31.0), lon=(73.8, 75.3))


# Windows' System32 curl lacks SFTP; prefer Git for Windows' libssh2-enabled curl when present.
CURL = next((c for c in [r"C:/Program Files/Git/mingw64/bin/curl.exe"] if Path(c).exists()), "curl")


def curl(url: str) -> bytes:
    return subprocess.run([CURL, "-s", "--max-time", "900", "-u", "fire:burnt", url],
                          check=True, capture_output=True).stdout


def fetch(prod: str, path: str, sensor: str, name: str) -> Path:
    cache = OUT / "monthly_cache" / f"{name}.parquet"
    if cache.exists():
        return cache
    text = gzip.decompress(curl(f"{BASE}/{path}/{name}")).decode("utf-8", "replace")
    if prod == "MCD14ML":
        df = pd.read_csv(io.StringIO(text), sep=r"\s+")
    else:
        df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().lower() for c in df.columns]
    df = df[df.lat.between(*BOX["lat"]) & df.lon.between(*BOX["lon"])].copy()
    df["sensor"], df["product"], df["source_file"] = sensor, prod, name
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    print(f"OK {name} rows_in_box={len(df)}", flush=True)
    return cache


def main() -> None:
    import argparse
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", default=MONTHS)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    jobs = []
    for prod, (path, sensor) in PRODUCTS.items():
        listing = curl(f"{BASE}/{path}/").decode("utf-8", "replace").split()
        names = [n for n in listing if n.startswith(prod + ".")]
        for month in args.months:
            hits = sorted(n for n in names if n.startswith(f"{prod}.{month}."))
            if hits:
                jobs.append((prod, path, sensor, hits[-1]))
            else:
                print(f"MISSING {prod} {month}", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda j: fetch(*j), jobs))
    parts = [pd.read_parquet(p) for p in sorted((OUT / "monthly_cache").glob("*.parquet"))]
    out = pd.concat(parts, ignore_index=True)
    out["real_or_synthetic"] = "REAL"
    out["source_provider"] = "UMD fire archive (NASA VIIRS C2 / MODIS C6.1 active fire)"
    out.to_parquet(OUT / "active_fire_monthly_punjab_box.parquet", index=False)
    print("WROTE", len(out), out.groupby(["product"]).size().to_dict(), flush=True)


if __name__ == "__main__":
    main()
