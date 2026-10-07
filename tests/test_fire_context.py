"""Fire context must be causal, coverage-aware proximity context."""
import pandas as pd

from src.features.fire_context import bais2_stability, firms_context, modis_burned_area_context


def _obs(when="2024-11-27T05:41Z"):
    return pd.DataFrame({"observation_datetime": [pd.Timestamp(when)], "centroid_lat": [30.30], "centroid_lon": [74.50]})


def _fires(rows):
    base = {"latitude": 30.30, "longitude": 74.50, "sensor": "VIIRS_NOAA20", "type": 0.0, "record_type": "ARCHIVE_YEARLY"}
    return pd.DataFrame([{**base, **r} for r in rows]).assign(acq_date=lambda d: pd.to_datetime(d.acq_date))


def test_detections_after_acquisition_or_far_away_are_not_counted():
    fires = _fires([
        {"acq_date": "2024-11-27", "acq_time": 530},                      # 05:30 UTC, before 05:41 image
        {"acq_date": "2024-11-27", "acq_time": 800},                      # after the image
        {"acq_date": "2024-11-20", "acq_time": 800, "latitude": 30.40},   # ~11 km away
        {"acq_date": "2024-11-20", "acq_time": 800, "type": 2.0},         # static land source
        {"acq_date": "2024-11-20", "acq_time": 800, "sensor": "MODIS"},
    ])
    row = firms_context(_obs(), fires).iloc[0]
    assert row.firms_coverage_status == "COMPLETE"
    assert row.firms_viirs_detections_near_field == 1
    assert row.firms_modis_detections_near_field == 1
    assert row.firms_latest_detection_datetime == "2024-11-27T05:30:00+00:00"


def test_uncovered_window_is_null_not_zero_and_partial_is_flagged():
    fires = _fires([{"acq_date": "2026-10-01", "acq_time": 800, "record_type": "NRT_7DAY", "latitude": 31.0}])
    uncovered = firms_context(_obs("2025-06-01T05:00Z"), fires).iloc[0]
    assert uncovered.firms_coverage_status == "NOT_COVERED"
    assert pd.isna(uncovered.firms_viirs_detections_near_field)
    partial = firms_context(_obs("2026-10-03T05:36Z"), fires).iloc[0]
    assert partial.firms_coverage_status == "PARTIAL" and partial.firms_viirs_detections_near_field == 0


def test_burned_area_uses_days_strictly_before_acquisition_and_reports_coverage():
    products = pd.DataFrame({"product_year": [2024], "product_start_doy": [306], "product_end_doy": [335]})
    pixels = pd.DataFrame({"burn_date": ["2024-11-20", "2024-11-27"], "latitude": [30.30, 30.30], "longitude": [74.50, 74.50]})
    row = modis_burned_area_context(_obs(), pixels, products).iloc[0]
    assert row.modis_ba_coverage_status == "PARTIAL"  # granule starts 1 Nov; window starts 28 Oct
    assert row.modis_ba_burned_pixels_near_field == 1 and row.modis_ba_latest_burn_date == "2024-11-20"
    assert row.modis_ba_availability.startswith("RETROSPECTIVE")
    assert pd.isna(modis_burned_area_context(_obs("2025-11-02T05:39Z"), pixels, products).iloc[0].modis_ba_burned_pixels_near_field)


def test_bais2_pixel_artefact_is_flagged_against_band_mean_recomputation():
    bands = {"b04_mean": .042, "b06_mean": .25, "b07_mean": .30, "b08_mean": .33, "b8a_mean": .34, "b12_mean": .16}
    frame = pd.DataFrame([{**bands, "BAIS2": .09}, {**bands, "BAIS2": -16.3}])
    flags = bais2_stability(frame)
    assert flags.BAIS2_quality.tolist() == ["OK", "UNSTABLE_PIXEL_ARTEFACT"]
