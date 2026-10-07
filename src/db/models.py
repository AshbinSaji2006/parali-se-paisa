from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class FieldRecord(Base):
    __tablename__ = "fields"
    field_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    district: Mapped[str | None] = mapped_column(String(120))
    village: Mapped[str | None] = mapped_column(String(120))
    area_ha: Mapped[float | None] = mapped_column(Float)
    centroid_lat: Mapped[float | None] = mapped_column(Float)
    centroid_lon: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[dict | None] = mapped_column(JSON)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[str] = mapped_column(String(20), default="SYNTHETIC")
    source: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FieldObservation(Base):
    __tablename__ = "field_observations"
    __table_args__ = (UniqueConstraint("field_id", "observation_datetime", name="uq_field_observation_time"),)
    observation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"), index=True)
    observation_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_image_id_s2: Mapped[str | None] = mapped_column(String(255))
    source_image_id_s1: Mapped[str | None] = mapped_column(String(255))
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[str] = mapped_column(String(20), default="SYNTHETIC")


class IntelligenceResult(Base):
    __tablename__ = "intelligence_results"
    result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"), index=True)
    result_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    result: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(20), default="SYNTHETIC")


class BalerRecord(Base):
    __tablename__ = "balers"
    baler_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    operator_name: Mapped[str | None] = mapped_column(String(160))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    current_location_lat: Mapped[float | None] = mapped_column(Float)
    current_location_lon: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="AVAILABLE")
    working_start: Mapped[str] = mapped_column(String(5), default="08:00")
    working_end: Mapped[str] = mapped_column(String(5), default="17:00")
    service_rate_acres_per_hour: Mapped[float] = mapped_column(Float)
    daily_capacity_acres: Mapped[float] = mapped_column(Float)
    max_straw_capacity_tonnes: Mapped[float | None] = mapped_column(Float)
    available_from: Mapped[str | None] = mapped_column(String(5))
    demo_or_real: Mapped[str] = mapped_column(String(20), default="DEMO")
    source: Mapped[str] = mapped_column(String(255), default="DEMO_FIXTURE")


class BuyerRecord(Base):
    __tablename__ = "buyers"
    buyer_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    buyer_type: Mapped[str] = mapped_column(String(40), default="OTHER")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accepted_residue_types: Mapped[list] = mapped_column(JSON, default=list)
    daily_demand_tonnes: Mapped[float] = mapped_column(Float)
    remaining_demand_tonnes: Mapped[float] = mapped_column(Float)
    max_moisture_pct: Mapped[float | None] = mapped_column(Float)
    price_per_tonne: Mapped[float | None] = mapped_column(Float)
    price_is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    operating_start: Mapped[str] = mapped_column(String(5), default="00:00")
    operating_end: Mapped[str] = mapped_column(String(5), default="23:59")
    status: Mapped[str] = mapped_column(String(30), default="AVAILABLE")
    demo_or_real: Mapped[str] = mapped_column(String(20), default="DEMO")
    source: Mapped[str] = mapped_column(String(255), default="DEMO_FIXTURE")


class DispatchRun(Base):
    __tablename__ = "dispatch_runs"
    dispatch_run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    method: Mapped[str] = mapped_column(String(40))
    solver_status: Mapped[str] = mapped_column(String(40))
    distance_method: Mapped[str] = mapped_column(String(40))
    provenance: Mapped[str] = mapped_column(String(20))
    output: Mapped[dict] = mapped_column(JSON)


class DispatchRoute(Base):
    __tablename__ = "dispatch_routes"
    route_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dispatch_run_id: Mapped[str] = mapped_column(ForeignKey("dispatch_runs.dispatch_run_id"), index=True)
    baler_id: Mapped[str] = mapped_column(ForeignKey("balers.baler_id"))
    route: Mapped[dict] = mapped_column(JSON)


class DispatchStop(Base):
    __tablename__ = "dispatch_stops"
    stop_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("dispatch_routes.route_id"), index=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"))
    sequence: Mapped[int] = mapped_column(Integer)
    stop: Mapped[dict] = mapped_column(JSON)


class BuyerAllocation(Base):
    __tablename__ = "buyer_allocations"
    __table_args__ = (UniqueConstraint("dispatch_run_id", "field_id", name="uq_run_field_allocation"),)
    allocation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dispatch_run_id: Mapped[str] = mapped_column(ForeignKey("dispatch_runs.dispatch_run_id"), index=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"))
    buyer_id: Mapped[str] = mapped_column(ForeignKey("buyers.buyer_id"))
    allocated_tonnes: Mapped[float] = mapped_column(Float)
    match: Mapped[dict] = mapped_column(JSON)


class CollectionJob(Base):
    __tablename__ = "collection_jobs"
    __table_args__ = (Index("ix_collection_job_state", "state"),
        Index("uq_collection_job_active_field", "field_id", unique=True,
              sqlite_where=text("state != 'CANCELLED'"),
              postgresql_where=text("state != 'CANCELLED'")))
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dispatch_run_id: Mapped[str] = mapped_column(ForeignKey("dispatch_runs.dispatch_run_id"), index=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"))
    baler_id: Mapped[str] = mapped_column(ForeignKey("balers.baler_id"))
    buyer_id: Mapped[str] = mapped_column(ForeignKey("buyers.buyer_id"))
    state: Mapped[str] = mapped_column(String(30), default="PLANNED")
    provenance: Mapped[str] = mapped_column(String(20), default="SYNTHETIC")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VerificationCaseRecord(Base):
    __tablename__ = "verification_cases"
    verification_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"), index=True)
    pilot: Mapped[str] = mapped_column(String(160))
    district: Mapped[str] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(40))
    monitoring_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monitoring_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    provenance: Mapped[str] = mapped_column(String(20), default="SYNTHETIC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VerificationObservationRecord(Base):
    __tablename__ = "verification_observations"
    observation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey("verification_cases.verification_id"), index=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"), index=True)
    observation_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observation: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(20), default="SYNTHETIC")


class CertificateRecord(Base):
    __tablename__ = "certificates"
    certificate_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey("verification_cases.verification_id"), index=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON)
    pdf_path: Mapped[str] = mapped_column(Text)
    qr_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provenance: Mapped[str] = mapped_column(String(20), default="SYNTHETIC")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(80), default="API")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))
    field_id: Mapped[str | None] = mapped_column(ForeignKey("fields.field_id"))
    baler_id: Mapped[str | None] = mapped_column(ForeignKey("balers.baler_id"))
    buyer_id: Mapped[str | None] = mapped_column(ForeignKey("buyers.buyer_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class PickupRequest(Base):
    __tablename__ = "pickup_requests"
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_accounts.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provenance: Mapped[str] = mapped_column(String(20))
