from __future__ import annotations

from copy import deepcopy
import pytest

from src.dispatch.eligibility import check_eligibility
from src.dispatch.models import Baler, DispatchField
from src.dispatch.optimizer import load_dispatch_config, optimize_dispatch
from src.dispatch.travel import FixtureMatrixProvider, GeodesicDistanceProvider, haversine_km


def field(field_id="F-1", **updates):
    data = {"field_id": field_id, "latitude": 30.02, "longitude": 74.52, "area_ha": 2.0,
            "field_status": "HARVESTED", "field_status_source": "RULE-BASED STATUS CANDIDATE",
            "field_status_confidence": "MODERATE", "harvest_evidence_state": "CANDIDATE",
            "estimated_straw_tonnes": 12.0, "burn_risk_score": 0.4, "burn_risk_level": "MEDIUM",
            "risk_method": "RULE_ENGINE_V1", "weather_suitability": "DRY",
            "weather_source": "SYNTHETIC_FIXTURE", "observation_quality": "GOOD", "provenance": "SYNTHETIC"}
    data.update(updates)
    return DispatchField(**data)


def baler(baler_id="B-1", **updates):
    data = {"baler_id": baler_id, "name": f"DEMO {baler_id}", "latitude": 30.02, "longitude": 74.52,
            "status": "AVAILABLE", "working_start": "08:00", "working_end": "17:00",
            "service_rate_acres_per_hour": 1.0, "daily_capacity_acres": 20.0,
            "max_straw_capacity_tonnes": 30.0, "demo_or_real": "DEMO", "source": "FIXTURE"}
    data.update(updates)
    return Baler(**data)


def test_ortools_assigns_eligible_field_once():
    result = optimize_dispatch([field()], [baler(), baler("B-2", latitude=30.025)])
    assert result.method == "ORTOOLS_V1"
    assigned = [s.field_id for r in result.baler_routes for s in r.stops]
    assert assigned == ["F-1"]
    stop = result.baler_routes[0].stops[0]
    assert stop.field_status == "HARVESTED"
    assert stop.field_status_source == "RULE-BASED STATUS CANDIDATE"
    assert stop.field_status_confidence == "MODERATE"
    assert stop.risk_method == "RULE_ENGINE_V1"
    assert stop.observation_quality == "GOOD"
    assert not result.unserved_fields


def test_service_time_uses_configured_acres_per_hour():
    result = optimize_dispatch([field()], [baler()])
    route = result.baler_routes[0]
    assert route.estimated_service_minutes == 297
    assert route.estimated_travel_minutes is None
    assert route.route_duration_basis == "SERVICE_ONLY_DISTANCE_NOT_TIME"


def test_area_capacity_drops_field_with_reason():
    result = optimize_dispatch([field()], [baler(daily_capacity_acres=4.0)])
    assert result.baler_routes == []
    assert result.unserved_fields[0].reason == "CAPACITY_EXCEEDED"


def test_straw_capacity_drops_field_with_reason():
    result = optimize_dispatch([field()], [baler(max_straw_capacity_tonnes=10)])
    assert result.unserved_fields[0].reason == "CAPACITY_EXCEEDED"


def test_working_hours_drop_field_with_reason():
    result = optimize_dispatch([field()], [baler(working_end="10:00")])
    assert result.unserved_fields[0].reason == "WORKING_HOURS_EXCEEDED"


def test_unavailable_baler_keeps_field_unserved():
    result = optimize_dispatch([field()], [baler(status="BUSY")])
    assert result.unserved_fields[0].reason == "NO_AVAILABLE_BALER"


def test_high_risk_field_wins_single_baler_capacity():
    fields = [field("LOW", latitude=30.02, longitude=74.52, burn_risk_score=0.1),
              field("HIGH", latitude=30.02, longitude=74.52, burn_risk_score=0.95)]
    result = optimize_dispatch(fields, [baler(daily_capacity_acres=5.0)])
    assert [s.field_id for r in result.baler_routes for s in r.stops] == ["HIGH"]
    assert result.unserved_fields[0].field_id == "LOW"


def test_distance_limit_is_hard_constraint():
    config = deepcopy(load_dispatch_config())
    config["constraints"]["maximum_route_distance_km"] = 1.0
    result = optimize_dispatch([field(latitude=30.2)], [baler()], config=config)
    assert result.unserved_fields[0].reason == "DISTANCE_LIMIT"


def test_unknown_weather_policy_block():
    config = deepcopy(load_dispatch_config())
    config["weather"]["unknown_policy"] = "BLOCK"
    result = optimize_dispatch([field(weather_suitability="UNKNOWN")], [baler()], config=config)
    assert result.unserved_fields[0].reason == "WEATHER_UNKNOWN_BLOCKED_BY_POLICY"


def test_unknown_weather_policy_warns_without_fake_forecast():
    result = optimize_dispatch([field(weather_suitability="UNKNOWN", weather_source="UNAVAILABLE")], [baler()])
    assert result.baler_routes
    assert "Weather suitability is unknown" in result.eligibility[0].warnings[0]


def test_unsuitable_weather_blocks_dispatch():
    result = optimize_dispatch([field(weather_suitability="UNSUITABLE")], [baler()])
    assert result.unserved_fields[0].reason == "WEATHER_UNSUITABLE"


def test_poor_observation_quality_is_not_eligible():
    result = optimize_dispatch([field(observation_quality="LIMITED")], [baler()])
    assert result.unserved_fields[0].reason == "OBSERVATION_QUALITY_UNACCEPTABLE"


def test_harvest_candidate_requires_supported_confidence():
    result = optimize_dispatch([field(field_status_confidence="LOW")], [baler()])
    assert result.unserved_fields[0].reason == "HARVEST_EVIDENCE_INSUFFICIENT"


def test_synthetic_test_model_is_never_dispatch_eligible():
    result = optimize_dispatch([field(field_status_source="SYNTHETIC_TEST_MODEL")], [baler()])
    assert "UNTRUSTED_SYNTHETIC_MODEL" in result.unserved_fields[0].details


def test_missing_location_is_reported():
    result = optimize_dispatch([field(latitude=None, longitude=None)], [baler()])
    assert result.unserved_fields[0].reason == "INVALID_LOCATION"


def test_duplicate_fields_are_rejected():
    with pytest.raises(ValueError, match="Duplicate field_id"):
        optimize_dispatch([field("DUP"), field("DUP")], [baler()])


def test_duplicate_balers_are_rejected():
    with pytest.raises(ValueError, match="Duplicate baler_id"):
        optimize_dispatch([field()], [baler("DUP"), baler("DUP")])


def test_current_baler_coordinates_must_be_a_pair():
    with pytest.raises(ValueError, match="supplied together"):
        baler(current_location_lat=30.0)


def test_unknown_field_without_buyer_is_explicit_when_required():
    config = deepcopy(load_dispatch_config())
    config["constraints"]["require_buyer_match"] = True
    result = optimize_dispatch([field()], [baler()], config=config)
    assert result.unserved_fields[0].reason == "NO_COMPATIBLE_BUYER"


def test_fixture_matrix_labels_distance_and_fixture_drive_time():
    ids = ["B-1", "F-1"]
    distances = {("B-1", "F-1"): 2.0}
    durations = {("B-1", "F-1"): 10}
    provider = FixtureMatrixProvider(distances, durations)
    result = optimize_dispatch([field()], [baler()], provider)
    route = result.baler_routes[0]
    assert route.distance_method == "FIXTURE_MATRIX"
    assert route.estimated_travel_minutes == 20
    assert route.route_duration_basis == "SERVICE_PLUS_FIXTURE_DRIVE"


def test_fixture_drive_duration_counts_against_working_hours():
    provider = FixtureMatrixProvider({("B-1", "F-1"): 2.0}, {("B-1", "F-1"): 200})
    result = optimize_dispatch([field()], [baler(working_end="12:00")], provider)
    assert result.unserved_fields[0].reason == "WORKING_HOURS_EXCEEDED"


def test_fixture_drive_duration_counts_against_working_hours():
    provider = FixtureMatrixProvider({("B-1", "F-1"): 2.0}, {("B-1", "F-1"): 200})
    result = optimize_dispatch([field()], [baler(working_end="12:00")], provider)
    assert result.unserved_fields[0].reason == "WORKING_HOURS_EXCEEDED"


def test_incomplete_fixture_matrix_fails_loudly():
    provider = FixtureMatrixProvider({("B-1", "F-1"): 2.0})
    with pytest.raises(KeyError, match="No fixture distance"):
        optimize_dispatch([field()], [baler("B-1"), baler("B-2")], provider)


def test_geodesic_distance_is_a_straight_line_proxy():
    distance = GeodesicDistanceProvider().distance("a", 30, 74, "b", 30.1, 74.1)
    assert distance.method == "GEODESIC_PROXY"
    assert distance.duration_minutes is None
    assert round(distance.kilometers, 2) == round(haversine_km(30, 74, 30.1, 74.1), 2)


def test_provenance_does_not_promote_mixed_fixture_run_to_real():
    result = optimize_dispatch([field()], [baler(demo_or_real="REAL", source="some source")])
    assert result.provenance == "SYNTHETIC"
