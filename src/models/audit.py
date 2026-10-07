from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .field_status.dataset import LABELS, load_schema
from .field_status.labels import validate_label


def _parse(value, kind):
    if value in (None, ""):
        return None
    if kind == "number":
        x = float(value)
        if not math.isfinite(x): raise ValueError("non_finite")
        return x
    if kind == "integer": return int(value)
    if kind == "boolean":
        if str(value).lower() not in ("true", "false"): raise ValueError("invalid_boolean")
        return str(value).lower() == "true"
    return str(value)


def audit_dataset(features_path="data/processed/features/field_features_temporal.csv", schema_path="config/feature_schema.yaml", labels_path="data/processed/labels/status_labels.csv", fields_report_path="reports/field_validation_report.json", acquisition_path="reports/acquisition_manifest.json"):
    schema = load_schema(schema_path); fields = schema["fields"]
    with Path(features_path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream); columns = reader.fieldnames or []; rows = list(reader)
    errors, warnings = [], []
    if columns != list(fields): errors.append("CSV columns or order differ from frozen feature schema")
    keys, last = set(), {}
    duplicate_count = 0
    nan_count = Counter(); numeric_count = Counter(); ranges = Counter(); future_flags = Counter(); non_finite_count = 0
    fixture_counts = Counter(); label_values = []
    group_ids, season_keys = set(), set()
    for ix, row in enumerate(rows, start=2):
        try:
            for name, spec in fields.items():
                value = row.get(name)
                parsed = _parse(value, spec["type"])
                if parsed is None:
                    nan_count[name] += 1
                    if not spec["nullable"]: errors.append(f"row {ix}: required {name} is null")
                else:
                    numeric_count[name] += 1
                    if name.startswith("NDVI_") and name.rsplit("_", 1)[-1] in ("mean", "median", "min", "max") and not -1 <= parsed <= 1: errors.append(f"row {ix}: {name} outside [-1,1]")
                    if name.startswith("NBR_") and name.rsplit("_", 1)[-1] in ("mean", "median", "min", "max") and not -1 <= parsed <= 1: errors.append(f"row {ix}: {name} outside [-1,1]")
                    if name == "area_ha" and parsed <= 0: errors.append(f"row {ix}: area_ha must be positive")
            dt = datetime.fromisoformat(row["observation_datetime"].replace("Z", "+00:00"))
            if dt.tzinfo is None: raise ValueError("observation_datetime timezone missing")
            key = tuple(row[k] for k in schema["primary_key"])
            if key in keys:
                duplicate_count += 1
                errors.append(f"duplicate field-time key: {key}")
            keys.add(key)
            group = tuple(row[k] for k in schema["group_columns"])
            if group in last and dt < last[group]: errors.append(f"row {ix}: chronology violation in group {group}")
            last[group] = dt
            group_ids.add(row["field_id"]); season_keys.add((row["season"], row["year"]))
            fixture_counts[row["fixture_or_real"]] += 1
            if row.get("status_label"): label_values.append(row["status_label"])
            for source, end_col in (("S1", "s1_observation_datetime"), ("weather", "weather_window_end"), ("FIRMS", "firms_window_end")):
                stamp = row.get(end_col)
                if stamp:
                    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    if parsed > dt: future_flags[f"{source}_future_timestamp"] += 1
            for dtcol in ("previous_observation_datetime", "peak_NDVI_datetime_so_far"):
                stamp = row.get(dtcol)
                if stamp and datetime.fromisoformat(stamp.replace("Z", "+00:00")) > dt:
                    future_flags[f"{dtcol}_after_current"] += 1
        except Exception as exc:
            if "non_finite" in str(exc): non_finite_count += 1
            errors.append(f"row {ix}: {exc}")
    if len(fixture_counts) > 1: warnings.append("dataset contains mixed REAL and SYNTHETIC rows; filter explicitly before training")
    unexpected_fixture = set(fixture_counts) - {"REAL", "SYNTHETIC"}
    if unexpected_fixture: errors.append(f"invalid fixture_or_real values: {sorted(unexpected_fixture)}")
    unknown_classes = sorted(set(label_values) - set(LABELS))
    if unknown_classes: errors.append(f"unsupported labels found: {unknown_classes}")
    for indicator, count in future_flags.items():
        if count: errors.append(f"future leakage indicator {indicator}: {count}")
    label_rows = []
    if Path(labels_path).exists():
        with Path(labels_path).open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            label_rows = list(reader)
            for i, lab in enumerate(label_rows, start=2):
                try: validate_label(lab)
                except Exception as exc: errors.append(f"label row {i}: {exc}")
    observation_keys = {(str(x.get("field_id")), str(x.get("observation_datetime"))) for x in rows}
    for lab in label_rows:
        if (str(lab.get("field_id")), str(lab.get("observation_datetime"))) not in observation_keys:
            errors.append(f"label does not match a field-time row: {lab.get('field_id')} {lab.get('observation_datetime')}")
    label_counts = Counter(l.get("status_label") for l in label_rows)
    label_quality_counts = Counter(l.get("label_quality") for l in label_rows)
    for c, n in nan_count.items():
        if rows and n / len(rows) > .8 and c in schema["training_features"]:
            warnings.append(f"training feature {c} has {n/len(rows):.1%} missing values")
    for name, spec in fields.items():
        if spec["training_allowed"] and name not in schema["training_features"]: errors.append(f"{name} marked trainable but omitted from training_features")
    for name in schema["training_features"]:
        if name not in fields or not fields[name]["training_allowed"]: errors.append(f"invalid training feature {name}")
    geometry_report = json.loads(Path(fields_report_path).read_text(encoding="utf-8")) if Path(fields_report_path).exists() else None
    acquisition = json.loads(Path(acquisition_path).read_text(encoding="utf-8")) if Path(acquisition_path).exists() else None
    base_quality_path = Path("reports/feature_quality_report.json")
    temporal_quality_path = Path("reports/temporal_feature_quality_report.json")
    base_quality = json.loads(base_quality_path.read_text(encoding="utf-8")) if base_quality_path.exists() else None
    temporal_quality = json.loads(temporal_quality_path.read_text(encoding="utf-8")) if temporal_quality_path.exists() else None
    if not rows: errors.append("feature dataset is empty")
    if not label_rows: warnings.append("No labels available; model training and scientific evaluation are not ready")
    if fixture_counts.get("REAL", 0) == 0: warnings.append("No real observations: scientific performance cannot be measured")
    summary = {"schema_version": schema["schema_version"], "dataset": str(features_path), "rows": len(rows),
               "columns": len(columns), "schema_columns": len(fields), "number_of_fields": len(group_ids),
               "number_of_seasons": len(season_keys), "fixture_or_real_counts": dict(fixture_counts),
               "duplicate_field_time_rows": duplicate_count, "chronology_valid": not any("chronology" in e for e in errors),
               "nan_rates": {k: nan_count[k] / len(rows) if rows else 0 for k in fields},
               "non_finite_count": non_finite_count, "future_leakage_indicators": dict(future_flags),
               "label_rows": len(label_rows), "label_class_counts": dict(label_counts), "label_quality_counts": dict(label_quality_counts),
               "label_availability": "AVAILABLE" if label_rows else "NONE", "ml_training_ready": False,
               "field_geometry_audit": {k: geometry_report.get(k) for k in ("dataset_type", "input_features", "valid_features", "skipped_features", "repaired_features", "overlap_warnings", "area_crs", "output_crs")} if geometry_report else None,
               "acquisition_audit_present": acquisition is not None,
               "integrated_pipeline_audit": {
                   "geometry": {"dataset_type": geometry_report.get("dataset_type"), "valid_fields": geometry_report.get("valid_features"), "known_repairs": geometry_report.get("repaired_features"), "known_overlap_pairs": len(geometry_report.get("overlap_warnings", []))} if geometry_report else None,
                   "acquisition": {"fixture_mode": acquisition.get("fixture_mode"), "source_names": sorted(acquisition.get("sources", {})), "source_fixture_flags": {k: v.get("fixture") for k, v in acquisition.get("sources", {}).items()}} if acquisition else None,
                   "checkpoint_c": {"dataset_type": base_quality.get("dataset_type"), "rows": base_quality.get("number_of_field_time_rows"), "columns": 78, "quality_categories": base_quality.get("quality_category_counts"), "real_rows": base_quality.get("real_rows"), "labels": base_quality.get("status_label_populated_rows")} if base_quality else None,
                   "checkpoint_d": {"schema_version": temporal_quality.get("feature_schema_version"), "rows": temporal_quality.get("temporal_rows"), "base_columns": temporal_quality.get("base_feature_count"), "temporal_columns": temporal_quality.get("temporal_feature_count"), "real_rows": temporal_quality.get("real_rows"), "radar_comparisons": temporal_quality.get("rows_with_radar_temporal_comparison"), "leakage_tests": temporal_quality.get("leakage_test_status")} if temporal_quality else None,
                   "real_provider_verification": "PENDING"},
               "training_feature_count": len(schema["training_features"]), "excluded_column_count": sum(not f["training_allowed"] for f in fields.values()),
               "passed": not errors, "errors": errors, "warnings": warnings}
    strong_real = [l for l in label_rows if l.get("label_quality") in ("A", "B") and l.get("label_source") != "SYNTHETIC_TEST"]
    groups = {c: len({l["field_id"] for l in strong_real if l.get("status_label") == c}) for c in LABELS}
    summary["real_high_quality_label_groups_by_class"] = groups
    summary["ml_training_ready"] = bool(fixture_counts.get("REAL", 0)) and all(n >= 3 for n in groups.values())
    return summary
