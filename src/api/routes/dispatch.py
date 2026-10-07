from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.api.dependencies import (baler_model, buyer_model, get_db, get_field_record, job_payload,
                                  record_audit, field_intelligence)
from src.api.schemas import DispatchRequest, JobTransitionRequest
from src.db.models import (BalerRecord, BuyerAllocation, BuyerRecord, CollectionJob, DispatchRoute,
                           DispatchRun, DispatchStop, FieldRecord, IntelligenceResult)
from src.operations.service import plan_action

LOGGER = logging.getLogger(__name__)
router = APIRouter(tags=["dispatch", "collection"])

JOB_TRANSITIONS = {
    "PLANNED": {"ACCEPTED", "CANCELLED"},
    "ACCEPTED": {"EN_ROUTE", "CANCELLED", "FAILED"},
    "EN_ROUTE": {"ARRIVED", "CANCELLED", "FAILED"},
    "ARRIVED": {"COLLECTING", "CANCELLED", "FAILED"},
    "COLLECTING": {"COLLECTED", "FAILED"},
    "COLLECTED": {"DELIVERED", "FAILED"},
    "DELIVERED": set(), "CANCELLED": set(), "FAILED": set(),
}


@router.post("/dispatch/optimise")
def dispatch_optimise(body: DispatchRequest, session: Session = Depends(get_db)):
    try:
        if body.field_ids and len(set(body.field_ids)) != len(body.field_ids):
            raise HTTPException(status_code=422, detail="Duplicate field_id values are not allowed")
        if session.bind.dialect.name == "sqlite":
            # Serialize SQLite reservation writers before reading buyer balances.
            session.execute(text("BEGIN IMMEDIATE"))
        query = select(FieldRecord).order_by(FieldRecord.field_id)
        if body.field_ids:
            query = query.where(FieldRecord.field_id.in_(body.field_ids))
        fields_db = session.scalars(query).all()
        if body.field_ids and {x.field_id for x in fields_db} != set(body.field_ids):
            raise HTTPException(status_code=404, detail="One or more requested fields were not found")
        balers_db = session.scalars(select(BalerRecord).order_by(BalerRecord.baler_id)).all()
        buyers_db = session.scalars(select(BuyerRecord).order_by(BuyerRecord.buyer_id).with_for_update()).all()
        intelligence = {}
        dispatch_inputs = []
        existing_assignments = {job.field_id: job for job in session.scalars(select(CollectionJob).where(
            CollectionJob.state != "CANCELLED").order_by(CollectionJob.updated_at.desc())).all()}
        excluded = []
        for item in fields_db:
            if item.field_id in existing_assignments:
                excluded.append(item)
                continue
            intel, dispatch_field = field_intelligence(session, item)
            intelligence[item.field_id] = intel
            dispatch_inputs.append(dispatch_field)
            session.add(IntelligenceResult(result_id=str(uuid.uuid4()), field_id=item.field_id,
                result_datetime=datetime.now(timezone.utc), result=intel, provenance=item.provenance))
        plan = plan_action(dispatch_inputs, [baler_model(x) for x in balers_db],
                           [buyer_model(x) for x in buyers_db])
        result, final_matches = plan.dispatch, plan.buyer_matching
        from src.dispatch.models import UnservedField
        result.unserved_fields.extend(UnservedField(field_id=x.field_id, reason="ALREADY_ASSIGNED",
            details=[f"Existing job {existing_assignments[x.field_id].job_id} is {existing_assignments[x.field_id].state}; resolve it before another reservation"],
            provenance=x.provenance) for x in excluded)
        served_ids = {stop.field_id for route in result.baler_routes for stop in route.stops}
        allocations = {match.field_id: match for match in final_matches.allocations}
        record = DispatchRun(dispatch_run_id=result.dispatch_run_id, created_at=result.created_at,
                             method=result.method, solver_status=result.solver_status,
                             distance_method=result.distance_method, provenance=result.provenance,
                             output={"dispatch": result.model_dump(mode="json"),
                                     "buyer_matching": final_matches.model_dump(mode="json"),
                                     "intelligence_field_ids": sorted(intelligence)})
        session.add(record)
        session.flush()
        baler_ids = {x.baler_id for x in balers_db}
        buyer_ids = {x.buyer_id for x in buyers_db}
        for route in result.baler_routes:
            if route.baler_id not in baler_ids:
                raise ValueError("Optimiser returned an unknown baler")
            route_id = str(uuid.uuid4())
            session.add(DispatchRoute(route_id=route_id, dispatch_run_id=result.dispatch_run_id,
                                      baler_id=route.baler_id, route=route.model_dump(mode="json")))
            session.flush()
            for stop in route.stops:
                if stop.buyer_id is None or stop.buyer_id not in buyer_ids:
                    raise ValueError("A routed field has no persisted compatible buyer allocation")
                session.add(DispatchStop(stop_id=str(uuid.uuid4()), route_id=route_id, field_id=stop.field_id,
                                         sequence=stop.sequence, stop=stop.model_dump(mode="json")))
                match = allocations[stop.field_id]
                session.add(BuyerAllocation(allocation_id=str(uuid.uuid4()), dispatch_run_id=result.dispatch_run_id,
                                            field_id=stop.field_id, buyer_id=stop.buyer_id,
                                            allocated_tonnes=match.allocated_tonnes, match=match.model_dump(mode="json")))
                buyer_record = session.get(BuyerRecord, stop.buyer_id)
                buyer_record.remaining_demand_tonnes = max(0.0,
                    buyer_record.remaining_demand_tonnes - match.allocated_tonnes)
                session.add(CollectionJob(job_id=str(uuid.uuid4()), dispatch_run_id=result.dispatch_run_id,
                                          field_id=stop.field_id, baler_id=route.baler_id,
                                          buyer_id=stop.buyer_id, state="PLANNED", provenance=stop.provenance))
        record_audit(session, "DISPATCH_CREATED", "dispatch_run", result.dispatch_run_id,
                     {"method": result.method, "served_fields": sorted(served_ids),
                      "unserved_fields": [x.model_dump(mode="json") for x in result.unserved_fields]})
        session.commit()
        return record.output
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        LOGGER.exception("Dispatch optimization failed")
        raise HTTPException(status_code=422, detail="Dispatch optimization failed; no reservations were committed") from exc


@router.get("/dispatch/runs/{dispatch_run_id}")
def dispatch_run(dispatch_run_id: str, session: Session = Depends(get_db)):
    record = session.get(DispatchRun, dispatch_run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Dispatch run not found")
    return record.output


@router.post("/dispatch/runs/{dispatch_run_id}/confirm")
def confirm_dispatch(dispatch_run_id: str, session: Session = Depends(get_db)):
    record = session.get(DispatchRun, dispatch_run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Dispatch run not found")
    jobs = session.scalars(select(CollectionJob).where(CollectionJob.dispatch_run_id == dispatch_run_id)).all()
    for job in jobs:
        if job.state != "PLANNED":
            raise HTTPException(status_code=409, detail=f"Job {job.job_id} is not PLANNED")
        job.state = "ACCEPTED"
    record_audit(session, "DISPATCH_CONFIRMED", "dispatch_run", dispatch_run_id, {"job_count": len(jobs)})
    session.commit()
    return {"dispatch_run_id": dispatch_run_id, "jobs": [job_payload(x) for x in jobs], "confirmed": True}


@router.get("/jobs")
def list_jobs(state: str | None = None, session: Session = Depends(get_db)):
    query = select(CollectionJob).order_by(CollectionJob.updated_at.desc())
    if state:
        query = query.where(CollectionJob.state == state.upper())
    rows = session.scalars(query).all()
    return {"items": [job_payload(x) for x in rows], "count": len(rows)}


@router.patch("/jobs/{job_id}/state")
def transition_job(job_id: str, body: JobTransitionRequest, session: Session = Depends(get_db)):
    job = session.get(CollectionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")
    target = body.state.upper()
    if target not in JOB_TRANSITIONS.get(job.state, set()):
        raise HTTPException(status_code=409, detail=f"Invalid job transition {job.state} -> {target}")
    old = job.state
    job.state = target
    if target == "CANCELLED":
        allocation = session.scalar(select(BuyerAllocation).where(
            BuyerAllocation.dispatch_run_id == job.dispatch_run_id,
            BuyerAllocation.field_id == job.field_id))
        if allocation is not None:
            buyer = session.get(BuyerRecord, allocation.buyer_id)
            buyer.remaining_demand_tonnes = min(buyer.daily_demand_tonnes,
                buyer.remaining_demand_tonnes + allocation.allocated_tonnes)
    record_audit(session, "COLLECTION_JOB_STATE_CHANGED", "collection_job", job_id,
                 {"from": old, "to": target}, source=body.source)
    session.commit()
    return job_payload(job)
