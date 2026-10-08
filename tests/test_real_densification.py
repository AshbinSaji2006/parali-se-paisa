"""Offline checks for the dense real-data reductions (S2 local stack, per-date S1, weather)."""
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from scripts.process_real_sentinel2 import BAIS2_MIN_B04, field_statistics, observation_row


def _refl(values):
    return {band: np.asarray(values[band], dtype=np.float32) for band in ("B04", "B06", "B07", "B08", "B8A", "B12")}


def test_field_statistics_apply_v4_mask_range_and_bais2_red_floor():
    # Zone 1: three clear pixels (one with red below the BAIS2 floor) and one excluded pixel.
    zones = np.array([1, 1, 1, 1, 0])
    refl = _refl({"B04": [.04, .06, .002, .05, .05], "B06": [.2] * 5, "B07": [.3] * 5,
                  "B08": [.40, .44, .42, .40, .40], "B8A": [.35] * 5, "B12": [.15, .15, .15, 2.0, .15]})
    valid = np.array([True, True, True, True, True])  # pixel 4 fails the reflectance range (B12 > 1.5)
    stats = field_statistics(refl, valid, zones, 1)
    assert stats["counts"][1] == 3 and stats["zone_pixels"][1] == 4
    assert stats["bais2_counts"][1] == 2  # B04 = 0.002 < BAIS2_MIN_B04 is not a BAIS2 pixel
    assert BAIS2_MIN_B04 == 0.005
    ndvi = [(.40 - .04) / .44, (.44 - .06) / .50, (.42 - .002) / .422]
    assert np.isclose(stats["means"]["ndvi"][1], np.mean(ndvi))
    field = pd.Series({"field_id": "f", "area_ha": 0.16, "cropland_fraction": 1.0})
    row = observation_row(field, 1, stats, {"observation_datetime": "2025-10-20T05:42:51+00:00"})
    assert row["valid_pixel_count"] == 3 and row["observation_quality"] == "POOR"  # < 10 clear pixels
    assert row["scl_valid_classes"] == "4,5,6" and row["real_or_synthetic"] == "REAL"
    # Fewer than three clear pixels never produce an observation.
    assert observation_row(field, 1, {**stats, "counts": np.array([0, 2])}, {}) is None


def test_s1_field_means_average_linear_power_not_db():
    from rasterio.io import MemoryFile
    from scripts.process_real_sentinel1 import reduce_pass
    vv = np.array([[-1000, -2000, -1000]], dtype=np.int16)  # dB x 100: -10, -20, -10 dB
    vh = np.array([[-1500, -2500, -32768]], dtype=np.int16)  # third pixel is nodata in VH
    memory = MemoryFile()
    with memory.open(driver="GTiff", width=3, height=1, count=2, dtype="int16", crs="EPSG:32643",
                     transform=from_origin(0, 20, 20, 20), nodata=-32768) as dst:
        dst.write(np.stack([vv, vh]))
        dst.set_band_description(1, "VV_dB_x100"); dst.set_band_description(2, "VH_dB_x100")
    path = memory.name
    zones = np.array([[1, 1, 1]])
    stats = reduce_pass(path, zones, np.flatnonzero(zones.ravel()), 1)
    assert stats["count"][1] == 2  # a pixel missing either polarisation is excluded from both
    # Too few pixels for a field mean -> NaN (MIN_PIXELS = 3); recompute with the rule relaxed.
    assert np.isnan(stats["VV"][1])
    import scripts.process_real_sentinel1 as s1
    original = s1.MIN_PIXELS
    try:
        s1.MIN_PIXELS = 2
        stats = reduce_pass(path, zones, np.flatnonzero(zones.ravel()), 1)
    finally:
        s1.MIN_PIXELS = original
    assert np.isclose(10 * np.log10(stats["VV"][1]), 10 * np.log10((0.1 + 0.01) / 2))  # -12.60 dB, not -15 dB
    assert not np.isclose(10 * np.log10(stats["VV"][1]), -15.0)


def test_weather_derivations_never_zero_fill_missing_hours():
    from scripts.acquire_real_data import weather_derived
    hours = pd.date_range("2026-09-20T00:00Z", "2026-10-02T23:00Z", freq="h")
    frame = pd.DataFrame({"grid_id": 0, "latitude": 30.25, "longitude": 74.5, "timestamp": hours,
                          "temperature_2m_c": 25.0, "relative_humidity_2m_pct": 60.0,
                          "precipitation_mm": 0.0, "wind_speed_10m_ms": 2.0})
    frame.loc[frame.timestamp >= "2026-10-02T00:00Z", ["temperature_2m_c", "relative_humidity_2m_pct",
                                                       "precipitation_mm", "wind_speed_10m_ms"]] = np.nan
    hourly, daily = weather_derived(frame)
    last = hourly.iloc[-1]
    assert np.isnan(last.rain_previous_24h_mm) and np.isnan(last.rain_previous_7d_mm)
    day = daily.set_index(daily.timestamp.dt.strftime("%Y-%m-%d"))
    assert np.isnan(day.loc["2026-10-02", "precipitation_mm"]) and not day.loc["2026-10-02", "complete_day"]
    assert day.loc["2026-10-01", "precipitation_mm"] == 0.0 and day.loc["2026-10-01", "dry_days_previous_7d"] == 7
    assert np.isnan(day.loc["2026-09-25", "dry_days_previous_7d"])  # fewer than 7 days of record
    assert hourly.loc[hourly.timestamp == "2026-10-02T12:00Z", "dry_days_previous_7d"].iloc[0] == 7


def test_weak_labels_compare_with_previous_usable_observation():
    from scripts.build_real_products import _build_proxy_labels
    frame = pd.DataFrame([
        {"field_id": "f", "year": 2025, "observation_datetime": "2025-10-08T05:37Z", "NDVI": .80, "cropland_fraction": .9, "observation_quality": "GOOD"},
        {"field_id": "f", "year": 2025, "observation_datetime": "2025-10-13T05:37Z", "NDVI": .30, "cropland_fraction": .9, "observation_quality": "POOR"},
        {"field_id": "f", "year": 2025, "observation_datetime": "2025-10-18T05:38Z", "NDVI": .25, "cropland_fraction": .9, "observation_quality": "GOOD"},
    ])
    frame["observation_datetime"] = pd.to_datetime(frame["observation_datetime"], utc=True)
    labels = _build_proxy_labels(frame)
    assert labels.weak_label.tolist() == ["UNKNOWN", "UNKNOWN", "HARVESTED"]
    assert round(labels.evidence_window_days.iloc[2]) == 10  # window from the last usable date, not the cloudy one
    assert not labels.is_ground_truth.any()


def test_gradual_harvest_is_labelled_once_from_the_last_high_observation():
    from scripts.build_real_products import _build_proxy_labels
    ndvi = [.80, .62, .45, .30, .28]
    frame = pd.DataFrame([{"field_id": "f", "year": 2025, "observation_datetime": pd.Timestamp("2025-10-03T05:36Z") + pd.Timedelta(days=5 * i),
                           "NDVI": v, "cropland_fraction": .9, "observation_quality": "GOOD"} for i, v in enumerate(ndvi)])
    labels = _build_proxy_labels(frame)
    assert labels.weak_label.tolist() == ["UNKNOWN", "UNKNOWN", "UNKNOWN", "HARVESTED", "UNKNOWN"]
    harvested = labels.iloc[3]
    assert harvested.evidence_window_start == frame.observation_datetime.iloc[1]  # last NDVI >= 0.55 date
    assert round(harvested.evidence_window_days) == 10 and harvested.temporal_gap_category == "NORMAL"


def test_normalized_differences_skip_pixels_with_negative_bands():
    # Atmospheric over-correction can leave slightly negative red; such a pixel is kept for the band
    # mean but would give |NDVI| > 1, so it never enters the NDVI or NBR mean (v5).
    zones = np.array([1, 1, 1])
    refl = _refl({"B04": [-.004, .03, .04], "B06": [.2] * 3, "B07": [.3] * 3,
                  "B08": [.30, .40, .42], "B8A": [.35] * 3, "B12": [.15, -.01, .16]})
    stats = field_statistics(refl, np.array([True, True, True]), zones, 1)
    assert stats["counts"][1] == 3  # all pixels stay valid for the band means
    assert np.isclose(stats["means"]["B04"][1], np.mean([-.004, .03, .04]))
    ndvi = stats["means"]["ndvi"][1]
    assert np.isclose(ndvi, np.mean([(.40 - .03) / .43, (.42 - .04) / .46])) and -1 <= ndvi <= 1
    nbr = stats["means"]["nbr"][1]
    assert np.isclose(nbr, np.mean([(.30 - .15) / .45, (.42 - .16) / .58])) and -1 <= nbr <= 1
