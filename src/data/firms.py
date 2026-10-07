from __future__ import annotations

import csv
import io
import math
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


def normalize_firms_rows(rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
    accepted, rejected, seen = [], [], set()
    for row_num, raw in enumerate(rows, 2):
        row = {str(k).strip().lower(): v for k, v in raw.items() if k is not None}
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("coordinates_out_of_bounds")
            d = date.fromisoformat(str(row.get("acq_date") or row.get("acquisition_date")))
            tm = str(row.get("acq_time") or row.get("acquisition_time") or "0000").zfill(4)
            dt = datetime.strptime(f"{d.isoformat()} {tm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
            confidence = row.get("confidence")
            if confidence not in (None, ""):
                confidence = float(confidence) if str(confidence).replace(".", "", 1).isdigit() else str(confidence).lower()
            frp = float(row["frp"]) if row.get("frp") not in (None, "") else None
            record = {"latitude": lat, "longitude": lon, "acquisition_date": d.isoformat(), "acquisition_time": tm, "acquisition_datetime": dt.isoformat(), "confidence": confidence, "satellite": row.get("satellite"), "instrument": row.get("instrument"), "frp": frp, "source": source}
            key = (record["latitude"], record["longitude"], record["acquisition_datetime"], record["satellite"], record["instrument"])
            if key in seen:
                rejected.append({"row": row_num, "reason": "duplicate_record"})
            else:
                seen.add(key)
                accepted.append(record)
        except Exception as exc:
            rejected.append({"row": row_num, "reason": str(exc) if str(exc) in ("coordinates_out_of_bounds",) else "malformed_or_missing_required_value"})
    return {"points_loaded": len(accepted), "points_rejected": rejected, "points": accepted}


def load_firms_csv(path: str | Path, source: str = "supplied_csv") -> dict[str, Any]:
    with open(path, newline="", encoding="utf-8-sig") as stream:
        return normalize_firms_rows(list(csv.DictReader(stream)), source)


def query_firms(config: dict[str, Any], map_key: str) -> dict[str, Any]:
    acq, fcfg = config["acquisition"], config["acquisition"]["firms"]
    west, south, east, north = acq.get("aoi_bbox_wgs84", config["pilot"]["aoi_bbox_wgs84"])
    source = fcfg.get("source", "VIIRS_NOAA20_NRT")
    points, rejected = [], []
    start, end = date.fromisoformat(acq["date_start"]), date.fromisoformat(acq["date_end"])
    cursor = start
    while cursor <= end:
        days = min(5, (end - cursor).days + 1)
        area = f"{west},{south},{east},{north}"
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{quote(map_key)}/{quote(source)}/{quote(area)}/{days}/{cursor.isoformat()}"
        with urllib.request.urlopen(url, timeout=60) as response:
            text = response.read().decode("utf-8-sig")
        parsed = normalize_firms_rows(list(csv.DictReader(io.StringIO(text))), f"NASA_FIRMS:{source}")
        points.extend(parsed["points"])
        rejected.extend(parsed["points_rejected"])
        cursor += timedelta(days=days)
    unique = {(p["latitude"], p["longitude"], p["acquisition_datetime"], p["satellite"]): p for p in points}
    return {"points_loaded": len(unique), "points_rejected": rejected, "points": list(unique.values())}
