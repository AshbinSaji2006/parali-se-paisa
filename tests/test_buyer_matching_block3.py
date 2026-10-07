from __future__ import annotations

from copy import deepcopy
import pytest

from src.buyers.matcher import load_buyer_config, match_buyers
from src.buyers.models import Buyer, BuyerCandidateField
from src.dispatch.travel import FixtureMatrixProvider


def candidate(field_id="F-1", **updates):
    values = {"field_id": field_id, "latitude": 30.02, "longitude": 74.52,
              "estimated_straw_tonnes": 10.0, "residue_type": "PADDY_STRAW",
              "burn_risk_score": 0.4, "provenance": "SYNTHETIC"}
    values.update(updates)
    return BuyerCandidateField(**values)


def buyer(buyer_id="BUYER-1", **updates):
    values = {"buyer_id": buyer_id, "name": f"DEMO {buyer_id}", "buyer_type": "BIOMASS_POWER",
              "latitude": 30.03, "longitude": 74.53, "accepted_residue_types": ["PADDY_STRAW"],
              "daily_demand_tonnes": 50, "remaining_demand_tonnes": 40,
              "status": "AVAILABLE", "demo_or_real": "DEMO", "source": "fixture"}
    values.update(updates)
    return Buyer(**values)


def test_compatible_buyer_receives_full_field():
    result = match_buyers([candidate()], [buyer()])
    allocation = result.allocations[0]
    assert allocation.status == "MATCHED"
    assert allocation.buyer_id == "BUYER-1"
    assert allocation.allocated_tonnes == 10
    assert allocation.remaining_buyer_capacity_tonnes == 30


def test_incompatible_nearest_buyer_is_rejected():
    near = buyer("NEAR", latitude=30.0201, longitude=74.5201, accepted_residue_types=["COTTON_STALK"])
    far = buyer("FAR", latitude=30.04, longitude=74.54)
    result = match_buyers([candidate()], [near, far])
    assert result.allocations[0].buyer_id == "FAR"
    assert result.allocations[0].allocated_tonnes == 10


def test_capacity_prevents_oversubscription():
    fields = [candidate("F1", estimated_straw_tonnes=8), candidate("F2", estimated_straw_tonnes=8)]
    result = match_buyers(fields, [buyer(remaining_demand_tonnes=12)])
    matched = [x for x in result.allocations if x.status == "MATCHED"]
    assert len(matched) == 1
    assert sum(x.allocated_tonnes for x in matched) <= 12
    assert len(result.unassigned_field_ids) == 1


def test_high_risk_whole_field_is_allocated_first():
    fields = [candidate("LOW", estimated_straw_tonnes=8, burn_risk_score=0.1),
              candidate("HIGH", estimated_straw_tonnes=8, burn_risk_score=0.9)]
    result = match_buyers(fields, [buyer(remaining_demand_tonnes=8)])
    assert result.unassigned_field_ids == ["LOW"]
    assert next(x for x in result.allocations if x.status == "MATCHED").field_id == "HIGH"


def test_field_is_not_split_across_two_buyers():
    buyers = [buyer("A", remaining_demand_tonnes=6), buyer("B", remaining_demand_tonnes=6)]
    result = match_buyers([candidate(estimated_straw_tonnes=10)], buyers)
    assert result.allocations[0].status == "UNMATCHED"
    assert result.allocations[0].allocated_tonnes == 0
    assert result.allocations[0].buyer_id is None


def test_incompatible_residue_explains_unmatched_field():
    result = match_buyers([candidate()], [buyer(accepted_residue_types=["COTTON_STALK"])])
    assert result.allocations[0].matching_reasons[0] == "NO_COMPATIBLE_BUYER"


def test_unavailable_buyer_is_not_matched():
    result = match_buyers([candidate()], [buyer(status="PAUSED")])
    assert result.allocations[0].status == "UNMATCHED"
    assert any("UNAVAILABLE" in x for x in result.allocations[0].matching_reasons)


def test_moisture_limit_is_enforced_when_known():
    result = match_buyers([candidate(moisture_pct=30)], [buyer(max_moisture_pct=20)])
    assert result.allocations[0].matching_reasons[0] == "BUYER_QUALITY_CONSTRAINT"


def test_missing_moisture_is_not_fabricated():
    result = match_buyers([candidate(moisture_pct=None)], [buyer(max_moisture_pct=20)])
    assert result.allocations[0].status == "MATCHED"
    assert "moisture" not in " ".join(result.allocations[0].matching_reasons).lower()


def test_operating_hours_checked_only_when_arrival_time_supplied():
    closed = buyer(operating_start="08:00", operating_end="17:00")
    not_checked = match_buyers([candidate()], [closed])
    checked = match_buyers([candidate()], [closed], arrival_time_local="19:00")
    assert not_checked.allocations[0].status == "MATCHED"
    assert checked.allocations[0].matching_reasons[0] == "BUYER_OUTSIDE_OPERATING_HOURS"


def test_remaining_demand_affects_score():
    high_capacity = buyer("HIGH-CAP", daily_demand_tonnes=100, remaining_demand_tonnes=80)
    low_capacity = buyer("LOW-CAP", daily_demand_tonnes=100, remaining_demand_tonnes=20)
    high_capacity = high_capacity.model_copy(update={"latitude": 30.03, "longitude": 74.53})
    low_capacity = low_capacity.model_copy(update={"latitude": 30.03, "longitude": 74.53})
    result = match_buyers([candidate()], [low_capacity, high_capacity])
    assert result.allocations[0].buyer_id == "HIGH-CAP"


def test_distance_score_prefers_nearer_when_other_factors_equal():
    near = buyer("NEAR", latitude=30.021, longitude=74.521)
    far = buyer("FAR", latitude=30.08, longitude=74.58)
    result = match_buyers([candidate()], [far, near])
    assert result.allocations[0].buyer_id == "NEAR"
    assert result.allocations[0].distance_method == "GEODESIC_PROXY"


def test_maximum_distance_returns_explicit_reason():
    cfg = deepcopy(load_buyer_config())
    cfg["scoring"]["maximum_distance_km"] = 0.1
    result = match_buyers([candidate()], [buyer()], config=cfg)
    assert result.allocations[0].matching_reasons[0] == "DISTANCE_LIMIT"


def test_fixture_matrix_method_is_preserved():
    provider = FixtureMatrixProvider({("F-1", "BUYER-1"): 3.25})
    result = match_buyers([candidate()], [buyer()], provider)
    assert result.allocations[0].distance_method == "FIXTURE_MATRIX"
    assert result.allocations[0].distance_km == 3.25


def test_unverified_price_is_not_used_as_score():
    unverified = buyer(price_per_tonne=90000, price_is_verified=False)
    base = buyer()
    result = match_buyers([candidate()], [unverified])
    without_price = match_buyers([candidate()], [base])
    assert result.allocations[0].match_score == without_price.allocations[0].match_score
    assert "Price omitted because it is not verified" in result.allocations[0].matching_reasons


def test_verified_real_price_can_be_scored_when_configured():
    cfg = deepcopy(load_buyer_config())
    cfg["scoring"]["price_weight"] = 20
    buyer_low = buyer("LOW", price_per_tonne=100, price_is_verified=True, demo_or_real="REAL")
    buyer_high = buyer("HIGH", price_per_tonne=150, price_is_verified=True, demo_or_real="REAL")
    result = match_buyers([candidate()], [buyer_low, buyer_high], config=cfg)
    allocation = result.allocations[0]
    assert allocation.buyer_id == "HIGH"
    assert any("Verified real price scored" in x for x in allocation.matching_reasons)


def test_demo_price_never_receives_real_price_score():
    cfg = deepcopy(load_buyer_config())
    cfg["scoring"]["price_weight"] = 20
    demo = buyer(price_per_tonne=150, price_is_verified=True, demo_or_real="DEMO")
    result = match_buyers([candidate()], [demo], config=cfg)
    assert not any("Verified real price scored" in x for x in result.allocations[0].matching_reasons)


def test_no_buyer_returns_capacity_safe_unmatched_result():
    result = match_buyers([candidate()], [])
    assert result.unassigned_field_ids == ["F-1"]
    assert result.allocations[0].buyer_id is None
    assert result.provenance == "SYNTHETIC"


def test_invalid_location_is_explained():
    result = match_buyers([candidate(latitude=None, longitude=None)], [buyer()])
    assert result.allocations[0].matching_reasons == ["INVALID_LOCATION"]


def test_duplicate_field_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate field_id"):
        match_buyers([candidate("X"), candidate("X")], [buyer()])


def test_duplicate_buyer_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate buyer_id"):
        match_buyers([candidate()], [buyer("X"), buyer("X")])


def test_allocation_provenance_is_not_promoted():
    result = match_buyers([candidate(provenance="SYNTHETIC")],
                          [buyer(demo_or_real="REAL", source="registry")])
    assert result.allocations[0].provenance == "SYNTHETIC"
