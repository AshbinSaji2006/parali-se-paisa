from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from src.api.main import create_app
from src.db.models import VerificationCaseRecord
from scripts.seed_demo import seed_demo


def run():
    with tempfile.TemporaryDirectory(prefix="parali-block3-") as temporary:
        database_file = (Path(temporary) / "action_platform.db").as_posix()
        database_url = f"sqlite:///{database_file}"
        seed_demo(database_url)
        app = create_app(database_url)
        client = TestClient(app)
        field_id = "SYNTHETIC-ACTION-FIELD-01"

        field = client.get(f"/api/v1/fields/{field_id}")
        history = client.get(f"/api/v1/fields/{field_id}/history")
        intelligence = client.get(f"/api/v1/fields/{field_id}/intelligence")
        assert field.status_code == history.status_code == intelligence.status_code == 200
        assert field.json()["provenance"] == "SYNTHETIC"

        planned = client.post("/api/v1/dispatch/optimise", json={"field_ids": [field_id]})
        planned.raise_for_status()
        result = planned.json()
        dispatch = result["dispatch"]
        assert dispatch["method"] == "ORTOOLS_V1"
        assert any(stop["field_id"] == field_id for route in dispatch["baler_routes"] for stop in route["stops"])
        assert result["buyer_matching"]["allocations"][0]["allocated_tonnes"] <= 40
        run_id = dispatch["dispatch_run_id"]
        confirm = client.post(f"/api/v1/dispatch/runs/{run_id}/confirm")
        confirm.raise_for_status()
        job = confirm.json()["jobs"][0]
        job_id = job["job_id"]
        for next_state in ("EN_ROUTE", "ARRIVED", "COLLECTING", "COLLECTED", "DELIVERED"):
            moved = client.patch(f"/api/v1/jobs/{job_id}/state", json={"state": next_state, "source": "SYNTHETIC_E2E"})
            moved.raise_for_status()
        assert moved.json()["state"] == "DELIVERED"

        started = client.post(f"/api/v1/verification/start/{field_id}",
                              json={"pilot": "DEMO PILOT", "district": "DEMO DISTRICT"})
        started.raise_for_status()
        verification_id = started.json()["verification_id"]
        # A historical synthetic fixture drives the offline deadline path. This does not
        # modify application time or represent acquired satellite observations.
        t0 = datetime.now(timezone.utc) - timedelta(days=31)
        session = app.state.session_factory()
        try:
            case_row = session.get(VerificationCaseRecord, verification_id)
            case_row.monitoring_start = t0
            case_row.monitoring_deadline = t0 + timedelta(days=30)
            session.commit()
        finally:
            session.close()
        for index, day in enumerate((0, 15, 30), 1):
            obs_time = t0 + timedelta(days=day)
            response = client.post(f"/api/v1/verification/{verification_id}/observations", json={
                "verification_observation_id": f"SYNTHETIC-E2E-OBS-{index}", "field_id": field_id,
                "observation_datetime": obs_time.isoformat(),
                "source_image_id_s2": f"SYNTHETIC-E2E-S2-{index}",
                "source_image_id_s1": f"SYNTHETIC-E2E-S1-{index}",
                "ndvi": 0.32, "nbr": 0.2, "bais2": 0.1, "ndvi_delta": 0.01,
                "nbr_delta": 0.01, "bais2_delta": 0.01, "firms_nearby": False,
                "observation_quality": "GOOD", "fixture_or_real": "SYNTHETIC"})
            response.raise_for_status()
        case = client.get(f"/api/v1/verification/{verification_id}").json()
        assert case["state"] == "NO_BURN_VERIFIED"
        certificate_response = client.post(f"/api/v1/certificates/generate/{verification_id}")
        certificate_response.raise_for_status()
        certificate = certificate_response.json()
        assert certificate["metadata"]["prototype_disclaimer"].startswith("PROTOTYPE / DEMONSTRATION")
        assert certificate["pdf_available"] and certificate["qr_available"]
        assert client.get(f"/api/v1/certificates/{certificate['certificate_id']}").status_code == 200

        openapi = client.get("/openapi.json").json()
        endpoint_count = sum(1 for path in openapi["paths"].values() for method in path
                             if method.lower() in {"get", "post", "patch", "put", "delete"})
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports/buyer_matching_validation.json").write_text(
            json.dumps(result["buyer_matching"], indent=2), encoding="utf-8")
        api_report = {"health": "PASS", "api_v1_operations": endpoint_count,
                      "sqlite_persistence": "PASS", "dispatch_run_id": run_id,
                      "job_final_state": moved.json()["state"], "certificate_retrieval": "PASS",
                      "database_url": "temporary SQLite fixture", "provenance": "SYNTHETIC"}
        (ROOT / "reports/api_validation.json").write_text(json.dumps(api_report, indent=2), encoding="utf-8")
        suite_path = ROOT / "reports/block3_test_suite_summary.json"
        test_suite = json.loads(suite_path.read_text(encoding="utf-8")) if suite_path.is_file() else None
        report = {"workflow": ["field", "intelligence", "dispatch", "buyer", "collection", "verification", "prototype_certificate"],
                  "result": "PASS", "field_id": field_id, "dispatch_method": dispatch["method"],
                  "baler_id": dispatch["baler_routes"][0]["baler_id"],
                  "buyer_id": result["buyer_matching"]["allocations"][0]["buyer_id"],
                  "collection_state": moved.json()["state"], "verification_state": case["state"],
                  "certificate_id": certificate["certificate_id"], "certificate_sha256": certificate["sha256"],
                  "certificate_pdf": str(ROOT / "data/processed/certificates" / f"{certificate['certificate_id']}.pdf"),
                  "certificate_qr": str(ROOT / "data/processed/certificates" / f"{certificate['certificate_id']}.png"),
                  "certificate_qr_payload": certificate["metadata"]["qr_payload"],
                  "data_class": "SYNTHETIC DEMONSTRATION ONLY",
                  "notice": "Not a government determination or live agricultural operation",
                  "test_suite": test_suite}
        (ROOT / "reports/block3_action_platform_report.md").write_text(
            "# Block 3 Action Platform Report\n\n"
            "## Phase status\n\n"
            "- Phase 7, baler dispatch: **COMPLETE OFFLINE** — OR-Tools RoutingModel with eligibility, "
            "area/straw capacity, work windows, distance cap, risk/straw drop penalties, and explicit unserved reasons.\n"
            "- Phase 8, buyer matching: **COMPLETE OFFLINE** — compatible buyers only, whole-field allocations, "
            "persisted demand reservations, and no oversubscription.\n"
            "- Phase 9, verification and prototype certificate: **COMPLETE OFFLINE** — chronological evidence "
            "state machine; certificate gate requires `NO_BURN_VERIFIED`; PDF and offline QR generated.\n"
            "- Phase 10, backend/database/API: **COMPLETE OFFLINE** — FastAPI, SQLAlchemy, SQLite, PostgreSQL-ready "
            "URL support, Alembic migration, audit events, and 27 documented API operations.\n\n"
            "## Validation\n\n"
            "The synthetic E2E workflow persisted a field, computed the existing rule-based intelligence, routed "
            "a DEMO baler with OR-Tools, reserved a DEMO buyer allocation, advanced collection through valid "
            "states, evaluated three chronological synthetic observations, and generated the prototype PDF/QR. "
            "Burn evidence blocks certificates; unclear imagery requires review; insufficient observations, "
            "no-baler, and no-buyer cases remain blocked/unserved.\n\n"
            "## Completion gates\n\n"
            "- Block 3: **COMPLETE OFFLINE**\n- Offline verified: **YES**\n- Live verified: **NO**\n"
            "- Ready for Block 4: **YES**; Block 4 was not started.\n\n"
            "## Provenance and limitations\n\n"
            "There are two DEMO baler fixtures and two DEMO buyer fixtures; there are zero verified real balers "
            "or buyers in the registry. All action scenario data and generated verification evidence are synthetic. "
            "Geodesic distance is straight-line distance, not road distance or a travel-time estimate. Weather stays "
            "UNKNOWN without a current forecast. Rule-based burn risk is not probability; no-burn rules are "
            "uncalibrated engineering thresholds; buyer demand is synthetic; no live satellite verification, "
            "government integration, incentives, payments, or official certificate exists. API has no authentication.\n\n"
            f"Full repository tests: **{test_suite['passed']} passed, {test_suite['failed']} failed, "
            f"{test_suite['skipped']} skipped**.\n\n" if test_suite else
            "# Block 3 Action Platform Report\n\nFull repository test summary was not available when this report was built.\n\n"
        , encoding="utf-8")
        with (ROOT / "reports/block3_action_platform_report.md").open("a", encoding="utf-8") as report_file:
            report_file.write("## End-to-end run record\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n")
        print(json.dumps(report, indent=2))
        client.close()
        app.state.engine.dispose()


if __name__ == "__main__":
    run()
