from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from .dataset import LABELS

LABEL_COLUMNS = ["field_id", "observation_datetime", "status_label", "label_source", "label_confidence", "label_quality", "reviewer", "notes", "created_at"]
SOURCE_TIERS = {"MANUAL_SATELLITE_REVIEW": {"A", "B"}, "FIELD_SURVEY": {"A"}, "TRUSTED_EXTERNAL": {"A", "B"}, "FIRMS_SUPPORTED_WEAK_LABEL": {"C"}, "SYNTHETIC_TEST": {"S"}}


def validate_label(row):
    missing = [c for c in LABEL_COLUMNS if c not in row or row[c] in (None, "")]
    if missing:
        raise ValueError(f"label missing required metadata: {', '.join(missing)}")
    if row["status_label"] not in LABELS:
        raise ValueError(f"status_label must be one of {', '.join(LABELS)}")
    if row["label_source"] not in SOURCE_TIERS:
        raise ValueError(f"unsupported label_source: {row['label_source']}")
    if row["label_quality"] not in SOURCE_TIERS[row["label_source"]]:
        raise ValueError("label_quality is inconsistent with source trust tier")
    try:
        value = float(row["label_confidence"])
    except (TypeError, ValueError):
        raise ValueError("label_confidence must be numeric in [0,1]")
    if not 0 <= value <= 1:
        raise ValueError("label_confidence must be numeric in [0,1]")
    stamp = datetime.fromisoformat(str(row["observation_datetime"]).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("observation_datetime must include a timezone")
    created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
    if created.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    if row["label_source"] == "SYNTHETIC_TEST" and row["label_quality"] != "S":
        raise ValueError("synthetic labels must use quality tier S")
    return {**row, "label_confidence": value}


def import_labels(input_path, output_path="data/processed/labels/status_labels.csv"):
    with Path(input_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != LABEL_COLUMNS:
            raise ValueError(f"label schema mismatch; expected columns: {','.join(LABEL_COLUMNS)}")
        imported = [validate_label(row) for row in reader]
    seen = set()
    for row in imported:
        key = (row["field_id"], row["observation_datetime"])
        if key in seen:
            raise ValueError(f"duplicate label for field/time: {key}")
        seen.add(key)
    out = Path(output_path); out.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if out.exists():
        with out.open(newline="", encoding="utf-8") as stream: existing = list(csv.DictReader(stream))
    keys = {(x["field_id"], x["observation_datetime"]) for x in existing}
    if any((x["field_id"], x["observation_datetime"]) in keys for x in imported):
        raise ValueError("import would duplicate an existing field/time label")
    with out.open("a" if out.exists() else "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LABEL_COLUMNS)
        if not existing: writer.writeheader()
        writer.writerows(imported)
    return imported


def empty_label_template(path="data/processed/labels/status_labels.csv"):
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        with out.open("w", newline="", encoding="utf-8") as stream: csv.writer(stream).writerow(LABEL_COLUMNS)
    return out
