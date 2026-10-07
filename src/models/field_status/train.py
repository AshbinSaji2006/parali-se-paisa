from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.utils.class_weight import compute_sample_weight
import joblib

from .dataset import LABELS, encode_feature_row, load_schema, schema_fingerprint, split_by_field


def _metrics(model, rows, features):
    y = [r["status_label"] for r in rows]
    pred = model.predict([encode_feature_row(r, features) for r in rows])
    report = classification_report(y, pred, labels=LABELS, output_dict=True, zero_division=0)
    return {"accuracy": accuracy_score(y, pred), "macro_precision": precision_score(y, pred, labels=LABELS, average="macro", zero_division=0),
            "macro_recall": recall_score(y, pred, labels=LABELS, average="macro", zero_division=0),
            "macro_f1": f1_score(y, pred, labels=LABELS, average="macro", zero_division=0),
            "weighted_f1": f1_score(y, pred, labels=LABELS, average="weighted", zero_division=0),
            "per_class": {c: {m: report[c][m] for m in ("precision", "recall", "f1-score", "support")} for c in LABELS},
            "harvested_recall": report["HARVESTED"]["recall"], "burnt_recall": report["BURNT"]["recall"],
            "confusion_matrix_labels": list(LABELS), "confusion_matrix": confusion_matrix(y, pred, labels=LABELS).tolist()}


def train_field_status(rows, output_dir="models/field_status", schema_path="config/feature_schema.yaml", dataset_provenance="REAL_LABELS"):
    if not rows:
        raise ValueError("no eligible field-status labels; training is not possible")
    if any(r.get("status_label") not in LABELS for r in rows):
        raise ValueError("training rows contain an unsupported status label")
    schema = load_schema(schema_path)
    splits = split_by_field(rows)
    if not splits["train"] or not splits["validation"] or not splits["test"]:
        raise ValueError("group split produced an empty partition")
    configured_features = schema["training_features"]
    features = [f for f in configured_features if any(r.get(f) not in (None, "") for r in splits["train"])]
    excluded_empty = [f for f in configured_features if f not in features]
    if not features: raise ValueError("no configured features have training observations")
    X_train = [encode_feature_row(r, features) for r in splits["train"]]
    y_train = [r["status_label"] for r in splits["train"]]
    if set(y_train) != set(LABELS):
        raise ValueError("training split must contain all four classes")
    models = {
        "random_forest": Pipeline([("imputer", SimpleImputer(strategy="median")),
                                    ("classifier", RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42, min_samples_leaf=1))]),
        "gradient_boosting": Pipeline([("imputer", SimpleImputer(strategy="median")),
                                       ("classifier", GradientBoostingClassifier(random_state=42, n_estimators=100, learning_rate=.05, max_depth=2))]),
    }
    sample_weights = compute_sample_weight("balanced", y_train)
    metrics = {}
    for name, model in models.items():
        if name == "gradient_boosting": model.fit(X_train, y_train, classifier__sample_weight=sample_weights)
        else: model.fit(X_train, y_train)
        metrics[name] = {"validation": _metrics(model, splits["validation"], features), "test": _metrics(model, splits["test"], features)}
    rf = models["random_forest"].named_steps["classifier"]
    importances = sorted(zip(features, rf.feature_importances_), key=lambda x: (-x[1], x[0]))
    synthetic = dataset_provenance == "SYNTHETIC_TEST"
    trust = "SYNTHETIC_TEST_MODEL" if synthetic else "REAL_EXPERIMENTAL_MODEL"
    metadata = {"trust_state": trust, "dataset_provenance": dataset_provenance,
                "metric_scope": "SYNTHETIC PIPELINE TEST ONLY — NOT A SCIENTIFIC PERFORMANCE RESULT" if synthetic else "HELD-OUT LABELLED DATA; NOT VALIDATED WITHOUT REVIEW",
                "schema_version": schema["schema_version"], "schema_fingerprint": schema_fingerprint(schema),
                "features": features, "classes": list(LABELS), "class_mapping": {x: i for i, x in enumerate(LABELS)},
                "all_missing_training_features_excluded": excluded_empty,
                "training_timestamp": datetime.now(timezone.utc).isoformat(), "split_method": "stratified field-group split; no field crosses train/validation/test",
                "dataset_provenance_summary": dataset_provenance,
                "split_groups": {k: sorted({r["field_id"] for r in v}) for k, v in splits.items()},
                "row_counts": {k: len(v) for k, v in splits.items()}, "models": list(models)}
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, out / "models.pkl")
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    report = {"trust_state": trust, "dataset_provenance": dataset_provenance, "metric_scope": metadata["metric_scope"],
              "eligible_rows": len(rows), "eligible_fields": len({r["field_id"] for r in rows}),
              "class_counts": {c: sum(r["status_label"] == c for r in rows) for c in LABELS},
              "metrics": metrics, "random_forest_global_feature_importance": [{"feature": n, "importance": float(v)} for n, v in importances[:20]],
              "all_missing_training_features_excluded": excluded_empty,
              "metadata_path": str(out / "metadata.json"), "model_path": str(out / "models.pkl")}
    return models, metadata, report
