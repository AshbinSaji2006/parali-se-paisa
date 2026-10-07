from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class BalerCreate(BaseModel):
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
    demo_or_real: Literal["DEMO", "SYNTHETIC", "FIXTURE", "REAL"] = "DEMO"
    source: str = "API_UNVERIFIED_INPUT"


class BalerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    operator_name: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    current_location_lat: float | None = Field(default=None, ge=-90, le=90)
    current_location_lon: float | None = Field(default=None, ge=-180, le=180)
    status: Literal["AVAILABLE", "BUSY", "OFFLINE", "MAINTENANCE"] | None = None
    working_start: str | None = None
    working_end: str | None = None
    service_rate_acres_per_hour: float | None = Field(default=None, gt=0)
    daily_capacity_acres: float | None = Field(default=None, gt=0)
    max_straw_capacity_tonnes: float | None = Field(default=None, gt=0)
    available_from: str | None = None
    demo_or_real: Literal["DEMO", "SYNTHETIC", "FIXTURE", "REAL"] | None = None
    source: str | None = None


class BuyerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyer_id: str
    name: str
    buyer_type: Literal["BIOMASS_POWER", "CBG", "PELLET", "INDUSTRIAL_BOILER", "OTHER"] = "OTHER"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accepted_residue_types: list[str] = Field(default_factory=lambda: ["PADDY_STRAW"])
    daily_demand_tonnes: float = Field(ge=0)
    remaining_demand_tonnes: float = Field(ge=0)
    max_moisture_pct: float | None = Field(default=None, ge=0, le=100)
    price_per_tonne: float | None = Field(default=None, ge=0)
    price_is_verified: bool = False
    operating_start: str = "00:00"
    operating_end: str = "23:59"
    status: Literal["AVAILABLE", "UNAVAILABLE", "PAUSED"] = "AVAILABLE"
    demo_or_real: Literal["DEMO", "SYNTHETIC", "FIXTURE", "REAL"] = "DEMO"
    source: str = "API_UNVERIFIED_INPUT"


class BuyerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    buyer_type: Literal["BIOMASS_POWER", "CBG", "PELLET", "INDUSTRIAL_BOILER", "OTHER"] | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accepted_residue_types: list[str] | None = None
    daily_demand_tonnes: float | None = Field(default=None, ge=0)
    remaining_demand_tonnes: float | None = Field(default=None, ge=0)
    max_moisture_pct: float | None = Field(default=None, ge=0, le=100)
    price_per_tonne: float | None = Field(default=None, ge=0)
    price_is_verified: bool | None = None
    operating_start: str | None = None
    operating_end: str | None = None
    status: Literal["AVAILABLE", "UNAVAILABLE", "PAUSED"] | None = None
    demo_or_real: Literal["DEMO", "SYNTHETIC", "FIXTURE", "REAL"] | None = None
    source: str | None = None


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_ids: list[str] | None = None


class VerificationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pilot: str = "DEMO PILOT"
    district: str = "DEMO DISTRICT"


class ObservationCreate(BaseModel):
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


class ManualReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=1000)


class JobTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str
    source: str = "API"
