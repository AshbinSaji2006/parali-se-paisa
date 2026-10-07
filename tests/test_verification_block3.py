from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from src.verification.engine import add_observation, classify_observation, close_case, evaluate_case, start_monitoring
from src.verification.models import BurnEvidence, VerificationObservation, VerificationState


def obs(field_id="F-1", index=1, day=0, start=None, *, quality="GOOD", ndvi_delta=0.01,
        nbr_delta=0.01, bais2_delta=0.01, firms=False, status=None, sowing_confidence=None):
    when = (start or datetime(2026, 1, 1, tzinfo=timezone.utc)) + timedelta(days=day)
    return VerificationObservation(verification_observation_id=f"OBS-{field_id}-{index}", field_id=field_id,
        observation_datetime=when, source_image_id_s2=f"S2-{index}", source_image_id_s1=f"S1-{index}",
        ndvi=0.3, nbr=0.2, bais2=0.1, ndvi_delta=ndvi_delta, nbr_delta=nbr_delta,
        bais2_delta=bais2_delta, firms_nearby=firms, observation_quality=quality,
        fixture_or_real="SYNTHETIC", field_status_candidate=status,
        sowing_candidate_confidence=sowing_confidence)


def test_strong_burn_requires_three_independent_spectral_indicators():
    evidence, reasons = classify_observation(obs(ndvi_delta=-0.3, nbr_delta=-0.3, bais2_delta=0.2))
    assert evidence == BurnEvidence.STRONG
    assert len(reasons) == 3


def test_firms_can_corroborate_but_not_create_strong_classification():
    evidence, reasons = classify_observation(obs(firms=True))
    assert evidence == BurnEvidence.UNCLEAR
    assert "FIRMS context alone" in reasons[0]


def test_moderate_spectral_evidence_requires_manual_review():
    evidence, _ = classify_observation(obs(ndvi_delta=-0.18, nbr_delta=-0.16, bais2_delta=0.01))
    assert evidence == BurnEvidence.MODERATE


def test_good_quality_observation_without_configured_signals_is_limited_no_burn_evidence():
    evidence, reasons = classify_observation(obs())
    assert evidence == BurnEvidence.NO_BURN
    assert "not proof" in reasons[0]


def test_poor_quality_never_returns_no_burn_evidence():
    evidence, _ = classify_observation(obs(quality="POOR"))
    assert evidence == BurnEvidence.UNCLEAR


def test_missing_spectral_deltas_are_unclear():
    item = obs(ndvi_delta=None, nbr_delta=None, bais2_delta=None)
    evidence, _ = classify_observation(item)
    assert evidence == BurnEvidence.UNCLEAR


def test_firms_absence_is_not_used_as_negative_evidence():
    no_firms, why = classify_observation(obs(firms=False))
    unknown_firms, _ = classify_observation(obs(firms=None))
    assert no_firms == unknown_firms == BurnEvidence.NO_BURN
    assert "absence is not proof" in why[0]


def test_observation_timestamp_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone"):
        VerificationObservation(verification_observation_id="X", field_id="F",
                               observation_datetime=datetime(2026, 1, 1), observation_quality="GOOD")


def test_monitoring_start_does_not_issue_verification():
    case = start_monitoring("F-1", start=datetime(2026, 1, 1, tzinfo=timezone.utc), provenance="SYNTHETIC")
    assert case.state == VerificationState.MONITORING
    assert case.monitoring_deadline - case.monitoring_start == timedelta(days=30)


def test_one_observation_cannot_complete_monitoring():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    case = add_observation(case, obs(start=start))
    assert case.state == VerificationState.MONITORING


def test_no_burn_requires_minimum_count_and_span_until_deadline():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    for i, day in enumerate((0, 15, 30), 1):
        case = add_observation(case, obs(index=i, day=day, start=start))
    assert case.state == VerificationState.NO_BURN_VERIFIED


def test_deadline_with_too_few_observations_is_insufficient():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    case = add_observation(case, obs(start=start, day=30))
    case = evaluate_case(case, as_of=start + timedelta(days=30))
    assert case.state == VerificationState.INSUFFICIENT_EVIDENCE


def test_sowing_candidate_may_close_early_only_after_minimum_evidence():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    for i, day in enumerate((0, 10, 20), 1):
        item = obs(index=i, day=day, start=start, status="SOWN" if i == 3 else None,
                   sowing_confidence=0.9 if i == 3 else None)
        case = add_observation(case, item)
    assert case.state == VerificationState.NO_BURN_VERIFIED
    assert any("no sowing date was inferred" in reason for reason in case.reasons)


def test_low_confidence_sowing_does_not_close_monitoring():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    for i, day in enumerate((0, 10, 20), 1):
        case = add_observation(case, obs(index=i, day=day, start=start,
                            status="SOWN" if i == 3 else None, sowing_confidence=0.7 if i == 3 else None))
    assert case.state == VerificationState.MONITORING


def test_burn_signal_stops_monitoring_and_blocks_no_burn_state():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    case = add_observation(case, obs(start=start, ndvi_delta=-0.3, nbr_delta=-0.3, bais2_delta=0.2))
    assert case.state == VerificationState.BURN_SIGNAL_DETECTED
    with pytest.raises(ValueError, match="terminal"):
        add_observation(case, obs(index=2, day=1, start=start))


def test_unclear_case_remains_manual_review_after_later_clear_observations():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    case = add_observation(case, obs(start=start, quality="POOR"))
    assert case.state == VerificationState.MANUAL_REVIEW_REQUIRED
    case = add_observation(case, obs(index=2, day=15, start=start))
    case = add_observation(case, obs(index=3, day=30, start=start))
    assert case.state == VerificationState.MANUAL_REVIEW_REQUIRED


def test_observation_must_match_case_field():
    case = start_monitoring("F-1", start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="does not match"):
        add_observation(case, obs(field_id="OTHER"))


def test_observations_must_be_chronological_and_unique():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    first = obs(index=1, day=3, start=start)
    case = add_observation(case, first)
    with pytest.raises(ValueError, match="chronological"):
        add_observation(case, obs(index=2, day=2, start=start))
    duplicate = first.model_copy(update={"observation_datetime": start + timedelta(days=4)})
    with pytest.raises(ValueError, match="Duplicate"):
        add_observation(case, duplicate)


def test_observation_before_monitoring_start_is_rejected():
    start = datetime(2026, 1, 10, tzinfo=timezone.utc)
    case = start_monitoring("F-1", start=start)
    with pytest.raises(ValueError, match="predates"):
        add_observation(case, obs(start=start, day=-1))


def test_future_dated_observation_is_rejected():
    now = datetime.now(timezone.utc)
    case = start_monitoring("F-1", start=now)
    future = obs(start=now, day=10)
    with pytest.raises(ValueError, match="Future-dated"):
        add_observation(case, future)


def test_manual_review_action_records_reason_and_blocks_auto_approval():
    case = start_monitoring("F-1", start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    case.state = VerificationState.MANUAL_REVIEW_REQUIRED
    case.reasons = ["Field inspection requested"]
    evaluated = evaluate_case(case, as_of=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert evaluated.state == VerificationState.MANUAL_REVIEW_REQUIRED


def test_close_case_is_explicit_and_immutable():
    case = start_monitoring("F-1", start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    closed = close_case(case, "Monitoring closed for demonstration")
    assert closed.state == VerificationState.CLOSED
    assert evaluate_case(closed, as_of=datetime(2026, 2, 1, tzinfo=timezone.utc)).state == VerificationState.CLOSED
    with pytest.raises(ValueError, match="terminal"):
        add_observation(closed, obs(start=datetime(2026, 1, 1, tzinfo=timezone.utc)))


def test_no_real_or_synthetic_source_is_inferred_from_absent_firms():
    evidence, reasons = classify_observation(obs(firms=False))
    assert evidence == BurnEvidence.NO_BURN
    assert "FIRMS" not in reasons[0]
