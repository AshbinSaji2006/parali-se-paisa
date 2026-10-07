from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import fmean


def parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def select_s1_asof(observations: list[dict], reference_datetime: str, lookback_days: int = 12, instrument_mode: str = "IW") -> dict | None:
    ref = parse_datetime(reference_datetime)
    lower = ref - timedelta(days=lookback_days)
    compatible = []
    for observation in observations:
        try:
            stamp = parse_datetime(observation["acquisition_datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        if lower <= stamp <= ref and observation.get("instrument_mode", "IW") == instrument_mode and "VV" in observation.get("polarizations", ["VV"]):
            compatible.append((stamp, observation))
    return max(compatible, key=lambda item: item[0])[1] if compatible else None


def weather_features(records: list[dict], reference_datetime: str, lookback_hours: int = 72) -> dict:
    ref = parse_datetime(reference_datetime)
    lower = ref - timedelta(hours=lookback_hours)
    past = []
    for record in records:
        try:
            stamp = parse_datetime(record.get("timestamp") or record["date"])
        except (KeyError, TypeError, ValueError):
            continue
        # A forecast is usable only when its issue time was already known at the row's reference time.
        if record.get("record_type") == "forecast":
            try:
                issued = parse_datetime(record["forecast_issued_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if issued > ref:
                continue
        if lower < stamp <= ref:
            past.append((stamp, record))
    past.sort(key=lambda pair: pair[0])
    def numeric(key):
        values = []
        for _, rec in past:
            value = rec.get(key)
            if value is not None:
                try:
                    values.append(float(value))
                except (ValueError, TypeError):
                    pass
        return values
    rain24 = [float(rec["precipitation_mm"]) for stamp, rec in past if ref - timedelta(hours=24) < stamp <= ref and rec.get("precipitation_mm") is not None]
    has_weather_values = any(rec.get(key) is not None for _, rec in past for key in ("precipitation_mm", "humidity_pct", "temperature_c", "wind_speed"))
    result = {"weather_available": has_weather_values, "rain_24h": sum(rain24) if rain24 else None,
              "rain_72h": sum(numeric("precipitation_mm")) if numeric("precipitation_mm") else None,
              "humidity_pct": numeric("humidity_pct")[-1] if numeric("humidity_pct") else None,
              "temperature_c": numeric("temperature_c")[-1] if numeric("temperature_c") else None,
              "wind_speed": numeric("wind_speed")[-1] if numeric("wind_speed") else None,
              "precipitation_mm": numeric("precipitation_mm")[-1] if numeric("precipitation_mm") else None,
              "weather_source": next((rec.get("source") for _, rec in reversed(past) if rec.get("source")), None),
              "weather_record_type": next((rec.get("record_type") for _, rec in reversed(past) if rec.get("record_type")), None),
              "weather_window_end": ref.isoformat() if past else None}
    return result
