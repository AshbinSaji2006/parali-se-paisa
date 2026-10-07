from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.models.field_status.dataset import eligible_label_rows, read_csv, synthetic_smoke_rows
from src.models.field_status.train import train_field_status


def main():
    parser = argparse.ArgumentParser(description="Train RF and gradient-boosted field status models.")
    parser.add_argument("--features", default="data/processed/features/field_features_temporal.csv")
    parser.add_argument("--labels", default="data/processed/labels/status_labels.csv")
    parser.add_argument("--synthetic-smoke", action="store_true", help="train only a tagged pipeline-test model on generated synthetic patterns")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    out_dir = args.output_dir or ("models/field_status/synthetic_test" if args.synthetic_smoke else "models/field_status/experimental")
    report_path = Path("reports/field_status_training_report.json")
    if args.synthetic_smoke:
        rows = synthetic_smoke_rows(); provenance = "SYNTHETIC_TEST"
    else:
        features = read_csv(args.features); labels = read_csv(args.labels) if Path(args.labels).exists() else []
        rows, excluded = eligible_label_rows(features, labels, minimum_quality="B", allow_synthetic=False)
        provenance = "REAL_LABELS"
        if not rows:
            report = {"status": "NO_MODEL", "trust_state": "NO_MODEL", "eligible_real_label_rows": 0,
                      "excluded_labels": excluded, "message": "No eligible A/B real labels. No model was trained and no project metrics are available."}
            if report_path.exists():
                previous = json.loads(report_path.read_text(encoding="utf-8"))
                if previous.get("trust_state") == "SYNTHETIC_TEST_MODEL":
                    report["synthetic_pipeline_test_only"] = {"metric_heading": previous.get("metric_heading"),
                        "metrics": previous.get("metrics"), "model_path": previous.get("model_path"),
                        "metadata_path": previous.get("metadata_path")}
            report_path.parent.mkdir(parents=True, exist_ok=True); report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print("No eligible real labels; training skipped. Report: reports/field_status_training_report.json"); return
    _, metadata, report = train_field_status(rows, out_dir, dataset_provenance=provenance)
    report["status"] = "PIPELINE TEST MODEL TRAINED" if args.synthetic_smoke else "REAL EXPERIMENTAL MODEL TRAINED"
    report["active_model_state"] = "NO_MODEL" if args.synthetic_smoke else "REAL_EXPERIMENTAL_MODEL_REQUIRES_REVIEW"
    if args.synthetic_smoke: report["metric_heading"] = "PIPELINE TEST METRICS — SYNTHETIC PIPELINE TEST ONLY — NOT A SCIENTIFIC PERFORMANCE RESULT"
    report_path.parent.mkdir(parents=True, exist_ok=True); report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['status']}; trust={metadata['trust_state']}; report={report_path}")


if __name__ == "__main__": main()
