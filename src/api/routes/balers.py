from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.api.dependencies import baler_model, baler_payload, commit_payload, get_db, record_audit
from src.api.schemas import BalerCreate, BalerPatch
from src.db.models import BalerRecord
from src.dispatch.models import Baler

router = APIRouter(prefix="/balers", tags=["balers"])


@router.get("")
def list_balers(session: Session = Depends(get_db)):
    rows = session.scalars(select(BalerRecord).order_by(BalerRecord.baler_id)).all()
    return {"items": [baler_payload(x) for x in rows], "count": len(rows)}


@router.post("", status_code=201)
def create_baler(body: BalerCreate, session: Session = Depends(get_db)):
    if body.demo_or_real == "REAL":
        raise HTTPException(status_code=422, detail="REAL registry imports require a verified ingestion workflow not provided by this prototype API")
    try:
        Baler.model_validate(body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = BalerRecord(**body.model_dump())
    session.add(record)
    record_audit(session, "BALER_CREATED", "baler", record.baler_id, {"provenance": record.demo_or_real})
    return commit_payload(session, record, baler_payload)


@router.patch("/{baler_id}")
def update_baler(baler_id: str, body: BalerPatch, session: Session = Depends(get_db)):
    record = session.get(BalerRecord, baler_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Baler not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("demo_or_real") == "REAL":
        raise HTTPException(status_code=422, detail="REAL registry imports require a verified ingestion workflow not provided by this prototype API")
    for key, value in changes.items():
        setattr(record, key, value)
    try:
        baler_model(record)
    except ValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(session, "BALER_UPDATED", "baler", baler_id, {"changed_fields": sorted(changes)})
    return commit_payload(session, record, baler_payload)
