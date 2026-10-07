"""Run isolated final release checks without touching the application's DB."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="parali-health-") as temp:
        db_url = f"sqlite:///{(Path(temp) / 'health.db').as_posix()}"
        os.environ.update({"DEMO_MODE": "true", "DATABASE_URL": db_url})
        from scripts.reset_demo import reset_demo
        import src.api.main as api_main
        from src.db.models import FieldRecord
        from src.db.session import make_session_factory
        from fastapi.testclient import TestClient

        accounts = {name: "health-check-password" for name in ("official", "operator", "buyer", "farmer")}
        reset_demo(db_url, passwords=accounts)
        engine = api_main.create_app(db_url, demo_mode=True).state.engine
        factory = make_session_factory(engine)
        with factory() as session:
            session.add(FieldRecord(field_id="HEALTH-REAL-PRESERVE", provenance="REAL", source="health-check",
                                    area_ha=1.0, centroid_lat=30.0, centroid_lon=74.0))
            session.commit()
        first = reset_demo(db_url, passwords=accounts)
        second = reset_demo(db_url, passwords=accounts)
        with factory() as session:
            preserved = session.get(FieldRecord, "HEALTH-REAL-PRESERVE") is not None
        engine.dispose()

        app = api_main.create_app(db_url, demo_mode=True)
        try:
            with TestClient(app) as client:
                health = client.get("/api/v1/health")
                login = client.post("/api/v1/auth/login", json={"username": "official", "password": accounts["official"]})
                product = client.get("/api/v1/product", headers={"Authorization": f"Bearer {login.json().get('access_token', '')}"}) if login.status_code == 200 else None
        finally:
            app.state.engine.dispose()
            api_main.app.state.engine.dispose()

    checks = {
        "isolated_sqlite_reset_repeated": first == accounts and second == accounts,
        "real_row_preserved": preserved,
        "health_endpoint": health.status_code == 200 and health.json().get("status") == "ok",
        "official_authentication": login.status_code == 200,
        "typed_product_endpoint": product is not None and product.status_code == 200,
        "openapi_export": (ROOT / "frontend/openapi.json").is_file(),
        "production_frontend_artifact": (ROOT / "frontend/dist/index.html").is_file(),
        "live_providers_configured": False,
        "postgresql_service_verified": False,
    }
    failures = [name for name, ok in checks.items() if name not in {"live_providers_configured", "postgresql_service_verified"} and not ok]
    warnings = ["Live satellite/provider integration is not configured or verified.",
                "PostgreSQL service is not available; PostgreSQL is configuration-only."]
    result = {"status": "FAIL" if failures else "WARN", "checks": checks, "failures": failures, "warnings": warnings}
    target = ROOT / "reports/final_health_check.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
