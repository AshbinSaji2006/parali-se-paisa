from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, average_precision_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.utils.class_weight import compute_sample_weight

from src.models.field_status.dataset import encode_feature_row, split_by_field
from .labels import validate_burn_outcome

RISK_FEATURES = ["NDVI_mean", "NDVI_delta", "NDVI_drop_from_peak", "NBR_mean", "NBR_delta", "BAIS2_mean", "BAIS2_delta", "VV_mean_db", "VH_mean_db", "rain_72h", "humidity_pct", "temperature_c", "recent_fire_72h", "valid_pixel_fraction", "days_since_previous_observation", "days_since_peak_NDVI"]


def train_burn_risk(rows, output_dir="models/burn_risk", allow_synthetic=False):
    if not rows: raise ValueError("no burned_within_next_3_days labels; burn-risk model remains untrained")
    rows = [validate_burn_outcome(r, allow_synthetic=allow_synthetic) for r in rows]
    for row in rows:
        row["status_label"] = str(int(row["burned_within_next_3_days"]))
    if not allow_synthetic and any(r.get("fixture_or_real") != "REAL" for r in rows):
        raise ValueError("trained burn-risk model requires real feature observations")
    splits = split_by_field(rows)
    train = splits["train"]
    features = [f for f in RISK_FEATURES if any(r.get(f) not in (None, "") for r in train)]
    excluded_empty = [f for f in RISK_FEATURES if f not in features]
    if not features: raise ValueError("no risk features have training observations")
    y = [int(r["burned_within_next_3_days"]) for r in train]
    if set(y) != {0, 1}: raise ValueError("training partition requires positive and negative groups")
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("classifier", GradientBoostingClassifier(random_state=42))])
    model.fit([encode_feature_row(r, features) for r in train], y, classifier__sample_weight=compute_sample_weight("balanced", y))
    test = splits["test"]; yt = [int(r["burned_within_next_3_days"]) for r in test]
    prob = model.predict_proba([encode_feature_row(r, features) for r in test])[:, list(model.named_steps["classifier"].classes_).index(1)]
    pred = (prob >= .5).astype(int)
    metrics = {"roc_auc": roc_auc_score(yt, prob), "pr_auc_average_precision": average_precision_score(yt, prob),
               "precision": precision_score(yt, pred, zero_division=0), "recall": recall_score(yt, pred, zero_division=0),
               "f1": f1_score(yt, pred, zero_division=0), "brier_score": brier_score_loss(yt, prob)} if len(set(yt)) == 2 else None
    metadata = {"trust_state": "SYNTHETIC_TEST_MODEL" if allow_synthetic else "REAL_EXPERIMENTAL_MODEL", "target": "burned_within_next_3_days",
                "features": features, "all_missing_training_features_excluded": excluded_empty, "training_timestamp": datetime.now(timezone.utc).isoformat(),
                "split_method": "field-group split", "split_groups": {k: sorted({r["field_id"] for r in v}) for k,v in splits.items()},
                "model": "sklearn GradientBoostingClassifier", "probability_calibration": "not calibrated"}
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.pkl"); (out / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {"status": "TRAINED_SYNTHETIC_PIPELINE_TEST_ONLY" if allow_synthetic else "REAL_EXPERIMENTAL_MODEL",
            "metrics": metrics, "metric_scope": "SYNTHETIC PIPELINE TEST ONLY — NOT A SCIENTIFIC PERFORMANCE RESULT" if allow_synthetic else "real held-out groups; review required",
            "metadata": metadata}
