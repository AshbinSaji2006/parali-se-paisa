"""Local-only integration checks; this module never makes network requests."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "data" / "real"
REQUIRED = [
    REAL / "boundaries" / "sri_muktsar_sahib_adm2.geojson",
    REAL / "fields" / "fields_of_the_world_muktsar.parquet",
    REAL / "landcover" / "worldcover_muktsar.tif",
    REAL / "derived" / "features" / "sentinel2_field_observations.parquet",
]
pytestmark = pytest.mark.skipif(not all(p.exists() for p in REQUIRED), reason="Real acquisitions are not present locally")


def test_real_boundary_and_research_fields_are_valid():
    boundary = gpd.read_file(REQUIRED[0])
    fields = gpd.read_parquet(REQUIRED[1])
    assert len(boundary) == 1 and boundary.crs.to_epsg() == 4326
    assert boundary.geometry.iloc[0].is_valid and "Muktsar" in boundary.district_name_source.iloc[0]
    assert boundary.area_km2_epsg32643.iloc[0] > 1000
    assert len(fields) >= 100 and fields.crs.to_epsg() == 4326
    assert fields.geometry.is_valid.all()
    assert fields.area_ha.between(0.2, 15).all()
    assert fields.boundary_type.eq("RESEARCH_FIELD_BOUNDARY").all()
    assert fields.real_or_synthetic.eq("REAL").all()


def test_worldcover_and_sentinel2_measurements_are_real_and_plausible():
    with rasterio.open(REQUIRED[2]) as ds:
        assert ds.crs is not None and ds.count == 1
        assert 40 in np.unique(ds.read(1))
    obs = pd.read_parquet(REQUIRED[3])
    assert len(obs) > 0 and obs.field_id.nunique() >= 100
    assert obs.real_or_synthetic.eq("REAL").all()
    assert obs.scene_id.notna().all() and obs.source_item_url.notna().all()
    assert obs.valid_pixel_count.gt(0).all()
    assert obs.NDVI.dropna().between(-1, 1).all()
    assert obs.NBR.dropna().between(-1, 1).all()
    assert np.isfinite(obs.BAIS2.dropna()).all()
    assert obs.observation_datetime.notna().all()
    assert obs.reflectance_scale.eq(0.0001).all()


def test_real_outputs_have_no_synthetic_or_demo_records():
    for path in REAL.rglob("*.parquet"):
        frame = pd.read_parquet(path)
        for column in ("real_or_synthetic", "fixture_or_real", "demo_or_real"):
            if column in frame:
                assert not frame[column].astype(str).str.casefold().isin({"synthetic", "demo", "synthetic_as_real"}).any(), path


def test_temporal_rows_are_chronological_and_proxy_labels_disclaim_ground_truth():
    path = REAL / "derived" / "features" / "real_temporal_features.parquet"
    labels = REAL / "derived" / "labels" / "real_weak_labels.parquet"
    if not path.exists() or not labels.exists(): pytest.skip("Temporal products are not built yet")
    temporal = pd.read_parquet(path)
    for _, rows in temporal.groupby("field_id"):
        times = pd.to_datetime(rows.observation_datetime, utc=True)
        assert times.is_monotonic_increasing
    label_rows = pd.read_parquet(labels)
    assert label_rows.label_source.eq("REAL_S2_HEURISTIC_PROXY").all()
    assert label_rows.confidence.eq("LOW").all()


def test_api_real_mode_reads_real_snapshot_without_demo_database(monkeypatch):
    snapshot = REAL / "derived" / "app_snapshot.json"
    if not snapshot.exists(): pytest.skip("Real application snapshot is not built yet")
    monkeypatch.setenv("DATA_MODE", "real")
    from src.api.routes.product import product
    payload = product(request=None, session=None)
    assert payload["data_mode"] == "REAL"
    assert payload["fields"]
    assert all(f["provenance"] == "REAL_RESEARCH_BOUNDARY" for f in payload["fields"])
    assert payload["notice"].find("no ground truth") >= 0
