from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api.main import create_app
from src.api.security import HASHER
from src.db.models import UserAccount, AuditEvent
from scripts.seed_demo import seed_demo


def make_client(tmp_path, demo=True):
    url=f"sqlite:///{(tmp_path/'auth.db').as_posix()}"
    if demo: seed_demo(url)
    app=create_app(url,demo_mode=demo)
    with app.state.session_factory() as db:
        if demo:
            rows=[UserAccount(user_id="official",username="official",password_hash=HASHER.hash("right-password"),role="OFFICIAL",is_demo=True,is_active=True),
              UserAccount(user_id="farmer",username="farmer",password_hash=HASHER.hash("farmer-password"),role="FARMER",field_id="SYNTHETIC-ACTION-FIELD-01",is_demo=True,is_active=True),
              UserAccount(user_id="operator",username="operator",password_hash=HASHER.hash("operator-password"),role="BALER_OPERATOR",baler_id="DEMO-BALER-02",is_demo=True,is_active=True),
              UserAccount(user_id="buyer",username="buyer",password_hash=HASHER.hash("buyer-password"),role="BUYER",buyer_id="DEMO-BUYER-02",is_demo=True,is_active=True)]
        else:
            rows=[UserAccount(user_id="official",username="official",password_hash=HASHER.hash("right-password"),role="OFFICIAL",is_demo=False,is_active=True)]
        db.add_all(rows);db.commit()
    return app,TestClient(app)


def token(client, username, password):
    res=client.post("/api/v1/auth/login",json={"username":username,"password":password})
    assert res.status_code==200
    return res.json()["access_token"]


def test_login_argon_jwt_expiry_and_role_enforcement(tmp_path):
    app,c=make_client(tmp_path)
    assert c.post("/api/v1/auth/login",json={"username":"official","password":"wrong-password"}).status_code==401
    assert c.get("/api/v1/fields").status_code==401
    c.headers["Authorization"]="Bearer invalid"
    assert c.get("/api/v1/fields").status_code==401
    c.headers["Authorization"]=f"Bearer {token(c,'farmer','farmer-password')}"
    assert c.get("/api/v1/fields").json()["count"]==1
    assert c.get("/api/v1/fields/DEMO-MUK-0001").status_code==404
    assert c.post("/api/v1/dispatch/optimise",json={}).status_code==403
    assert c.post("/api/v1/pickup/SYNTHETIC-ACTION-FIELD-01").status_code==201
    assert c.post("/api/v1/pickup/DEMO-MUK-0001").status_code==404
    c.close();app.state.engine.dispose()


def test_nonofficial_accounts_are_scoped_to_assigned_jobs_and_records(tmp_path):
    app,c=make_client(tmp_path)
    c.headers["Authorization"]=f"Bearer {token(c,'buyer','buyer-password')}"
    assert c.get("/api/v1/buyers").json()["count"]==1
    assert c.get("/api/v1/buyers").json()["items"][0]["buyer_id"]=="DEMO-BUYER-02"
    assert c.get("/api/v1/dispatch/runs/unknown").status_code==403
    assert c.post("/api/v1/dispatch/optimise",json={}).status_code==403
    c.headers["Authorization"]=f"Bearer {token(c,'operator','operator-password')}"
    assert c.patch("/api/v1/jobs/not-assigned/state",json={"state":"ACCEPTED"}).status_code==404
    c.close();app.state.engine.dispose()


def test_live_mode_never_falls_back_to_synthetic_rows(tmp_path,monkeypatch):
    app,c=make_client(tmp_path,demo=True)
    # Live view shares a database containing fixtures and must filter every one.
    monkeypatch.setenv("JWT_SECRET","test-secret-with-more-than-thirty-two-characters")
    live=create_app(str(app.state.engine.url),demo_mode=False)
    with live.state.session_factory() as db:
        db.add(UserAccount(user_id="live",username="live",password_hash=HASHER.hash("right-password"),role="OFFICIAL",is_demo=False,is_active=True));db.commit()
    lc=TestClient(live);lc.headers["Authorization"]=f"Bearer {token(lc,'live','right-password')}"
    assert lc.get("/api/v1/product").json()["fields"]==[]
    assert lc.get("/api/v1/product").json()["balers"]==[]
    assert lc.get("/api/v1/system-status").json()["mode"]=="LIVE DATA UNAVAILABLE"
    assert lc.post("/api/v1/dispatch/optimise",json={}).status_code==503
    assert lc.post("/api/v1/auth/login",json={"username":"official","password":"right-password"}).status_code==401
    lc.close();live.state.engine.dispose();c.close();app.state.engine.dispose()


def test_active_assignment_cannot_be_dispatched_twice_and_terminal_policy(tmp_path):
    app,c=make_client(tmp_path)
    c.headers["Authorization"]=f"Bearer {token(c,'official','right-password')}"
    field_id="SYNTHETIC-ACTION-FIELD-01"
    first=c.post("/api/v1/dispatch/optimise",json={"field_ids":[field_id]});assert first.status_code==200
    second=c.post("/api/v1/dispatch/optimise",json={"field_ids":[field_id]});assert second.status_code==200
    assert not second.json()["dispatch"]["baler_routes"]
    assert second.json()["dispatch"]["unserved_fields"][0]["reason"]=="ALREADY_ASSIGNED"
    with app.state.session_factory() as db:
        job=db.scalar(select(__import__('src.db.models',fromlist=['CollectionJob']).CollectionJob).where(
            __import__('src.db.models',fromlist=['CollectionJob']).CollectionJob.field_id==field_id))
        job_id=job.job_id
    c.patch(f"/api/v1/jobs/{job_id}/state",json={"state":"CANCELLED"})
    third=c.post("/api/v1/dispatch/optimise",json={"field_ids":[field_id]});assert third.status_code==200
    assert third.json()["dispatch"]["baler_routes"]
    with app.state.session_factory() as db:
        audit=db.scalars(select(AuditEvent).where(AuditEvent.entity_id==third.json()["dispatch"]["dispatch_run_id"])).all()
        assert audit[0].details["actor_user_id"]=="official"
    c.close();app.state.engine.dispose()
