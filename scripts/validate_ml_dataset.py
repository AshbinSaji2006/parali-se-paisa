from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.models.audit import audit_dataset
from src.models.field_status.dataset import eligible_label_rows, read_csv, write_training_contract
from src.models.field_status.labels import empty_label_template


def main():
    parser = argparse.ArgumentParser(description="Audit the frozen A-D dataset and build its ML training contract.")
    parser.add_argument("--features", default="data/processed/features/field_features_temporal.csv")
    parser.add_argument("--labels", default="data/processed/labels/status_labels.csv")
    parser.add_argument("--schema", default="config/feature_schema.yaml")
    parser.add_argument("--report", default="reports/ml_dataset_audit.json")
    parser.add_argument("--contract", default="data/processed/ml/field_status_dataset.csv")
    args = parser.parse_args()
    empty_label_template(args.labels)
    features = read_csv(args.features); labels = read_csv(args.labels)
    eligible, excluded = eligible_label_rows(features, labels, allow_synthetic=False)
    contract = write_training_contract(eligible, args.contract, args.schema)
    report = audit_dataset(args.features, args.schema, args.labels)
    report["training_contract"] = contract
    report["excluded_labels"] = excluded
    report["ml_training_ready"] = report["ml_training_ready"] and len(eligible) > 0
    out = Path(args.report); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = ["# ML dataset audit", "", f"- Audit passed: **{report['passed']}**", f"- Training ready: **{report['ml_training_ready']}**",
          f"- Rows / columns: {report['rows']} / {report['columns']}", f"- Fields / seasons: {report['number_of_fields']} / {report['number_of_seasons']}",
          f"- Training features: {report['training_feature_count']}", f"- Excluded columns: {report['excluded_column_count']}",
          f"- Fixture counts: `{report['fixture_or_real_counts']}`", f"- Labels: {report['label_rows']} ({report['label_class_counts']})", "",
          "## Warnings", ""]
    md += [f"- {x}" for x in report["warnings"]] or ["- None"]
    md += ["", "## Errors", ""]
    md += [f"- {x}" for x in report["errors"]] or ["- None"]
    md += ["", "## Training contract", "", f"- Contract CSV: `{contract['path']}`", "- Identifiers, model inputs, labels, and provenance have separate schema roles.", ""]
    out.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    print(f"Audit passed={report['passed']}; training_ready={report['ml_training_ready']}; report={out}")
    if not report["passed"]: raise SystemExit(1)


if __name__ == "__main__": main()
