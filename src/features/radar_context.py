"""Sentinel-1 field radar context: per-date VV/VH passes and the 2025 VH season summary.

Per-date observations come from ``data/real/sentinel1/sentinel1_field_observations.parquet``
(``scripts/process_real_sentinel1.py``): Planetary Computer ``sentinel-1-rtc`` gamma0 passes,
reduced per field in linear power and converted to dB once. Each Sentinel-2 row receives the
latest pass at or before its acquisition, at most ``S1_MAX_AGE_DAYS`` earlier; otherwise the
radar columns stay null. Temporal radar deltas (src.features.temporal_features) compare only
passes with the same instrument mode, orbit direction and relative orbit.

The season summary comes from ``data/real/derived/research/paddy_mask_s1_2025.parquet``
(``scripts/build_paddy_mask.py``), built from descending relative orbit 34, ten passes
2025-05-31..2025-09-28, and is attached only after the last pass, so the context is causal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

S1_SEASON = 2025
S1_LAST_PASS = pd.Timestamp("2025-09-28T01:00:38Z")
# One repeat cycle of a single Sentinel-1 platform on one relative orbit.
S1_MAX_AGE_DAYS = 12
S1_PROVENANCE = {
    "s1_season_product": "Sentinel-1 RTC gamma0 (Planetary Computer sentinel-1-rtc), IW GRDH 1SDV",
    "s1_season_platform": "SENTINEL-1A", "s1_season_orbit_pass": "DESCENDING", "s1_season_relative_orbit": 34,
    "s1_season_polarization": "VH", "s1_season_units": "dB of field-mean linear gamma0",
    "s1_season_passes": 10, "s1_season_window": "2025-05-31/2025-09-28",
}
COLUMNS = ["s1_vh_min_transplant_db", "s1_vh_canopy_db", "s1_vh_rise_db", "s1_paddy_signature"]
PASS_COLUMNS = ["s1_observation_datetime", "source_image_id_s1", "s1_platform", "s1_instrument_mode",
                "s1_orbit_pass", "s1_relative_orbit_number", "s1_processing_level", "s1_units",
                "VV_mean_db", "VH_mean_db", "VV_minus_VH_db", "VV_VH_ratio_linear", "s1_valid_pixel_count"]


def radar_season_context(obs: pd.DataFrame, summary: pd.DataFrame | None) -> pd.DataFrame:
    """Per-row radar season context with an explicit status; never fills missing values."""
    out = pd.DataFrame(index=obs.index, columns=["s1_context_status", *COLUMNS], dtype=object)
    out["s1_context_status"] = "NOT_ACQUIRED_FOR_SEASON"
    if summary is None:
        return out
    table = summary.set_index("field_id")[["vh_min_transplant_db", "vh_canopy_db", "vh_rise_db", "paddy_s1"]]
    times = pd.to_datetime(obs.observation_datetime, utc=True)
    in_season = obs.year.astype(int).eq(S1_SEASON) & times.gt(S1_LAST_PASS)
    joined = table.reindex(obs.field_id.astype(str).to_numpy())
    joined.index = obs.index
    has_value = joined.vh_canopy_db.notna() & joined.vh_min_transplant_db.notna()
    rows = in_season & has_value
    out.loc[in_season & ~has_value, "s1_context_status"] = "INSUFFICIENT_RADAR_PIXELS"
    out.loc[rows, "s1_context_status"] = "SEASON_SUMMARY_AVAILABLE"
    for col, src in zip(COLUMNS, ["vh_min_transplant_db", "vh_canopy_db", "vh_rise_db", "paddy_s1"]):
        out.loc[rows, col] = joined.loc[rows, src]
    for key, value in S1_PROVENANCE.items():
        out[key] = None
        out.loc[rows, key] = value
    out["s1_paddy_signature"] = out["s1_paddy_signature"].astype("boolean")
    for col in COLUMNS[:3]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def radar_observation_context(obs: pd.DataFrame, passes: pd.DataFrame | None,
                              max_age_days: float = S1_MAX_AGE_DAYS) -> pd.DataFrame:
    """Latest per-date Sentinel-1 pass at or before each optical acquisition, per field.

    ``s1_observation_status`` is PASS_AVAILABLE, NO_PASS_WITHIN_<n>_DAYS (the archive has passes
    for the field, none in the window) or NOT_ACQUIRED. Missing radar is never filled.
    """
    out = pd.DataFrame(index=obs.index, columns=["s1_observation_status", "s1_available", "s1_age_days", *PASS_COLUMNS],
                       dtype=object)
    out["s1_available"] = False
    out["s1_observation_status"] = "NOT_ACQUIRED"
    if passes is None or passes.empty:
        return out
    times = pd.to_datetime(obs.observation_datetime, utc=True)
    by_field = {fid: g.assign(_t=pd.to_datetime(g.s1_observation_datetime, utc=True)).sort_values("_t")
                for fid, g in passes.groupby("field_id")}
    window = pd.Timedelta(days=max_age_days)
    for idx, field_id, t in zip(obs.index, obs.field_id.astype(str), times):
        g = by_field.get(field_id)
        if g is None:
            continue
        prior = g.loc[g._t <= t]
        if prior.empty or t - prior._t.iloc[-1] > window:
            out.at[idx, "s1_observation_status"] = f"NO_PASS_WITHIN_{int(max_age_days)}_DAYS"
            continue
        last = prior.iloc[-1]
        out.at[idx, "s1_observation_status"] = "PASS_AVAILABLE"
        out.at[idx, "s1_available"] = True
        out.at[idx, "s1_age_days"] = (t - last._t).total_seconds() / 86400
        for col in PASS_COLUMNS:
            out.at[idx, col] = last[col]
    out["s1_available"] = out["s1_available"].astype(bool)
    for col in ("s1_age_days", "VV_mean_db", "VH_mean_db", "VV_minus_VH_db", "VV_VH_ratio_linear"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    # Identifier and metadata cells without a pass are None (not NaN), so downstream code
    # that parses timestamps or compares orbits sees an explicit absence.
    for col in ("s1_observation_datetime", "source_image_id_s1", "s1_platform", "s1_instrument_mode", "s1_orbit_pass",
                "s1_relative_orbit_number", "s1_processing_level", "s1_units", "s1_valid_pixel_count"):
        out[col] = out[col].astype(object).where(out.s1_available, None)
    out["s1_polarizations"] = np.where(out.s1_available, "VV,VH", None)
    out["s1_collection"] = np.where(out.s1_available, "sentinel-1-rtc", None)
    return out
