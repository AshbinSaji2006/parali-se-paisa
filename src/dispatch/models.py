from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Provenance = Literal["DEMO", "SYNTHETIC", "FIXTURE", "REAL"]


class Baler(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baler_id: str
    name: str
    operator_name: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    current_location_lat: float | None = Field(default=None, ge=-90, le=90)
    current_location_lon: float | None = Field(default=None, ge=-180, le=180)
    status: Literal["AVAILABLE", "BUSY", "OFFLINE", "MAINTENANCE"] = "AVAILABLE"
    working_start: str = "08:00"
    working_end: str = "17:00"
    service_rate_acres_per_hour: float = Field(gt=0)
    daily_capacity_acres: float = Field(gt=0)
    max_straw_capacity_tonnes: float | None = Field(default=None, gt=0)
    available_from: str | None = None
    demo_or_real: Provenance = "DEMO"
    source: str = "DEMO_FIXTURE"

    @field_validator("working_start", "working_end", "available_from")
    @classmethod
    def validate_clock_time(cls, value):
        if value is None:
            return value
        if value == "":
            return None
        try:
            hour, minute = map(int, value.split(":"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("time must use HH:MM") from exc
        if hour not in range(24) or minute not in range(60):
            raise ValueError("time must use a valid 24-hour HH:MM clock value")
        return value

    @model_validator(mode="after")
    def validate_current_location_pair(self):
        if (self.current_location_lat is None) != (self.current_location_lon is None):
            raise ValueError("current_location_lat and current_location_lon must be supplied together")
        return self

    @property
    def route_latitude(self) -> float:
        return self.current_location_lat if self.current_location_lat is not None else self.latitude

    @property
    def route_longitude(self) -> float:
        return self.current_location_lon if self.current_location_lon is not None else self.longitude


class DispatchField(BaseModel):
    model_config = ConfigDict(extra="allow")
    field_id: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    area_ha: float = Field(gt=0)
    field_status: str | None = None
    field_status_source: str | None = None
    field_status_confidence: str | None = None
    harvest_evidence_state: str = "UNKNOWN"
    estimated_straw_tonnes: float | None = Field(default=None, ge=0)
    burn_risk_score: float | None = Field(default=None, ge=0, le=1)
    burn_risk_level: str | None = None
    risk_method: str | None = None
    weather_suitability: Literal["DRY", "UNSUITABLE", "UNKNOWN"] = "UNKNOWN"
    weather_source: str = "UNAVAILABLE"
    observation_quality: str | None = None
    provenance: Provenance = "SYNTHETIC"
    buyer_id: str | None = None
    buyer_match_score: float | None = None


class EligibilityResult(BaseModel):
    field_id: str
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DispatchStop(BaseModel):
    sequence: int
    field_id: str
    estimated_straw_tonnes: float
    service_minutes: int
    burn_risk_score: float | None
    burn_risk_level: str | None = None
    risk_method: str | None = None
    field_status: str | None = None
    field_status_source: str | None = None
    field_status_confidence: str | None = None
    harvest_evidence_state: str | None = None
    weather_suitability: str | None = None
    weather_source: str | None = None
    observation_quality: str | None = None
    buyer_id: str | None = None
    provenance: Provenance


class BalerRoute(BaseModel):
    baler_id: str
    stops: list[DispatchStop]
    total_distance_km: float
    distance_method: str
    estimated_service_minutes: int
    estimated_travel_minutes: int | None = None
    estimated_total_minutes: int | None = None
    assigned_area_acres: float
    assigned_straw_tonnes: float
    route_duration_basis: str = "SERVICE_ONLY_DISTANCE_NOT_TIME"
    provenance: Provenance


class UnservedField(BaseModel):
    field_id: str
    reason: str
    details: list[str] = Field(default_factory=list)
    provenance: Provenance


class DispatchResult(BaseModel):
    dispatch_run_id: str
    method: str
    solver_status: str
    baler_routes: list[BalerRoute]
    unserved_fields: list[UnservedField]
    eligibility: list[EligibilityResult]
    distance_method: str
    provenance: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
