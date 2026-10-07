"""Real snapshot mode must not leak demo ORM rows or write to the demo store."""
from fastapi.testclient import TestClient

from src.api.security import HASHER
from src.db.models import UserAccount
from src.api.main import create_app
from scripts.seed_demo import seed_demo


def test_real_snapshot_mode_is_read_only_and_hides_demo_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    database = f"sqlite:///{(tmp_path / 'mixed.db').as_posix()}"
    seed_demo(database)
    app = create_app(database, demo_mode=True)
    with app.state.session_factory() as session:
        session.add(UserAccount(user_id="judge", username="judge",
            password_hash=HASHER.hash("judge-password"), role="OFFICIAL",
            is_demo=True, is_active=True))
        session.commit()
    with TestClient(app) as client:
        token = client.post("/api/v1/auth/login", json={
            "username": "judge", "password": "judge-password"}).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        snapshot = client.get("/api/v1/product")
        assert snapshot.status_code == 200
        assert snapshot.json()["data_mode"] == "REAL"
        assert snapshot.json()["fields"]
        status = client.get("/api/v1/system-status").json()
        assert status["mode"] == "REAL DATA / WEAK PROXIES"
        assert client.get("/api/v1/fields").json()["count"] == 0
        assert client.post("/api/v1/dispatch/optimise", json={}).status_code == 503
        assert client.post("/api/v1/verification/start/FTW-IN-PB-1629045").status_code == 503
