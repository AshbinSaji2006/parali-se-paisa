from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Buyer(BaseModel):
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
    source: str = "DEMO_FIXTURE"

    @field_validator("operating_start", "operating_end")
    @classmethod
    def validate_clock_time(cls, value):
        try:
            hour, minute = map(int, value.split(":"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("time must use HH:MM") from exc
        if hour not in range(24) or minute not in range(60):
            raise ValueError("time must use a valid 24-hour HH:MM clock value")
        return value


class BuyerCandidateField(BaseModel):
    field_id: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    estimated_straw_tonnes: float = Field(gt=0)
    residue_type: str = "PADDY_STRAW"
    moisture_pct: float | None = Field(default=None, ge=0, le=100)
    burn_risk_score: float | None = Field(default=None, ge=0, le=1)
    provenance: Literal["DEMO", "SYNTHETIC", "FIXTURE", "REAL"] = "SYNTHETIC"


class BuyerMatch(BaseModel):
    field_id: str
    buyer_id: str | None
    match_score: float | None
    distance_km: float | None
    distance_method: str
    allocated_tonnes: float
    remaining_buyer_capacity_tonnes: float | None
    matching_reasons: list[str]
    status: Literal["MATCHED", "UNMATCHED"]
    provenance: str


class BuyerMatchResult(BaseModel):
    allocations: list[BuyerMatch]
    buyer_remaining_capacity_tonnes: dict[str, float]
    unassigned_field_ids: list[str]
    distance_method: str
    provenance: str
