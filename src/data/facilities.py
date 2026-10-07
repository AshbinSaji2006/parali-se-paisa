"""Optional buyer/baler distance context with explicit demo/real provenance."""
from __future__ import annotations

import csv
import math
from pathlib import Path

REQUIRED = {"facility_id", "facility_type", "name", "latitude", "longitude", "dataset_type", "source"}


def load_facilities(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing: raise ValueError(f"facility schema missing: {', '.join(sorted(missing))}")
        rows = list(reader)
    for row in rows:
        if row["facility_type"] not in ("BALER", "BUYER") or row["dataset_type"] not in ("DEMO", "REAL"):
            raise ValueError("facility type or dataset_type is invalid")
        lat, lon = float(row["latitude"]), float(row["longitude"])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("facility coordinates outside WGS84 bounds")
        row["latitude"], row["longitude"] = lat, lon
    return rows


def facility_distance_context(latitude, longitude, facilities):
    if latitude is None or longitude is None:
        return {"baler_distance_m": None, "buyer_distance_m": None, "facility_dataset_type": "UNAVAILABLE", "facility_source": None}
    candidates = {"BALER": [], "BUYER": []}
    for facility in facilities:
        distance = _haversine(float(latitude), float(longitude), facility["latitude"], facility["longitude"])
        candidates[facility["facility_type"]].append((distance, facility))
    result = {}
    types = {f["dataset_type"] for f in facilities}
    result["facility_dataset_type"] = "MIXED" if len(types) > 1 else next(iter(types), "UNAVAILABLE")
    result["facility_source"] = "|".join(sorted({f["source"] for f in facilities})) or None
    for kind, key in (("BALER", "baler"), ("BUYER", "buyer")):
        nearest = min(candidates[kind], default=None, key=lambda x: x[0])
        result[f"{key}_distance_m"] = nearest[0] if nearest else None
        result[f"{key}_facility_id"] = nearest[1]["facility_id"] if nearest else None
    return result


def _haversine(lat1, lon1, lat2, lon2):
    radius = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*radius*math.asin(math.sqrt(a))
