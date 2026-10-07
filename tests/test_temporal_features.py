from datetime import datetime, timedelta, timezone

import pytest

from src.features.temporal_features import build_temporal_rows


T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def observation(day, ndvi, nbr=None, bais=None, **kw):
    dt = T0 + timedelta(days=day)
    row = {"field_id": "F1", "season": "kharif", "year": 2026,
           "observation_datetime": dt.isoformat(), "source_image_id_s2": f"S2-{day}",
           "observation_quality": "LIMITED", "valid_pixel_count": 10, "valid_pixel_fraction": .6,
           "NDVI_mean": ndvi, "NBR_mean": nbr, "BAIS2_mean": bais,
           "VV_mean_db": None, "VH_mean_db": None, "VV_minus_VH_db": None,
           "VV_VH_ratio_linear": None, "s1_observation_datetime": None,
           "source_image_id_s1": None, "s1_instrument_mode": None,
           "s1_orbit_pass": None, "s1_relative_orbit_number": None,
           "fixture_or_real": "SYNTHETIC", "status_label": None}
    row.update(kw)
    return row


def build(rows, **settings):
    return build_temporal_rows(rows, settings)[0]


def test_previous_delta_peak_and_peak_age_math():
    rows = build([observation(0, .75, .6, .1), observation(5, .72, .55, .2), observation(10, .30, .25, .4)])
    assert rows[0]["NDVI_prev"] is None
    assert rows[1]["NDVI_prev"] == pytest.approx(.75)
    assert rows[1]["NDVI_delta"] == pytest.approx(-.03)
    assert rows[2]["NDVI_prev"] == pytest.approx(.72)
    assert rows[2]["NDVI_delta"] == pytest.approx(-.42)
    assert rows[2]["peak_NDVI_so_far"] == pytest.approx(.75)
    assert rows[2]["NDVI_drop_from_peak"] == pytest.approx(-.45)
    assert rows[2]["days_since_peak_NDVI"] == pytest.approx(10)


def test_all_indices_deltas_and_pct_change_zero_epsilon():
    rows = build([observation(0, .5, .2, .1), observation(1, .4, .1, .3), observation(2, .2, .05, .4)])
    assert rows[1]["NBR_delta"] == pytest.approx(-.1)
    assert rows[1]["BAIS2_delta"] == pytest.approx(.2)
    assert rows[1]["NBR_pct_change"] == pytest.approx(-.5)
    zero_rows = build([observation(0, 0, 0, 0), observation(1, .3, .1, .1)])
    assert zero_rows[1]["NDVI_pct_change"] is None
    assert zero_rows[1]["NBR_pct_change"] is None


def test_rolling_windows_include_current_and_std_population():
    rows = build([observation(0, .2, .2, .2), observation(1, .4, .4, .4), observation(2, .6, .6, .6)])
    assert rows[0]["NDVI_rolling_mean_2"] is None
    assert rows[1]["NDVI_rolling_mean_2"] == pytest.approx(.3)
    assert rows[2]["NDVI_rolling_mean_3"] == pytest.approx(.4)
    assert rows[2]["NDVI_rolling_std_3"] == pytest.approx((.08/3)**.5)


def test_slope_uses_actual_elapsed_days_and_multi_step_delta():
    rows = build([observation(0, .2, .1, 0), observation(4, .4, .2, .2), observation(13, .85, .7, .8)])
    assert rows[2]["NDVI_slope_last_3"] == pytest.approx(.05)
    assert rows[2]["NDVI_delta_2obs"] == pytest.approx(.65)


def test_sorting_group_reset_and_calendar_features():
    source = [observation(8, .3), observation(0, .2), observation(4, .25)]
    source.append(observation(10, .9, field_id="OTHER"))
    source.append(observation(11, .8, year=2027))
    rows = build(source)
    f1 = [r for r in rows if r["field_id"] == "F1" and r["year"] == 2026]
    assert [r["observation_number_in_season"] for r in f1] == [1, 2, 3]
    assert f1[-1]["days_since_first_observation_in_season"] == pytest.approx(8)
    assert next(r for r in rows if r["year"] == 2026 and r["field_id"] == "F1" and r["observation_number_in_season"] == 1)["NDVI_prev"] is None
    assert next(r for r in rows if r["field_id"] == "OTHER")["NDVI_prev"] is None
    assert next(r for r in rows if r["year"] == 2027)["NDVI_prev"] is None


def test_duplicate_timestamps_flagged_and_same_time_rows_do_not_see_each_other():
    rows, report = build_temporal_rows([observation(0, .2), observation(5, .5), observation(5, .7), observation(9, .4)])
    same = [r for r in rows if r["observation_datetime"] == (T0 + timedelta(days=5)).isoformat()]
    assert len(same) == 2 and all(r["temporal_duplicate_timestamp"] for r in same)
    assert all(r["NDVI_prev"] == pytest.approx(.2) for r in same)
    assert report["duplicate_timestamp_rows"] == 2
    assert report["warnings"]


def test_poor_observation_does_not_enter_history_but_limited_does():
    rows = build([observation(0, .2), observation(2, .8, observation_quality="POOR"), observation(4, .5)])
    assert rows[2]["NDVI_prev"] == pytest.approx(.2)
    assert rows[2]["temporal_previous_quality"] == "LIMITED"
    assert rows[2]["temporal_history_count"] == 1


def test_missing_index_is_not_imputed_and_metric_lag_skips_null():
    rows = build([observation(0, .2, .3, .1), observation(2, None, None, .2), observation(5, .5, .6, None)])
    assert rows[1]["NDVI_prev"] == pytest.approx(.2)
    assert rows[2]["NDVI_prev"] == pytest.approx(.2)
    assert rows[2]["NBR_prev"] == pytest.approx(.3)
    assert rows[2]["BAIS2_prev"] == pytest.approx(.2)
    assert rows[2]["BAIS2_mean"] is None


def test_radar_requires_compatible_pass_orbit_and_distinct_prior_acquisition():
    def radar(day, vv, pass_dir="ASCENDING", orbit=42):
        return {"s1_observation_datetime": (T0 + timedelta(days=day)).isoformat(),
                "source_image_id_s1": f"S1-{day}", "s1_instrument_mode": "IW", "s1_orbit_pass": pass_dir,
                "s1_relative_orbit_number": orbit, "VV_mean_db": vv, "VH_mean_db": vv-5,
                "VV_minus_VH_db": 5, "VV_VH_ratio_linear": 3.0}
    rows = build([observation(1, .2, **radar(0, -10)), observation(4, .3, **radar(3, -12)),
                  observation(8, .4, **radar(7, -20, pass_dir="DESCENDING"))])
    assert rows[0]["radar_temporal_comparison_available"] is False
    assert rows[1]["VV_prev_db"] == pytest.approx(-10)
    assert rows[1]["VV_delta_db"] == pytest.approx(-2)
    assert rows[1]["VV_minus_VH_delta_db"] == pytest.approx(0)
    assert rows[2]["radar_temporal_comparison_available"] is False
    assert rows[2]["VV_delta_db"] is None


def test_gaps_are_configurable_and_large_gaps_reported():
    rows, report = build_temporal_rows([observation(0, .2), observation(15, .3), observation(50, .4)],
                                       {"moderate_gap_days": 10, "large_gap_days": 30})
    assert rows[1]["temporal_gap_category"] == "MODERATE"
    assert rows[2]["temporal_gap_category"] == "LARGE"
    assert report["large_gap_count"] == 1


def test_same_prefix_features_unchanged_after_appending_future_rows():
    prefix = [observation(0, .7, .6, .1, **_radar(0, -10)), observation(4, .65, .55, .2, **_radar(4, -11)),
              observation(9, .3, .2, .5, **_radar(9, -15))]
    future = [observation(13, .95, .9, -.2, **_radar(13, -4), recent_fire_24h=True, rain_72h=999),
              observation(22, .99, .99, -.5, **_radar(22, -2))]
    before, after = build(prefix), build(prefix + future)
    for a, b in zip(before, after[:len(before)]):
        assert a == b


def _radar(day, vv):
    return {"s1_observation_datetime": (T0 + timedelta(days=day)).isoformat(),
            "source_image_id_s1": f"S1-{day}", "s1_instrument_mode": "IW", "s1_orbit_pass": "ASCENDING",
            "s1_relative_orbit_number": 42, "VV_mean_db": vv, "VH_mean_db": vv-5,
            "VV_minus_VH_db": 5, "VV_VH_ratio_linear": 3.0}
