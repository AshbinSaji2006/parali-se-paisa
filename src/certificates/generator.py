from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from src.certificates.integrity import metadata_sha256, qr_payload
from src.verification.models import VerificationCase, VerificationState


def generate_prototype_certificate(case: VerificationCase, output_dir: str | Path | None = None,
                                   *, generated_at: datetime | None = None) -> dict:
    """Generate a clearly marked demonstration PDF only for verified evidence state."""
    if case.state != VerificationState.NO_BURN_VERIFIED:
        raise ValueError("Certificate generation requires NO_BURN_VERIFIED state")
    if not case.observations:
        raise ValueError("A certificate requires stored observation evidence")
    certificate_id = f"PARALI-DEMO-{uuid.uuid4()}"
    now = generated_at or datetime.now(timezone.utc)
    metadata = {
        "certificate_id": certificate_id,
        "field_id": case.field_id,
        "pilot": case.pilot,
        "district": case.district,
        "monitoring_start": case.monitoring_start.isoformat() if case.monitoring_start else None,
        "monitoring_end": case.observations[-1].observation_datetime.isoformat(),
        "verification_status": case.state.value,
        "satellite_observation_count": len(case.observations),
        "before_image_reference": next((o.source_image_id_s2 for o in case.observations if o.source_image_id_s2), None),
        "after_image_reference": next((o.source_image_id_s2 for o in reversed(case.observations) if o.source_image_id_s2), None),
        "verification_method": "CONFIGURED_MULTI_OBSERVATION_RULES_V1",
        "generated_at": now.isoformat(),
        "certificate_version": "0.1.0-PROTOTYPE",
        "fixture_or_real": case.provenance,
        "prototype_disclaimer": "PROTOTYPE / DEMONSTRATION CERTIFICATE — NOT OFFICIAL GOVERNMENT CERTIFICATE",
    }
    checksum = metadata_sha256(metadata)
    payload = qr_payload(certificate_id, checksum)
    metadata["sha256"] = checksum
    metadata["qr_payload"] = payload
    root = Path(output_dir) if output_dir else Path(__file__).resolve().parents[2] / "data" / "processed" / "certificates"
    root.mkdir(parents=True, exist_ok=True)
    pdf_path = root / f"{certificate_id}.pdf"
    qr_path = root / f"{certificate_id}.png"
    qrcode.make(payload).save(qr_path)
    page = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    page.setTitle("Prototype Demonstration Certificate")
    page.setFont("Helvetica-Bold", 18)
    page.drawCentredString(width / 2, height - 28 * mm, "PROTOTYPE / DEMONSTRATION CERTIFICATE")
    page.setFont("Helvetica-Bold", 12)
    page.drawCentredString(width / 2, height - 37 * mm, "NOT OFFICIAL GOVERNMENT CERTIFICATE")
    page.setFont("Helvetica", 11)
    lines = [f"Certificate ID: {certificate_id}", f"Field: {case.field_id}",
             f"Pilot / district: {case.pilot} / {case.district}",
             f"Monitoring: {metadata['monitoring_start']} to {metadata['monitoring_end']}",
             f"Status: {case.state.value}", f"Good quality satellite observations: {len(case.observations)}",
             f"Before image: {metadata['before_image_reference'] or 'Not available'}",
             f"After image: {metadata['after_image_reference'] or 'Not available'}",
             f"Method: {metadata['verification_method']}", f"Provenance: {case.provenance}",
             "This prototype is for software demonstration only. It is not a government",
             "decision, legal finding, incentive approval, or proof beyond stored evidence.",
             f"Metadata SHA-256: {checksum}"]
    y = height - 57 * mm
    for line in lines:
        page.drawString(22 * mm, y, line[:110])
        y -= 9 * mm
    page.drawImage(str(qr_path), width - 58 * mm, 17 * mm, width=35 * mm, height=35 * mm)
    page.setFont("Helvetica", 8)
    page.drawString(22 * mm, 17 * mm, "QR encodes certificate ID and metadata checksum for offline verification.")
    page.save()
    return {**metadata, "pdf_path": str(pdf_path), "qr_path": str(qr_path)}
