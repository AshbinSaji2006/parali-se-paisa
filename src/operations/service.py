from __future__ import annotations

from dataclasses import dataclass

from src.buyers.matcher import match_buyers
from src.buyers.models import Buyer, BuyerCandidateField, BuyerMatchResult
from src.dispatch.eligibility import check_eligibility
from src.dispatch.models import Baler, DispatchField, DispatchResult
from src.dispatch.optimizer import load_dispatch_config, optimize_dispatch
from src.dispatch.travel import GeodesicDistanceProvider, TravelMatrixProvider


@dataclass(frozen=True)
class ActionPlan:
    dispatch: DispatchResult
    buyer_matching: BuyerMatchResult


def plan_action(fields: list[DispatchField], balers: list[Baler], buyers: list[Buyer],
                travel_provider: TravelMatrixProvider | None = None) -> ActionPlan:
    """Coordinate eligibility → whole-field buyer capacity → baler routing.

    Buyer demand is previewed before routing but only fields actually routed receive
    a final allocation. The API persists and reserves those final allocations in one
    transaction with their route and collection job.
    """
    provider = travel_provider or GeodesicDistanceProvider()
    config = load_dispatch_config()
    eligibility = [check_eligibility(f,
        unknown_weather_policy=config["weather"]["unknown_policy"],
        accepted_quality=tuple(config["weather"]["accepted_quality"])) for f in fields]
    candidates = [BuyerCandidateField(field_id=f.field_id, latitude=f.latitude, longitude=f.longitude,
                  estimated_straw_tonnes=f.estimated_straw_tonnes, burn_risk_score=f.burn_risk_score,
                  provenance=f.provenance) for f, eligible in zip(fields, eligibility)
                  if eligible.eligible and f.estimated_straw_tonnes]
    preview = match_buyers(candidates, buyers, provider)
    match_by_id = {item.field_id: item for item in preview.allocations}
    for index, field in enumerate(fields):
        match = match_by_id.get(field.field_id)
        if match is not None:
            fields[index] = field.model_copy(update={"buyer_id": match.buyer_id,
                                                     "buyer_match_score": match.match_score})
    config["constraints"]["require_buyer_match"] = True
    dispatch = optimize_dispatch(fields, balers, provider, config)
    routed_ids = {stop.field_id for route in dispatch.baler_routes for stop in route.stops}
    final_fields = [field for field in candidates if field.field_id in routed_ids]
    final_matching = match_buyers(final_fields, buyers, provider)
    final_by_id = {item.field_id: item for item in final_matching.allocations}
    for route in dispatch.baler_routes:
        for stop in route.stops:
            stop.buyer_id = final_by_id[stop.field_id].buyer_id
    return ActionPlan(dispatch=dispatch, buyer_matching=final_matching)
