from __future__ import annotations

import math
import statistics
from collections import defaultdict

from .vegetation_indices import ndvi, nbr, bais2

BANDS = ("B2", "B3", "B4", "B6", "B7", "B8", "B8A", "B11", "B12")
INDEX_NAMES = ("NDVI", "NBR", "BAIS2")


def _finite(x):
    try:
        f = float(x)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _stats(values):
    xs = [x for x in values if x is not None and math.isfinite(x)]
    if not xs:
        return {"mean": None, "median": None, "std": None, "min": None, "max": None}
    return {"mean": statistics.fmean(xs), "median": statistics.median(xs), "std": statistics.pstdev(xs), "min": min(xs), "max": max(xs)}


def aggregate_s2_observation(observation: dict) -> dict:
    """Reduce controlled pixel samples with the same schema expected from a field reducer."""
    if "field_statistics" in observation:
        # Input produced by an Earth Engine field reducer: indices must have been
        # calculated per pixel before the reducer, not from band means afterward.
        summary = observation["field_statistics"]
        out = {}
        for name in INDEX_NAMES:
            stats = summary.get("indices", {}).get(name, {})
            for stat in ("mean", "median", "std", "min", "max"):
                out[f"{name}_{stat}"] = _finite(stats.get(stat))
        for band in BANDS:
            out[f"{band}_mean"] = _finite(summary.get("bands", {}).get(band, {}).get("mean"))
        valid_count, total_count = summary.get("valid_pixel_count"), summary.get("total_pixel_count")
        out["valid_pixel_count"] = int(valid_count) if valid_count is not None else 0
        out["total_pixel_count"] = int(total_count) if total_count is not None else 0
        if out["valid_pixel_count"] < 0 or out["total_pixel_count"] < 0 or out["valid_pixel_count"] > out["total_pixel_count"]:
            raise ValueError("server reducer returned inconsistent pixel counts")
        out["valid_pixel_fraction"] = summary.get("valid_pixel_fraction")
        if out["valid_pixel_fraction"] is None and total_count:
            out["valid_pixel_fraction"] = out["valid_pixel_count"] / out["total_pixel_count"]
        out["cloud_fraction"] = summary.get("cloud_fraction")
        if out["cloud_fraction"] is None and total_count:
            out["cloud_fraction"] = (summary.get("cloud_pixel_count") or 0) / out["total_pixel_count"]
        for fraction_name in ("valid_pixel_fraction", "cloud_fraction"):
            fraction = out[fraction_name]
            if fraction is not None and (not math.isfinite(float(fraction)) or not 0 <= float(fraction) <= 1):
                raise ValueError(f"server reducer returned invalid {fraction_name}")
        return out
    scale = float(observation.get("value_scale", 1.0))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("value_scale must be a finite positive number")
    pixels = observation.get("pixels", [])
    total = len(pixels)
    cloudy = sum(bool(p.get("cloudy", False)) for p in pixels)
    values = defaultdict(list)
    index_values = defaultdict(list)
    valid_count = 0
    for pixel in pixels:
        if pixel.get("cloudy") or not pixel.get("valid", True):
            continue
        bands = {band: _finite(pixel.get(band)) for band in BANDS}
        if any(value is None for value in bands.values()):
            continue
        refl = {band: value * scale for band, value in bands.items()}
        valid_count += 1
        for band in BANDS:
            values[band].append(refl[band])
        index_values["NDVI"].append(ndvi(refl["B8"], refl["B4"]))
        index_values["NBR"].append(nbr(refl["B8A"], refl["B12"]))
        index_values["BAIS2"].append(bais2(refl["B4"], refl["B6"], refl["B7"], refl["B8A"], refl["B12"]))
    out = {f"{name}_{stat}": val for name, vals in index_values.items() for stat, val in _stats(vals).items()}
    for band, vals in values.items():
        out[f"{band}_mean"] = _stats(vals)["mean"]
    out.update({"valid_pixel_count": valid_count, "total_pixel_count": total,
                "valid_pixel_fraction": valid_count / total if total else None,
                "cloud_fraction": cloudy / total if total else None})
    return out
