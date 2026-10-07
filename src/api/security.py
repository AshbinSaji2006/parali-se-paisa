"""JWT authentication and default-deny role policy; no UI-only permissions."""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import logging
import os
import secrets
from threading import Lock
import time
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select

from src.db.models import UserAccount, CollectionJob

HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/auth", tags=["authentication"])
LOGGER = logging.getLogger("parali.security")


def configure_security(app, demo_mode: bool):
    key = os.getenv("JWT_SECRET", "")
    if not demo_mode and len(key) < 32:
        raise RuntimeError("Live mode requires JWT_SECRET with at least 32 characters")
    if key and len(key) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")
    app.state.jwt_secret = key or secrets.token_urlsafe(48)
    app.state.ephemeral_jwt_key = not bool(key)
    app.state.login_attempts = defaultdict(deque)
    app.state.login_lock = Lock()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512)


class UserView(BaseModel):
    user_id: str
    username: str
    role: str
    field_id: str | None
    baler_id: str | None
    buyer_id: str | None
    is_demo: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1800
    user: UserView


def user_view(user):
    return {k: getattr(user, k) for k in UserView.model_fields}


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    # Single-process limiter. Production reverse proxy should also rate-limit.
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with request.app.state.login_lock:
        attempts = request.app.state.login_attempts
        for key in list(attempts):
            if not attempts[key] or attempts[key][-1] < now - 300:
                del attempts[key]
        bucket = attempts[address]
        while bucket and bucket[0] < now - 300:
            bucket.popleft()
        if len(bucket) >= 20:
            raise HTTPException(429, "Too many login attempts. Try again in five minutes.")
        bucket.append(now)
    with request.app.state.session_factory() as session:
        user = session.scalar(select(UserAccount).where(UserAccount.username == body.username))
        try:
            valid = HASHER.verify(user.password_hash if user else DUMMY_HASH, body.password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid or not user or not user.is_active or (user.is_demo and not request.app.state.demo_mode):
            LOGGER.warning('{"event":"authentication_failed"}')
            raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        issued = datetime.now(timezone.utc)
        token = jwt.encode({"sub": user.user_id, "iat": issued, "exp": issued + timedelta(minutes=30),
            "iss": "parali-api", "aud": "parali-web", "jti": str(uuid.uuid4())},
            request.app.state.jwt_secret, algorithm="HS256")
        return LoginResponse(access_token=token, user=UserView(**user_view(user)))


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(credentials.credentials, request.app.state.jwt_secret, algorithms=["HS256"],
            audience="parali-web", issuer="parali-api", options={"require": ["sub", "exp", "iat", "jti"]})
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}) from exc
    with request.app.state.session_factory() as session:
        user = session.get(UserAccount, claims["sub"])
        if not user or not user.is_active or (user.is_demo and not request.app.state.demo_mode):
            raise HTTPException(401, "Account unavailable")
        request.state.user = user_view(user)
    return request.state.user


@router.get("/me", response_model=UserView)
def me(user=Depends(current_user)):
    return user


def authorize(request: Request, user=Depends(current_user)):
    path = request.url.path.removeprefix("/api/v1")
    if os.getenv("DATA_MODE", "demo").lower() == "real" and request.method not in {"GET", "HEAD"}:
        raise HTTPException(503, "REAL DATA MODE IS READ ONLY: operational actions require verified real fields, buyers, balers, and providers")
    if request.method not in {"GET", "HEAD"} and not request.app.state.demo_mode:
        raise HTTPException(503, "LIVE DATA UNAVAILABLE: operational writes require verified providers")
    if user["role"] in {"ADMIN", "OFFICIAL"}:
        return user
    read_paths = ("/product", "/fields", "/jobs", "/balers", "/buyers", "/verification", "/certificates", "/system-status")
    if request.method == "GET" and any(path == p or path.startswith(p + "/") for p in read_paths):
        return user
    if request.method == "POST" and path.startswith("/pickup/") and user["role"] == "FARMER":
        return user
    if request.method == "PATCH" and path.startswith("/jobs/") and user["role"] == "BALER_OPERATOR":
        return user
    raise HTTPException(403, "Your role cannot perform this action")


def apply_scope(session, request):
    """Apply mode and ownership criteria to every ORM SELECT, including get(id)."""
    from sqlalchemy import event
    from sqlalchemy.orm import with_loader_criteria
    from src.db import models as m
    user = getattr(request.state, "user", None)
    session.info["actor"] = user
    criteria = []
    real_data_mode = os.getenv("DATA_MODE", "demo").lower() == "real"
    if not request.app.state.demo_mode or real_data_mode:
        for model in (m.FieldRecord, m.FieldObservation, m.IntelligenceResult, m.DispatchRun,
                      m.CollectionJob, m.VerificationCaseRecord, m.VerificationObservationRecord,
                      m.CertificateRecord, m.PickupRequest):
            criteria.append(with_loader_criteria(model, model.provenance == "REAL"))
        for model in (m.BalerRecord, m.BuyerRecord):
            criteria.append(with_loader_criteria(model, model.demo_or_real == "REAL"))
    if user and user["role"] not in {"ADMIN", "OFFICIAL"}:
        query = select(CollectionJob)
        if user["role"] == "FARMER":
            query = query.where(CollectionJob.field_id == user["field_id"])
        elif user["role"] == "BALER_OPERATOR":
            query = query.where(CollectionJob.baler_id == user["baler_id"])
        else:
            query = query.where(CollectionJob.buyer_id == user["buyer_id"])
        jobs = session.scalars(query).all()
        fields = list({j.field_id for j in jobs} | ({user["field_id"]} if user["field_id"] else set()))
        balers = list({j.baler_id for j in jobs} | ({user["baler_id"]} if user["baler_id"] else set()))
        buyers = list({j.buyer_id for j in jobs} | ({user["buyer_id"]} if user["buyer_id"] else set()))
        session.expunge_all()  # get() must not bypass criteria via a warmed identity map.
        for model in (m.FieldRecord, m.FieldObservation, m.IntelligenceResult, m.CollectionJob,
                      m.BuyerAllocation, m.VerificationCaseRecord, m.VerificationObservationRecord,
                      m.CertificateRecord, m.PickupRequest):
            criteria.append(with_loader_criteria(model, model.field_id.in_(fields)))
        criteria.append(with_loader_criteria(m.CollectionJob, m.CollectionJob.job_id.in_([j.job_id for j in jobs])))
        criteria.append(with_loader_criteria(m.BalerRecord, m.BalerRecord.baler_id.in_(balers)))
        criteria.append(with_loader_criteria(m.BuyerRecord, m.BuyerRecord.buyer_id.in_(buyers)))
        # Dispatch run output contains other farmers' fields; officials alone receive it.
        criteria.append(with_loader_criteria(m.DispatchRun, m.DispatchRun.dispatch_run_id == ""))
    @event.listens_for(session, "do_orm_execute")
    def scoped(execute_state):
        if execute_state.is_select and criteria:
            execute_state.statement = execute_state.statement.options(*criteria)
