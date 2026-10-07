"""Render before/after Sentinel-2 chips for a field (true colour and SWIR false colour)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "data" / "real" / "s2_stack"
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12", "SCL"]


@lru_cache(maxsize=4)
def _zones():
    return np.load(ROOT / "data" / "real" / "derived" / "timeseries" / "field_zones.npy", mmap_mode="r")


def stack_path(date) -> Path | None:
    d = date.strftime("%Y%m%d")
    hits = sorted((STACK / str(date.year)).glob(f"S2_{d}T*_43RDP.tif"))
    return hits[0] if hits else None


def chip(path: Path, row: int, col: int, half: int = 24):
    with rasterio.open(path) as src:
        a = src.read(window=Window(col - half, row - half, 2 * half, 2 * half)).astype(np.float32) / 1e4
    b = dict(zip(BANDS, a))
    rgb = np.clip(np.dstack([b["B04"], b["B03"], b["B02"]]) / 0.20, 0, 1)
    swir = np.clip(np.dstack([b["B12"] / 0.35, b["B8A"] / 0.45, b["B04"] / 0.20]), 0, 1)
    return rgb, swir


def outline(row: int, col: int, zone: int, half: int = 24):
    z = np.asarray(_zones()[row - half: row + half, col - half: col + half])
    m = z == zone
    edge = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
    return edge


def field_mask(row: int, col: int, zone: int, half: int = 24) -> np.ndarray:
    return np.asarray(_zones()[row - half: row + half, col - half: col + half]) == zone


def ring(mask: np.ndarray, scale: int) -> np.ndarray:
    """One-pixel outline drawn just outside the field after nearest-neighbour upscaling."""
    up = np.kron(mask, np.ones((scale, scale), dtype=bool))
    grown = up.copy()
    grown[1:, :] |= up[:-1, :]; grown[:-1, :] |= up[1:, :]; grown[:, 1:] |= up[:, :-1]; grown[:, :-1] |= up[:, 1:]
    return grown & ~up
