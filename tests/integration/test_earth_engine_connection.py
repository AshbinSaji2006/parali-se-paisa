import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(os.getenv("RUN_EXTERNAL_INTEGRATION") != "1", reason="set RUN_EXTERNAL_INTEGRATION=1 to query Earth Engine")
def test_earth_engine_small_pilot_query():
    import ee
    from src.data.common import load_config

    config, _ = load_config("config/pilot.yaml")
    project = os.getenv("EE_PROJECT")
    ee.Initialize(project=project) if project else ee.Initialize()
    from src.data.sentinel2 import query_sentinel2
    from src.data.sentinel1 import query_sentinel1
    s2, s1 = query_sentinel2(config), query_sentinel1(config)
    assert s2["images_queried"] >= 0
    assert s1["images_queried"] >= 0
