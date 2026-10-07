"""Reset synthetic rows only, transactionally; refuse mixed real/demo dependencies."""
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, delete

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.db import models as m
from src.db.session import make_engine, make_session_factory, create_schema
from src.api.dependencies import save_verification_case
from src.verification.engine import start_monitoring
from scripts.seed_demo import seed_demo
from scripts.seed_accounts import seed_accounts, write_credentials

SCENARIOS = {"safe": "SYNTHETIC-ACTION-FIELD-01", "burn": "DEMO-MUK-0001", "unclear": "DEMO-MUK-0002"}


def seed_story(database_url=None):
    engine = make_engine(database_url)
    with make_session_factory(engine)() as session:
        for scenario, field_id in SCENARIOS.items():
            case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "parali:block4:" + scenario))
            if session.get(m.VerificationCaseRecord, case_id):
                continue
            case = start_monitoring(field_id, pilot="HISTORICAL SYNTHETIC DEMO", district="DEMO DISTRICT",
                provenance="SYNTHETIC", start=datetime(2026, 9, 1, tzinfo=timezone.utc))
            case.verification_id = case_id
            save_verification_case(session, case)
        session.commit()
    engine.dispose()


def reset_demo(database_url=None, passwords=None):
    if os.getenv("DEMO_MODE", "true").lower() != "true":
        raise RuntimeError("Reset requires explicit demo mode")
    engine = make_engine(database_url)
    create_schema(engine)
    try:
        with make_session_factory(engine)() as session:
            # Children are deleted first. A real child referencing a demo parent
            # triggers FK protection and rolls the entire transaction back.
            demo_certificates = session.scalars(select(m.CertificateRecord).where(
                m.CertificateRecord.provenance.in_(["DEMO", "SYNTHETIC", "FIXTURE"]))).all()
            demo_runs = select(m.DispatchRun.dispatch_run_id).where(m.DispatchRun.provenance.in_(
                ["DEMO", "SYNTHETIC", "FIXTURE"]))
            demo_routes = select(m.DispatchRoute.route_id).where(m.DispatchRoute.dispatch_run_id.in_(demo_runs))
            for model in (m.CertificateRecord, m.VerificationObservationRecord, m.VerificationCaseRecord,
                          m.PickupRequest, m.IntelligenceResult, m.FieldObservation, m.CollectionJob):
                session.execute(delete(model).where(model.provenance.in_(["DEMO", "SYNTHETIC", "FIXTURE"])))
            session.execute(delete(m.DispatchStop).where(m.DispatchStop.route_id.in_(demo_routes)))
            session.execute(delete(m.DispatchRoute).where(m.DispatchRoute.dispatch_run_id.in_(demo_runs)))
            session.execute(delete(m.BuyerAllocation).where(m.BuyerAllocation.dispatch_run_id.in_(demo_runs)))
            session.execute(delete(m.DispatchRun).where(m.DispatchRun.provenance.in_(
                ["DEMO", "SYNTHETIC", "FIXTURE"])))
            session.execute(delete(m.UserAccount).where(m.UserAccount.is_demo.is_(True)))
            session.execute(delete(m.FieldRecord).where(m.FieldRecord.provenance.in_(
                ["DEMO", "SYNTHETIC", "FIXTURE"])))
            session.execute(delete(m.BalerRecord).where(m.BalerRecord.demo_or_real.in_(
                ["DEMO", "SYNTHETIC", "FIXTURE"])))
            session.execute(delete(m.BuyerRecord).where(m.BuyerRecord.demo_or_real.in_(
                ["DEMO", "SYNTHETIC", "FIXTURE"])))
            # Preserve audit records: reset is itself auditable, including old history.
            from src.api.dependencies import record_audit
            record_audit(session, "DEMO_RESET", "system", "demo", source="EXPLICIT_SEED_COMMAND")
            session.commit()
            certificate_root = (ROOT / "data/processed/certificates").resolve()
            for certificate in demo_certificates:
                for stored_path in (certificate.pdf_path, certificate.qr_path):
                    candidate = Path(stored_path).resolve()
                    if candidate.is_relative_to(certificate_root) and candidate.is_file():
                        candidate.unlink()
    finally:
        engine.dispose()
    seed_demo(database_url)
    seed_story(database_url)
    return seed_accounts(database_url, passwords)


if __name__ == "__main__":
    write_credentials(reset_demo())
