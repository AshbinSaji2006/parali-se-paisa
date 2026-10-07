from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import cached_json, env, load_config, write_json
from .firms import load_firms_csv, query_firms
from .sentinel1 import query_sentinel1
from .sentinel2 import query_sentinel2
from .weather import OpenMeteoProvider, load_weather_fixture

LOG = logging.getLogger(__name__)


def _fixture_json(path: Path, kind: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("dataset_type") != "DEMO":
        raise ValueError(f"{kind} fixture must explicitly declare dataset_type: DEMO")
    payload["fixture"] = True
    return payload


def _cache(root: Path, cfg: dict, name: str, producer, fixture_path: Path | None = None):
    key_obj = {"source": name, "acquisition": cfg["acquisition"]}
    if fixture_path:
        key_obj["fixture_sha256"] = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    key = json.dumps(key_obj, sort_keys=True)
    return cached_json(root / cfg["acquisition"]["cache_dir"], key, producer)


def run_acquisition(config_path: str | Path = "config/pilot.yaml", offline: bool = True) -> dict[str, Any]:
    config, root = load_config(config_path)
    acq = config["acquisition"]
    outdir = root / acq["output_dir"]
    manifest: dict[str, Any] = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(), "pilot": config["pilot"],
        "aoi_bbox_wgs84": acq.get("aoi_bbox_wgs84", config["pilot"]["aoi_bbox_wgs84"]),
        "date_range": {"start": acq["date_start"], "end": acq["date_end"]}, "fixture_mode": offline,
        "sources": {}, "warnings": [], "output_paths": {},
    }

    if offline:
        base = root / "data/fixtures/demo"
        s2path, s1path = base / "sentinel2.json", base / "sentinel1.json"
        s2, s2_hit = _cache(root, config, "s2-fixture", lambda: _fixture_json(s2path, "Sentinel-2"), s2path)
        s1, s1_hit = _cache(root, config, "s1-fixture", lambda: _fixture_json(s1path, "Sentinel-1"), s1path)
        firms_path = root / acq["firms"]["fixture"]
        firms, firms_hit = _cache(root, config, "firms-fixture", lambda: load_firms_csv(firms_path, "DEMO_SYNTHETIC_FIXTURE"), firms_path)
        weather_path = root / acq["weather"]["fixture"]
        weather, weather_hit = _cache(root, config, "weather-fixture", lambda: load_weather_fixture(weather_path), weather_path)
        for source, data, hit in (("sentinel2", s2, s2_hit), ("sentinel1", s1, s1_hit), ("firms", firms, firms_hit), ("weather", weather, weather_hit)):
            data["fixture"] = True
            data["dataset_type"] = "DEMO"
            data["cache_hit"] = hit
            manifest["sources"][source] = data
    else:
        ee_status = {"images_queried": 0, "images_accepted": [], "images_rejected": [], "fixture": False}
        ee_s1 = {"images_queried": 0, "images_accepted": [], "fixture": False}
        try:
            import ee
            project = env("EE_PROJECT")
            if project:
                ee.Initialize(project=project)
            else:
                ee.Initialize()
            ee_status, _ = _cache(root, config, "sentinel2-real", lambda: query_sentinel2(config))
            ee_s1, _ = _cache(root, config, "sentinel1-real", lambda: query_sentinel1(config))
            ee_status.update({"fixture": False, "dataset_type": "REAL_METADATA"})
            ee_s1.update({"fixture": False, "dataset_type": "REAL_METADATA"})
        except Exception as exc:
            manifest["warnings"].append(f"Earth Engine unavailable: {type(exc).__name__}: {exc}")
        manifest["sources"]["sentinel2"] = ee_status
        manifest["sources"]["sentinel1"] = ee_s1

        map_key = env("FIRMS_MAP_KEY")
        if map_key:
            try:
                firms, _ = _cache(root, config, "firms-real", lambda: query_firms(config, map_key))
                firms.update({"fixture": False, "dataset_type": "REAL"})
            except Exception as exc:
                firms = {"points_loaded": 0, "points_rejected": [], "points": [], "fixture": False, "error": f"{type(exc).__name__}: {exc}"}
                manifest["warnings"].append(f"FIRMS unavailable: {firms['error']}")
        else:
            firms = {"points_loaded": 0, "points_rejected": [], "points": [], "fixture": False, "status": "skipped; FIRMS_MAP_KEY not configured"}
            manifest["warnings"].append("FIRMS skipped: configure FIRMS_MAP_KEY")
        manifest["sources"]["firms"] = firms

        west, south, east, north = manifest["aoi_bbox_wgs84"]
        center_lat, center_lon = (south + north) / 2, (west + east) / 2
        try:
            weather, _ = _cache(root, config, "weather-open-meteo", lambda: OpenMeteoProvider().fetch(center_lat, center_lon, acq["date_start"], acq["date_end"]))
            weather.update({"fixture": False, "dataset_type": "REAL", "provider": "Open-Meteo"})
        except Exception as exc:
            weather = {"records_loaded": 0, "records_rejected": [], "records": [], "fixture": False, "error": f"{type(exc).__name__}: {exc}"}
            manifest["warnings"].append(f"Weather unavailable: {weather['error']}")
        manifest["sources"]["weather"] = weather

    for source, data in manifest["sources"].items():
        path = outdir / f"{source}.json"
        write_json(path, data)
        manifest["output_paths"][source] = str(path.relative_to(root))
    manifest_path = root / "reports/acquisition_manifest.json"
    write_json(manifest_path, manifest)
    LOG.info("Acquisition fixture=%s output=%s warnings=%d", offline, outdir, len(manifest["warnings"]))
    print(f"Manifest: {manifest_path.relative_to(root)}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire satellite metadata, FIRMS detections, and weather context.")
    parser.add_argument("--config", default="config/pilot.yaml")
    parser.add_argument("--online", action="store_true", help="Use Earth Engine/FIRMS/Open-Meteo integrations")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    manifest = run_acquisition(args.config, offline=not args.online)
    for source, data in manifest["sources"].items():
        LOG.info("%s fixture=%s", source, data.get("fixture"))


if __name__ == "__main__":
    main()
