from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

import yaml

LABELS = ("STANDING", "HARVESTED", "BURNT", "SOWN")
QUALITY_RANK = {"A": 4, "B": 3, "C": 2, "S": 1}


def load_schema(path="config/feature_schema.yaml"):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def schema_fingerprint(schema):
    payload = json.dumps({"schema_version": schema["schema_version"], "training_features": schema["training_features"]}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def eligible_label_rows(features, labels, minimum_quality="B", allow_synthetic=False):
    rank = QUALITY_RANK[minimum_quality]
    by_key = {(str(x.get("field_id")), str(x.get("observation_datetime"))): x for x in features}
    result, excluded = [], []
    for label in labels:
        source = str(label.get("label_source", ""))
        tier = str(label.get("label_quality", ""))
        if source == "SYNTHETIC_TEST" or tier == "S":
            if not allow_synthetic or source != "SYNTHETIC_TEST" or tier != "S":
                excluded.append({"field_id": label.get("field_id"), "reason": "synthetic_label_not_allowed"}); continue
        elif tier not in QUALITY_RANK or QUALITY_RANK[tier] < rank:
            excluded.append({"field_id": label.get("field_id"), "reason": "label_quality_below_threshold"}); continue
        if label.get("status_label") not in LABELS:
            excluded.append({"field_id": label.get("field_id"), "reason": "invalid_status_label"}); continue
        row = by_key.get((str(label.get("field_id")), str(label.get("observation_datetime"))))
        if row is None:
            excluded.append({"field_id": label.get("field_id"), "reason": "no_matching_feature_row"}); continue
        if source == "SYNTHETIC_TEST" and row.get("fixture_or_real") != "SYNTHETIC":
            excluded.append({"field_id": label.get("field_id"), "reason": "synthetic_label_requires_synthetic_features"}); continue
        if source != "SYNTHETIC_TEST" and row.get("fixture_or_real") != "REAL":
            excluded.append({"field_id": label.get("field_id"), "reason": "real_label_requires_real_features"}); continue
        result.append({**row, **label})
    return result, excluded


def split_by_field(rows, seed=42, fractions=(0.6, 0.2, 0.2)):
    """Deterministic stratified field-group split; no field may cross partitions."""
    if abs(sum(fractions) - 1) > 1e-9 or min(fractions) <= 0:
        raise ValueError("split fractions must be positive and sum to one")
    class_counts = {}
    for row in rows:
        field = str(row["field_id"])
        label = row["status_label"]
        class_counts.setdefault(field, {}).setdefault(label, 0)
        class_counts[field][label] += 1
    # A field can change status over time; the modal status is used only for
    # stratifying field groups, while every row remains in its one partition.
    group_label = {field: sorted(counts, key=lambda x: (-counts[x], x))[0] for field, counts in class_counts.items()}
    by_class = {}
    for field, label in group_label.items():
        by_class.setdefault(label, []).append(field)
    rng = random.Random(seed)
    assignment = {}
    for label, fields in sorted(by_class.items()):
        if len(fields) < 3:
            raise ValueError(f"class {label} has {len(fields)} field groups; at least 3 needed for train/validation/test")
        rng.shuffle(fields)
        n = len(fields)
        n_train = max(1, int(n * fractions[0]))
        n_val = max(1, int(n * fractions[1]))
        if n_train + n_val >= n:
            n_train, n_val = n - 2, 1
        for f in fields[:n_train]: assignment[f] = "train"
        for f in fields[n_train:n_train+n_val]: assignment[f] = "validation"
        for f in fields[n_train+n_val:]: assignment[f] = "test"
    splits = {name: [r for r in rows if assignment[str(r["field_id"])] == name] for name in ("train", "validation", "test")}
    memberships = {name: {str(r["field_id"]) for r in part} for name, part in splits.items()}
    if any(memberships[a] & memberships[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise AssertionError("field leakage across group split")
    return splits


def encode_feature_row(row, features):
    encoded = []
    for name in features:
        value = row.get(name)
        if name == "observation_quality":
            value = {"POOR": 0.0, "LIMITED": 1.0, "GOOD": 2.0}.get(str(value).upper())
        elif isinstance(value, bool):
            value = float(value)
        elif str(value).lower() in ("true", "false"):
            value = 1.0 if str(value).lower() == "true" else 0.0
        elif value in (None, ""):
            value = None
        else:
            try: value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"feature {name} must be numeric, boolean, or observation_quality; got {value!r}")
        encoded.append(value)
    return encoded


def write_training_contract(rows, path="data/processed/ml/field_status_dataset.csv", schema_path="config/feature_schema.yaml"):
    import csv
    schema = load_schema(schema_path)
    identifiers = schema["primary_key"]
    features = schema["training_features"]
    labels = ["status_label", "label_source", "label_quality", "label_confidence", "reviewer", "notes"]
    metadata = ["split_group", "fixture_or_real", "source_image_id_s2", "processing_version"]
    columns = list(dict.fromkeys(identifiers + features + labels + metadata))
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "split_group": row.get("field_id")})
    return {"path": str(out), "rows": len(rows), "identifier_columns": identifiers,
            "model_feature_columns": features, "label_columns": labels, "non_feature_metadata": metadata,
            "split_policy": "field_id grouped; field groups must remain disjoint across partitions"}


def synthetic_smoke_rows():
    """Explicitly synthetic labels for pipeline tests only; never scientific data."""
    patterns = {
        "STANDING": {"NDVI_mean": .78, "NDVI_delta": -.01, "NDVI_drop_from_peak": -.02, "NBR_mean": .58, "BAIS2_mean": .02},
        "HARVESTED": {"NDVI_mean": .32, "NDVI_delta": -.42, "NDVI_drop_from_peak": -.45, "NBR_mean": .22, "BAIS2_mean": .18},
        "BURNT": {"NDVI_mean": .12, "NDVI_delta": -.3, "NDVI_drop_from_peak": -.62, "NBR_mean": -.15, "BAIS2_mean": .45},
        "SOWN": {"NDVI_mean": .42, "NDVI_delta": .28, "NDVI_drop_from_peak": 0, "NBR_mean": .31, "BAIS2_mean": .04},
    }
    rows = []
    features = load_schema()["training_features"]
    for status, pattern in patterns.items():
        for field_i in range(3):
            field_id = f"SYNTH-{status}-{field_i}"
            for t in range(3):
                row = {"field_id": field_id, "season": "kharif", "year": 2026,
                       "observation_datetime": f"2026-10-{1+t*5:02d}T00:00:00+00:00",
                       "fixture_or_real": "SYNTHETIC", "observation_quality": "GOOD",
                       "status_label": status, "label_source": "SYNTHETIC_TEST", "label_quality": "S",
                       "label_confidence": 1, "label_group": field_id}
                row.update({name: 0.0 for name in features})
                row.update(pattern)
                row["NDVI_mean"] = pattern["NDVI_mean"] + (t * .005)
                row["NDVI_delta"] = pattern["NDVI_delta"] + (t * .002)
                row["NDVI_drop_from_peak"] = pattern["NDVI_drop_from_peak"] - (t * .003)
                row["observation_quality"] = "GOOD"
                row["recent_fire_24h"] = status == "BURNT" and t == 2
                rows.append(row)
    return rows
