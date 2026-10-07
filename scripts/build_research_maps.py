"""Render web-map overlays (EPSG:4326 PNG + bounds) and a static burn-scar map figure.

Per season, every crop field's 20 m pixels are coloured by its Sentinel-2 burn tier (strict char,
loose candidate, unburned); the 2026 overlay colours fields by pre-season risk decile. Overlays are
reprojected from the UTM 43N analysis grid to EPSG:4326 for Leaflet ImageOverlay.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research import figstyle as fs  # noqa: E402

TS = ROOT / "data" / "real" / "derived" / "timeseries"
PROD = ROOT / "data" / "real" / "derived" / "research"
OUT = PROD / "overlays"
FIG = ROOT / "reports" / "research" / "figures"

CLASS_RGBA = {1: (195, 194, 183, 110),   # crop field, no burn candidate (muted, translucent)
              2: (236, 131, 90, 235),    # loose burn candidate (serious)
              3: (208, 59, 59, 255)}     # strict char-confirmed burn (critical)


def hex_rgba(h: str, a: int = 255):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def grid():
    first = next((ROOT / "data" / "real" / "s2_stack" / "2025").glob("*.tif"))
    with rasterio.open(first) as src:
        return src.transform, src.crs, src.width, src.height


def to_wgs84(rgba: np.ndarray, transform, crs, name: str) -> dict:
    h, w = rgba.shape[1:]
    dst_crs = "EPSG:4326"
    left, bottom = transform * (0, h)
    right, top = transform * (w, 0)
    dt, dw, dh = calculate_default_transform(crs, dst_crs, w, h, left, bottom, right, top, resolution=0.0002)
    out = np.zeros((4, dh, dw), dtype=np.uint8)
    for b in range(4):
        reproject(rgba[b], out[b], src_transform=transform, src_crs=crs, dst_transform=dt, dst_crs=dst_crs,
                  resampling=Resampling.nearest)
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.moveaxis(out, 0, -1), "RGBA").save(OUT / f"{name}.png", optimize=True)
    west, north = dt * (0, 0)
    east, south = dt * (dw, dh)
    return {"name": name, "png": f"{name}.png", "bounds": [[south, west], [north, east]], "width": int(dw), "height": int(dh)}


def main() -> None:
    transform, crs, w, h = grid()
    zones = np.load(TS / "field_zones.npy")
    ids = pd.read_parquet(TS / "field_zone_ids.parquet")[["field_id", "zone"]]
    nz = int(ids.zone.max()) + 1
    meta = {"crs_source": str(crs), "overlays": []}
    lut_store = {}
    for y in [2023, 2024, 2025]:
        e = pd.read_parquet(TS / f"events_{y}.parquet").merge(ids, on="field_id")
        e = e[e.peak_ndvi >= 0.6]
        lut = np.zeros(nz, dtype=np.uint8)
        lut[e.zone.values] = 1
        lut[e.zone.values[e.burned.values]] = 2
        lut[e.zone.values[e.burned_strict.values]] = 3
        lut_store[y] = lut
        cls = lut[zones]
        rgba = np.zeros((4, h, w), dtype=np.uint8)
        for k, col in CLASS_RGBA.items():
            m = cls == k
            for b in range(4):
                rgba[b][m] = col[b]
        info = to_wgs84(rgba, transform, crs, f"burn_{y}")
        info.update(year=y, kind="burn_tier", legend=[["Char-confirmed burn (strict)", "#d03b3b"], ["Burn candidate (loose)", "#ec835a"], ["Crop field, no burn candidate", "#c3c2b7"]])
        meta["overlays"].append(info)
        print("overlay", y, info["width"], info["height"], flush=True)
    r = pd.read_parquet(PROD / "risk_2026_preseason.parquet").merge(ids, on="field_id")
    lut = np.zeros(nz, dtype=np.uint8)
    lut[r.zone.values] = r.risk_decile.values.astype(np.uint8)
    dec = lut[zones]
    ramp = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#1c5cab", "#0d366b"]
    rgba = np.zeros((4, h, w), dtype=np.uint8)
    for d in range(1, 11):
        col = hex_rgba(ramp[d - 1], 120 if d <= 5 else 230)
        m = dec == d
        for b in range(4):
            rgba[b][m] = col[b]
    info = to_wgs84(rgba, transform, crs, "risk_2026")
    info.update(year=2026, kind="risk_decile", legend=[["Decile 10 (highest relative risk)", ramp[9]], ["Decile 6", ramp[5]], ["Decile 1 (lowest)", ramp[0]]])
    meta["overlays"].append(info)
    (OUT / "overlays.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    # Static figure: 2025 burn map with VIIRS detections
    import geopandas as gpd
    import matplotlib.pyplot as plt
    fs.setup()
    cls = lut_store[2025][zones][::2, ::2]
    left, top = transform.c, transform.f
    ext = [left, left + w * 20, top - h * 20, top]
    img = np.zeros(cls.shape + (4,), dtype=float)
    for k, col in CLASS_RGBA.items():
        img[cls == k] = np.array(col) / 255
    fig, ax = plt.subplots(figsize=(6.4, 8.6))
    ax.imshow(img, extent=ext, interpolation="nearest")
    dist = gpd.read_file(ROOT / "data/real/boundaries/sri_muktsar_sahib_adm2.geojson").to_crs(crs)
    dist.boundary.plot(ax=ax, color=fs.INK2, linewidth=0.8)
    fires = pd.read_parquet(ROOT / "data/real/firms/active_fire_unified.parquet")
    f = fires[(fires.year == 2025) & fires.in_muktsar & fires.sensor.str.startswith("VIIRS") & (fires["type"].fillna(0) == 0)]
    from pyproj import Transformer
    x, yv = Transformer.from_crs(4326, crs, always_xy=True).transform(f.longitude.values, f.latitude.values)
    ax.scatter(x, yv, s=7, c=fs.INK, marker="o", linewidths=0, label=f"VIIRS fire alert ({len(f):,})")
    ax.scatter([], [], s=30, c="#d03b3b", marker="s", label="Char-confirmed burn (strict)")
    ax.scatter([], [], s=30, c="#ec835a", marker="s", label="Burn candidate (loose)")
    ax.scatter([], [], s=30, c="#c3c2b7", marker="s", label="Crop field, no burn candidate")
    ax.legend(loc="lower left", fontsize=8, frameon=True, facecolor=fs.SURFACE, edgecolor=fs.GRID)
    ax.set_axis_off()
    ax.set_title("Muktsar 2025: burn scars mapped field by field")
    fs.note(fig, "Sentinel-2 L2A harvest-aware burn detection on 165,025 crop fields (Fields of The World boundaries).\nBlack dots: VIIRS 375 m active-fire alerts (S-NPP, NOAA-20, NOAA-21), Sep-Dec 2025.")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / "f8_burn_map_2025.png", dpi=170)
    plt.close(fig)
    print("done", flush=True)


if __name__ == "__main__":
    main()
