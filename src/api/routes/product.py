"""Read model for the web product, backed by existing domain services."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.dependencies import (get_db, field_payload, field_intelligence, baler_payload, buyer_payload,
    job_payload, certificate_payload, load_verification_case, verification_payload, record_audit, get_field_record)
from src.db.models import (FieldRecord, FieldObservation, BalerRecord, BuyerRecord, CollectionJob, DispatchRun,
    VerificationCaseRecord, CertificateRecord, BuyerAllocation, PickupRequest)
from src.dispatch.eligibility import check_eligibility
from src.certificates.integrity import metadata_sha256

router = APIRouter(tags=["product"])
public_router = APIRouter(tags=["public certificate verification"])


class ProductSnapshot(BaseModel):
    fields: list[dict]
    balers: list[dict]
    buyers: list[dict]
    jobs: list[dict]
    runs: list[dict]
    verification: list[dict]
    certificates: list[dict]
    allocations: list[dict]
    pickup_requests: list[dict]
    stats: dict[str, float]
    generated_at: str
    data_mode: str | None = None
    read_only: bool | None = None
    notice: str | None = None
    real_data_summary: dict | None = None


def status_payload(request):
    real_snapshot = Path(__file__).resolve().parents[3] / "data/real/derived/app_snapshot.json"
    real_requested = os.getenv("DATA_MODE", "demo").lower() == "real"
    real_mode = real_requested and real_snapshot.is_file()
    mode = "REAL DATA / WEAK PROXIES" if real_mode else ("REAL DATA NOT READY" if real_requested else ("DEMO / SYNTHETIC" if request.app.state.demo_mode else "LIVE DATA UNAVAILABLE"))
    return {"mode": mode,
        "demo_mode": request.app.state.demo_mode, "live_verified": False,
        "providers": {"Earth Engine": "NOT USED; Planetary Computer Sentinel-2" if real_mode else "UNVERIFIED — 0 real field observations", "FIRMS": "ARCHIVE ACQUIRED (2023-2024 full years; 2025 Oct-Dec; 2026 NRT 7-day); field proximity context only" if real_mode else "LIVE UNAVAILABLE",
            "Weather": "Open-Meteo ERA5 historical reanalysis acquired (0.25 deg grid; not a forecast)" if real_mode else "LIVE UNAVAILABLE",
            "Field status": "RULE-BASED STATUS CANDIDATE (weak proxy; no trained model)" if real_mode else "RULE-BASED STATUS CANDIDATE",
            "Sentinel-1": "CATALOG ONLY — 0 field observations" if real_mode else "LIVE UNAVAILABLE", "Database": "CONNECTED", "Model trust state": "NO_MODEL",
            "Routing provider": "GEODESIC_PROXY", "Buyer registry": "DEMO ONLY — 0 verified real buyers",
            "Baler registry": "DEMO ONLY — 0 verified real balers"},
        "ephemeral_jwt_key": request.app.state.ephemeral_jwt_key,
        "notice": ("Read-only real-data mode displays acquired Sentinel-2 and ERA5 observations with research field boundaries, plus FIRMS/MODIS fire detections as proximity context. Field status is a rule-based status candidate from weak proxy labels; no ground truth, verified buyer/baler registry, or operational decision model is available." if real_mode else ("DATA_MODE=real is requested but the snapshot is unavailable; the product endpoint will not fall back to demo records." if real_requested else "Synthetic demonstration. Rule candidates, normalized risk scores and prototype certificates are not ground truth or government decisions."))}


@router.get("/system-status")
def system_status(request: Request, session: Session = Depends(get_db)):
    session.execute(select(1))
    return status_payload(request)


@router.get("/product", response_model=ProductSnapshot)
def product(request: Request, session: Session = Depends(get_db)):
    real_snapshot = Path(__file__).resolve().parents[3] / "data/real/derived/app_snapshot.json"
    if os.getenv("DATA_MODE", "demo").lower() == "real":
        if not real_snapshot.is_file():
            raise HTTPException(503, "Real-data snapshot is not ready; demo records are not served in DATA_MODE=real.")
        # Dedicated read-only snapshot keeps real evidence separate from demo records.
        return json.loads(real_snapshot.read_text(encoding="utf-8"))
    fields = []
    jobs = session.scalars(select(CollectionJob)).all()
    active = {j.field_id for j in jobs if j.state != "CANCELLED"}
    for field in session.scalars(select(FieldRecord).order_by(FieldRecord.field_id)).all():
        intel, candidate = field_intelligence(session, field)
        eligibility = check_eligibility(candidate, unknown_weather_policy="WARN")
        if field.field_id in active:
            eligibility.eligible = False
            eligibility.reasons.append("ALREADY_ASSIGNED")
        observations = session.scalars(select(FieldObservation).where(FieldObservation.field_id == field.field_id)
                                      .order_by(FieldObservation.observation_datetime)).all()
        fields.append({**field_payload(field, demo_mode=session.info.get("demo_mode", True)), "intelligence": intel, "eligibility": eligibility.model_dump(),
            "history": [{"observation_datetime": o.observation_datetime.isoformat(), "features": o.features,
                         "provenance": o.provenance} for o in observations]})
    cases = [verification_payload(load_verification_case(session, c.verification_id))
             for c in session.scalars(select(VerificationCaseRecord).order_by(VerificationCaseRecord.created_at.desc())).all()]
    certificates = [certificate_payload(c) for c in session.scalars(select(CertificateRecord)).all()]
    allocations = [{"field_id": a.field_id, "buyer_id": a.buyer_id, "allocated_tonnes": a.allocated_tonnes,
                    "dispatch_run_id": a.dispatch_run_id, "match": a.match}
                   for a in session.scalars(select(BuyerAllocation)).all()]
    collected_runs_fields = {(j.dispatch_run_id, j.field_id) for j in jobs if j.state in {"COLLECTED", "DELIVERED"}}
    stats = {"fields": len(fields), "harvested_candidates": sum(f["intelligence"]["field_status"].get("status_candidate") == "HARVESTED" for f in fields),
        "high_risk": sum(f["intelligence"]["burn_risk"].get("risk_level") in {"HIGH", "CRITICAL"} for f in fields),
        "estimated_straw_tonnes": sum(f["intelligence"]["straw"].get("estimated_straw_tonnes") or 0 for f in fields),
        "assigned_fields": len(active), "collected_tonnes": sum(a["allocated_tonnes"] for a in allocations if (a["dispatch_run_id"], a["field_id"]) in collected_runs_fields),
        "active_verification": sum(c["state"] in {"MONITORING", "INSUFFICIENT_EVIDENCE", "MANUAL_REVIEW_REQUIRED"} for c in cases),
        "certificates": len(certificates), "manual_review": sum(c["state"] == "MANUAL_REVIEW_REQUIRED" for c in cases)}
    return ProductSnapshot(fields=fields, balers=[baler_payload(b) for b in session.scalars(select(BalerRecord)).all()],
        buyers=[buyer_payload(b) for b in session.scalars(select(BuyerRecord)).all()], jobs=[job_payload(j) for j in jobs],
        runs=[r.output for r in session.scalars(select(DispatchRun).order_by(DispatchRun.created_at.desc())).all()],
        verification=cases, certificates=certificates, allocations=allocations,
        pickup_requests=[{"field_id": p.field_id, "request_id": p.request_id, "created_at": p.created_at.isoformat()}
                         for p in session.scalars(select(PickupRequest)).all()], stats=stats,
        generated_at=datetime.now(timezone.utc).isoformat())


@router.post("/pickup/{field_id}", status_code=201)
def request_pickup(field_id: str, request: Request, session: Session = Depends(get_db)):
    field = get_field_record(session, field_id)
    existing = session.scalar(select(PickupRequest).where(PickupRequest.field_id == field_id))
    if existing:
        return {"request_id": existing.request_id, "field_id": field_id, "state": "REQUESTED"}
    _, candidate = field_intelligence(session, field)
    if not check_eligibility(candidate, unknown_weather_policy="WARN").eligible:
        raise HTTPException(409, "Field does not currently have eligible harvest evidence")
    record = PickupRequest(request_id=str(uuid.uuid4()), field_id=field_id,
        user_id=request.state.user["user_id"], provenance=field.provenance)
    session.add(record)
    record_audit(session, "PICKUP_REQUESTED", "field", field_id)
    session.commit()
    return {"request_id": record.request_id, "field_id": field_id, "state": "REQUESTED"}


@router.post("/demo/evidence/{scenario}")
def demo_evidence(scenario: str, request: Request, session: Session = Depends(get_db)):
    """Replay one historical fixture through the ordinary observation API logic."""
    from datetime import timedelta
    from scripts.reset_demo import SCENARIOS
    from src.api.routes.verification import verification_add_observation
    from src.api.schemas import ObservationCreate
    if not request.app.state.demo_mode or scenario not in SCENARIOS:
        raise HTTPException(404, "Demo scenario unavailable")
    case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "parali:block4:" + scenario))
    case = load_verification_case(session, case_id)
    if case.provenance != "SYNTHETIC":
        raise HTTPException(409, "Demo replay requires a synthetic case")
    index = len(case.observations)
    if index >= (3 if scenario == "safe" else 1):
        raise HTTPException(409, "All stored scenario observations have been processed")
    burning = scenario == "burn"
    body = ObservationCreate(verification_observation_id=f"{case_id}-{index}", field_id=case.field_id,
        observation_datetime=case.monitoring_start + timedelta(days=[0, 15, 30][index]),
        source_image_id_s2=f"SYNTHETIC-{scenario.upper()}-{index + 1}",
        ndvi=0.3, nbr=0.3, bais2=0.1, ndvi_delta=-0.4 if burning else 0.01,
        nbr_delta=-0.4 if burning else 0.01, bais2_delta=0.3 if burning else 0.01,
        firms_nearby=False, observation_quality="POOR" if scenario == "unclear" else "GOOD",
        notes="Historical synthetic fixture replay; not live satellite acquisition")
    return verification_add_observation(case_id, body, session)


def public_certificate(certificate_id, session):
    record = session.get(CertificateRecord, certificate_id)
    if record is None:
        raise HTTPException(404, "Certificate not found")
    metadata = {k: v for k, v in record.metadata_json.items() if k not in {"sha256", "qr_payload"}}
    payload = certificate_payload(record)
    payload["integrity_valid"] = metadata_sha256(metadata) == record.sha256
    payload["integrity_scope"] = "Stored metadata SHA-256 check only; it does not authenticate the PDF document."
    return record, payload


@public_router.get("/public/certificates/{certificate_id}")
def public_verify(certificate_id: str, session: Session = Depends(get_db)):
    return public_certificate(certificate_id, session)[1]


def safe_pdf(record):
    root = Path(__file__).resolve().parents[3] / "data/processed/certificates"
    path = Path(record.pdf_path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.suffix != ".pdf":
        raise HTTPException(404, "Certificate PDF unavailable")
    return FileResponse(path, media_type="application/pdf", filename=f"{record.certificate_id}.pdf")


@public_router.get("/public/certificates/{certificate_id}/file")
def public_pdf(certificate_id: str, session: Session = Depends(get_db)):
    record, payload = public_certificate(certificate_id, session)
    if not payload["integrity_valid"]:
        raise HTTPException(409, "Certificate metadata integrity check failed")
    return safe_pdf(record)


@public_router.get("/public/certificates/{certificate_id}/qr")
def public_qr(certificate_id: str, session: Session = Depends(get_db)):
    record, payload = public_certificate(certificate_id, session)
    if not payload["integrity_valid"]:
        raise HTTPException(409, "Certificate metadata integrity check failed")
    root = Path(__file__).resolve().parents[3] / "data/processed/certificates"
    path = Path(record.qr_path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.suffix.lower() != ".png":
        raise HTTPException(404, "Certificate QR unavailable")
    return FileResponse(path, media_type="image/png", filename=f"{record.certificate_id}-qr.png")
