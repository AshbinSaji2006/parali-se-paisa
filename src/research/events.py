"""Field-level harvest and burn-candidate detection from dense Sentinel-2 time series.

Rules are physically motivated and deliberately transparent (see docs/RESEARCH_METHODS.md). Every
output is a RULE-BASED BURN CANDIDATE or a rule-based harvest candidate, never a confirmed burn and
never ground truth. Active-fire (FIRMS) data are NOT used here, so the thermal comparison stays
independent of the tiers.

Haze-quality flag (per field-date observation)
----------------------------------------------
Sen2Cor SCL does not flag smoke haze, which is thickest in the peak burning weeks. The haze metric is
the field-mean Sentinel-2 B02 (blue, 490 nm) surface reflectance, because smoke scatters strongly in
the blue and very little at 2.2 um:
- CLOUD_EXCLUDED: fewer than 60 % of field pixels usable (SCL 2/4/5/6/7); observation not used;
- THICK_SMOKE_EXCLUDED: B02 >= 0.20; observation not used;
- HAZE_DOWNGRADED: 0.10 <= B02 < 0.20; used for NIR/SWIR change logic but cannot serve as the
  pre-event reference of a STRICT candidate (haze raises pre-event NIR and can fake a drop);
- CLEAR: B02 < 0.10.
No scene is discarded as a whole; each observation is flagged.

Tiers
-----
- harvest: first usable observation with NBR < 0.30 after the running NBR maximum reached 0.50;
- LOOSE_BURN_CANDIDATE (exploratory, recall-oriented): at or after harvest, the field turns
  char-dark relative to the previous usable observation (B8A < 0.15, B12 < 0.17, NBR < 0.03 with
  B8A drop > 0.06, B12 drop > 0.03, NBR drop > 0.08) or >= 25 % of its pixels are char-like;
- STRICT_BURN_CANDIDATE (precision-oriented): a loose observation that also has
  (a) a darker char signature with dNBR >= 0.10 (B8A < 0.12, B12 < 0.14, NBR < 0 and the drops above),
      or >= 40 % char-like pixels with dNBR >= 0.10 and a NIR drop > 0.06;
  (b) a CLEAR pre-event observation; and
  (c) temporal consistency: the next usable observation keeps NBR at least 0.05 below the
      pre-event NBR (rules out one-date dips).
Wet/irrigated soil darkens SWIR more than NIR and keeps NBR positive, so it fails the char test.
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
STRICT_MIN_DNBR = 0.10
CONSISTENCY_NBR_MARGIN = 0.05
BAIS2_MIN_B04 = 0.005
HAZE_METRIC = "field-mean Sentinel-2 B02 (blue) surface reflectance"
HAZE_CLASSES = ("CLEAR", "HAZE_DOWNGRADED", "THICK_SMOKE_EXCLUDED", "CLOUD_EXCLUDED", "NO_DATA_EXCLUDED")
STRICT, LOOSE = "STRICT_BURN_CANDIDATE", "LOOSE_BURN_CANDIDATE"
RULE_VERSION = "burn-candidate-rules-v2"
NEIGHBOUR_COLS = ["date", "B02", "B04", "B06", "B07", "B08", "B8A", "B11", "B12", "ndvi", "nbr", "char_frac",
                  "haze_class", "valid_frac", "n_valid"]


def haze_class(d: pd.DataFrame) -> pd.Series:
    valid_frac = d.n_valid / (d.n_valid + d.n_cloud).clip(lower=1)
    nodata = d.B02.isna() | d.B8A.isna() | d.B12.isna()
    return pd.Series(np.select([nodata, valid_frac < MIN_VALID_FRAC, d.B02 >= THICK_SMOKE_B02, d.B02 >= CLEAR_B02],
                               ["NO_DATA_EXCLUDED", "CLOUD_EXCLUDED", "THICK_SMOKE_EXCLUDED", "HAZE_DOWNGRADED"], "CLEAR"),
                     index=d.index)


def bais2(b4, b6, b7, b8a, b12):
    """BAIS2 (Filipponi 2018) from field-mean bands; null where red is below the physical floor."""
    b4 = np.asarray(b4, dtype=float)
    val = (1 - np.sqrt(np.maximum(np.asarray(b6) * np.asarray(b7) * np.asarray(b8a) / np.maximum(b4, BAIS2_MIN_B04), 0))) * \
          ((np.asarray(b12) - np.asarray(b8a)) / np.sqrt(np.maximum(np.asarray(b12) + np.asarray(b8a), 1e-8)) + 1)
    return np.where(b4 >= BAIS2_MIN_B04, val, np.nan)


def add_indices(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["ndvi"] = (d.B08 - d.B04) / (d.B08 + d.B04)
    d["nbr"] = (d.B8A - d.B12) / (d.B8A + d.B12)
    d["nbr2"] = (d.B11 - d.B12) / (d.B11 + d.B12)
    d["valid_frac"] = d.n_valid / (d.n_valid + d.n_cloud).clip(lower=1)
    d["haze_class"] = haze_class(d)
    d["usable"] = d.haze_class.isin(["CLEAR", "HAZE_DOWNGRADED"]) & d.nbr.notna()
    d["clear"] = d.haze_class.eq("CLEAR") & d.nbr.notna()
    return d


def burn_flags(u: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Observation-level (loose, strict) flags; ``u`` needs prev_*/next_* columns and ``post_harvest``."""
    dnbr = u.prev_nbr - u.nbr
    nir_drop = u.prev_B8A - u.B8A
    dark = (u.B8A < 0.15) & (u.B12 < 0.17) & (u.nbr < 0.03)
    drop = (nir_drop > 0.06) & ((u.prev_B12 - u.B12) > 0.03) & (dnbr > 0.08)
    loose = u.post_harvest & ((dark & drop) | (u.char_frac >= 0.25))
    strict_dark = (u.B8A < 0.12) & (u.B12 < 0.14) & (u.nbr < 0.0)
    spectral = (strict_dark & drop & (dnbr >= STRICT_MIN_DNBR)) | ((u.char_frac >= 0.40) & (dnbr >= STRICT_MIN_DNBR) & (nir_drop > 0.06))
    pre_clear = u.prev_haze_class.eq("CLEAR")
    consistent = u.next_nbr.notna() & (u.next_nbr <= u.prev_nbr - CONSISTENCY_NBR_MARGIN)
    strict = loose & spectral & pre_clear & consistent
    return loose.fillna(False).astype(bool), strict.fillna(False).astype(bool)


def annotate_observations(d: pd.DataFrame) -> pd.DataFrame:
    """Usable observations with neighbours, harvest context and tier flags (one row per field-date)."""
    d = add_indices(d)
    u = d[d.usable].sort_values(["field_id", "date"]).reset_index(drop=True)
    g = u.groupby("field_id", sort=False)
    for c in NEIGHBOUR_COLS:
        u[f"prev_{c}"] = g[c].shift()
        u[f"next_{c}"] = g[c].shift(-1)
    u["cummax_nbr"] = g.nbr.cummax()
    u["is_harvest_obs"] = (u.cummax_nbr >= PEAK_NBR) & (u.nbr < HARVEST_NBR)
    harv = u[u.is_harvest_obs].groupby("field_id").agg(harvest_date=("date", "first"), last_green_date=("prev_date", "first"))
    u = u.merge(harv, on="field_id", how="left")
    u["post_harvest"] = u.harvest_date.notna() & (u.date >= u.harvest_date)
    u["dnbr"] = u.prev_nbr - u.nbr
    u["nir_drop"] = u.prev_B8A - u.B8A
    u["swir2_drop"] = u.prev_B12 - u.B12
    u["loose_obs"], u["strict_obs"] = burn_flags(u)
    dnbr_ok = u.dnbr >= STRICT_MIN_DNBR
    spectral_only = u.loose_obs & ~u.strict_obs
    u["strict_blocked_by_haze"] = spectral_only & dnbr_ok & u.prev_haze_class.ne("CLEAR")
    u["strict_blocked_by_consistency"] = spectral_only & dnbr_ok & u.prev_haze_class.eq("CLEAR") & \
        ~(u.next_nbr.notna() & (u.next_nbr <= u.prev_nbr - CONSISTENCY_NBR_MARGIN))
    return u


def detect_events(d: pd.DataFrame, annotated: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per field-season with peak, harvest and burn-candidate summary (strict event first)."""
    u = annotated if annotated is not None else annotate_observations(d)
    harv = u.groupby("field_id").agg(harvest_date=("harvest_date", "first"), last_green_date=("last_green_date", "first"))
    loose_obs, strict_obs = u[u.loose_obs], u[u.strict_obs]
    first_strict = strict_obs.groupby("field_id").head(1).set_index("field_id")
    first_loose = loose_obs.groupby("field_id").head(1).set_index("field_id")
    event = pd.concat([first_strict, first_loose[~first_loose.index.isin(first_strict.index)]])
    fb = pd.DataFrame({"burn_date": event.date, "burn_prev_date": event.prev_date, "burn_char_frac": event.char_frac,
                       "burn_B8A": event.B8A, "burn_B12": event.B12, "burn_nbr": event.nbr, "burn_prev_nbr": event.prev_nbr,
                       "burn_dnbr": event.dnbr, "burn_tier": np.where(event.index.isin(first_strict.index), STRICT, LOOSE)},
                      index=event.index)
    clear = u[u.clear]
    stats = u.groupby("field_id").agg(n_usable=("date", "size"), n_clear=("clear", "sum"), peak_nbr=("nbr", "max"),
                                      last_date=("date", "max"), n_haze_downgraded=("haze_class", lambda s: int((s == "HAZE_DOWNGRADED").sum())),
                                      strict_blocked_by_haze=("strict_blocked_by_haze", "any"))
    peak = clear.loc[clear.groupby("field_id").ndvi.idxmax(), ["field_id", "ndvi", "date"]]
    peak = peak.rename(columns={"ndvi": "peak_ndvi", "date": "peak_date"}).set_index("field_id")
    out = stats.join(peak).join(harv).join(fb)
    out["harvested"] = out.harvest_date.notna()
    out["burned"] = out.burn_date.notna()              # any rule-based burn candidate (loose tier or stricter)
    out["burned_strict"] = out.burn_tier.eq(STRICT)    # strict rule-based burn candidate
    out["harvest_window_days"] = (out.harvest_date - out.last_green_date).dt.days
    out["burn_window_days"] = (out.burn_date - out.burn_prev_date).dt.days
    out["harvest_to_burn_days"] = (out.burn_date - out.harvest_date).dt.days
    out["rule_version"] = RULE_VERSION
    return out.reset_index()
