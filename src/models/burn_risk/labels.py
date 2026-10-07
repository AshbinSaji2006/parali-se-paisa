from __future__ import annotations

from datetime import datetime

BURN_LABEL_FIELDS = ("field_id", "observation_datetime", "burned_within_next_3_days", "label_source", "label_quality", "reviewer", "evidence_reference", "created_at")
STRONG_SOURCES = {"FIELD_SURVEY", "MANUAL_SATELLITE_REVIEW", "TRUSTED_EXTERNAL"}


def validate_burn_outcome(row, allow_synthetic=False):
    missing = [k for k in BURN_LABEL_FIELDS if row.get(k) in (None, "")]
    if missing: raise ValueError(f"burn outcome missing provenance: {', '.join(missing)}")
    try: value = int(row["burned_within_next_3_days"])
    except (TypeError, ValueError): raise ValueError("burned_within_next_3_days must be 0 or 1")
    if value not in (0, 1): raise ValueError("burned_within_next_3_days must be 0 or 1")
    synthetic = row["label_source"] == "SYNTHETIC_TEST" and row["label_quality"] == "S"
    if synthetic:
        if not allow_synthetic or row.get("fixture_or_real") != "SYNTHETIC": raise ValueError("synthetic burn labels require explicit test mode and synthetic features")
    elif row["label_source"] not in STRONG_SOURCES or row["label_quality"] not in ("A", "B"):
        raise ValueError("burn-risk training requires A/B outcome evidence from a trusted source")
    elif row.get("fixture_or_real") != "REAL":
        raise ValueError("real burn outcomes require real feature observations")
    for key in ("observation_datetime", "created_at"):
        dt = datetime.fromisoformat(str(row[key]).replace("Z", "+00:00"))
        if dt.tzinfo is None: raise ValueError(f"{key} must include timezone")
    return {**row, "burned_within_next_3_days": value}
