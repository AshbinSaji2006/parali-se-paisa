from __future__ import annotations

from src.dispatch.models import DispatchField, EligibilityResult


def check_eligibility(field: DispatchField, *, unknown_weather_policy: str = "WARN",
                      accepted_quality: tuple[str, ...] = ("GOOD",),
                      require_high_risk: bool = False) -> EligibilityResult:
    reasons: list[str] = []
    warnings: list[str] = []
    if field.latitude is None or field.longitude is None:
        reasons.append("INVALID_LOCATION")
    status = (field.field_status or "").upper()
    credible_status = status in {"HARVESTED", "HARVESTED_CANDIDATE"}
    credible_evidence = (field.harvest_evidence_state or "").upper() in {"CANDIDATE", "SUPPORTED", "CONFIRMED"}
    confidence = (field.field_status_confidence or "").upper()
    source = (field.field_status_source or "").upper()
    if not credible_status or not credible_evidence or confidence not in {"MODERATE", "HIGH", "VALIDATED"}:
        reasons.append("HARVEST_EVIDENCE_INSUFFICIENT")
    if source in {"SYNTHETIC_TEST_MODEL", "SYNTHETIC_MODEL"}:
        reasons.append("UNTRUSTED_SYNTHETIC_MODEL")
    if field.estimated_straw_tonnes is None or field.estimated_straw_tonnes <= 0:
        reasons.append("NO_POSITIVE_STRAW_ESTIMATE")
    if field.observation_quality not in accepted_quality:
        reasons.append("OBSERVATION_QUALITY_UNACCEPTABLE")
    if field.weather_suitability == "UNSUITABLE":
        reasons.append("WEATHER_UNSUITABLE")
    elif field.weather_suitability == "UNKNOWN":
        policy = unknown_weather_policy.upper()
        if policy == "BLOCK":
            reasons.append("WEATHER_UNKNOWN_BLOCKED_BY_POLICY")
        elif policy == "WARN":
            warnings.append("Weather suitability is unknown; no forecast was available")
        elif policy != "PERMIT":
            raise ValueError(f"Unsupported unknown weather policy: {unknown_weather_policy}")
    if require_high_risk and (field.burn_risk_score is None or field.burn_risk_score < 0.6):
        reasons.append("HIGH_RISK_PRIORITY_FILTER")
    return EligibilityResult(field_id=field.field_id, eligible=not reasons, reasons=reasons, warnings=warnings)
