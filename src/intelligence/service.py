from __future__ import annotations

from src.models.field_status.rules import rule_status_candidate
from src.models.straw import estimate_straw
from src.models.burn_risk.rules import rule_burn_risk
from src.models.registry import is_trusted_for_decision


def intelligence_for_row(row, status_model=None, harvest_date=None, context=None):
    supplied_trust = status_model.metadata.get("trust_state") if status_model is not None else "NO_MODEL"
    if supplied_trust == "SYNTHETIC_TEST_MODEL":
        raise ValueError("synthetic test model cannot serve an intelligence prediction")
    if status_model is not None and is_trusted_for_decision(supplied_trust):
        status = status_model.predict(row)
    else:
        status = rule_status_candidate(row)
        status["model_trust_state"] = supplied_trust
        if status_model is not None:
            status["inactive_model_reason"] = "Only VALIDATED_MODEL is active for intelligence; experimental models are not trusted for this service"
    candidate = status.get("status") or status.get("status_candidate")
    straw = estimate_straw(row, status) if candidate == "HARVESTED" else {"eligible": False, "status": "NOT_ELIGIBLE", "reason": "Status is not harvested", "is_ground_truth": False}
    sufficiently_harvested = candidate == "HARVESTED" and (status.get("confidence_band") in ("MODERATE", "HIGH") or status.get("model_trust_state") == "VALIDATED_MODEL")
    if sufficiently_harvested:
        burn = rule_burn_risk(row, straw, harvest_date=harvest_date, context=context)
    else:
        burn = {"status": "NOT_APPLICABLE_INSUFFICIENT_HARVEST_EVIDENCE", "risk_score": None,
                "method": "RULE_ENGINE_V1", "score_kind": "NORMALIZED_RULE_SCORE_NOT_PROBABILITY", "is_ground_truth": False}
    return {"field_id": row.get("field_id"), "field_status": status, "straw": straw, "burn_risk": burn,
            "provenance": {"season": row.get("season"), "year": row.get("year"),
                           "observation_datetime": row.get("observation_datetime"),
                           "source_image_id_s2": row.get("source_image_id_s2"),
                           "source_image_id_s1": row.get("source_image_id_s1"),
                           "fixture_or_real": row.get("fixture_or_real"),
                           "processing_version": row.get("processing_version"),
                           "feature_schema_version": row.get("feature_schema_version"),
                           "status_source": status.get("method", "trained_model"),
                           "model_trust_state": status.get("model_trust_state", "NO_MODEL")}}
