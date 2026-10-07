import json
import math
from datetime import timedelta
from pathlib import Path

import pytest
from pyproj import CRS, Transformer
from shapely.geometry import box, Point
from shapely.ops import transform

from src.features.aggregation import aggregate_s2_observation
from src.features.build_features import build_feature_rows, run_feature_build
from src.features.radar_features import aggregate_s1_observation
from src.features.spatial_features import firms_features
from src.features.temporal_context import parse_datetime, select_s1_asof, weather_features
from src.features.vegetation_indices import ndvi, nbr, bais2
from src.geo.fields import process_fields

ROOT = Path(__file__).resolve().parents[1]
RAW_PIXEL = {"B2":500,"B3":700,"B4":1000,"B6":3000,"B7":4000,"B8":7000,"B8A":6500,"B11":2500,"B12":1500}


def test_ndvi_exact_calculation_and_zero_denominator():
    assert ndvi(0.7, 0.1) == pytest.approx(0.75)
    assert ndvi(0, 0) is None
    assert ndvi(0.2, -0.2) is None


def test_nbr_exact_calculation_and_zero_denominator():
    assert nbr(0.65, 0.15) == pytest.approx(0.625)
    assert nbr(0.1, -0.1) is None


def test_bais2_exact_published_formula_and_undefined_domain():
    b4, b6, b7, b8a, b12 = 0.1, 0.3, 0.4, 0.5, 0.2
    expected = (1 - math.sqrt((b6 * b7 * b8a) / b4)) * (((b12 - b8a) / math.sqrt(b12 + b8a)) + 1)
    assert bais2(b4, b6, b7, b8a, b12) == pytest.approx(expected, rel=1e-12)
    assert bais2(0, b6, b7, b8a, b12) is None
    assert bais2(b4, b6, b7, b8a, -b8a) is None


def test_scaled_reflectance_bais2_matches_unit_reflectance_formula():
    raw = {"field_id":"F","value_scale":0.0001,"pixels":[RAW_PIXEL]}
    unit = {"field_id":"F","value_scale":1,"pixels":[{k:v*0.0001 for k,v in RAW_PIXEL.items()}]}
    raw_result, unit_result = aggregate_s2_observation(raw), aggregate_s2_observation(unit)
    assert raw_result["BAIS2_mean"] == pytest.approx(unit_result["BAIS2_mean"], rel=1e-12)
    assert raw_result["NDVI_mean"] == pytest.approx(0.75)


def test_field_statistics_cloud_mask_and_valid_fraction():
    obs = {"value_scale":0.0001,"pixels":[RAW_PIXEL,{**RAW_PIXEL,"B4":1200,"B8":6800},{**RAW_PIXEL,"cloudy":True},{**RAW_PIXEL,"valid":False}]}
    result = aggregate_s2_observation(obs)
    assert result["valid_pixel_count"] == 2
    assert result["total_pixel_count"] == 4
    assert result["valid_pixel_fraction"] == pytest.approx(0.5)
    assert result["cloud_fraction"] == pytest.approx(0.25)
    assert result["NDVI_mean"] == pytest.approx((0.75 + 0.7) / 2)
    assert result["NDVI_median"] == pytest.approx(0.725)
    assert result["NDVI_std"] == pytest.approx(0.025)
    assert result["NDVI_min"] == pytest.approx(0.7)
    assert result["NDVI_max"] == pytest.approx(0.75)
    assert result["B2_mean"] == pytest.approx(0.05)


def test_earth_engine_field_statistics_bundle_uses_shared_optical_schema():
    summary = {"indices": {name:{"mean":0.2,"median":0.21,"std":0.03,"min":0.1,"max":0.3} for name in ("NDVI","NBR","BAIS2")},
               "bands": {band:{"mean":0.15} for band in ("B2","B3","B4","B6","B7","B8","B8A","B11","B12")},
               "valid_pixel_count":8,"total_pixel_count":10,"cloud_pixel_count":1}
    result = aggregate_s2_observation({"field_statistics":summary})
    assert result["NDVI_mean"] == pytest.approx(0.2)
    assert result["BAIS2_median"] == pytest.approx(0.21)
    assert result["B6_mean"] == pytest.approx(0.15)
    assert result["valid_pixel_fraction"] == pytest.approx(0.8)
    assert result["cloud_fraction"] == pytest.approx(0.1)
    with pytest.raises(ValueError, match="inconsistent pixel counts"):
        aggregate_s2_observation({"field_statistics":{"valid_pixel_count":2,"total_pixel_count":1}})


def test_s2_empty_and_zero_denominator_samples_do_not_invent_indices():
    empty = aggregate_s2_observation({"pixels":[]})
    assert empty["valid_pixel_count"] == 0
    assert empty["valid_pixel_fraction"] is None
    zero = aggregate_s2_observation({"pixels":[{**RAW_PIXEL,"B4":0,"B8":0,"B8A":0,"B12":0}]})
    assert zero["NDVI_mean"] is None
    assert zero["NBR_mean"] is None
    assert zero["BAIS2_mean"] is None


def test_radar_db_means_difference_and_linear_power_ratio():
    radar = aggregate_s1_observation({"VV_dB":[-10,-20],"VH_dB":[-15,-25]})
    assert radar["VV_mean_db"] == pytest.approx(-15)
    assert radar["VH_mean_db"] == pytest.approx(-20)
    assert radar["VV_minus_VH_db"] == pytest.approx(5)
    expected_ratio = ((10**(-10/10) + 10**(-20/10))/2) / ((10**(-15/10) + 10**(-25/10))/2)
    assert radar["VV_VH_ratio_linear"] == pytest.approx(expected_ratio)
    assert radar["VV_VH_ratio_linear"] != pytest.approx(-15 / -20)


def test_radar_handles_scalar_summary_and_missing_vh():
    radar = aggregate_s1_observation({"VV_mean_db":-11.0,"VH_dB":None})
    assert radar["VV_mean_db"] == pytest.approx(-11)
    assert radar["VH_mean_db"] is None
    assert radar["VV_minus_VH_db"] is None
    assert radar["VV_VH_ratio_linear"] is None
    assert radar["missing_vh"] is True
    assert aggregate_s1_observation(None)["missing_vh"] is True
    summary = aggregate_s1_observation({"VV_mean_db":-10,"VH_mean_db":-20})
    assert summary["VV_VH_ratio_linear"] is None
    reduced = aggregate_s1_observation({"VV_mean_db":-10,"VH_mean_db":-20,"VV_VH_ratio_linear_mean":7.5})
    assert reduced["VV_VH_ratio_linear"] == pytest.approx(7.5)


def _field_and_metric():
    geom = box(74.52, 30.02, 74.522, 30.022)
    center = geom.centroid
    metric = CRS.from_proj4(f"+proj=aeqd +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m +no_defs")
    fwd = Transformer.from_crs("EPSG:4326", metric, always_xy=True).transform
    back = Transformer.from_crs(metric, "EPSG:4326", always_xy=True).transform
    geom_m = transform(fwd, geom)
    y = (geom_m.bounds[1] + geom_m.bounds[3]) / 2
    def at_distance(distance):
        return transform(back, Point(geom_m.bounds[2] + distance, y))
    return geom, at_distance


def _fire(point, stamp):
    return {"latitude":point.y,"longitude":point.x,"acquisition_datetime":stamp,"source":"test"}


def test_firms_inside_buffers_nearest_and_asof_time_windows():
    geom, at_distance = _field_and_metric()
    ref = "2026-10-05T12:00:00+00:00"
    points = [_fire(geom.centroid,"2026-10-05T11:00:00+00:00"),
              _fire(at_distance(450),"2026-10-04T12:00:00+00:00"),
              _fire(at_distance(850),"2026-10-03T12:00:00+00:00"),
              _fire(at_distance(200),"2026-10-05T12:01:00+00:00")]
    result = firms_features(geom, points, ref, available=True)
    assert result["firms_points_within_field"] == 1
    assert result["firms_points_within_500m"] == 2
    assert result["firms_points_within_1km"] == 3
    assert result["nearest_firms_distance_m"] == pytest.approx(0, abs=0.01)
    assert result["recent_fire_24h"] is True
    assert result["recent_fire_72h"] is True
    assert firms_features(geom, points, ref, available=False)["recent_fire_24h"] is None


def test_firms_future_only_points_do_not_leak():
    geom, _ = _field_and_metric()
    point = _fire(geom.centroid,"2026-10-05T12:00:01+00:00")
    result = firms_features(geom, [point], "2026-10-05T12:00:00+00:00", available=True)
    assert result["firms_points_within_field"] == 0
    assert result["nearest_firms_distance_m"] is None
    assert result["recent_fire_24h"] is False
    assert result["recent_fire_72h"] is False


def test_firms_window_open_left_boundary():
    geom, _ = _field_and_metric()
    point = _fire(geom.centroid,"2026-10-04T12:00:00+00:00")
    result = firms_features(geom,[point],"2026-10-05T12:00:00+00:00",available=True)
    assert result["recent_fire_24h"] is False
    assert result["recent_fire_72h"] is True


def test_weather_24h_72h_aggregation_and_no_future_leak():
    ref = "2026-10-03T06:00:00+00:00"
    records = [
        {"timestamp":"2026-10-01T00:00:00+00:00","precipitation_mm":5,"humidity_pct":55,"temperature_c":19,"wind_speed":8,"record_type":"historical"},
        {"timestamp":"2026-10-02T12:00:00+00:00","precipitation_mm":1,"humidity_pct":60,"temperature_c":20,"wind_speed":9,"record_type":"historical"},
        {"timestamp":"2026-10-03T03:00:00+00:00","precipitation_mm":2,"humidity_pct":62,"temperature_c":21,"wind_speed":10,"record_type":"historical"},
        {"timestamp":"2026-10-03T07:00:00+00:00","precipitation_mm":100,"humidity_pct":99,"temperature_c":99,"wind_speed":99,"record_type":"forecast"},
    ]
    result = weather_features(records, ref)
    assert result["rain_24h"] == pytest.approx(3)
    assert result["rain_72h"] == pytest.approx(8)
    assert result["humidity_pct"] == pytest.approx(62)
    assert result["temperature_c"] == pytest.approx(21)
    assert result["wind_speed"] == pytest.approx(10)
    assert result["weather_record_type"] == "historical"
    assert result["weather_window_end"] == ref
    retroactive_forecast = {"timestamp":"2026-10-03T05:00:00+00:00","precipitation_mm":77,"record_type":"forecast","forecast_issued_at":"2026-10-03T06:01:00+00:00"}
    assert weather_features([retroactive_forecast],ref)["rain_24h"] is None
    boundary = weather_features([{"timestamp":"2026-09-30T06:00:00+00:00","precipitation_mm":77}], ref)
    assert boundary["rain_72h"] is None
    empty_values = weather_features([{"timestamp":ref,"precipitation_mm":None,"humidity_pct":None,"temperature_c":None,"wind_speed":None}],ref)
    assert empty_values["weather_available"] is False


def test_s1_asof_selects_latest_prior_within_lookback_and_same_mode():
    candidates = [
        {"source_image_id":"prior","acquisition_datetime":"2026-10-02T00:00:00Z","instrument_mode":"IW","polarizations":["VV"]},
        {"source_image_id":"future","acquisition_datetime":"2026-10-04T00:00:01Z","instrument_mode":"IW","polarizations":["VV","VH"]},
        {"source_image_id":"wrong-mode","acquisition_datetime":"2026-10-03T12:00:00Z","instrument_mode":"EW","polarizations":["VV"]},
        {"source_image_id":"too-old","acquisition_datetime":"2026-09-01T00:00:00Z","instrument_mode":"IW","polarizations":["VV"]},
    ]
    chosen = select_s1_asof(candidates,"2026-10-04T00:00:00Z",lookback_days=12)
    assert chosen["source_image_id"] == "prior"
    assert select_s1_asof(candidates,"2026-10-04T00:00:00Z",lookback_days=1) is None


def test_quality_categories_make_poor_and_missing_inputs_explicit():
    from src.features.build_features import _quality
    poor, flags = _quality({"valid_pixel_count":0,"valid_pixel_fraction":0,"cloud_fraction":1},None,aggregate_s1_observation(None),{"weather_available":False},{"firms_available":False})
    assert poor == "POOR"
    assert "s1_missing" in flags and "weather_missing" in flags and "firms_unavailable" in flags
    limited, flags = _quality({"valid_pixel_count":1,"valid_pixel_fraction":0.5,"cloud_fraction":0},None,aggregate_s1_observation(None),{"weather_available":True},{"firms_available":True})
    assert limited == "LIMITED"


def test_complete_synthetic_field_time_pipeline_and_quality_report():
    process_fields(ROOT / "config/pilot.yaml")
    rows, report = run_feature_build(ROOT / "config/pilot.yaml")
    assert len(rows) == 6
    assert report["number_of_fields"] == 4
    assert report["number_of_field_time_rows"] == 6
    assert report["synthetic_rows"] == 6 and report["real_rows"] == 0
    assert report["status_label_populated_rows"] == 0
    assert report["number_missing_s1"] == 2
    assert report["number_missing_vh"] == 1
    by_id = {x["source_image_id_s2"]:x for x in rows}
    assert by_id["SYNTH-S2-A1"]["rain_24h"] == pytest.approx(3)
    assert by_id["SYNTH-S2-A1"]["rain_72h"] == pytest.approx(8)
    assert by_id["SYNTH-S2-A1"]["weather_record_type"] == "historical"
    assert by_id["SYNTH-S2-A1"]["s1_observation_datetime"] <= by_id["SYNTH-S2-A1"]["observation_datetime"]
    assert by_id["SYNTH-S2-A1"]["source_image_id_s1"] == "SYNTH-S1-A1"
    assert by_id["SYNTH-S2-B1"]["source_image_id_s1"] == "SYNTH-S1-B1"
    assert by_id["SYNTH-S2-A2"]["missing_vh"] is True
    assert by_id["SYNTH-S2-C1"]["s1_available"] is False
    assert by_id["SYNTH-S2-C1"]["VV_mean_db"] is None
    assert all(r["status_label"] is None for r in rows)
    for row in rows:
        if row["s1_observation_datetime"]:
            assert row["s1_observation_datetime"] <= row["observation_datetime"]
    saved = list(csv_rows(ROOT / "data/processed/features/field_features.csv"))
    assert len(saved) == 6
    qreport = json.loads((ROOT / "reports/feature_quality_report.json").read_text(encoding="utf-8"))
    assert qreport["quality_category_counts"] == {"GOOD":3,"LIMITED":3}
    assert qreport["nan_rate"]["VH_mean_db"] == pytest.approx(3/6)


def csv_rows(path):
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)
