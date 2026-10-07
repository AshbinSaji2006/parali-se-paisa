from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def normalize_weather(payload: dict[str, Any], source: str, record_type: str, forecast_issued_at: str | None = None) -> dict[str, Any]:
    accepted, rejected = [], []
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    names = ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m")
    for i, stamp in enumerate(times):
        try:
            datetime.fromisoformat(stamp)
            rec = {"timestamp": stamp, "date": stamp[:10], "temperature_c": _at(hourly, "temperature_2m", i), "humidity_pct": _at(hourly, "relative_humidity_2m", i), "precipitation_mm": _at(hourly, "precipitation", i), "wind_speed": _at(hourly, "wind_speed_10m", i), "source": source, "record_type": record_type, "forecast_issued_at": forecast_issued_at}
            accepted.append(rec)
        except (IndexError, TypeError, ValueError):
            rejected.append({"index": i, "reason": "malformed_weather_record"})
    return {"records_loaded": len(accepted), "records_rejected": rejected, "records": accepted, "variables": list(names)}


def _at(hourly, name, index):
    vals = hourly.get(name, [])
    if index >= len(vals):
        return None
    value = vals[index]
    return None if value is None else float(value)


class OpenMeteoProvider:
    """Open-Meteo ERA5 archive for past dates and live forecast for future dates."""
    variables = "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"

    def fetch(self, latitude: float, longitude: float, start: str, end: str) -> dict[str, Any]:
        today = date.today()
        start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
        records, rejected, warnings = [], [], []
        segments = []
        if start_d < today:
            hist_end = min(end_d, today - timedelta(days=1))
            segments.append(("archive", start_d, hist_end, "https://archive-api.open-meteo.com/v1/archive", "historical_reanalysis"))
        if end_d >= today:
            fc_start = max(start_d, today)
            fc_end = min(end_d, today + timedelta(days=15))
            if fc_start <= fc_end:
                segments.append(("forecast", fc_start, fc_end, "https://api.open-meteo.com/v1/forecast", "forecast"))
            if end_d > fc_end:
                warnings.append(f"Forecast requested through {end_d}; Open-Meteo free forecast horizon ends at {fc_end}; later values were not fabricated.")
        for _, a, b, url, kind in segments:
            params = {"latitude": latitude, "longitude": longitude, "start_date": a.isoformat(), "end_date": b.isoformat(), "hourly": self.variables, "timezone": "UTC"}
            request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "ParaliSePaisa/0.1 (research prototype)"})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read())
            issued_at = datetime.now(timezone.utc).isoformat() if kind == "forecast" else None
            parsed = normalize_weather(payload, f"Open-Meteo:{kind}", kind, issued_at)
            records.extend(parsed["records"])
            rejected.extend(parsed["records_rejected"])
        return {"records_loaded": len(records), "records_rejected": rejected, "records": records, "warnings": warnings}


def load_weather_fixture(path: str | Path) -> dict[str, Any]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    result = normalize_weather(obj["payload"], "DEMO_SYNTHETIC_FIXTURE", obj.get("record_type", "demo"), obj.get("forecast_issued_at"))
    result["dataset_type"] = "DEMO"
    return result
