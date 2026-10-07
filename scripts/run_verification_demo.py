from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.certificates.generator import generate_prototype_certificate
from src.verification.engine import add_observation, evaluate_case, start_monitoring
from src.verification.models import VerificationObservation, VerificationState


def observation(field_id, index, when, *, quality="GOOD", burn=False, firms=False):
    return VerificationObservation(verification_observation_id=f"SYNTH-OBS-{field_id}-{index}",
        field_id=field_id, observation_datetime=when,
        source_image_id_s2=f"SYNTHETIC-S2-{field_id}-{index}",
        source_image_id_s1=f"SYNTHETIC-S1-{field_id}-{index}",
        ndvi=0.3 if burn else 0.34, nbr=0.1 if burn else 0.2, bais2=0.3 if burn else 0.1,
        ndvi_delta=-0.30 if burn else 0.01, nbr_delta=-0.28 if burn else 0.01,
        bais2_delta=0.20 if burn else 0.01, firms_nearby=firms,
        observation_quality=quality, fixture_or_real="SYNTHETIC",
        notes="Synthetic test scenario; not acquired satellite evidence")


def run():
    start = datetime.now(timezone.utc) - timedelta(days=31)
    safe = start_monitoring("SYNTHETIC-VERIFY-SAFE-01", pilot="DEMO PILOT", district="DEMO DISTRICT",
                            start=start, provenance="SYNTHETIC")
    for i, day in enumerate((0, 15, 30), 1):
        safe = add_observation(safe, observation(safe.field_id, i, start + timedelta(days=day)))
    safe = evaluate_case(safe, as_of=start + timedelta(days=30))
    certificate = generate_prototype_certificate(safe)

    burned = start_monitoring("SYNTHETIC-VERIFY-BURN-01", start=start, provenance="SYNTHETIC")
    burned = add_observation(burned, observation(burned.field_id, 1, start + timedelta(days=2), burn=True))
    burned = evaluate_case(burned, as_of=start + timedelta(days=2))
    try:
        generate_prototype_certificate(burned)
        burn_certificate_blocked = False
    except ValueError:
        burn_certificate_blocked = True

    unclear = start_monitoring("SYNTHETIC-VERIFY-UNCLEAR-01", start=start, provenance="SYNTHETIC")
    unclear = add_observation(unclear, observation(unclear.field_id, 1, start + timedelta(days=3), quality="POOR"))
    unclear = evaluate_case(unclear, as_of=start + timedelta(days=3))
    short = start_monitoring("SYNTHETIC-VERIFY-SHORT-01", start=start, provenance="SYNTHETIC")
    short = add_observation(short, observation(short.field_id, 1, start + timedelta(days=30)))
    short = evaluate_case(short, as_of=start + timedelta(days=30))

    report = {"provenance": "SYNTHETIC_FIXTURES_ONLY", "no_burn_state": safe.state.value,
        "no_burn_certificate_generated": safe.state == VerificationState.NO_BURN_VERIFIED,
        "certificate_id": certificate["certificate_id"], "certificate_pdf": certificate["pdf_path"],
        "certificate_qr": certificate["qr_path"], "certificate_sha256": certificate["sha256"],
        "prototype_disclaimer": certificate["prototype_disclaimer"],
        "burn_state": burned.state.value, "burn_certificate_blocked": burn_certificate_blocked,
        "unclear_state": unclear.state.value, "insufficient_state_at_deadline": short.state.value,
        "firms_alone_policy": "UNCLEAR / MANUAL REVIEW; never a burn finding",
        "absence_of_firms_policy": "NOT evidence that burning did not occur"}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/verification_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
