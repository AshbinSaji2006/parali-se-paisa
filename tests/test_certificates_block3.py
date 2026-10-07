from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest

from src.certificates.generator import generate_prototype_certificate
from src.certificates.integrity import metadata_sha256, qr_payload
from src.verification.engine import add_observation, start_monitoring
from src.verification.models import VerificationObservation, VerificationState


def verified_case(field_id="SYNTHETIC-CERT-FIELD"):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = start_monitoring(field_id, pilot="DEMO PILOT", district="DEMO DISTRICT",
                            start=start, provenance="SYNTHETIC")
    for index, day in enumerate((0, 15, 30), 1):
        case = add_observation(case, VerificationObservation(
            verification_observation_id=f"SYNTH-OBS-{index}", field_id=field_id,
            observation_datetime=start + timedelta(days=day), source_image_id_s2=f"SYNTH-S2-{index}",
            source_image_id_s1=f"SYNTH-S1-{index}", ndvi=0.3, nbr=0.2, bais2=0.1,
            ndvi_delta=0.01, nbr_delta=0.01, bais2_delta=0.01,
            observation_quality="GOOD", fixture_or_real="SYNTHETIC"))
    return case


@pytest.mark.parametrize("state", ["MONITORING", "INSUFFICIENT_EVIDENCE", "MANUAL_REVIEW_REQUIRED", "BURN_SIGNAL_DETECTED", "CLOSED"])
def test_certificate_generation_rejects_nonverified_state(tmp_path, state):
    case = verified_case()
    case.state = VerificationState(state)
    with pytest.raises(ValueError, match="NO_BURN_VERIFIED"):
        generate_prototype_certificate(case, tmp_path)


def test_certificate_pdf_and_qr_are_generated_with_required_disclaimers(tmp_path):
    certificate = generate_prototype_certificate(verified_case(), tmp_path)
    pdf = Path(certificate["pdf_path"])
    qr = Path(certificate["qr_path"])
    assert pdf.is_file() and pdf.read_bytes().startswith(b"%PDF")
    assert qr.is_file() and qr.stat().st_size > 0
    assert certificate["prototype_disclaimer"] == "PROTOTYPE / DEMONSTRATION CERTIFICATE — NOT OFFICIAL GOVERNMENT CERTIFICATE"
    assert certificate["fixture_or_real"] == "SYNTHETIC"


def test_metadata_hash_is_reproducible_and_key_order_independent():
    first = {"field_id": "F", "status": "NO_BURN_VERIFIED", "count": 3}
    second = {"count": 3, "status": "NO_BURN_VERIFIED", "field_id": "F"}
    assert metadata_sha256(first) == metadata_sha256(second)


def test_qr_payload_carries_certificate_id_and_checksum_without_official_url():
    payload = qr_payload("CERT-1", "abc123")
    data = json.loads(payload)
    assert data["certificate_id"] == "CERT-1"
    assert data["sha256"] == "abc123"
    assert data["verification"] == "OFFLINE_PROTOTYPE"
    assert "http" not in payload.lower()


def test_certificate_fields_include_observation_image_references(tmp_path):
    certificate = generate_prototype_certificate(verified_case("SYNTHETIC-FIELD"), tmp_path)
    assert certificate["field_id"] == "SYNTHETIC-FIELD"
    assert certificate["satellite_observation_count"] == 3
    assert certificate["before_image_reference"] == "SYNTH-S2-1"
    assert certificate["after_image_reference"] == "SYNTH-S2-3"
    assert certificate["certificate_version"] == "0.1.0-PROTOTYPE"


def test_certificate_ids_are_unique(tmp_path):
    case = verified_case()
    first = generate_prototype_certificate(case, tmp_path)
    second = generate_prototype_certificate(case, tmp_path)
    assert first["certificate_id"] != second["certificate_id"]


def test_certificate_checksum_recomputes_from_canonical_metadata(tmp_path):
    certificate = generate_prototype_certificate(verified_case(), tmp_path)
    metadata = {k: v for k, v in certificate.items() if k not in {"sha256", "qr_payload", "pdf_path", "qr_path"}}
    assert metadata_sha256(metadata) == certificate["sha256"]
    payload = json.loads(certificate["qr_payload"])
    assert payload["sha256"] == certificate["sha256"]


def test_certificate_cannot_be_created_without_stored_observations(tmp_path):
    case = verified_case()
    case.observations.clear()
    with pytest.raises(ValueError, match="requires stored observation"):
        generate_prototype_certificate(case, tmp_path)
