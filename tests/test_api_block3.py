from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api.main import create_app
from src.buyers.models import BuyerMatch, BuyerMatchResult
from src.dispatch.models import BalerRoute, DispatchResult, DispatchStop
from src.db.models import (AuditEvent, BalerRecord, BuyerRecord, CollectionJob, DispatchRun,
                           IntelligenceResult, VerificationCaseRecord, VerificationObservationRecord)
from scripts.seed_demo import seed_demo
from scripts.seed_accounts import seed_accounts
from src.api.security import HASHER
from src.db.models import UserAccount
from src.operations.service import ActionPlan


@pytest.fixture
def api(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'block3.db').as_posix()}"
    seed_demo(database_url)
    seed_accounts(database_url, passwords={"official": "test-official-password"}, roles={"official"})
    app = create_app(database_url)
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"username": "official", "password": "test-official-password"})
    assert response.status_code == 200
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    yield client, app
    client.close()
    app.state.engine.dispose()


def plan_synthetic(api):
    client, _app = api
    return client.post("/api/v1/dispatch/optimise", json={"field_ids": ["SYNTHETIC-ACTION-FIELD-01"]})


def test_health_and_openapi_are_available(api):
    client, _ = api
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert "/api/v1/dispatch/optimise" in client.get("/openapi.json").json()["paths"]
    assert client.get("/docs").status_code == 200


def test_fields_read_history_and_server_intelligence(api):
    client, _ = api
    field_id = "SYNTHETIC-ACTION-FIELD-01"
    item = client.get(f"/api/v1/fields/{field_id}").json()
    history = client.get(f"/api/v1/fields/{field_id}/history").json()
    intel_response = client.get(f"/api/v1/fields/{field_id}/intelligence")
    assert item["provenance"] == "SYNTHETIC"
    assert history["count"] == 1
    assert intel_response.status_code == 200
    assert intel_response.json()["field_status"]["status_candidate"] == "HARVESTED"
    assert intel_response.json()["provenance"]["fixture_or_real"] == "SYNTHETIC"


def test_missing_field_returns_404(api):
    client, _ = api
    assert client.get("/api/v1/fields/UNKNOWN").status_code == 404


def test_baler_create_patch_and_read(api):
    client, _ = api
    payload = {"baler_id": "TEST-BALER", "name": "DEMO Test Baler", "latitude": 30.1, "longitude": 74.6,
               "service_rate_acres_per_hour": 1, "daily_capacity_acres": 12, "demo_or_real": "DEMO"}
    created = client.post("/api/v1/balers", json=payload)
    assert created.status_code == 201
    assert created.json()["demo_or_real"] == "DEMO"
    updated = client.patch("/api/v1/balers/TEST-BALER", json={"status": "BUSY"})
    assert updated.status_code == 200 and updated.json()["status"] == "BUSY"
    assert client.get("/api/v1/balers").json()["count"] == 3


def test_real_baler_claim_is_rejected_without_verified_ingestion(api):
    client, _ = api
    payload = {"baler_id": "CLAIMED-REAL", "name": "Real?", "latitude": 30, "longitude": 74,
               "service_rate_acres_per_hour": 1, "daily_capacity_acres": 12,
               "demo_or_real": "REAL", "source": "made-up"}
    assert client.post("/api/v1/balers", json=payload).status_code == 422


def test_baler_status_enum_is_validated(api):
    client, _ = api
    payload = {"baler_id": "BAD", "name": "x", "latitude": 30, "longitude": 74,
               "service_rate_acres_per_hour": 1, "daily_capacity_acres": 12, "status": "DRIVING"}
    assert client.post("/api/v1/balers", json=payload).status_code == 422


def test_buyer_create_patch_and_read(api):
    client, _ = api
    payload = {"buyer_id": "TEST-BUYER", "name": "DEMO Test Buyer", "latitude": 30.1, "longitude": 74.6,
               "daily_demand_tonnes": 25, "remaining_demand_tonnes": 20, "demo_or_real": "DEMO"}
    assert client.post("/api/v1/buyers", json=payload).status_code == 201
    patched = client.patch("/api/v1/buyers/TEST-BUYER", json={"remaining_demand_tonnes": 10})
    assert patched.status_code == 200 and patched.json()["remaining_demand_tonnes"] == 10
    assert client.get("/api/v1/buyers").json()["count"] == 3


def test_buyer_remaining_capacity_cannot_exceed_daily_demand(api):
    client, _ = api
    response = client.post("/api/v1/buyers", json={"buyer_id": "OVER", "name": "x", "latitude": 30,
        "longitude": 74, "daily_demand_tonnes": 2, "remaining_demand_tonnes": 3})
    assert response.status_code == 422


def test_api_cannot_reopen_already_reserved_buyer_capacity(api):
    client, _ = api
    response = plan_synthetic(api)
    assert response.status_code == 200
    current = client.get("/api/v1/buyers").json()["items"]
    buyer = next(x for x in current if x["buyer_id"] == "DEMO-BUYER-02")
    assert buyer["remaining_demand_tonnes"] == 18
    reopened = client.patch("/api/v1/buyers/DEMO-BUYER-02", json={"remaining_demand_tonnes": 30})
    assert reopened.status_code == 409


def test_real_buyer_claim_is_rejected(api):
    client, _ = api
    response = client.post("/api/v1/buyers", json={"buyer_id": "REAL?", "name": "x", "latitude": 30,
        "longitude": 74, "daily_demand_tonnes": 2, "remaining_demand_tonnes": 2,
        "demo_or_real": "REAL", "source": "made-up"})
    assert response.status_code == 422


def test_dispatch_uses_ortools_and_persists_route_allocation_and_intelligence(api):
    client, app = api
    response = plan_synthetic(api)
    assert response.status_code == 200
    payload = response.json()
    assert payload["dispatch"]["method"] == "ORTOOLS_V1"
    assert payload["dispatch"]["distance_method"] == "GEODESIC_PROXY"
    assert payload["buyer_matching"]["allocations"][0]["allocated_tonnes"] == 12
    run_id = payload["dispatch"]["dispatch_run_id"]
    assert client.get(f"/api/v1/dispatch/runs/{run_id}").status_code == 200
    assert client.get("/api/v1/jobs").json()["count"] == 1
    session = app.state.session_factory()
    try:
        assert session.get(DispatchRun, run_id) is not None
        assert session.scalar(select(IntelligenceResult).where(IntelligenceResult.field_id == "SYNTHETIC-ACTION-FIELD-01"))
        assert session.scalar(select(BuyerRecord).where(BuyerRecord.buyer_id == "DEMO-BUYER-02")).remaining_demand_tonnes == 18
    finally:
        session.close()


def test_dispatch_cannot_accept_client_supplied_risk_or_straw(api):
    client, _ = api
    response = client.post("/api/v1/dispatch/optimise", json={"field_ids": ["SYNTHETIC-ACTION-FIELD-01"],
        "burn_risk_score": 1, "estimated_straw_tonnes": 99})
    assert response.status_code == 422


def test_no_baler_keeps_candidate_unserved_and_persists_reason(api):
    client, app = api
    for item in client.get("/api/v1/balers").json()["items"]:
        client.patch(f"/api/v1/balers/{item['baler_id']}", json={"status": "OFFLINE"})
    response = plan_synthetic(api)
    assert response.status_code == 200
    assert response.json()["dispatch"]["unserved_fields"][0]["reason"] == "NO_AVAILABLE_BALER"
    assert client.get("/api/v1/jobs").json()["count"] == 0


def test_no_buyer_keeps_candidate_unserved_with_reason(api):
    client, _ = api
    for item in client.get("/api/v1/buyers").json()["items"]:
        client.patch(f"/api/v1/buyers/{item['buyer_id']}", json={"status": "PAUSED"})
    response = plan_synthetic(api)
    assert response.status_code == 200
    assert response.json()["dispatch"]["unserved_fields"][0]["reason"] == "NO_COMPATIBLE_BUYER"
    assert client.get("/api/v1/jobs").json()["count"] == 0


def test_dispatch_failed_request_rolls_back_all_changes(api):
    client, app = api
    before = {x["buyer_id"]: x["remaining_demand_tonnes"] for x in client.get("/api/v1/buyers").json()["items"]}
    assert client.post("/api/v1/dispatch/optimise", json={"field_ids": ["NO-SUCH-FIELD"]}).status_code == 404
    session = app.state.session_factory()
    try:
        assert session.scalar(select(DispatchRun)) is None
        after = {x.buyer_id: x.remaining_demand_tonnes for x in session.scalars(select(BuyerRecord)).all()}
        assert after == before
    finally:
        session.close()


def test_database_transaction_rolls_back_after_staged_dispatch_failure(api, monkeypatch):
    client, app = api
    import src.api.routes.dispatch as dispatch_routes
    field_id = "SYNTHETIC-ACTION-FIELD-01"
    dispatch = DispatchResult(dispatch_run_id="forced-failure-run", method="ORTOOLS_V1",
        solver_status="FEASIBLE_SOLUTION", distance_method="GEODESIC_PROXY", provenance="SYNTHETIC",
        baler_routes=[BalerRoute(baler_id="UNKNOWN-BALER", stops=[DispatchStop(sequence=1,
            field_id=field_id, estimated_straw_tonnes=12, service_minutes=100,
            burn_risk_score=0.5, buyer_id="DEMO-BUYER-02", provenance="SYNTHETIC")],
            total_distance_km=1, distance_method="GEODESIC_PROXY", estimated_service_minutes=100,
            assigned_area_acres=5, assigned_straw_tonnes=12, provenance="DEMO")], unserved_fields=[], eligibility=[])
    match = BuyerMatch(field_id=field_id, buyer_id="DEMO-BUYER-02", match_score=50, distance_km=1,
        distance_method="GEODESIC_PROXY", allocated_tonnes=12, remaining_buyer_capacity_tonnes=18,
        matching_reasons=["fixture"], status="MATCHED", provenance="SYNTHETIC")
    plan = ActionPlan(dispatch=dispatch, buyer_matching=BuyerMatchResult(allocations=[match],
        buyer_remaining_capacity_tonnes={"DEMO-BUYER-02": 18}, unassigned_field_ids=[],
        distance_method="GEODESIC_PROXY", provenance="SYNTHETIC"))
    monkeypatch.setattr(dispatch_routes, "plan_action", lambda *args, **kwargs: plan)
    response = plan_synthetic(api)
    assert response.status_code == 422
    session = app.state.session_factory()
    try:
        assert session.get(DispatchRun, "forced-failure-run") is None
        assert session.scalar(select(IntelligenceResult)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "DISPATCH_CREATED")) is None
        assert session.get(BuyerRecord, "DEMO-BUYER-02").remaining_demand_tonnes == 30
    finally:
        session.close()


def test_collection_state_machine_rejects_invalid_transition_and_accepts_valid_path(api):
    client, _ = api
    response = plan_synthetic(api)
    run_id = response.json()["dispatch"]["dispatch_run_id"]
    job = client.get("/api/v1/jobs").json()["items"][0]
    assert client.patch(f"/api/v1/jobs/{job['job_id']}/state", json={"state": "DELIVERED"}).status_code == 409
    confirmed = client.post(f"/api/v1/dispatch/runs/{run_id}/confirm")
    assert confirmed.status_code == 200
    for state in ("EN_ROUTE", "ARRIVED", "COLLECTING", "COLLECTED", "DELIVERED"):
        moved = client.patch(f"/api/v1/jobs/{job['job_id']}/state", json={"state": state})
        assert moved.status_code == 200
    assert moved.json()["state"] == "DELIVERED"


def test_cancelled_collection_releases_buyer_reservation(api):
    client, _ = api
    response = plan_synthetic(api)
    job = client.get("/api/v1/jobs").json()["items"][0]
    initial = 30.0
    current = {x["buyer_id"]: x["remaining_demand_tonnes"] for x in client.get("/api/v1/buyers").json()["items"]}
    allocated_buyer = job["buyer_id"]
    assert current[allocated_buyer] < initial
    cancelled = client.patch(f"/api/v1/jobs/{job['job_id']}/state", json={"state": "CANCELLED"})
    assert cancelled.status_code == 200
    after = {x["buyer_id"]: x["remaining_demand_tonnes"] for x in client.get("/api/v1/buyers").json()["items"]}
    assert after[allocated_buyer] == initial


def test_verification_api_computes_evidence_and_overwrites_provenance(api):
    client, app = api
    field_id = "SYNTHETIC-ACTION-FIELD-01"
    started = client.post(f"/api/v1/verification/start/{field_id}", json={})
    assert started.status_code == 201
    case = started.json()
    response = client.post(f"/api/v1/verification/{case['verification_id']}/observations", json={
        "verification_observation_id": "API-OBS-1", "field_id": field_id,
        "observation_datetime": case["monitoring_start"], "ndvi_delta": 0.01, "nbr_delta": 0.01,
        "bais2_delta": 0.01, "observation_quality": "GOOD", "fixture_or_real": "REAL"})
    assert response.status_code == 200
    assert response.json()["observations"][0]["fixture_or_real"] == "SYNTHETIC"
    assert response.json()["observations"][0]["evidence"] == "NO_BURN_INDICATORS_DETECTED"
    with client as _:
        forged = client.post(f"/api/v1/verification/{case['verification_id']}/observations", json={
            "verification_observation_id": "API-OBS-2", "field_id": field_id,
            "observation_datetime": case["monitoring_start"], "evidence": "NO_BURN_INDICATORS_DETECTED"})
        assert forged.status_code == 422


def test_unclear_verification_goes_to_manual_review_and_is_audited(api):
    client, app = api
    field_id = "SYNTHETIC-ACTION-FIELD-01"
    started = client.post(f"/api/v1/verification/start/{field_id}", json={}).json()
    response = client.post(f"/api/v1/verification/{started['verification_id']}/observations", json={
        "verification_observation_id": "POOR-OBS", "field_id": field_id,
        "observation_datetime": started["monitoring_start"], "observation_quality": "POOR"})
    assert response.status_code == 200
    assert response.json()["state"] == "MANUAL_REVIEW_REQUIRED"
    denied = client.post(f"/api/v1/certificates/generate/{started['verification_id']}")
    assert denied.status_code == 409
    session = app.state.session_factory()
    try:
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "VERIFICATION_OBSERVATION_ADDED"))
        assert session.scalar(select(VerificationObservationRecord).where(VerificationObservationRecord.observation_id == "POOR-OBS"))
    finally:
        session.close()


def test_certificate_generation_rechecks_state_and_serves_pdf(api, tmp_path):
    client, app = api
    field_id = "SYNTHETIC-ACTION-FIELD-01"
    started = client.post(f"/api/v1/verification/start/{field_id}", json={}).json()
    start = datetime.now(timezone.utc) - timedelta(days=31)
    session = app.state.session_factory()
    try:
        item = session.get(VerificationCaseRecord, started["verification_id"])
        item.monitoring_start = start
        item.monitoring_deadline = start + timedelta(days=30)
        session.commit()
    finally:
        session.close()
    for i, day in enumerate((0, 15, 30), 1):
        response = client.post(f"/api/v1/verification/{started['verification_id']}/observations", json={
            "verification_observation_id": f"CERT-OBS-{i}", "field_id": field_id,
            "observation_datetime": (start + timedelta(days=day)).isoformat(),
            "source_image_id_s2": f"SYNTH-CERT-S2-{i}", "ndvi_delta": 0.01, "nbr_delta": 0.01,
            "bais2_delta": 0.01, "observation_quality": "GOOD"})
        assert response.status_code == 200
    certificate = client.post(f"/api/v1/certificates/generate/{started['verification_id']}")
    assert certificate.status_code == 201
    item = certificate.json()
    assert item["metadata"]["verification_status"] == "NO_BURN_VERIFIED"
    assert "NOT OFFICIAL GOVERNMENT CERTIFICATE" in item["metadata"]["prototype_disclaimer"]
    assert item["pdf_available"] and item["qr_available"]
    assert client.get(f"/api/v1/certificates/{item['certificate_id']}").status_code == 200
    file = client.get(f"/api/v1/certificates/{item['certificate_id']}/file")
    assert file.status_code == 200 and file.content.startswith(b"%PDF")


def test_verification_manual_review_and_close_endpoints(api):
    client, _ = api
    started = client.post("/api/v1/verification/start/SYNTHETIC-ACTION-FIELD-01", json={}).json()
    case_id = started["verification_id"]
    review = client.post(f"/api/v1/verification/{case_id}/manual-review", json={"reason": "Check image context"})
    assert review.status_code == 200 and review.json()["state"] == "MANUAL_REVIEW_REQUIRED"
    closed = client.post(f"/api/v1/verification/{case_id}/close", json={"reason": "Closed for demo"})
    assert closed.status_code == 200 and closed.json()["state"] == "CLOSED"


def test_api_reports_entity_provenance_and_route_count(api):
    client, _ = api
    assert client.get("/api/v1/balers").json()["items"][0]["demo_or_real"] == "DEMO"
    assert client.get("/api/v1/buyers").json()["items"][0]["demo_or_real"] == "DEMO"
    paths = client.get("/openapi.json").json()["paths"]
    operations = sum(1 for methods in paths.values() for method in methods if method in {"get", "post", "patch"})
    assert operations >= 25


def test_application_startup_does_not_seed_demo_data(tmp_path):
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    with app.state.session_factory() as session:
        session.add(UserAccount(user_id="test-official", username="official",
            password_hash=HASHER.hash("test-official-password"), role="OFFICIAL", is_active=True, is_demo=False))
        session.commit()
    response = client.post("/api/v1/auth/login", json={"username": "official", "password": "test-official-password"})
    assert response.status_code == 200
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    assert client.get("/api/v1/fields").json()["count"] == 0
    client.close()
    app.state.engine.dispose()
