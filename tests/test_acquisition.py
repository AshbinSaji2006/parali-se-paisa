import csv
import json
from pathlib import Path

import pytest

from src.data.acquire import run_acquisition
from src.data.common import load_config
from src.data.firms import load_firms_csv, normalize_firms_rows
from src.data.sentinel1 import normalize_s1_metadata
from src.data.sentinel2 import normalize_s2_metadata
from src.data.weather import normalize_weather

ROOT = Path(__file__).resolve().parents[1]


def test_acquisition_configuration_is_validated():
    cfg, root = load_config(ROOT / "config/pilot.yaml")
    assert root == ROOT
    assert cfg["acquisition"]["earth_engine"]["sentinel2_collection"] == "COPERNICUS/S2_SR_HARMONIZED"


def test_sentinel2_metadata_normalization():
    meta = normalize_s2_metadata({"system:id": "S2/test", "system:time_start": 0, "CLOUDY_PIXEL_PERCENTAGE": 18}, "COPERNICUS/S2_SR_HARMONIZED")
    assert meta["source_image_id"] == "S2/test"
    assert meta["acquisition_datetime"].startswith("1970-01-01")
    assert meta["cloud_percentage"] == 18
    assert "B12" in meta["bands"]


def test_sentinel1_metadata_gracefully_records_missing_vh():
    meta = normalize_s1_metadata({"system:index": "S1/one", "transmitterReceiverPolarisation": ["VV"]}, "COPERNICUS/S1_GRD")
    assert meta["has_vv"] is True
    assert meta["has_vh"] is False
    assert meta["orbit_pass"] is None


def test_firms_rows_validate_date_coordinates_and_remove_duplicates():
    row = {"latitude": "30.1", "longitude": "74.4", "acq_date": "2026-10-01", "acq_time": "530", "confidence": "nominal", "satellite": "NOAA-20", "instrument": "VIIRS", "frp": "1.2"}
    result = normalize_firms_rows([row, row, {**row, "latitude": "91"}, {**row, "acq_date": "bad-date"}], "test")
    assert result["points_loaded"] == 1
    assert len(result["points_rejected"]) == 3
    assert result["points"][0]["acquisition_datetime"].endswith("+00:00")
    assert result["points_rejected"][0]["reason"] == "duplicate_record"


def test_firms_fixture_malformed_row_is_reported():
    result = load_firms_csv(ROOT / "data/fixtures/demo/firms.csv", "DEMO_SYNTHETIC_FIXTURE")
    assert result["points_loaded"] == 1
    assert len(result["points_rejected"]) == 1


def test_weather_normalization_handles_missing_values_and_keeps_record_type():
    result = normalize_weather({"hourly": {"time": ["2026-10-01T00:00"], "temperature_2m": [None], "relative_humidity_2m": [55], "precipitation": [0], "wind_speed_10m": [8]}}, "fixture", "forecast")
    assert result["records_loaded"] == 1
    assert result["records"][0]["temperature_c"] is None
    assert result["records"][0]["record_type"] == "forecast"
    assert result["records"][0]["date"] == "2026-10-01"


def test_offline_acquisition_is_fixture_only_and_cache_idempotent():
    first = run_acquisition(ROOT / "config/pilot.yaml", offline=True)
    second = run_acquisition(ROOT / "config/pilot.yaml", offline=True)
    assert all(data["fixture"] is True for data in first["sources"].values())
    assert all(data["fixture"] is True for data in second["sources"].values())
    assert first["sources"]["firms"]["points_loaded"] == 1
    assert len(first["sources"]["firms"]["points"]) == len(second["sources"]["firms"]["points"]) == 1
    assert all(data["cache_hit"] is True for data in second["sources"].values())
    manifest_path = ROOT / "reports/acquisition_manifest.json"
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["fixture_mode"] is True
    assert saved["sources"]["sentinel2"]["images_accepted"][0]["source_image_id"].startswith("DEMO-")


def test_cached_json_reuses_producer(tmp_path):
    from src.data.common import cached_json
    calls = []
    producer = lambda: calls.append(1) or {"value": 2}
    assert cached_json(tmp_path, "same-input", producer) == ({"value": 2}, False)
    assert cached_json(tmp_path, "same-input", producer) == ({"value": 2}, True)
    assert calls == [1]


def test_invalid_date_range_rejected(tmp_path):
    p = tmp_path / "pilot.yaml"
    p.write_text("pilot:\n  aoi_bbox_wgs84: [0,0,1,1]\nacquisition:\n  date_start: '2026-02-02'\n  date_end: '2026-02-01'\n  aoi_bbox_wgs84: [0,0,1,1]\n  cloud_threshold_pct: 40\n", encoding="utf-8")
    with pytest.raises(ValueError, match="date_start"):
        load_config(p)
