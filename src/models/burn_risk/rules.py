from __future__ import annotations

from pathlib import Path
from datetime import datetime
import yaml


def rule_burn_risk(row, straw_result=None, harvest_date=None, context=None, config=None):
    cfg = config or yaml.safe_load(Path("config/risk_model.yaml").read_text(encoding="utf-8"))
    context = context or {}; straw_result = straw_result or {}
    harvest_state = str((harvest_date or {}).get("state", "UNKNOWN"))
    harvest_provenance = (harvest_date or {}).get("provenance")
    days = _num((harvest_date or {}).get("days_since_harvest"))
    scores, reasons, availability = {}, {}, {}
    def add(name, value, reason, present=True):
        availability[f"has_{name}"] = bool(present)
        if present and value is not None:
            scores[name] = max(0.0, min(1.0, float(value)))
            reasons[name] = reason
    # Unknown/candidate harvest dates stay explicitly uncertain; no inferred date becomes confirmed.
    add("time_pressure", min(1.0, days / float(cfg["thresholds"]["days_to_deadline"])) if days is not None and days >= 0 else None,
        "More time has elapsed since the supplied harvest date", days is not None and harvest_state in ("CONFIRMED", "MODEL_INFERRED", "RULE_CANDIDATE"))
    rain = _num(row.get("rain_72h"))
    add("dry_weather", max(0.0, 1 - rain / float(cfg["thresholds"]["rain_72h_mm_for_wet"])) if rain is not None else None,
        "Low preceding 72-hour rainfall", rain is not None)
    forecast_rain = _num(context.get("forecast_rain_next_72h"))
    forecast_issued = context.get("forecast_issued_at")
    obs_time = row.get("observation_datetime")
    forecast_known = False
    if forecast_rain is not None and forecast_issued and obs_time:
        try:
            issue_dt = datetime.fromisoformat(str(forecast_issued).replace("Z", "+00:00"))
            obs_dt = datetime.fromisoformat(str(obs_time).replace("Z", "+00:00"))
            forecast_known = issue_dt.tzinfo is not None and obs_dt.tzinfo is not None and issue_dt <= obs_dt
        except ValueError:
            forecast_known = False
    add("forecast_dryness", max(0.0, 1 - forecast_rain / float(cfg["thresholds"]["forecast_rain_72h_mm_for_wet"])) if forecast_known else None,
        "Low forecast rainfall over the next 72 hours", forecast_known)
    humidity = _num(row.get("humidity_pct"))
    add("low_humidity", (100-humidity)/100 if humidity is not None else None, "Low observed humidity", humidity is not None)
    for name in ("baler", "buyer"):
        distance = _num(context.get(f"{name}_distance_m"))
        add(f"{name}_access", min(1.0, distance / float(cfg["thresholds"][f"{name}_distance_m_for_max"])) if distance is not None else None,
            f"Long distance to available {name}", distance is not None)
        availability[f"has_{name}_distance"] = distance is not None
    burn_rate = _num(context.get("historical_burn_rate"))
    add("historical_burn_tendency", burn_rate, "Historical local burn tendency", burn_rate is not None)
    straw = _num(straw_result.get("estimated_straw_tonnes"))
    add("straw_volume", min(1.0, straw / float(cfg["thresholds"]["straw_tonnes_for_max"])) if straw is not None else None,
        "Estimated straw volume is available", straw is not None)
    fire = row.get("recent_fire_72h")
    if isinstance(fire, str): fire = fire.lower() == "true" if fire.lower() in ("true", "false") else None
    add("nearby_fire_activity", 1.0 if fire else 0.0 if fire is False else None,
        "Recent nearby FIRMS activity is present" if fire else "No recent FIRMS detections in the configured context", fire is not None)
    quality = row.get("observation_quality")
    availability["has_observation_quality"] = quality not in (None, "")
    availability["has_weather_forecast"] = forecast_known
    availability["has_historical_burn_rate"] = burn_rate is not None
    availability["has_weather_observation"] = rain is not None or humidity is not None
    available_weight = sum(float(cfg["weights"].get(k, 0)) for k in scores)
    if available_weight <= 0:
        score = None
    else:
        score = sum(scores[k] * float(cfg["weights"].get(k, 0)) for k in scores) / available_weight
    risk_level = "INSUFFICIENT_DATA" if score is None else next((level for level, threshold in cfg["levels"].items() if score < float(threshold)), "CRITICAL")
    top = sorted(scores, key=lambda k: (-scores[k] * float(cfg["weights"].get(k, 0)), k))[:3]
    return {"risk_score": score, "risk_level": risk_level, "method": "RULE_ENGINE_V1",
            "score_kind": "NORMALIZED_RULE_SCORE_NOT_PROBABILITY", "component_scores": scores,
            "component_weights": {k: cfg["weights"].get(k) for k in scores}, "availability": availability,
            "top_factors": [reasons[k] for k in top], "harvest_date_state": harvest_state,
            "harvest_date_provenance": harvest_provenance, "target_horizon": "next 3 days",
            "forecast_features_used": bool(forecast_known),
            "facility_context_dataset_type": context.get("facility_dataset_type", "UNAVAILABLE"),
            "facility_context_source": context.get("facility_source"), "is_ground_truth": False}


def _num(x):
    try: return float(x) if x not in (None, "") else None
    except (TypeError, ValueError): return None
