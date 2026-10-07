from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerificationState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    MONITORING = "MONITORING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    BURN_SIGNAL_DETECTED = "BURN_SIGNAL_DETECTED"
    NO_BURN_VERIFIED = "NO_BURN_VERIFIED"
    CLOSED = "CLOSED"


class BurnEvidence(StrEnum):
    STRONG = "STRONG_BURN_EVIDENCE"
    MODERATE = "MODERATE_BURN_EVIDENCE"
    NO_BURN = "NO_BURN_INDICATORS_DETECTED"
    UNCLEAR = "UNCLEAR"


class VerificationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_observation_id: str
    field_id: str
    observation_datetime: datetime
    source_image_id_s2: str | None = None
    source_image_id_s1: str | None = None
    ndvi: float | None = Field(default=None, ge=-1, le=1)
    nbr: float | None = Field(default=None, ge=-2, le=2)
    bais2: float | None = None
    ndvi_delta: float | None = None
    nbr_delta: float | None = None
    bais2_delta: float | None = None
    firms_nearby: bool | None = None
    field_status_candidate: str | None = None
    sowing_candidate_confidence: float | None = Field(default=None, ge=0, le=1)
    observation_quality: str = "UNKNOWN"
    fixture_or_real: str = "SYNTHETIC"
    notes: str | None = None
    evidence: BurnEvidence | None = None
    evidence_reasons: list[str] = Field(default_factory=list)

    @field_validator("observation_datetime")
    @classmethod
    def make_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observation_datetime must include timezone information")
        return value


class VerificationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_id: str
    field_id: str
    pilot: str = "DEMO PILOT"
    district: str = "DEMO DISTRICT"
    state: VerificationState = VerificationState.NOT_STARTED
    monitoring_start: datetime | None = None
    monitoring_deadline: datetime | None = None
    observations: list[VerificationObservation] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    provenance: str = "SYNTHETIC"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
