from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from src.buyers.models import Buyer, BuyerCandidateField, BuyerMatch, BuyerMatchResult
from src.dispatch.travel import GeodesicDistanceProvider, TravelMatrixProvider


def load_buyer_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "buyer_matching.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def match_buyers(fields: list[BuyerCandidateField | dict[str, Any]],
                 buyers: list[Buyer | dict[str, Any]],
                 travel_provider: TravelMatrixProvider | None = None,
                 config: dict[str, Any] | None = None,
                 arrival_time_local: str | None = None) -> BuyerMatchResult:
    """Reserve whole fields only; capacity is consumed in risk-priority order."""
    cfg = config or load_buyer_config()
    provider = travel_provider or GeodesicDistanceProvider()
    field_rows = [f if isinstance(f, BuyerCandidateField) else BuyerCandidateField.model_validate(f) for f in fields]
    buyer_rows = [b if isinstance(b, Buyer) else Buyer.model_validate(b) for b in buyers]
    if len({f.field_id for f in field_rows}) != len(field_rows):
        raise ValueError("Duplicate field_id values are not allowed in one matching run")
    if len({b.buyer_id for b in buyer_rows}) != len(buyer_rows):
        raise ValueError("Duplicate buyer_id values are not allowed")
    capacity = {b.buyer_id: float(b.remaining_demand_tonnes) for b in buyer_rows}
    allocations: list[BuyerMatch] = []
    unmatched: list[str] = []
    score_cfg = cfg["scoring"]
    max_distance = float(score_cfg["maximum_distance_km"])
    sorted_fields = sorted(field_rows, key=lambda f: (-(f.burn_risk_score or 0), -f.estimated_straw_tonnes, f.field_id))
    for field in sorted_fields:
        if field.latitude is None or field.longitude is None:
            allocations.append(_unmatched(field, provider.method, ["INVALID_LOCATION"]))
            unmatched.append(field.field_id)
            continue
        candidates = []
        rejected: list[str] = []
        materially_compatible = False
        for buyer in buyer_rows:
            if buyer.status != "AVAILABLE":
                rejected.append(f"{buyer.buyer_id}:UNAVAILABLE")
                continue
            if field.residue_type.upper() not in {x.upper() for x in buyer.accepted_residue_types}:
                rejected.append(f"{buyer.buyer_id}:INCOMPATIBLE_RESIDUE")
                continue
            materially_compatible = True
            if field.moisture_pct is not None and buyer.max_moisture_pct is not None and field.moisture_pct > buyer.max_moisture_pct:
                rejected.append(f"{buyer.buyer_id}:MOISTURE_LIMIT")
                continue
            if arrival_time_local and not _within_hours(arrival_time_local, buyer.operating_start, buyer.operating_end):
                rejected.append(f"{buyer.buyer_id}:OUTSIDE_OPERATING_HOURS")
                continue
            remaining = capacity[buyer.buyer_id]
            if field.estimated_straw_tonnes > remaining + float(cfg["allocation"]["oversubscription_tolerance_tonnes"]):
                rejected.append(f"{buyer.buyer_id}:INSUFFICIENT_REMAINING_DEMAND")
                continue
            distance = provider.distance(field.field_id, field.latitude, field.longitude,
                                         buyer.buyer_id, buyer.latitude, buyer.longitude).kilometers
            if distance > max_distance:
                rejected.append(f"{buyer.buyer_id}:DISTANCE_LIMIT")
                continue
            compatibility = float(score_cfg["compatibility_weight"])
            demand_fit = (float(score_cfg["demand_fit_weight"]) *
                          min(1.0, remaining / buyer.daily_demand_tonnes)
                          if buyer.daily_demand_tonnes > 0 else 0.0)
            distance_fit = float(score_cfg["distance_weight"]) * max(0.0, 1 - distance / max_distance)
            # Price is excluded unless both the buyer and the caller provide a verified,
            # normalized price basis. No demo fixture currently provides one.
            score = compatibility + demand_fit + distance_fit
            candidates.append((score, -distance, buyer.buyer_id, buyer, distance, remaining))
        if not candidates:
            if not buyer_rows or not materially_compatible:
                reason = "NO_COMPATIBLE_BUYER"
            elif any("DISTANCE_LIMIT" in x for x in rejected):
                reason = "DISTANCE_LIMIT"
            elif any("OUTSIDE_OPERATING_HOURS" in x for x in rejected):
                reason = "BUYER_OUTSIDE_OPERATING_HOURS"
            elif any("MOISTURE_LIMIT" in x for x in rejected):
                reason = "BUYER_QUALITY_CONSTRAINT"
            else:
                reason = "NO_BUYER_CAPACITY"
            allocations.append(_unmatched(field, provider.method, [reason, *rejected]))
            unmatched.append(field.field_id)
            continue
        price_weight = float(score_cfg.get("price_weight", 0))
        verified_prices = [float(item[3].price_per_tonne) for item in candidates
                           if item[3].demo_or_real == "REAL" and item[3].price_is_verified
                           and item[3].price_per_tonne is not None]
        low_price = min(verified_prices) if verified_prices else None
        high_price = max(verified_prices) if verified_prices else None
        scored = []
        for item in candidates:
            score, distance_key, buyer_id, candidate_buyer, distance, remaining = item
            reasons = []
            if (price_weight > 0 and candidate_buyer.demo_or_real == "REAL" and
                    candidate_buyer.price_is_verified and candidate_buyer.price_per_tonne is not None):
                price_fit = 1.0 if high_price == low_price else (
                    float(candidate_buyer.price_per_tonne) - low_price) / (high_price - low_price)
                score += price_weight * price_fit
                reasons.append("Verified real price scored relative to compatible verified real offers")
            scored.append((score, distance_key, buyer_id, candidate_buyer, distance, remaining, reasons))
        score, _, _, buyer, distance, remaining, price_reasons = max(
            scored, key=lambda item: (item[0], item[1], item[2]))
        capacity[buyer.buyer_id] = max(0.0, remaining - field.estimated_straw_tonnes)
        reasons = ["Accepted residue type matches", "Whole field fits remaining daily demand",
                   f"Distance scored using {provider.method}"]
        reasons.extend(price_reasons)
        if field.burn_risk_score is not None:
            reasons.append("Field priority order reflects supplied normalized risk score; it is not a probability")
        if buyer.price_per_tonne is not None and not buyer.price_is_verified:
            reasons.append("Price omitted because it is not verified")
        allocations.append(BuyerMatch(field_id=field.field_id, buyer_id=buyer.buyer_id,
                                      match_score=round(score, 4), distance_km=round(distance, 3),
                                      distance_method=provider.method, allocated_tonnes=field.estimated_straw_tonnes,
                                      remaining_buyer_capacity_tonnes=round(capacity[buyer.buyer_id], 6),
                                      matching_reasons=reasons, status="MATCHED", provenance=_provenance(field.provenance, buyer.demo_or_real)))
    allocation_by_field = {a.field_id: a for a in allocations}
    allocations = [allocation_by_field[f.field_id] for f in field_rows]
    classes = {f.provenance for f in field_rows} | {b.demo_or_real for b in buyer_rows}
    provenance = "REAL" if classes == {"REAL"} else "SYNTHETIC" if classes & {"DEMO", "FIXTURE", "SYNTHETIC"} else "UNVERIFIED"
    return BuyerMatchResult(allocations=allocations,
                            buyer_remaining_capacity_tonnes={k: round(v, 6) for k, v in capacity.items()},
                            unassigned_field_ids=unmatched, distance_method=provider.method, provenance=provenance)


def _unmatched(field, method, reasons):
    return BuyerMatch(field_id=field.field_id, buyer_id=None, match_score=None, distance_km=None,
                      distance_method=method, allocated_tonnes=0, remaining_buyer_capacity_tonnes=None,
                      matching_reasons=reasons, status="UNMATCHED", provenance=field.provenance)


def _provenance(field_class, buyer_class):
    return "REAL" if field_class == buyer_class == "REAL" else "SYNTHETIC"


def _within_hours(value: str, start: str, end: str) -> bool:
    def minutes(t):
        h, m = map(int, t.split(":"))
        return h * 60 + m
    now, begin, finish = minutes(value), minutes(start), minutes(end)
    return begin <= now <= finish if finish >= begin else now >= begin or now <= finish
