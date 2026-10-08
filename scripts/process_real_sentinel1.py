"""Per-date field-level Sentinel-1 VV/VH for the sampled research fields.

Reads the local RTC stacks written by download_s1_stack.py (one GeoTIFF per pass, VV and VH as
int16 dB x 100 of 20 m pixels whose linear gamma0 was averaged from 10 m) and reduces each pass
to field means for the same 520 fields as the Sentinel-2 reduction (process_real_sentinel2.py).

Field means are taken in linear power and converted to dB once; dB values are never averaged
or divided. VV-VH in dB is the log of the linear VV/VH ratio. Nothing is interpolated: a field
only gets a row for a pass with >= 3 valid radar pixels.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.process_real_sentinel2 import _sha256, sample_fields

REAL = ROOT / "data" / "real"
STACK = REAL / "s1_stack"
OUT = REAL / "sentinel1" / "sentinel1_field_observations.parquet"
NODATA = -32768
MIN_PIXELS = 3
# Relative orbit 34 over Muktsar is a descending (~01:00 UTC) pass; 100 is ascending (~13:00 UTC).
ORBIT_PASS = {34: "DESCENDING", 100: "ASCENDING"}
ITEM = re.compile(r"^(S1[A-D])_(IW)_(GRDH)_(1SDV)_(\d{8}T\d{6})_(\d{8}T\d{6})_")
PROCESSING_LEVEL = ("Sentinel-1 RTC gamma0 (radiometrically terrain-corrected), Planetary Computer sentinel-1-rtc, "
                    "from IW GRDH 1SDV")
UNITS = "dB = 10*log10(field-mean linear gamma0)"


def _pass_metadata(meta: dict) -> dict:
    parts = [ITEM.match(item) for item in meta["items"]]
    if not parts or not all(parts):
        raise ValueError(f"Unrecognised Sentinel-1 item IDs: {meta['items']}")
    platforms = sorted({p.group(1) for p in parts})
    start = min(pd.Timestamp(p.group(5), tz="UTC") for p in parts)
    end = max(pd.Timestamp(p.group(6), tz="UTC") for p in parts)
    return {"s1_observation_datetime": start.isoformat(), "s1_observation_end_datetime": end.isoformat(),
            "source_image_id_s1": ",".join(meta["items"]), "s1_platform": ",".join(platforms),
            "s1_instrument_mode": parts[0].group(2), "s1_product_type": parts[0].group(3),
            "s1_polarisation_mode": parts[0].group(4), "s1_relative_orbit_number": int(meta["orbit"]),
            "s1_orbit_pass": ORBIT_PASS.get(int(meta["orbit"]), "UNKNOWN"), "s1_slices_mosaicked": len(parts)}


def reduce_pass(path: Path, zones: np.ndarray, pixels: np.ndarray, n_zones: int) -> dict[str, np.ndarray]:
    """Field means of linear VV and VH power plus valid pixel counts for one pass."""
    zone_vector = zones.ravel()[pixels]
    out = {}
    with rasterio.open(path) as src:
        bands = {name.split("_")[0]: i for i, name in enumerate(src.descriptions, start=1)}
        values = {pol: src.read(bands[pol]).ravel()[pixels] for pol in ("VV", "VH")}
    ok = (values["VV"] != NODATA) & (values["VH"] != NODATA)
    z = zone_vector[ok].astype(np.int64)
    n = np.bincount(z, minlength=n_zones + 1)
    out["count"] = n
    out["zone_pixels"] = np.bincount(zone_vector.astype(np.int64), minlength=n_zones + 1)
    for pol, db100 in values.items():
        linear = 10 ** (db100[ok].astype(np.float64) / 1000.0)  # dB x 100 -> linear power
        out[pol] = np.divide(np.bincount(z, weights=linear, minlength=n_zones + 1), n,
                             out=np.full(n_zones + 1, np.nan), where=n >= MIN_PIXELS)
    return out


def run() -> pd.DataFrame:
    files = sorted(p for p in STACK.glob("*/S1_*_o*.tif") if p.with_suffix(".json").exists())
    if not files:
        raise FileNotFoundError(f"No local Sentinel-1 stacks in {STACK.relative_to(ROOT)}; run scripts/download_s1_stack.py")
    with rasterio.open(files[0]) as ref:
        crs, transform, width, height = ref.crs, ref.transform, ref.width, ref.height
    fields = sample_fields(gpd.read_parquet(REAL / "fields" / "fields_of_the_world_muktsar.parquet")).to_crs(crs)
    zones = rasterize(((g, i) for i, g in enumerate(fields.geometry, start=1)), out_shape=(height, width),
                      transform=transform, fill=0, dtype="int32", all_touched=False)
    pixels = np.flatnonzero(zones.ravel())
    rows = []
    for path in files:
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        with rasterio.open(path) as src:
            if src.crs != crs or src.transform != transform or (src.width, src.height) != (width, height):
                raise ValueError(f"{path.name} is not on the common stack grid")
        stats = reduce_pass(path, zones, pixels, len(fields))
        provenance = {**_pass_metadata(meta), "s1_processing_level": PROCESSING_LEVEL, "s1_units": UNITS,
                      "s1_pixel_aggregation": "20 m pixels averaged in linear power; field mean in linear power; one dB conversion",
                      "source_provider": "Microsoft Planetary Computer", "source_raster": path.relative_to(ROOT).as_posix(),
                      "source_raster_sha256": _sha256(path), "real_or_synthetic": "REAL"}
        provenance["year"] = int(pd.Timestamp(provenance["s1_observation_datetime"]).year)
        for i, field in enumerate(fields.itertuples(), start=1):
            vv, vh = stats["VV"][i], stats["VH"][i]
            if not (np.isfinite(vv) and np.isfinite(vh) and vv > 0 and vh > 0):
                continue
            rows.append({"field_id": field.field_id, **provenance,
                         "VV_mean_linear": float(vv), "VH_mean_linear": float(vh),
                         "VV_mean_db": float(10 * np.log10(vv)), "VH_mean_db": float(10 * np.log10(vh)),
                         "VV_minus_VH_db": float(10 * np.log10(vv / vh)), "VV_VH_ratio_linear": float(vv / vh),
                         "s1_valid_pixel_count": int(stats["count"][i]), "s1_zone_pixels": int(stats["zone_pixels"][i]),
                         "s1_valid_pixel_fraction": float(stats["count"][i] / stats["zone_pixels"][i]) if stats["zone_pixels"][i] else None})
        print(f"S1_PASS {path.name} fields={sum(r['source_raster'] == provenance['source_raster'] for r in rows)}", flush=True)
    frame = pd.DataFrame(rows).sort_values(["field_id", "s1_observation_datetime"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT, index=False)
    return frame


def record(frame: pd.DataFrame) -> None:
    from scripts.acquire_real_data import record_dataset
    passes = frame.drop_duplicates("source_raster")
    record_dataset("sentinel1_field_observations", "real_derived", source_provider="Microsoft Planetary Computer",
                   source_dataset="sentinel-1-rtc per-date field VV/VH reductions",
                   date_range={"start": str(frame.s1_observation_datetime.min()), "end": str(frame.s1_observation_datetime.max())},
                   paths=[OUT], metadata={"passes": int(len(passes)), "field_observations": int(len(frame)),
                                          "observed_fields": int(frame.field_id.nunique()),
                                          "passes_by_year": {str(k): int(v) for k, v in passes.groupby("year").size().items()},
                                          "orbits": sorted({f"{o} {p}" for o, p in zip(passes.s1_relative_orbit_number, passes.s1_orbit_pass)}),
                                          "platforms": sorted(set(passes.s1_platform)), "units": UNITS,
                                          "processing_level": PROCESSING_LEVEL, "minimum_valid_pixels": MIN_PIXELS,
                                          "note": "Per-date radar backscatter; no interpolation; compare only same-orbit, same-pass acquisitions."})


if __name__ == "__main__":
    result = run()
    record(result)
    print(f"Wrote {OUT}: passes={result.source_raster.nunique()} fields={result.field_id.nunique()} rows={len(result)}")
