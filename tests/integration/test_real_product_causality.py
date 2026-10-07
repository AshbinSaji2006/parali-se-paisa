"""Offline causal checks for real observation weather joins and weak labels."""
import pandas as pd

from scripts.build_real_products import _asof_weather, _build_proxy_labels


def test_weather_join_ignores_hours_after_satellite_acquisition():
    hourly = pd.DataFrame({
        "grid_id": [1, 1, 1],
        "timestamp": pd.to_datetime(["2023-10-04T04:00Z", "2023-10-04T05:00Z", "2023-10-04T06:00Z"], utc=True),
        "temperature_2m_c": [19.0, 20.0, 99.0],
        "relative_humidity_2m_pct": [70.0, 71.0, 1.0],
        "wind_speed_10m_ms": [2.0, 3.0, 99.0],
        "precipitation_mm": [0.0, 0.1, 100.0],
        "rain_previous_24h_mm": [1.0, 1.1, 100.0],
        "rain_previous_72h_mm": [2.0, 2.1, 100.0],
        "rain_previous_7d_mm": [3.0, 3.1, 100.0],
        "record_type": ["historical_reanalysis"] * 3,
    })
    joined = _asof_weather(hourly, 1, pd.Timestamp("2023-10-04T05:30Z"))
    assert joined["temperature_2m_c"] == 20.0
    assert joined["rain_previous_72h_mm"] == 2.1
    assert joined["weather_observation_datetime"] == "2023-10-04T05:00:00+00:00"


def test_weak_labels_do_not_bridge_crop_years_but_sown_needs_three_step_sequence():
    frame = pd.DataFrame([
        {"field_id": "cross-year", "year": 2023, "observation_datetime": "2023-10-01T00:00Z", "NDVI": .8, "cropland_fraction": .8, "observation_quality": "GOOD"},
        {"field_id": "cross-year", "year": 2024, "observation_datetime": "2024-10-01T00:00Z", "NDVI": .2, "cropland_fraction": .8, "observation_quality": "GOOD"},
        {"field_id": "valid-sequence", "year": 2024, "observation_datetime": "2024-10-01T00:00Z", "NDVI": .8, "cropland_fraction": .8, "observation_quality": "GOOD"},
        {"field_id": "valid-sequence", "year": 2024, "observation_datetime": "2024-10-10T00:00Z", "NDVI": .25, "cropland_fraction": .8, "observation_quality": "GOOD"},
        {"field_id": "valid-sequence", "year": 2024, "observation_datetime": "2024-10-20T00:00Z", "NDVI": .45, "cropland_fraction": .8, "observation_quality": "GOOD"},
    ])
    frame["observation_datetime"] = pd.to_datetime(frame["observation_datetime"], utc=True)
    labels = _build_proxy_labels(frame).set_index(["field_id", "observation_datetime"])
    assert labels.loc[("cross-year", pd.Timestamp("2024-10-01T00:00Z")), "weak_label"] == "UNKNOWN"
    assert labels.loc[("valid-sequence", pd.Timestamp("2024-10-10T00:00Z")), "weak_label"] == "HARVESTED"
    assert labels.loc[("valid-sequence", pd.Timestamp("2024-10-20T00:00Z")), "weak_label"] == "SOWN"


def test_weather_join_skips_unpublished_reanalysis_hours():
    # ERA5 latency leaves trailing hours with null values; they are not observations.
    hourly = pd.DataFrame({
        "grid_id": [1, 1],
        "timestamp": pd.to_datetime(["2026-10-01T23:00Z", "2026-10-02T23:00Z"], utc=True),
        "temperature_2m_c": [26.5, None], "relative_humidity_2m_pct": [60.0, None],
        "wind_speed_10m_ms": [2.0, None], "precipitation_mm": [0.0, None],
        "rain_previous_24h_mm": [0.0, 0.0], "rain_previous_72h_mm": [0.0, 0.0], "rain_previous_7d_mm": [0.0, 0.0],
        "record_type": ["historical_reanalysis"] * 2,
    })
    joined = _asof_weather(hourly, 1, pd.Timestamp("2026-10-03T05:36Z"))
    assert joined["weather_observation_datetime"] == "2026-10-01T23:00:00+00:00"
    assert joined["temperature_2m_c"] == 26.5
    assert joined["weather_available"] is False  # last published hour is more than 24 h old


def test_weak_label_records_its_evidence_window():
    frame = pd.DataFrame([
        {"field_id": "f", "year": 2023, "observation_datetime": "2023-10-04T05:36Z", "NDVI": .8, "cropland_fraction": .9, "observation_quality": "GOOD"},
        {"field_id": "f", "year": 2023, "observation_datetime": "2023-12-03T05:42Z", "NDVI": .2, "cropland_fraction": .9, "observation_quality": "GOOD"},
    ])
    frame["observation_datetime"] = pd.to_datetime(frame["observation_datetime"], utc=True)
    label = _build_proxy_labels(frame).iloc[1]
    assert label.weak_label == "HARVESTED" and not label.is_ground_truth
    assert label.temporal_gap_category == "LARGE" and round(label.evidence_window_days) == 60
    assert "ambiguous" in label.reason
