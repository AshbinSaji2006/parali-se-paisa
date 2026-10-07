import argparse
import json
from pathlib import Path

from src.models.field_status.dataset import eligible_label_rows, read_csv
from src.models.field_status.inference import FieldStatusModel
from src.models.field_status.train import _metrics

parser = argparse.ArgumentParser(description="Evaluate a serialized field-status model on eligible field groups.")
parser.add_argument("--model-dir", required=True)
parser.add_argument("--features", default="data/processed/features/field_features_temporal.csv")
parser.add_argument("--labels", default="data/processed/labels/status_labels.csv")
parser.add_argument("--allow-synthetic", action="store_true")
parser.add_argument("--output", default="reports/field_status_evaluation.json")
args = parser.parse_args()
features = read_csv(args.features); labels = read_csv(args.labels)
rows, excluded = eligible_label_rows(features, labels, allow_synthetic=args.allow_synthetic)
model = FieldStatusModel(args.model_dir, allow_synthetic=args.allow_synthetic)
metrics = _metrics(model.model, rows, model.features) if rows else None
scope = "SYNTHETIC PIPELINE TEST ONLY — NOT A SCIENTIFIC PERFORMANCE RESULT" if args.allow_synthetic else "held-out labelled dataset; not project performance unless labels and split are verified"
report = {"trust_state": model.metadata["trust_state"], "metric_scope": scope, "rows": len(rows), "metrics": metrics, "excluded": excluded}
out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(f"Evaluation rows={len(rows)}; scope={scope}; report={out}")
