"""Explicit demo accounts; passwords from environment or randomly generated."""
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.api.security import HASHER
from src.db.models import UserAccount
from src.db.session import make_engine, make_session_factory, create_schema

ACCOUNTS = {
    "official": ("OFFICIAL", None, None, None),
    "operator": ("BALER_OPERATOR", None, "DEMO-BALER-02", None),
    "buyer": ("BUYER", None, None, "DEMO-BUYER-02"),
    "farmer": ("FARMER", "SYNTHETIC-ACTION-FIELD-01", None, None),
}


def seed_accounts(database_url=None, passwords=None, roles=None):
    if os.getenv("DEMO_MODE", "true").lower() != "true":
        raise RuntimeError("Demo account seed requires DEMO_MODE=true")
    engine = make_engine(database_url)
    create_schema(engine)
    credentials = {}
    try:
        with make_session_factory(engine)() as session:
            for name, (role, field, baler, buyer) in ACCOUNTS.items():
                if roles is not None and name not in roles:
                    continue
                password = (passwords or {}).get(name) or os.getenv(f"DEMO_{name.upper()}_PASSWORD") or secrets.token_urlsafe(18)
                if len(password) < 12:
                    raise ValueError("Demo passwords must contain at least 12 characters")
                record = session.get(UserAccount, "demo-" + name)
                if record and not record.is_demo:
                    raise RuntimeError("Refusing to overwrite a non-demo account")
                if not record:
                    record = UserAccount(user_id="demo-" + name, username=name)
                    session.add(record)
                record.password_hash = HASHER.hash(password)
                record.role, record.field_id, record.baler_id, record.buyer_id = role, field, baler, buyer
                record.is_active, record.is_demo = True, True
                credentials[name] = password
            session.commit()
    finally:
        engine.dispose()
    return credentials


def write_credentials(credentials):
    directory = ROOT / ".demo"
    directory.mkdir(exist_ok=True)
    path = directory / "credentials.json"
    path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    print(f"Local DEMO credentials written to {path}. This ignored file is for the local demo only.")


if __name__ == "__main__":
    write_credentials(seed_accounts())
