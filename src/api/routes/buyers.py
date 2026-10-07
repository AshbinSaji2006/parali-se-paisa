from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.api.dependencies import buyer_model, buyer_payload, commit_payload, get_db, record_audit
from src.api.schemas import BuyerCreate, BuyerPatch
from src.db.models import BuyerRecord
from src.buyers.models import Buyer

router = APIRouter(prefix="/buyers", tags=["buyers"])


@router.get("")
def list_buyers(session: Session = Depends(get_db)):
    rows = session.scalars(select(BuyerRecord).order_by(BuyerRecord.buyer_id)).all()
    return {"items": [buyer_payload(x) for x in rows], "count": len(rows)}


@router.post("", status_code=201)
def create_buyer(body: BuyerCreate, session: Session = Depends(get_db)):
    if body.remaining_demand_tonnes > body.daily_demand_tonnes:
        raise HTTPException(status_code=422, detail="Remaining demand cannot exceed daily demand")
    if body.demo_or_real == "REAL":
        raise HTTPException(status_code=422, detail="REAL registry imports require a verified ingestion workflow not provided by this prototype API")
    try:
        Buyer.model_validate(body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = BuyerRecord(**body.model_dump())
    session.add(record)
    record_audit(session, "BUYER_CREATED", "buyer", record.buyer_id, {"provenance": record.demo_or_real})
    return commit_payload(session, record, buyer_payload)


@router.patch("/{buyer_id}")
def update_buyer(buyer_id: str, body: BuyerPatch, session: Session = Depends(get_db)):
    record = session.get(BuyerRecord, buyer_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Buyer not found")
    changes = body.model_dump(exclude_unset=True)
    new_demand = changes.get("daily_demand_tonnes", record.daily_demand_tonnes)
    new_remaining = changes.get("remaining_demand_tonnes", record.remaining_demand_tonnes)
    if new_demand is None or new_remaining is None:
        raise HTTPException(status_code=422, detail="Demand values cannot be null")
    if new_remaining > new_demand:
        raise HTTPException(status_code=422, detail="Remaining demand cannot exceed daily demand")
    if "remaining_demand_tonnes" in changes and new_remaining > record.remaining_demand_tonnes:
        raise HTTPException(status_code=409, detail="Increasing reserved capacity requires a verified registry reconciliation")
    if "daily_demand_tonnes" in changes and "remaining_demand_tonnes" not in changes:
        changes["remaining_demand_tonnes"] = min(record.remaining_demand_tonnes, new_demand)
    if changes.get("demo_or_real") == "REAL":
        raise HTTPException(status_code=422, detail="REAL registry imports require a verified ingestion workflow not provided by this prototype API")
    for key, value in changes.items():
        setattr(record, key, value)
    try:
        buyer_model(record)
    except ValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(session, "BUYER_UPDATED", "buyer", buyer_id, {"changed_fields": sorted(changes)})
    return commit_payload(session, record, buyer_payload)
