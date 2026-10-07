from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from shapely.geometry import shape

from src.data.common import load_config, write_json
from src.features.aggregation import aggregate_s2_observation, INDEX_NAMES
from src.features.radar_features import aggregate_s1_observation
from src.features.spatial_features import firms_features
from src.features.temporal_context import parse_datetime, select_s1_asof, weather_features

LOG = logging.getLogger(__name__)
PROCESSING_VERSION = "0.1.0"
INDEX_COLUMNS = [f"{index}_{stat}" for index in INDEX_NAMES for stat in ("mean", "median", "std", "min", "max")]
BAND_COLUMNS = [f"{band}_mean" for band in ("B2", "B3", "B4", "B6", "B7", "B8", "B8A", "B11", "B12")]
FEATURE_COLUMNS = [
    "field_id", "district", "village", "season", "year", "observation_date", "observation_datetime", "area_ha",
    *INDEX_COLUMNS, *BAND_COLUMNS, "valid_pixel_count", "total_pixel_count", "valid_pixel_fraction", "cloud_fraction",
    "VV_mean_db", "VH_mean_db", "VV_minus_VH_db", "VV_VH_ratio_linear", "missing_vh",
    "firms_points_within_field", "firms_points_within_500m", "firms_points_within_1km", "nearest_firms_distance_m", "recent_fire_24h", "recent_fire_72h",
    "precipitation_mm", "rain_24h", "rain_72h", "humidity_pct", "temperature_c", "wind_speed",
    "s2_available", "s1_available", "weather_available", "firms_available", "observation_quality", "observation_quality_flags",
    "s2_observation_datetime", "s1_observation_datetime", "s1_age_days", "weather_window_end", "firms_window_end",
    "source_image_id_s2", "source_image_id_s1", "s2_collection", "s1_collection", "s1_orbit_pass", "s1_relative_orbit_number", "s1_instrument_mode", "s1_polarizations",
    "weather_source", "weather_record_type", "firms_source", "fixture_or_real", "processing_version", "status_label",
]


def _quality(s2, s1, radar, weather, firms):
    flags = []
    if not s2.get("valid_pixel_count"):
        flags.append("no_valid_optical_pixels")
    elif (s2.get("valid_pixel_fraction") or 0) < 0.5:
        flags.append("low_valid_pixel_fraction")
    if s2.get("cloud_fraction") is not None and s2["cloud_fraction"] > 0.5:
        flags.append("high_cloud_fraction")
    if s1 is None:
        flags.append("s1_missing")
    elif radar["missing_vh"]:
        flags.append("vh_missing")
    if not weather["weather_available"]:
        flags.append("weather_missing")
    if not firms["firms_available"]:
        flags.append("firms_unavailable")
    if "no_valid_optical_pixels" in flags:
        quality = "POOR"
    elif s1 is not None and not radar["missing_vh"] and weather["weather_available"] and firms["firms_available"] and not any(f in flags for f in ("low_valid_pixel_fraction", "high_cloud_fraction")):
        quality = "GOOD"
    else:
        quality = "LIMITED"
    return quality, flags


def build_feature_rows(fields: dict, observations: dict, settings: dict) -> tuple[list[dict], dict]:
    fixture_type = observations.get("fixture_type")
    if fixture_type not in ("synthetic", "real"):
        raise ValueError("feature observations must declare fixture_type as 'synthetic' or 'real'")
    fixture_or_real = "SYNTHETIC" if fixture_type == "synthetic" else "REAL"
    field_map = {f["properties"]["field_id"]: f for f in fields.get("features", []) if f.get("properties", {}).get("field_id")}
    s1_by_field: dict[str, list[dict]] = {}
    for item in observations.get("s1_observations", []):
        s1_by_field.setdefault(item.get("field_id"), []).append(item)
    firms_points = observations.get("firms_points", [])
    weather_records = observations.get("weather_records", [])
    availability = observations.get("source_availability", {})
    seen, rows, warnings = set(), [], []
    s2_list = observations.get("s2_observations", [])
    for optical in sorted(s2_list, key=lambda x: (x.get("field_id", ""), x.get("acquisition_datetime", ""), x.get("source_image_id", ""))):
        fid = optical.get("field_id")
        if fid not in field_map:
            warnings.append(f"Sentinel-2 observation references unknown field_id {fid!r}; skipped")
            continue
        ref = parse_datetime(optical["acquisition_datetime"])
        dupe_key = (fid, ref.isoformat())
        if dupe_key in seen:
            warnings.append(f"duplicate S2 field/time observation skipped: {fid} {ref.isoformat()}")
            continue
        seen.add(dupe_key)
        field = field_map[fid]
        props = field["properties"]
        geom = shape(field["geometry"])
        s2 = aggregate_s2_observation(optical)
        s1 = select_s1_asof(s1_by_field.get(fid, []), ref.isoformat(), int(settings.get("s1_lookback_days", 12)), settings.get("s1_instrument_mode", "IW"))
        radar = aggregate_s1_observation(s1)
        firms = firms_features(geom, firms_points, ref.isoformat(), bool(availability.get("firms", False)), tuple(settings.get("firms_buffers_m", (500, 1000))), observations.get("firms_source"))
        weather = weather_features(weather_records, ref.isoformat(), int(settings.get("weather_lookback_hours", 72)))
        weather["weather_source"] = weather["weather_source"] or observations.get("weather_source")
        # Availability means a provider furnished its source file; the time-window flag remains separately visible.
        weather["weather_available"] = bool(availability.get("weather", False) and weather["weather_available"])
        quality, flags = _quality(s2, s1, radar, weather, firms)
        age_days = (ref - parse_datetime(s1["acquisition_datetime"])).total_seconds() / 86400 if s1 else None
        row = {key: None for key in FEATURE_COLUMNS}
        row.update({
            "field_id": fid, "district": props.get("district"), "village": props.get("village"),
            "season": props.get("season"), "year": ref.year, "observation_date": ref.date().isoformat(),
            "observation_datetime": ref.isoformat(), "area_ha": props.get("area_ha"), **s2, **radar, **firms, **weather,
            "s2_available": True, "s1_available": s1 is not None,
            "observation_quality": quality, "observation_quality_flags": "|".join(flags),
            "s2_observation_datetime": ref.isoformat(), "s1_observation_datetime": s1.get("acquisition_datetime") if s1 else None,
            "s1_age_days": age_days, "firms_window_end": ref.isoformat(),
            "source_image_id_s2": optical.get("source_image_id"), "source_image_id_s1": s1.get("source_image_id") if s1 else None,
            "s2_collection": optical.get("collection"), "s1_collection": s1.get("collection") if s1 else None,
            "s1_orbit_pass": s1.get("orbit_pass") if s1 else None,
            "s1_relative_orbit_number": s1.get("relative_orbit_number") if s1 else None,
            "s1_instrument_mode": s1.get("instrument_mode") if s1 else None,
            "s1_polarizations": ",".join(s1.get("polarizations", [])) if s1 else None,
            "fixture_or_real": fixture_or_real, "processing_version": settings.get("processing_version", PROCESSING_VERSION),
            "status_label": None,
        })
        # Keep source-availability flags explicit even when a point/window has no measurements.
        row["weather_available"] = weather["weather_available"]
        rows.append(row)
    report = _quality_report(rows, field_map, s2_list, observations, warnings)
    return rows, report


def _quality_report(rows, fields, optical, observations, warnings):
    important = ["NDVI_mean", "NBR_mean", "BAIS2_mean", "VV_mean_db", "VH_mean_db", "rain_24h", "humidity_pct", "nearest_firms_distance_m"]
    n = len(rows)
    nan_rates = {column: (sum(row.get(column) is None for row in rows) / n if n else 0.0) for column in important}
    weather = observations.get("weather_records", [])
    dates = sorted(str(r.get("timestamp") or r.get("date")) for r in weather)
    return {
        "dataset_type": "SYNTHETIC" if observations.get("fixture_type") == "synthetic" else "REAL",
        "number_of_fields": len(fields), "number_of_field_time_rows": n,
        "number_of_optical_observations": len(optical), "number_of_radar_observations": len(observations.get("s1_observations", [])),
        "number_missing_s1": sum(not row["s1_available"] for row in rows),
        "number_missing_vh": sum(row["s1_available"] and row["missing_vh"] is True for row in rows),
        "firms_points_considered": len(observations.get("firms_points", [])),
        "weather_record_coverage": {"records": len(weather), "first_timestamp": dates[0] if dates else None, "last_timestamp": dates[-1] if dates else None},
        "nan_rate": nan_rates, "quality_category_counts": dict(Counter(row["observation_quality"] for row in rows)),
        "synthetic_rows": sum(row["fixture_or_real"] == "SYNTHETIC" for row in rows),
        "real_rows": sum(row["fixture_or_real"] == "REAL" for row in rows),
        "status_label_populated_rows": sum(row["status_label"] is not None for row in rows),
        "warnings": warnings + ([observations["fixture_warning"]] if observations.get("fixture_warning") else []),
    }


def run_feature_build(config_path="config/pilot.yaml"):
    config, root = load_config(config_path)
    fcfg = config["features"]
    fields = json.loads((root / config["fields"]["output"]).read_text(encoding="utf-8"))
    observation_path = root / fcfg["input"]
    observations = json.loads(observation_path.read_text(encoding="utf-8"))
    settings = {**fcfg, "s1_instrument_mode": config["acquisition"]["earth_engine"].get("instrument_mode", "IW")}
    rows, report = build_feature_rows(fields, observations, settings)
    out_path, report_path = root / fcfg["output"], root / fcfg["quality_report"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FEATURE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(out_path)
    report.update({"input": str(observation_path.relative_to(root)), "output": str(out_path.relative_to(root)), "generated_at": datetime.now(timezone.utc).isoformat(), "processing_version": fcfg.get("processing_version", PROCESSING_VERSION)})
    write_json(report_path, report)
    LOG.info("Feature table rows=%d fields=%d output=%s", len(rows), report["number_of_fields"], out_path)
    return rows, report


def main():
    parser = argparse.ArgumentParser(description="Build leakage-safe field-time observations from normalized sources.")
    parser.add_argument("--config", default="config/pilot.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rows, report = run_feature_build(args.config)
    print(f"Feature rows: {len(rows)}; output: {report['output']}; quality: {report['quality_category_counts']}")


if __name__ == "__main__":
    main()
