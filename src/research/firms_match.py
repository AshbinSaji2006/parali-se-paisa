"""Match Sentinel-2 field burn candidates with FIRMS active-fire detections.

Two directions are reported:
- recall vs thermal evidence: of VIIRS detections over Muktsar cropland, how many have at least one
  field within RADIUS_M whose S2 burn interval brackets the detection date;
- blind spot: of S2 burn-candidate fields, how many have NO VIIRS/MODIS detection within RADIUS_M
  during their burn interval (previous usable observation -> burn observation, +/- TOL_DAYS).
Distances use field centroids in UTM 43N. VIIRS 375 m pixels grow toward the scan edge, so a
500 m centroid radius is a pragmatic tolerance, recorded with every result.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
RADIUS_M = 500.0
TOL_DAYS = 1
_tr = Transformer.from_crs(4326, 32643, always_xy=True)


def load_firms(year: int, in_district: bool = False) -> pd.DataFrame:
    f = pd.read_parquet(ROOT / "data" / "real" / "firms" / "active_fire_unified.parquet")
    f = f[(f.acq_date.dt.year == year) & f.acq_date.dt.month.isin([9, 10, 11, 12])].copy()
    f = f[f["type"].fillna(0) == 0]  # presumed vegetation fires only
    if in_district:
        f = f[f.in_muktsar]
    x, y = _tr.transform(f.longitude.values, f.latitude.values)
    f["x"], f["y"] = x, y
    return f.reset_index(drop=True)


def field_xy(ids: pd.DataFrame) -> pd.DataFrame:
    x, y = _tr.transform(ids.centroid_lon.values, ids.centroid_lat.values)
    return ids.assign(x=x, y=y)


def blind_spot(events: pd.DataFrame, firms: pd.DataFrame, sensors: list[str]) -> pd.DataFrame:
    """Annotate burned fields with whether any active fire of `sensors` matches them."""
    b = events[events.burned].copy()
    f = firms[firms.sensor.isin(sensors)]
    b["fire_match"] = False
    b["n_fire_matches"] = 0
    if f.empty or b.empty:
        return b
    tree = cKDTree(f[["x", "y"]].values)
    hits = tree.query_ball_point(b[["x", "y"]].values, r=RADIUS_M)
    fd = f.acq_date.values
    start = (b.burn_prev_date.fillna(b.burn_date) - pd.Timedelta(days=TOL_DAYS)).values
    end = (b.burn_date + pd.Timedelta(days=TOL_DAYS)).values
    n = np.zeros(len(b), dtype=int)
    for i, h in enumerate(hits):
        if h:
            d = fd[h]
            n[i] = int(((d >= start[i]) & (d <= end[i])).sum())
    b["n_fire_matches"] = n
    b["fire_match"] = n > 0
    return b


def recall_vs_fires(events: pd.DataFrame, firms: pd.DataFrame, sensors: list[str]) -> pd.DataFrame:
    """For each active-fire detection inside the district, is there a matching S2 burn interval nearby?"""
    f = firms[firms.sensor.isin(sensors) & firms.in_muktsar].copy()
    ev = events[events.burned]
    f["s2_match"] = False
    f["near_fields"] = 0
    f["near_observed"] = 0
    if f.empty:
        return f
    tree_all = cKDTree(events[["x", "y"]].values)
    near = tree_all.query_ball_point(f[["x", "y"]].values, r=RADIUS_M)
    ev_idx = set(np.flatnonzero(events.burned.values))
    bp = events.burn_prev_date.values
    bd = events.burn_date.values
    fd = f.acq_date.values
    ok = np.zeros(len(f), dtype=bool)
    nf = np.zeros(len(f), dtype=int)
    for i, h in enumerate(near):
        nf[i] = len(h)
        for j in h:
            if j in ev_idx:
                s = (bp[j] if not pd.isna(bp[j]) else bd[j]) - np.timedelta64(TOL_DAYS, "D")
                e = bd[j] + np.timedelta64(TOL_DAYS, "D")
                if s <= fd[i] <= e:
                    ok[i] = True
                    break
    f["s2_match"] = ok
    f["near_fields"] = nf
    return f
