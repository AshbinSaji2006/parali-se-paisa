from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Protocol


@dataclass(frozen=True)
class Distance:
    kilometers: float
    method: str
    duration_minutes: float | None = None


class TravelMatrixProvider(Protocol):
    method: str

    def distance(self, from_id: str, from_lat: float, from_lon: float,
                 to_id: str, to_lat: float, to_lon: float) -> Distance: ...


class GeodesicDistanceProvider:
    """Straight-line proxy. It deliberately does not imply road distance or time."""

    method = "GEODESIC_PROXY"

    def distance(self, from_id: str, from_lat: float, from_lon: float,
                 to_id: str, to_lat: float, to_lon: float) -> Distance:
        return Distance(haversine_km(from_lat, from_lon, to_lat, to_lon), self.method)


class FixtureMatrixProvider:
    """Explicit offline distance fixture, optionally with fixture-supplied durations."""

    method = "FIXTURE_MATRIX"

    def __init__(self, distances_km: dict[tuple[str, str], float],
                 durations_minutes: dict[tuple[str, str], float] | None = None):
        self.distances_km = distances_km
        self.durations_minutes = durations_minutes or {}

    def distance(self, from_id: str, from_lat: float, from_lon: float,
                 to_id: str, to_lat: float, to_lon: float) -> Distance:
        key = (from_id, to_id)
        reverse = (to_id, from_id)
        if key not in self.distances_km and reverse not in self.distances_km:
            raise KeyError(f"No fixture distance for {from_id!r} to {to_id!r}")
        kilometers = self.distances_km.get(key, self.distances_km.get(reverse))
        duration = self.durations_minutes.get(key, self.durations_minutes.get(reverse))
        return Distance(float(kilometers), self.method, float(duration) if duration is not None else None)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(min(1.0, value)))
