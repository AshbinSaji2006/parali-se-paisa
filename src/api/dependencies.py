from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (AuditEvent, BalerRecord, BuyerRecord, FieldObservation, FieldRecord,
                           VerificationCaseRecord, VerificationObservationRecord)
from src.dispatch.models import Baler, DispatchField
from src.buyers.models import Buyer
from src.intelligence.service import intelligence_for_row
from src.verification.models import VerificationCase, VerificationObservation


def get_db(request: Request):
    session: Session = request.app.state.session_factory()
    session.info["demo_mode"] = request.app.state.demo_mode
    from src.api.security import apply_scope
    apply_scope(session, request)
    try:
        yield session
    finally:
        session.close()


def record_audit(session: Session, event_type: str, entity_type: str, entity_id: str,
                 details: dict | None = None, source: str = "API"):
    import json
    import logging
    actor = session.info.get("actor")
    details = {**(details or {}), "actor_user_id": actor["user_id"] if actor else "SYSTEM",
               "actor_role": actor["role"] if actor else "SYSTEM"}
    logging.getLogger("parali.audit").info(json.dumps({"event": event_type, "entity_id": entity_id,
                                                    "actor_user_id": details["actor_user_id"]}))
    session.add(AuditEvent(event_id=str(uuid.uuid4()), event_type=event_type, entity_type=entity_type,
                           entity_id=entity_id, timestamp=datetime.now(timezone.utc), source=source,
                           details=details or {}))


def get_field_record(session: Session, field_id: str) -> FieldRecord:
    item = session.get(FieldRecord, field_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Field not found")
    return item


def field_intelligence(session: Session, field: FieldRecord) -> tuple[dict, DispatchField]:
    row = field.properties.get("latest_features") if field.properties else None
    if not session.info.get("demo_mode", True) and row and row.get("fixture_or_real") != "REAL":
        row = None
    if not row:
        obs = session.scalar(select(FieldObservation).where(FieldObservation.field_id == field.field_id)
                             .order_by(FieldObservation.observation_datetime.desc()).limit(1))
        row = obs.features if obs else None
    if not session.info.get("demo_mode", True) and row and row.get("fixture_or_real") != "REAL":
        row = None
    if not row:
        row = {"field_id": field.field_id, "observation_quality": "UNKNOWN", "fixture_or_real": field.provenance}
    row = {**row, "field_id": field.field_id, "area_ha": field.area_ha or row.get("area_ha"),
           "fixture_or_real": field.provenance if field.provenance != "REAL" else row.get("fixture_or_real", "REAL")}
    intel = intelligence_for_row(row)
    status = intel["field_status"]
    risk = intel["burn_risk"]
    straw = intel["straw"]
    dispatch_field = DispatchField(
        field_id=field.field_id, latitude=field.centroid_lat, longitude=field.centroid_lon,
        area_ha=field.area_ha or float(row.get("area_ha") or 0.0),
        field_status=status.get("status_candidate") or status.get("status"),
        field_status_source=status.get("method"), field_status_confidence=status.get("confidence_band"),
        harvest_evidence_state="CANDIDATE" if status.get("confidence_band") in {"MODERATE", "HIGH"} else "UNKNOWN",
        estimated_straw_tonnes=straw.get("estimated_straw_tonnes") if straw.get("eligible") else None,
        burn_risk_score=risk.get("risk_score"), burn_risk_level=risk.get("risk_level"),
        risk_method=risk.get("method"), weather_suitability="UNKNOWN", weather_source="UNAVAILABLE",
        observation_quality=row.get("observation_quality"), provenance=field.provenance)
    return intel, dispatch_field


def load_verification_case(session: Session, verification_id: str) -> VerificationCase:
    record = session.get(VerificationCaseRecord, verification_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Verification case not found")
    rows = session.scalars(select(VerificationObservationRecord).where(
        VerificationObservationRecord.verification_id == verification_id).order_by(
        VerificationObservationRecord.observation_datetime)).all()
    observations = [VerificationObservation.model_validate(row.observation) for row in rows]
    return VerificationCase(verification_id=record.verification_id, field_id=record.field_id,
                            pilot=record.pilot, district=record.district, state=record.state,
                            monitoring_start=_aware(record.monitoring_start),
                            monitoring_deadline=_aware(record.monitoring_deadline), observations=observations,
                            reasons=record.reasons or [], provenance=record.provenance,
                            created_at=_aware(record.created_at), updated_at=_aware(record.updated_at))


def save_verification_case(session: Session, case: VerificationCase):
    record = session.get(VerificationCaseRecord, case.verification_id)
    if record is None:
        record = VerificationCaseRecord(verification_id=case.verification_id, field_id=case.field_id,
                                        pilot=case.pilot, district=case.district,
                                        state=case.state.value, monitoring_start=case.monitoring_start,
                                        monitoring_deadline=case.monitoring_deadline, reasons=case.reasons,
                                        provenance=case.provenance)
        session.add(record)
    else:
        record.state = case.state.value
        record.reasons = case.reasons
        record.updated_at = datetime.now(timezone.utc)


def verification_payload(case: VerificationCase):
    return case.model_dump(mode="json")


def field_payload(f, *, demo_mode=True):
    properties = f.properties
    if not demo_mode and properties:
        properties = {}
    return {"field_id": f.field_id, "district": f.district, "village": f.village, "area_ha": f.area_ha,
            "centroid": {"latitude": f.centroid_lat, "longitude": f.centroid_lon}, "geometry": f.geometry,
            "provenance": f.provenance, "source": f.source, "properties": properties}


def baler_payload(x):
    return {key: getattr(x, key) for key in ("baler_id", "name", "operator_name", "latitude", "longitude",
            "current_location_lat", "current_location_lon", "status", "working_start", "working_end",
            "service_rate_acres_per_hour", "daily_capacity_acres", "max_straw_capacity_tonnes",
            "available_from", "demo_or_real", "source")}


def buyer_payload(x):
    return {key: getattr(x, key) for key in ("buyer_id", "name", "buyer_type", "latitude", "longitude",
            "accepted_residue_types", "daily_demand_tonnes", "remaining_demand_tonnes", "max_moisture_pct",
            "price_per_tonne", "price_is_verified", "operating_start", "operating_end", "status",
            "demo_or_real", "source")}


def baler_model(x):
    return Baler.model_validate(baler_payload(x))


def buyer_model(x):
    return Buyer.model_validate(buyer_payload(x))


def job_payload(x):
    return {"job_id": x.job_id, "dispatch_run_id": x.dispatch_run_id, "field_id": x.field_id,
            "baler_id": x.baler_id, "buyer_id": x.buyer_id, "state": x.state, "provenance": x.provenance}


def certificate_payload(x):
    from pathlib import Path
    return {"certificate_id": x.certificate_id, "verification_id": x.verification_id,
            "field_id": x.field_id, "sha256": x.sha256, "metadata": x.metadata_json,
            "pdf_available": Path(x.pdf_path).is_file(), "qr_available": Path(x.qr_path).is_file(),
            "provenance": x.provenance}


def commit_payload(session, record, serializer):
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError
    try:
        session.commit()
        return serializer(record)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Unique identifier already exists") from exc


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
