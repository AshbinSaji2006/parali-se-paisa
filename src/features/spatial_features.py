from __future__ import annotations

from datetime import timedelta

from pyproj import CRS, Transformer
from shapely.geometry import Point
from shapely.ops import transform

from src.features.temporal_context import parse_datetime


def firms_features(geometry_wgs84, points: list[dict], reference_datetime: str, available: bool, buffers_m=(500, 1000), source: str | None = None) -> dict:
    """Count prior/equal-time detections relative to the field boundary in local metric AEQD."""
    reference = parse_datetime(reference_datetime)
    centroid = geometry_wgs84.centroid
    local_crs = CRS.from_proj4(f"+proj=aeqd +lat_0={centroid.y} +lon_0={centroid.x} +datum=WGS84 +units=m +no_defs")
    project = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True).transform
    field_m = transform(project, geometry_wgs84)
    candidates = []
    for point in points:
        try:
            stamp = parse_datetime(point["acquisition_datetime"])
            if stamp > reference:
                continue
            p = Point(float(point["longitude"]), float(point["latitude"]))
            p_m = transform(project, p)
            candidates.append((point, stamp, p, p_m, field_m.distance(p_m), field_m.covers(p_m)))
        except (KeyError, TypeError, ValueError):
            continue
    if not available:
        return {"firms_available": False, "firms_points_within_field": None, "firms_points_within_500m": None,
                "firms_points_within_1km": None, "nearest_firms_distance_m": None,
                "recent_fire_24h": None, "recent_fire_72h": None, "firms_source": None}
    result = {"firms_available": True,
              "firms_points_within_field": sum(inside for _, _, _, _, _, inside in candidates),
              "nearest_firms_distance_m": min((dist for _, _, _, _, dist, _ in candidates), default=None),
              "firms_source": source or ",".join(sorted({str(p.get("source")) for p, *_ in candidates if p.get("source")})) or None}
    for radius in buffers_m:
        suffix = "1km" if radius == 1000 else f"{radius}m"
        result[f"firms_points_within_{suffix}"] = sum(dist <= radius for _, _, _, _, dist, _ in candidates)
    one_km = [stamp for _, stamp, _, _, dist, _ in candidates if dist <= max(buffers_m)]
    result["recent_fire_24h"] = any(reference - timedelta(hours=24) < stamp <= reference for stamp in one_km)
    result["recent_fire_72h"] = any(reference - timedelta(hours=72) < stamp <= reference for stamp in one_km)
    return result
