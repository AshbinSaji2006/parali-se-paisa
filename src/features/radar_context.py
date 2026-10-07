"""Sentinel-1 field radar context from the committed 2025 VH season summary.

Source: ``data/real/derived/research/paddy_mask_s1_2025.parquet`` (``scripts/build_paddy_mask.py``),
built from Planetary Computer ``sentinel-1-rtc`` gamma0 (terrain-flattened) IW GRDH 1SDV scenes,
descending relative orbit 34, ten passes 2025-05-31..2025-09-28. Field means were taken in
linear power and converted to dB (10*log10); dB values are never averaged or divided.

These are season summaries, not per-date VV/VH observations: VV was not reduced and the
raw stack is excluded from Git. A row only receives the summary when its acquisition is
after the last radar pass, so the context is causal.
"""
from __future__ import annotations

import pandas as pd

S1_SEASON = 2025
S1_LAST_PASS = pd.Timestamp("2025-09-28T01:00:38Z")
S1_PROVENANCE = {
    "s1_product": "Sentinel-1 RTC gamma0 (Planetary Computer sentinel-1-rtc), IW GRDH 1SDV",
    "s1_platform": "SENTINEL-1A", "s1_orbit_pass": "DESCENDING", "s1_relative_orbit": 34,
    "s1_polarization": "VH", "s1_units": "dB of field-mean linear gamma0",
    "s1_passes": 10, "s1_window": "2025-05-31/2025-09-28",
}
COLUMNS = ["s1_vh_min_transplant_db", "s1_vh_canopy_db", "s1_vh_rise_db", "s1_paddy_signature"]


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
