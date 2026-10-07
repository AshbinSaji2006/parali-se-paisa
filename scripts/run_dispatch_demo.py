from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from scripts.seed_demo import seed_demo
from src.api.main import create_app


def run():
    with tempfile.TemporaryDirectory(prefix="parali-dispatch-demo-") as temporary:
        database_url = f"sqlite:///{(Path(temporary) / 'action_platform.db').as_posix()}"
        seed_demo(database_url)
        app = create_app(database_url)
        client = TestClient(app)
        response = client.post("/api/v1/dispatch/optimise", json={"field_ids": ["SYNTHETIC-ACTION-FIELD-01"]})
        response.raise_for_status()
        result = response.json()
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports/dispatch_validation.json").write_text(
            json.dumps(result["dispatch"], indent=2), encoding="utf-8")
        print(json.dumps({"method": result["dispatch"]["method"],
                          "solver_status": result["dispatch"]["solver_status"],
                          "served": [s["field_id"] for r in result["dispatch"]["baler_routes"] for s in r["stops"]],
                          "unserved": result["dispatch"]["unserved_fields"],
                          "buyer_allocations": result["buyer_matching"]["allocations"],
                          "provenance": result["dispatch"]["provenance"]}, indent=2))
        client.close()
        app.state.engine.dispose()


if __name__ == "__main__":
    run()
