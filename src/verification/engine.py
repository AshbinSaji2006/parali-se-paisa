from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import yaml

from src.verification.models import BurnEvidence, VerificationCase, VerificationObservation, VerificationState


def load_verification_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "verification.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def classify_observation(observation: VerificationObservation | dict[str, Any], config: dict[str, Any] | None = None):
    obs = observation if isinstance(observation, VerificationObservation) else VerificationObservation.model_validate(observation)
    cfg = (config or load_verification_config())["burn_rules"]
    if obs.observation_quality.upper() != "GOOD":
        return BurnEvidence.UNCLEAR, [f"Image quality {obs.observation_quality} is below the approval threshold"]
    if obs.nbr_delta is None and obs.bais2_delta is None and obs.ndvi_delta is None:
        return BurnEvidence.UNCLEAR, ["No usable spectral deltas are available"]
    nbr_strong = obs.nbr_delta is not None and obs.nbr_delta <= float(cfg["strong_nbr_delta_max"])
    bais_strong = obs.bais2_delta is not None and obs.bais2_delta >= float(cfg["strong_bais2_delta_min"])
    ndvi_strong = obs.ndvi_delta is not None and obs.ndvi_delta <= float(cfg["strong_ndvi_delta_max"])
    signals = sum((nbr_strong, bais_strong, ndvi_strong))
    reasons = []
    if nbr_strong: reasons.append("Large NBR decline")
    if bais_strong: reasons.append("BAIS2 increase")
    if ndvi_strong: reasons.append("Sharp NDVI decline")
    if signals >= 3:
        if obs.firms_nearby:
            reasons.append("Nearby FIRMS context corroborates spectral evidence; it is not decisive alone")
        return BurnEvidence.STRONG, reasons
    nbr_moderate = obs.nbr_delta is not None and obs.nbr_delta <= float(cfg["moderate_nbr_delta_max"])
    bais_moderate = obs.bais2_delta is not None and obs.bais2_delta >= float(cfg["moderate_bais2_delta_min"])
    ndvi_moderate = obs.ndvi_delta is not None and obs.ndvi_delta <= float(cfg["moderate_ndvi_delta_max"])
    moderate_count = sum((nbr_moderate, bais_moderate, ndvi_moderate))
    if moderate_count >= 2:
        if obs.firms_nearby:
            reasons.append("Nearby FIRMS context corroborates moderate spectral evidence; it is not decisive alone")
        return BurnEvidence.MODERATE, reasons or ["Multiple moderate spectral changes"]
    if obs.firms_nearby:
        return BurnEvidence.UNCLEAR, ["FIRMS context alone cannot confirm burning; manual review is appropriate"]
    if signals == 0 and moderate_count == 0:
        return BurnEvidence.NO_BURN, ["No configured burn indicators detected in this good-quality observation; absence is not proof of no burn"]
    return BurnEvidence.UNCLEAR, ["Spectral indicators are mixed or below configured evidence thresholds"]


def start_monitoring(field_id: str, *, pilot: str = "DEMO PILOT", district: str = "DEMO DISTRICT",
                     start: datetime | None = None, provenance: str = "SYNTHETIC",
                     config: dict[str, Any] | None = None) -> VerificationCase:
    cfg = config or load_verification_config()
    started = start or datetime.now(timezone.utc)
    if started.tzinfo is None:
        raise ValueError("monitoring start must include timezone information")
    deadline = started + timedelta(days=int(cfg["monitoring"]["deadline_days"]))
    import uuid
    return VerificationCase(verification_id=str(uuid.uuid4()), field_id=field_id, pilot=pilot, district=district,
                           state=VerificationState.MONITORING, monitoring_start=started,
                           monitoring_deadline=deadline, provenance=provenance,
                           reasons=["Monitoring started; no conclusion has been reached"])


def add_observation(case: VerificationCase, observation: VerificationObservation | dict[str, Any],
                    config: dict[str, Any] | None = None) -> VerificationCase:
    if case.state in {VerificationState.CLOSED, VerificationState.BURN_SIGNAL_DETECTED, VerificationState.NO_BURN_VERIFIED}:
        raise ValueError(f"Cannot add evidence to terminal verification state {case.state.value}")
    obs = observation if isinstance(observation, VerificationObservation) else VerificationObservation.model_validate(observation)
    if obs.field_id != case.field_id:
        raise ValueError("Observation field_id does not match the verification case")
    if obs.observation_datetime > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("Future-dated observations are not accepted")
    if case.monitoring_start is None or obs.observation_datetime < case.monitoring_start:
        raise ValueError("Observation predates monitoring start")
    if case.observations and obs.observation_datetime <= case.observations[-1].observation_datetime:
        raise ValueError("Observations must be appended in strictly chronological order")
    if any(x.verification_observation_id == obs.verification_observation_id for x in case.observations):
        raise ValueError("Duplicate verification_observation_id")
    evidence, reasons = classify_observation(obs, config)
    obs = obs.model_copy(update={"evidence": evidence, "evidence_reasons": reasons})
    updated = case.model_copy(deep=True)
    updated.observations.append(obs)
    updated.updated_at = datetime.now(timezone.utc)
    evaluate_case(updated, as_of=obs.observation_datetime, config=config)
    return updated


def evaluate_case(case: VerificationCase, *, as_of: datetime | None = None,
                  config: dict[str, Any] | None = None) -> VerificationCase:
    cfg = config or load_verification_config()
    current = as_of or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("evaluation time must include timezone information")
    if case.state == VerificationState.NOT_STARTED:
        return case.model_copy(update={"reasons": ["Monitoring has not started"]})
    if case.state == VerificationState.CLOSED:
        return case
    if any(x.evidence == BurnEvidence.STRONG for x in case.observations):
        case.state = VerificationState.BURN_SIGNAL_DETECTED
        case.reasons = ["Strong multi-indicator burn signal detected; certificate is blocked"]
        case.updated_at = datetime.now(timezone.utc)
        return case
    if case.state == VerificationState.MANUAL_REVIEW_REQUIRED:
        return case
    if any(x.evidence in {BurnEvidence.MODERATE, BurnEvidence.UNCLEAR} for x in case.observations):
        case.state = VerificationState.MANUAL_REVIEW_REQUIRED
        case.reasons = ["Evidence is uncertain or imagery quality is inadequate; field review is required"]
        case.updated_at = datetime.now(timezone.utc)
        return case
    minimum = int(cfg["monitoring"]["minimum_observations"])
    span_days = float(cfg["monitoring"]["minimum_span_days"])
    obs = case.observations
    sowing = bool(cfg["monitoring"]["allow_sowing_candidate_to_close"]) and any(
        x.field_status_candidate == "SOWN" and (x.sowing_candidate_confidence or 0) >= 0.8 for x in obs)
    end = obs[-1].observation_datetime if obs else None
    span = (end - obs[0].observation_datetime).total_seconds() / 86400 if len(obs) > 1 else 0
    enough = len(obs) >= minimum and span >= span_days and all(x.evidence == BurnEvidence.NO_BURN for x in obs)
    deadline_reached = case.monitoring_deadline is not None and current >= case.monitoring_deadline
    if enough and (deadline_reached or sowing):
        case.state = VerificationState.NO_BURN_VERIFIED
        case.reasons = ["Minimum chronological evidence met with no configured burn signal"]
        if sowing:
            case.reasons.append("A high-confidence sowing candidate was observed; no sowing date was inferred")
        case.updated_at = datetime.now(timezone.utc)
        return case
    if deadline_reached:
        case.state = VerificationState.INSUFFICIENT_EVIDENCE
        case.reasons = [f"Monitoring deadline reached without {minimum} good-quality observations spanning {span_days:g} days"]
    else:
        case.state = VerificationState.MONITORING if obs else VerificationState.INSUFFICIENT_EVIDENCE
        case.reasons = [f"Evidence in progress ({len(obs)}/{minimum} observations; {span:.1f}/{span_days:g} day span)"]
    case.updated_at = datetime.now(timezone.utc)
    return case


def close_case(case: VerificationCase, reason: str) -> VerificationCase:
    if case.state in {VerificationState.NOT_STARTED, VerificationState.CLOSED}:
        raise ValueError(f"Cannot close a verification case in state {case.state.value}")
    if not reason.strip():
        raise ValueError("A close reason is required")
    case.state = VerificationState.CLOSED
    case.reasons = [reason.strip()]
    case.updated_at = datetime.now(timezone.utc)
    return case
