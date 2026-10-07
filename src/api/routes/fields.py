from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.dependencies import field_intelligence, field_payload, get_db, get_field_record
from src.db.models import FieldObservation, FieldRecord, IntelligenceResult
from datetime import datetime, timezone
import uuid

router = APIRouter(prefix="/fields", tags=["fields"])


@router.get("")
def list_fields(request: Request, limit: int = Query(default=100, ge=1, le=500), session: Session = Depends(get_db)):
    rows = session.scalars(select(FieldRecord).order_by(FieldRecord.field_id).limit(limit)).all()
    return {"items": [field_payload(f, demo_mode=request.app.state.demo_mode) for f in rows], "count": len(rows), "provenance": "per item"}


@router.get("/{field_id}")
def field_detail(field_id: str, request: Request, session: Session = Depends(get_db)):
    return field_payload(get_field_record(session, field_id), demo_mode=request.app.state.demo_mode)


@router.get("/{field_id}/history")
def field_history(field_id: str, session: Session = Depends(get_db)):
    get_field_record(session, field_id)
    rows = session.scalars(select(FieldObservation).where(FieldObservation.field_id == field_id)
                           .order_by(FieldObservation.observation_datetime)).all()
    return {"field_id": field_id, "items": [{"observation_id": x.observation_id,
            "observation_datetime": x.observation_datetime, "source_image_id_s2": x.source_image_id_s2,
            "source_image_id_s1": x.source_image_id_s1, "features": x.features,
            "provenance": x.provenance} for x in rows], "count": len(rows)}


@router.get("/{field_id}/intelligence")
def field_intelligence_endpoint(field_id: str, session: Session = Depends(get_db)):
    field = get_field_record(session, field_id)
    result, _dispatch = field_intelligence(session, field)
    result["provenance"] = {**result.get("provenance", {}), "fixture_or_real": field.provenance}
    session.add(IntelligenceResult(result_id=str(uuid.uuid4()), field_id=field_id,
                                   result_datetime=datetime.now(timezone.utc), result=result,
                                   provenance=field.provenance))
    session.commit()
    return result
