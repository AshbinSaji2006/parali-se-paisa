from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.dependencies import (get_db, get_field_record, load_verification_case, record_audit,
                                  save_verification_case, verification_payload)
from src.api.schemas import ManualReviewRequest, ObservationCreate, VerificationStartRequest
from src.db.models import VerificationCaseRecord, VerificationObservationRecord
from src.verification.engine import add_observation, close_case, evaluate_case, start_monitoring
from src.verification.models import VerificationCase, VerificationObservation, VerificationState

router = APIRouter(prefix="/verification", tags=["verification"])


@router.post("/start/{field_id}", status_code=201)
def verification_start(field_id: str, body: VerificationStartRequest, session: Session = Depends(get_db)):
    field = get_field_record(session, field_id)
    case = start_monitoring(field_id, pilot=body.pilot, district=body.district, provenance=field.provenance)
    save_verification_case(session, case)
    record_audit(session, "VERIFICATION_STARTED", "verification_case", case.verification_id,
                 {"field_id": field_id, "provenance": case.provenance})
    session.commit()
    return verification_payload(case)


@router.get("/{verification_id}")
def verification_get(verification_id: str, session: Session = Depends(get_db)):
    return verification_payload(load_verification_case(session, verification_id))


@router.get("/field/{field_id}")
def verification_for_field(field_id: str, session: Session = Depends(get_db)):
    rows = session.scalars(select(VerificationCaseRecord).where(VerificationCaseRecord.field_id == field_id)
                           .order_by(VerificationCaseRecord.created_at.desc())).all()
    return {"items": [verification_payload(load_verification_case(session, row.verification_id)) for row in rows],
            "count": len(rows)}


@router.post("/{verification_id}/observations")
def verification_add_observation(verification_id: str, body: ObservationCreate,
                                 session: Session = Depends(get_db)):
    case = load_verification_case(session, verification_id)
    # Evidence class and fixture provenance are calculated from persisted case state.
    observation = VerificationObservation.model_validate(body.model_dump()).model_copy(
        update={"fixture_or_real": case.provenance})
    try:
        updated = add_observation(case, observation)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    saved = updated.observations[-1]
    session.add(VerificationObservationRecord(observation_id=saved.verification_observation_id,
              verification_id=verification_id, field_id=updated.field_id,
              observation_datetime=saved.observation_datetime,
              observation=saved.model_dump(mode="json"), provenance=saved.fixture_or_real))
    save_verification_case(session, updated)
    record_audit(session, "VERIFICATION_OBSERVATION_ADDED", "verification_case", verification_id,
                 {"observation_id": saved.verification_observation_id, "evidence": saved.evidence.value})
    session.commit()
    return verification_payload(updated)


@router.post("/{verification_id}/evaluate")
def verification_evaluate(verification_id: str, session: Session = Depends(get_db)):
    case = load_verification_case(session, verification_id)
    before = case.state
    evaluated = evaluate_case(case, as_of=datetime.now(timezone.utc))
    save_verification_case(session, evaluated)
    if evaluated.state != before:
        record_audit(session, "VERIFICATION_STATE_CHANGED", "verification_case", verification_id,
                     {"from": before.value, "to": evaluated.state.value})
    session.commit()
    return verification_payload(evaluated)


@router.post("/{verification_id}/manual-review")
def verification_manual_review(verification_id: str, body: ManualReviewRequest,
                               session: Session = Depends(get_db)):
    case = load_verification_case(session, verification_id)
    if case.state in {VerificationState.BURN_SIGNAL_DETECTED, VerificationState.NO_BURN_VERIFIED,
                      VerificationState.CLOSED}:
        raise HTTPException(status_code=409, detail="Terminal verification cannot be moved to manual review")
    case.state = VerificationState.MANUAL_REVIEW_REQUIRED
    case.reasons = [body.reason]
    save_verification_case(session, case)
    record_audit(session, "MANUAL_REVIEW_REQUESTED", "verification_case", verification_id,
                 {"reason": body.reason})
    session.commit()
    return verification_payload(case)


@router.post("/{verification_id}/close")
def verification_close(verification_id: str, body: ManualReviewRequest,
                       session: Session = Depends(get_db)):
    case = load_verification_case(session, verification_id)
    try:
        closed = close_case(case, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    save_verification_case(session, closed)
    record_audit(session, "VERIFICATION_CLOSED", "verification_case", verification_id,
                 {"reason": body.reason})
    session.commit()
    return verification_payload(closed)
