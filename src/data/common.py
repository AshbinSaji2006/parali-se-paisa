from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> tuple[dict[str, Any], Path]:
    path = Path(path).resolve()
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    acq = cfg.get("acquisition") or {}
    for key in ("date_start", "date_end"):
        date.fromisoformat(str(acq[key]))
    if acq["date_start"] > acq["date_end"]:
        raise ValueError("acquisition.date_start must be <= date_end")
    bbox = acq.get("aoi_bbox_wgs84") or cfg["pilot"]["aoi_bbox_wgs84"]
    if len(bbox) != 4 or not (-180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90):
        raise ValueError("AOI must be [west, south, east, north] within EPSG:4326 bounds")
    if not 0 <= float(acq["cloud_threshold_pct"]) <= 100:
        raise ValueError("cloud_threshold_pct must be in [0, 100]")
    return cfg, path.parent.parent


def write_json(path: str | Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def cached_json(cache_dir: Path, key: str, producer):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), True
    value = producer()
    write_json(path, value)
    return value, False


def env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None
