from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.dependencies import (certificate_payload, get_db, load_verification_case, record_audit,
                                  save_verification_case)
from src.certificates.generator import generate_prototype_certificate
from src.certificates.integrity import metadata_sha256
from src.db.models import CertificateRecord
from src.verification.engine import evaluate_case
from src.verification.models import VerificationState

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/certificates", tags=["certificates"])


@router.get("")
def certificates_list(session: Session = Depends(get_db)):
    rows = session.scalars(select(CertificateRecord).order_by(CertificateRecord.created_at.desc())).all()
    return {"items": [certificate_payload(x) for x in rows], "count": len(rows)}


@router.get("/{certificate_id}")
def certificate_get(certificate_id: str, session: Session = Depends(get_db)):
    record = session.get(CertificateRecord, certificate_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return certificate_payload(record)


@router.get("/{certificate_id}/file")
def certificate_file(certificate_id: str, session: Session = Depends(get_db)):
    record = session.get(CertificateRecord, certificate_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    from src.api.routes.product import safe_pdf
    return safe_pdf(record)


@router.post("/generate/{verification_id}", status_code=201)
def certificate_generate(verification_id: str, session: Session = Depends(get_db)):
    case = load_verification_case(session, verification_id)
    evaluated = evaluate_case(case, as_of=datetime.now(timezone.utc))
    if evaluated.state != VerificationState.NO_BURN_VERIFIED:
        raise HTTPException(status_code=409, detail=f"Certificate denied; verification state is {evaluated.state.value}")
    try:
        output = generate_prototype_certificate(evaluated)
        check = {k: v for k, v in output.items() if k not in {"sha256", "qr_payload", "pdf_path", "qr_path"}}
        if metadata_sha256(check) != output["sha256"]:
            raise ValueError("Generated certificate metadata checksum failed revalidation")
        record = CertificateRecord(certificate_id=output["certificate_id"], verification_id=verification_id,
                                  field_id=evaluated.field_id, sha256=output["sha256"],
                                  metadata_json={k: v for k, v in output.items() if k not in {"pdf_path", "qr_path"}},
                                  pdf_path=output["pdf_path"], qr_path=output["qr_path"],
                                  created_at=datetime.now(timezone.utc), provenance=evaluated.provenance)
        session.add(record)
        save_verification_case(session, evaluated)
        record_audit(session, "PROTOTYPE_CERTIFICATE_GENERATED", "certificate", output["certificate_id"],
                     {"verification_id": verification_id, "sha256": output["sha256"],
                      "provenance": evaluated.provenance})
        session.commit()
        return certificate_payload(record)
    except Exception as exc:
        session.rollback()
        LOGGER.exception("Certificate creation failed")
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise
