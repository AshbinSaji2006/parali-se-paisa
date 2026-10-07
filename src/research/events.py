"""Field-level harvest and burn event detection from dense Sentinel-2 time series.

Rules are physically motivated and deliberately transparent (see docs/RESEARCH_METHODS.md).

Smoke from residue burning is not flagged by Sen2Cor SCL and is thickest exactly in the peak
burning weeks. Smoke scatters strongly in the blue but very little at 2.2 um, so harvest and burn
logic uses NIR (B8A) and SWIR (B11/B12) only, and observations are discarded only for cloud or
very thick smoke (field blue reflectance >= THICK_SMOKE_B02):
- usable observation: >= 60 % of field pixels usable (SCL 2/4/5/6/7) and B02 < THICK_SMOKE_B02;
- clear observation: usable and B02 < CLEAR_B02 (used for NDVI-based crop peak only);
- crop field: clear-sky peak NDVI >= 0.60;
- harvest: first usable observation with NBR < 0.30 after the running NBR maximum reached 0.50
  (agrees with clear-sky NDVI < 0.40 on 91 % of 2025 observations);
- burn: at/after harvest, a usable observation where the field turns char-dark (NIR and SWIR-2 fall
  with NBR falling below ~0) relative to the previous usable observation, or >= 25 % of pixels are
  char-like. Wet/irrigated soil darkens SWIR more than NIR, keeping NBR positive, so it is excluded.
  The strict tier requires darker char or >= 40 % char pixels.
Outputs are rule-derived event candidates, not ground truth.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

THICK_SMOKE_B02 = 0.20
CLEAR_B02 = 0.10
MIN_VALID_FRAC = 0.6
PEAK_NDVI = 0.60
PEAK_NBR = 0.50
HARVEST_NBR = 0.30


def add_indices(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["ndvi"] = (d.B08 - d.B04) / (d.B08 + d.B04)
    d["nbr"] = (d.B8A - d.B12) / (d.B8A + d.B12)
    d["nbr2"] = (d.B11 - d.B12) / (d.B11 + d.B12)
    d["valid_frac"] = d.n_valid / (d.n_valid + d.n_cloud).clip(lower=1)
    d["usable"] = (d.valid_frac >= MIN_VALID_FRAC) & (d.B02 < THICK_SMOKE_B02) & d.nbr.notna()
    d["clear"] = d.usable & (d.B02 < CLEAR_B02)
    return d


def burn_flags(u: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    dark = (u.B8A < 0.15) & (u.B12 < 0.17) & (u.nbr < 0.03)
    drop = ((u.prev_B8A - u.B8A) > 0.06) & ((u.prev_B12 - u.B12) > 0.03) & ((u.prev_nbr - u.nbr) > 0.08)
    loose = (dark & drop) | (u.char_frac >= 0.25)
    strict_dark = (u.B8A < 0.12) & (u.B12 < 0.14) & (u.nbr < 0.0)
    strict = loose & ((strict_dark & drop) | (u.char_frac >= 0.40))
    return loose, strict


def detect_events(d: pd.DataFrame) -> pd.DataFrame:
    """Return one row per field-season with peak, harvest and burn candidates."""
    d = add_indices(d)
    u = d[d.usable].sort_values(["field_id", "date"]).copy()
    g = u.groupby("field_id", sort=False)
    for c in ["B8A", "B12", "nbr", "date"]:
        u[f"prev_{c}"] = g[c].shift()
    u["cummax_nbr"] = g.nbr.cummax()
    u["is_harvest_obs"] = (u.cummax_nbr >= PEAK_NBR) & (u.nbr < HARVEST_NBR)
    loose, strict = burn_flags(u)
    u["burn_signal"], u["burn_strict"] = loose, strict
    harv = u[u.is_harvest_obs].groupby("field_id").agg(harvest_date=("date", "first"),
                                                       last_green_date=("prev_date", "first"))
    u = u.merge(harv, on="field_id", how="left")
    post = u.harvest_date.notna() & (u.date >= u.harvest_date)
    burns = u[post & u.burn_signal]
    fb = burns.groupby("field_id").agg(burn_date=("date", "first"), burn_prev_date=("prev_date", "first"),
                                       burn_char_frac=("char_frac", "first"), burn_B8A=("B8A", "first"),
                                       burn_B12=("B12", "first"), burn_nbr=("nbr", "first"),
                                       burn_prev_nbr=("prev_nbr", "first"))
    fb["burn_dnbr"] = fb.burn_prev_nbr - fb.burn_nbr
    fb["burned_strict"] = burns.groupby("field_id").burn_strict.first()
    clear = u[u.clear]
    stats = u.groupby("field_id").agg(n_usable=("date", "size"), n_clear=("clear", "sum"),
                                      peak_nbr=("nbr", "max"), last_date=("date", "max"))
    peak = clear.loc[clear.groupby("field_id").ndvi.idxmax(), ["field_id", "ndvi", "date"]]
    peak = peak.rename(columns={"ndvi": "peak_ndvi", "date": "peak_date"}).set_index("field_id")
    # observation gap that brackets each event (temporal precision of the event date)
    out = stats.join(peak).join(harv).join(fb)
    out["harvested"] = out.harvest_date.notna()
    out["burned"] = out.burn_date.notna()
    out["burned_strict"] = out.burned_strict.astype("boolean").fillna(False).astype(bool)
    out["harvest_window_days"] = (out.harvest_date - out.last_green_date).dt.days
    out["burn_window_days"] = (out.burn_date - out.burn_prev_date).dt.days
    out["harvest_to_burn_days"] = (out.burn_date - out.harvest_date).dt.days
    return out.reset_index()
