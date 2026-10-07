"""Burn-risk features and temporal hold-out evaluation on rule-derived burn outcomes.

Unit: a harvested crop field in one season. Outcome: Sentinel-2 burn candidate (loose tier) later in
that season. Every feature is available on the day the harvest is first observed, so the score can
rank fields for baler dispatch before any burn happens:
- prior_burn: the same field was a burn candidate in the previous season (persistence);
- nbhd_prior_rate: burn-candidate share of fields in the surrounding ~1.5 km block last season;
- nbhd_burned_before: burn candidates in the block already observed before this field's harvest
  (in-season contagion);
- nbhd_harvested_before: harvest progress in the block by this field's harvest date;
- harvest_doy, pixel_area_ha, peak_ndvi: timing, size and biomass proxy.
Labels are rule candidates, not ground truth, so metrics measure agreement with the rule outcome.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.ndimage import uniform_filter

ROOT = Path(__file__).resolve().parents[2]
TS = ROOT / "data" / "real" / "derived" / "timeseries"
CELL_M = 500
BLOCK = 3  # 3x3 cells of 500 m = 1.5 km block
FEATURES = ["prior_burn", "nbhd_prior_rate", "nbhd_burned_before", "nbhd_harvested_before",
            "harvest_doy", "pixel_area_ha", "peak_ndvi"]
_tr = Transformer.from_crs(4326, 32643, always_xy=True)


def load_events(year: int) -> pd.DataFrame:
    e = pd.read_parquet(TS / f"events_{year}.parquet")
    x, y = _tr.transform(e.centroid_lon.values, e.centroid_lat.values)
    e["x"], e["y"] = x, y
    return e


def _cells(e: pd.DataFrame, x0: float, y0: float):
    return ((e.x.values - x0) // CELL_M).astype(int), ((e.y.values - y0) // CELL_M).astype(int)


def _block_sum(ix, iy, weights, shape):
    grid = np.zeros(shape, dtype=np.float64)
    np.add.at(grid, (iy, ix), weights)
    return uniform_filter(grid, size=BLOCK, mode="constant") * BLOCK * BLOCK


def build_features(year: int) -> pd.DataFrame:
    cur = load_events(year)
    prev = load_events(year - 1)
    x0, y0 = min(cur.x.min(), prev.x.min()) - 2000, min(cur.y.min(), prev.y.min()) - 2000
    shape = (int((max(cur.y.max(), prev.y.max()) - y0) // CELL_M) + 3,
             int((max(cur.x.max(), prev.x.max()) - x0) // CELL_M) + 3)
    pcrop = prev[prev.peak_ndvi >= 0.6]
    pix, piy = _cells(pcrop, x0, y0)
    burned_prev = _block_sum(pix, piy, pcrop.burned.values.astype(float), shape)
    n_prev = _block_sum(pix, piy, np.ones(len(pcrop)), shape)
    crop = cur[(cur.peak_ndvi >= 0.6) & cur.harvested].copy()
    cix, ciy = _cells(crop, x0, y0)
    crop["prior_burn"] = crop.field_id.map(prev.set_index("field_id").burned).fillna(False).astype(float)
    crop["nbhd_prior_rate"] = np.divide(burned_prev[ciy, cix], np.maximum(n_prev[ciy, cix], 1))
    allcrop = cur[cur.peak_ndvi >= 0.6]
    aix, aiy = _cells(allcrop, x0, y0)
    n_all = _block_sum(aix, aiy, np.ones(len(allcrop)), shape)
    crop["nbhd_burned_before"] = 0.0
    crop["nbhd_harvested_before"] = 0.0
    for d in sorted(crop.harvest_date.dropna().unique()):
        bmask = (allcrop.burn_date < d).values
        hmask = (allcrop.harvest_date < d).values
        bgrid = _block_sum(aix[bmask], aiy[bmask], np.ones(bmask.sum()), shape)
        hgrid = _block_sum(aix[hmask], aiy[hmask], np.ones(hmask.sum()), shape)
        sel = (crop.harvest_date == d).values
        crop.loc[sel, "nbhd_burned_before"] = np.divide(bgrid[ciy[sel], cix[sel]], np.maximum(n_all[ciy[sel], cix[sel]], 1))
        crop.loc[sel, "nbhd_harvested_before"] = np.divide(hgrid[ciy[sel], cix[sel]], np.maximum(n_all[ciy[sel], cix[sel]], 1))
    crop["harvest_doy"] = crop.harvest_date.dt.dayofyear.astype(float)
    crop["y_loose"] = crop.burned.astype(int)
    crop["y_strict"] = crop.burned_strict.astype(int)
    return crop


def precision_at(y_true: np.ndarray, score: np.ndarray, frac: float) -> float:
    k = max(1, int(round(len(score) * frac)))
    top = np.argsort(-score, kind="stable")[:k]
    return float(y_true[top].mean())
