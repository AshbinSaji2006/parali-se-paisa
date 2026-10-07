from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from src.db.models import BalerRecord, BuyerRecord, FieldObservation, FieldRecord
from src.db.session import create_schema, make_engine, make_session_factory


def _read_features(path: Path):
    by_field = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            field_id = row["field_id"]
            by_field.setdefault(field_id, []).append(row)
    for rows in by_field.values():
        rows.sort(key=lambda x: x.get("observation_datetime", ""))
    return by_field


def _feature_values(row):
    values = {}
    for key, value in row.items():
        if value == "":
            values[key] = None
        elif key in {"recent_fire_24h", "recent_fire_72h", "s2_available", "s1_available", "weather_available", "firms_available"}:
            values[key] = value.lower() == "true"
        else:
            try:
                values[key] = float(value) if any(c in value for c in ".eE") else int(value)
            except (ValueError, TypeError):
                values[key] = value
    return values


def seed_demo(database_url: str | None = None):
    engine = make_engine(database_url)
    create_schema(engine)
    Session = make_session_factory(engine)
    fields_path = ROOT / "data" / "processed" / "fields" / "fields_clean.geojson"
    feature_path = ROOT / "data" / "processed" / "features" / "field_features_temporal.csv"
    if not fields_path.is_file():
        raise FileNotFoundError(f"Missing normalized demo fields: {fields_path}")
    field_geojson = json.loads(fields_path.read_text(encoding="utf-8"))
    features = _read_features(feature_path) if feature_path.is_file() else {}
    balers = list(csv.DictReader((ROOT / "data/fixtures/demo/balers.csv").open(encoding="utf-8-sig", newline="")))
    buyers = list(csv.DictReader((ROOT / "data/fixtures/demo/buyers.csv").open(encoding="utf-8-sig", newline="")))
    session = Session()
    try:
        for feature in field_geojson["features"]:
            props = feature["properties"]
            field_id = props["field_id"]
            rows = features.get(field_id, [])
            latest = _feature_values(rows[-1]) if rows else None
            record = session.get(FieldRecord, field_id)
            if record is not None and record.provenance == "REAL":
                raise RuntimeError(f"Refusing to overwrite verified real field {field_id} with demo fixture")
            values = {"field_id": field_id, "district": props.get("district"), "village": props.get("village"),
                      "area_ha": props.get("area_ha"), "centroid_lat": props.get("centroid_lat"),
                      "centroid_lon": props.get("centroid_lon"), "geometry": feature.get("geometry"),
                      "properties": {"latest_features": latest, "data_status": "DEMO_SYNTHETIC"},
                      "provenance": "DEMO", "source": props.get("source", "synthetic_demo_fixture")}
            if record is None: session.add(FieldRecord(**values))
            else:
                for key, value in values.items(): setattr(record, key, value)
            session.flush()
            for row in rows:
                timestamp = datetime.fromisoformat(row["observation_datetime"].replace("Z", "+00:00"))
                obs_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"demo:{field_id}:{timestamp.isoformat()}"))
                exists = session.get(FieldObservation, obs_id)
                if exists is None:
                    values = _feature_values(row)
                    session.add(FieldObservation(observation_id=obs_id, field_id=field_id,
                        observation_datetime=timestamp, source_image_id_s2=values.get("source_image_id_s2"),
                        source_image_id_s1=values.get("source_image_id_s1"), features=values, provenance="SYNTHETIC"))

        # A separate, explicitly synthetic scenario row exercises the Block 3 route.
        # It is never passed off as an acquired satellite observation.
        action_id = "SYNTHETIC-ACTION-FIELD-01"
        action_features = {"field_id": action_id, "area_ha": 2.0, "season": "synthetic_demo",
            "year": 2026, "observation_datetime": "2026-10-06T06:00:00+00:00", "NDVI_mean": 0.31,
            "NDVI_delta": -0.30, "NDVI_drop_from_peak": -0.30, "NBR_mean": 0.20, "NBR_delta": -0.16,
            "BAIS2_mean": 0.14, "BAIS2_delta": 0.04, "observation_quality": "GOOD",
            "source_image_id_s2": "SYNTHETIC-EXAMPLE-S2-01", "source_image_id_s1": "SYNTHETIC-EXAMPLE-S1-01",
            "s2_available": True, "s1_available": True, "fixture_or_real": "SYNTHETIC",
            "processing_version": "BLOCK3_SCENARIO_V1", "valid_pixel_fraction": 0.95}
        action = session.get(FieldRecord, action_id)
        if action is not None and action.provenance == "REAL":
            raise RuntimeError(f"Refusing to overwrite verified real field {action_id} with demo fixture")
        values = {"field_id": action_id, "district": "DEMO DISTRICT", "village": "SYNTHETIC TEST LOCALITY",
                  "area_ha": 2.0, "centroid_lat": 30.023, "centroid_lon": 74.523, "geometry": None,
                  "properties": {"latest_features": action_features, "purpose": "SYNTHETIC_E2E_SCENARIO"},
                  "provenance": "SYNTHETIC", "source": "in_code_synthetic_scenario_fixture"}
        if action is None: session.add(FieldRecord(**values))
        else:
            for key, value in values.items(): setattr(action, key, value)
        session.flush()
        action_obs_id = str(uuid.uuid5(uuid.NAMESPACE_URL, action_id + ":observation"))
        if session.get(FieldObservation, action_obs_id) is None:
            session.add(FieldObservation(observation_id=action_obs_id, field_id=action_id,
                observation_datetime=datetime(2026, 10, 6, 6, tzinfo=timezone.utc),
                source_image_id_s2=action_features["source_image_id_s2"], source_image_id_s1=action_features["source_image_id_s1"],
                features=action_features, provenance="SYNTHETIC"))

        for row in balers:
            values = {**row, "latitude": float(row["latitude"]), "longitude": float(row["longitude"]),
                      "service_rate_acres_per_hour": float(row["service_rate_acres_per_hour"]),
                      "daily_capacity_acres": float(row["daily_capacity_acres"]),
                      "max_straw_capacity_tonnes": float(row["max_straw_capacity_tonnes"]),
                      "current_location_lat": None, "current_location_lon": None}
            existing = session.get(BalerRecord, row["baler_id"])
            if existing is not None and existing.demo_or_real == "REAL":
                raise RuntimeError(f"Refusing to overwrite verified real baler {row['baler_id']}")
            if existing is None: session.add(BalerRecord(**values))
            else:
                for key, value in values.items(): setattr(existing, key, value)
        for row in buyers:
            values = {**row, "latitude": float(row["latitude"]), "longitude": float(row["longitude"]),
                      "accepted_residue_types": row["accepted_residue_types"].split("|"),
                      "daily_demand_tonnes": float(row["daily_demand_tonnes"]),
                      "max_moisture_pct": float(row["max_moisture_pct"]),
                      "remaining_demand_tonnes": float(row["remaining_demand_tonnes"]),
                      "price_per_tonne": None, "price_is_verified": row["price_is_verified"].lower() == "true"}
            existing = session.get(BuyerRecord, row["buyer_id"])
            if existing is not None and existing.demo_or_real == "REAL":
                raise RuntimeError(f"Refusing to overwrite verified real buyer {row['buyer_id']}")
            if existing is None: session.add(BuyerRecord(**values))
            else:
                current_remaining = existing.remaining_demand_tonnes
                for key, value in values.items():
                    if key != "remaining_demand_tonnes": setattr(existing, key, value)
                existing.remaining_demand_tonnes = min(current_remaining, values["daily_demand_tonnes"])
        session.commit()
        print(json.dumps({"status": "seeded", "demo_fields": len(field_geojson["features"]),
                          "synthetic_action_fields": 1, "synthetic_observations": sum(map(len, features.values())) + 1,
                          "demo_balers": len(balers), "demo_buyers": len(buyers),
                          "database": str(engine.url), "provenance": "DEMO/SYNTHETIC"}, indent=2))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    seed_demo()
