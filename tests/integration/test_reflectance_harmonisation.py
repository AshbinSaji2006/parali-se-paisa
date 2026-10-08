"""Guard against the Sentinel-2 BOA_ADD_OFFSET regression (baseline >= 04.00 needs DN - 1000)."""
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
OBS = ROOT / "data" / "real" / "derived" / "features" / "sentinel2_field_observations.parquet"


@pytest.mark.skipif(not OBS.exists(), reason="real snapshot not built")
def test_offset_is_applied_and_green_paddy_ndvi_is_plausible():
    obs = pd.read_parquet(OBS)
    assert obs.processing_version.isin({"grid-aligned-20m-v3-boa-offset", "grid-aligned-20m-v4-bais2-red-floor",
                                       "grid-aligned-20m-v5-nd-nonnegative"}).all()
    assert (obs.loc[obs.processing_baseline >= 4.0, "boa_offset_dn"] == 1000).all()
    day = pd.to_datetime(obs.observation_datetime).dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")
    early = obs[day == "2023-10-04"]  # standing paddy before harvest
    # Without the offset, red reflectance is inflated by ~0.10 and this median falls to ~0.55.
    assert early.NDVI.median() > 0.7
    assert early.b04_mean.median() < 0.08
