"""Dynamic burn hazard: re-score every harvested, unburned field at each Sentinel-2 pass.

Panel unit: (field, acquisition date t) for crop fields harvested by t, not yet burned at t, and within
30 days of harvest. Label: the field's burn is first observed at the next pass (its last unburned
observation is t). Features use only information available at t:
- days_since_harvest, day of year;
- prior_burn and nbhd_prior_rate (last season, 1.5 km block);
- nbhd_recent_burn_rate: share of block crop fields whose burn was observed in (t-10 d, t];
- nbhd_recent_burn_rate_wide: the same in a 4.5 km block;
- nbhd_straw_on_ground: share of block crop fields harvested and not burned at t;
- pixel_area_ha, peak_ndvi; rain over the previous 3 days and the next 5 days (ERA5 used as a
  perfect-forecast proxy; operationally this would be a weather forecast).
Scores are relative ranks for dispatch ordering, not calibrated probabilities.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter

from src.research.risk import CELL_M, load_events

ROOT = Path(__file__).resolve().parents[2]
TS = ROOT / "data" / "real" / "derived" / "timeseries"
FEATURES = ["days_since_harvest", "doy", "prior_burn", "nbhd_prior_rate", "nbhd_recent_burn_rate",
            "nbhd_recent_burn_rate_wide", "nbhd_straw_on_ground", "pixel_area_ha", "peak_ndvi",
            "rain_prev_3d", "rain_next_5d"]
MAX_DAYS_AFTER_HARVEST = 30


def _grid_rate(ix, iy, mask, shape, block, denom):
    g = np.zeros(shape)
    np.add.at(g, (iy[mask], ix[mask]), 1.0)
    return uniform_filter(g, size=block, mode="constant") * block * block / np.maximum(denom, 1)


def rain_series() -> pd.Series:
    w = pd.read_parquet(ROOT / "data" / "real" / "weather" / "weather_daily.parquet")
    w["day"] = pd.to_datetime(w.timestamp).dt.tz_localize(None).dt.normalize()
    return w.groupby("day").precipitation_mm.mean()


def build_panel(year: int) -> pd.DataFrame:
    cur, prev = load_events(year), load_events(year - 1)
    crop = cur[cur.peak_ndvi >= 0.6].reset_index(drop=True)
    pc = prev[prev.peak_ndvi >= 0.6]
    x0, y0 = min(crop.x.min(), pc.x.min()) - 3000, min(crop.y.min(), pc.y.min()) - 3000
    shape = (int((max(crop.y.max(), pc.y.max()) - y0) // CELL_M) + 7, int((max(crop.x.max(), pc.x.max()) - x0) // CELL_M) + 7)
    cx, cy = ((crop.x - x0) // CELL_M).astype(int).values, ((crop.y - y0) // CELL_M).astype(int).values
    px, py = ((pc.x - x0) // CELL_M).astype(int).values, ((pc.y - y0) // CELL_M).astype(int).values
    n3 = _grid_rate(cx, cy, np.ones(len(crop), bool), shape, 3, 1)
    n9 = _grid_rate(cx, cy, np.ones(len(crop), bool), shape, 9, 1)
    pn3 = _grid_rate(px, py, np.ones(len(pc), bool), shape, 3, 1)
    prior_rate = _grid_rate(px, py, pc.burned.values, shape, 3, pn3)[cy, cx]
    prior_burn = crop.field_id.map(prev.set_index("field_id").burned).fillna(False).astype(float).values
    rain = rain_series()
    dates = sorted(pd.read_parquet(TS / f"field_timeseries_{year}.parquet", columns=["date"]).date.unique())
    hd, bd, bp = crop.harvest_date.values, crop.burn_date.values, crop.burn_prev_date.values
    burned = crop.burned.values
    parts = []
    for t in dates:
        t = np.datetime64(t)
        at_risk = (hd <= t) & (t <= hd + np.timedelta64(MAX_DAYS_AFTER_HARVEST, "D")) & ~(burned & (bp < t))
        if not at_risk.any():
            continue
        recent = burned & (bd <= t) & (bd > t - np.timedelta64(10, "D"))
        straw = (hd <= t) & ~(burned & (bd <= t))
        r3 = _grid_rate(cx, cy, recent, shape, 3, n3)[cy, cx]
        r9 = _grid_rate(cx, cy, recent, shape, 9, n9)[cy, cx]
        s3 = _grid_rate(cx, cy, straw, shape, 3, n3)[cy, cx]
        ts = pd.Timestamp(t)
        rp = float(rain.loc[ts - pd.Timedelta(days=3): ts - pd.Timedelta(days=1)].sum())
        rn = float(rain.loc[ts: ts + pd.Timedelta(days=4)].sum())
        idx = np.flatnonzero(at_risk)
        parts.append(pd.DataFrame({
            "field_id": crop.field_id.values[idx], "t": ts, "x": crop.x.values[idx], "y": crop.y.values[idx],
            "days_since_harvest": ((t - hd[idx]) / np.timedelta64(1, "D")).astype(float), "doy": float(ts.dayofyear),
            "prior_burn": prior_burn[idx], "nbhd_prior_rate": prior_rate[idx], "nbhd_recent_burn_rate": r3[idx],
            "nbhd_recent_burn_rate_wide": r9[idx], "nbhd_straw_on_ground": s3[idx],
            "pixel_area_ha": crop.pixel_area_ha.values[idx], "peak_ndvi": crop.peak_ndvi.values[idx],
            "rain_prev_3d": rp, "rain_next_5d": rn,
            "y": (burned[idx] & (bp[idx] == t)).astype(int)}))
    return pd.concat(parts, ignore_index=True)
