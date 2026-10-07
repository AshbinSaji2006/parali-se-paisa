from __future__ import annotations

import json
from pathlib import Path

import joblib

from .dataset import LABELS, encode_feature_row, load_schema, schema_fingerprint


class FieldStatusModel:
    def __init__(self, model_dir, allow_synthetic=False, model_name="random_forest", schema_path="config/feature_schema.yaml"):
        model_dir = Path(model_dir)
        self.metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
        schema = load_schema(schema_path)
        if self.metadata.get("schema_fingerprint") != schema_fingerprint(schema):
            raise ValueError("model feature schema does not match current frozen schema")
        if self.metadata.get("trust_state") == "SYNTHETIC_TEST_MODEL" and not allow_synthetic:
            raise ValueError("synthetic pipeline-test model cannot be loaded as a genuine prediction model")
        if model_name not in self.metadata.get("models", []):
            raise ValueError(f"model {model_name!r} is not present in serialized artifact")
        self.model = joblib.load(model_dir / "models.pkl")[model_name]
        self.model_name = model_name
        self.features = self.metadata["features"]

    def predict(self, row):
        missing = [x for x in self.features if x not in row]
        if missing:
            raise ValueError(f"inference row is missing frozen feature columns: {', '.join(missing)}")
        vector = encode_feature_row(row, self.features)
        estimator = self.model.named_steps["classifier"]
        raw = self.model.predict_proba([vector])[0]
        probabilities = {name: 0.0 for name in LABELS}
        for label, value in zip(estimator.classes_, raw): probabilities[label] = float(value)
        status = max(probabilities, key=probabilities.get)
        signals = []
        raw_delta = _number(row.get("NDVI_delta")); raw_ndvi = _number(row.get("NDVI_mean"))
        raw_bais = _number(row.get("BAIS2_delta")); raw_nbr = _number(row.get("NBR_mean"))
        if raw_delta is not None and raw_delta < -.2: signals.append("large negative NDVI change")
        if raw_bais is not None and raw_bais > .1: signals.append("BAIS2 increased")
        if raw_nbr is not None and raw_nbr < .15: signals.append("low current NBR")
        if raw_ndvi is not None and raw_ndvi > .6: signals.append("high current NDVI")
        return {"status": status, "predicted_status": status, "confidence": probabilities[status],
                "confidence_semantics": "uncalibrated maximum classifier probability score",
                "probabilities": probabilities, "model_name": self.model_name,
                "explanation": signals[:3] or ["No simple threshold explanation was triggered; consult stored global feature importance"],
                "model_trust_state": self.metadata["trust_state"], "is_ground_truth": False}


def _number(x):
    try: return float(x) if x not in (None, "") else None
    except (TypeError, ValueError): return None
