"""Run the real persisted Block 4 story through FastAPI endpoints and actors."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DEMO_MODE"] = "true"
os.environ.setdefault("JWT_SECRET", "local-demo-only-key-change-before-deployment-" + uuid.uuid4().hex)

from fastapi.testclient import TestClient
from src.api.main import create_app
from scripts.reset_demo import reset_demo

DB = ROOT / ".demo" / "block4-judge.db"
URL = f"sqlite:///{DB.as_posix()}"


def require(response, expected=200):
    if response.status_code != expected:
        raise RuntimeError(f"Expected HTTP {expected}, received {response.status_code}: {response.text}")
    return response.json()


def signin(client, username, password):
    response = require(client.post("/api/v1/auth/login", json={"username": username, "password": password}))
    client.headers["Authorization"] = "Bearer " + response["access_token"]


def run_story():
    credentials = reset_demo(URL)
    app = create_app(URL)
    story = []
    try:
        with TestClient(app) as official:
            signin(official, "official", credentials["official"])
            require(official.get("/api/v1/health"))
            require(official.get("/api/v1/product"))
            require(official.get("/api/v1/fields/SYNTHETIC-ACTION-FIELD-01"))
            story.extend(["official login", "dashboard data", "field map API", "harvest candidate detail"])
            dispatch = require(official.post("/api/v1/dispatch/optimise", json={"field_ids": ["SYNTHETIC-ACTION-FIELD-01"]}))
            route = dispatch["dispatch"]["baler_routes"]
            if not route or not dispatch["buyer_matching"]["allocations"]:
                raise RuntimeError("The synthetic judge field was not assigned to both a baler and buyer")
            duplicate = require(official.post("/api/v1/dispatch/optimise", json={"field_ids": ["SYNTHETIC-ACTION-FIELD-01"]}))
            if duplicate["dispatch"]["unserved_fields"][0]["reason"] != "ALREADY_ASSIGNED":
                raise RuntimeError("Repeated optimisation failed to protect the active assignment")
            job = require(official.get("/api/v1/jobs"))["items"][0]
            story.extend(["dispatch persisted", "baler and buyer reserved", "duplicate dispatch rejected"])

            with TestClient(app) as operator:
                signin(operator, "operator", credentials["operator"])
                own = require(operator.get("/api/v1/jobs"))["items"]
                if not any(j["job_id"] == job["job_id"] for j in own):
                    raise RuntimeError("Baler operator cannot see its assigned job")
                for state in ["ACCEPTED", "EN_ROUTE", "ARRIVED", "COLLECTING", "COLLECTED", "DELIVERED"]:
                    moved = require(operator.patch(f"/api/v1/jobs/{job['job_id']}/state", json={"state": state}))
                    if moved["state"] != state:
                        raise RuntimeError(f"Operator workflow failed at {state}")
            story.append("operator transitions: ACCEPTED → EN_ROUTE → ARRIVED → COLLECTING → COLLECTED → DELIVERED")

            safe_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "parali:block4:safe"))
            for _ in range(3):
                safe = require(official.post("/api/v1/demo/evidence/safe"))
            if safe["state"] != "NO_BURN_VERIFIED":
                raise RuntimeError(f"Stored safe scenario did not evaluate to NO_BURN_VERIFIED: {safe['state']}")
            certificate = require(official.post(f"/api/v1/certificates/generate/{safe_id}"), 201)
            public = require(official.get(f"/api/v1/public/certificates/{certificate['certificate_id']}"))
            if not public["integrity_valid"] or "NOT OFFICIAL GOVERNMENT CERTIFICATE" not in public["metadata"]["prototype_disclaimer"]:
                raise RuntimeError("Public certificate integrity or prototype disclaimer failed")
            pdf = official.get(f"/api/v1/public/certificates/{certificate['certificate_id']}/file")
            if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
                raise RuntimeError("Prototype certificate PDF retrieval failed")
            story.extend(["three stored chronological observations", "NO_BURN_VERIFIED", "prototype certificate generated",
                          "public checksum verified", "certificate PDF retrieved"])

            burned = require(official.post("/api/v1/demo/evidence/burn"))
            if burned["state"] != "BURN_SIGNAL_DETECTED":
                raise RuntimeError(f"Burn scenario did not block certificate: {burned['state']}")
            denied = official.post(f"/api/v1/certificates/generate/{burned['verification_id']}")
            if denied.status_code != 409:
                raise RuntimeError("Burn evidence did not block certificate generation")
            manual = require(official.post("/api/v1/demo/evidence/unclear"))
            if manual["state"] != "MANUAL_REVIEW_REQUIRED":
                raise RuntimeError("Unclear observation failed to enter manual review")
            story.extend(["burn evidence blocks certificate", "unclear evidence enters manual review"])

            with TestClient(app) as farmer:
                signin(farmer, "farmer", credentials["farmer"])
                own = require(farmer.get("/api/v1/fields"))
                if own["count"] != 1 or own["items"][0]["field_id"] != "SYNTHETIC-ACTION-FIELD-01":
                    raise RuntimeError("Farmer ownership scope returned the wrong fields")
                if farmer.post("/api/v1/dispatch/optimise", json={}).status_code != 403:
                    raise RuntimeError("Farmer was allowed to optimise dispatch")
            story.append("farmer ownership and role restrictions")

            report = {"result": "PASS", "created_at": datetime.now(timezone.utc).isoformat(),
                "database": str(DB), "story": story, "dispatch_run_id": dispatch["dispatch"]["dispatch_run_id"],
                "baler_id": route[0]["baler_id"], "buyer_id": dispatch["buyer_matching"]["allocations"][0]["buyer_id"],
                "collection_job_id": job["job_id"], "collection_state": "DELIVERED",
                "verification_id": safe_id, "verification_state": safe["state"],
                "certificate_id": certificate["certificate_id"], "certificate_sha256": certificate["sha256"],
                "certificate_integrity": public["integrity_valid"], "burn_state": burned["state"],
                "manual_state": manual["state"], "data_class": "SYNTHETIC DEMONSTRATION ONLY"}
            (ROOT / "reports").mkdir(exist_ok=True)
            (ROOT / "reports/e2e_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            return report
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    run_story()
