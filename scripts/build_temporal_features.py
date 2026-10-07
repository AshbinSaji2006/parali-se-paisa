from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.data.common import load_config, write_json
from src.features.build_features import FEATURE_COLUMNS
from src.features.temporal_features import TEMPORAL_COLUMNS, build_temporal_rows

LOG = logging.getLogger(__name__)


def run_temporal_build(config_path="config/pilot.yaml"):
    config, root = load_config(config_path)
    fcfg = config["features"]
    tcfg = fcfg.get("temporal", {})
    input_path = root / fcfg["output"]
    output_path = root / tcfg.get("output", "data/processed/features/field_features_temporal.csv")
    json_report = root / tcfg.get("quality_report", "reports/temporal_feature_quality_report.json")
    md_report = root / tcfg.get("quality_report_markdown", "reports/temporal_feature_quality_report.md")
    with input_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        actual = reader.fieldnames or []
        missing = [c for c in FEATURE_COLUMNS if c not in actual]
        if missing:
            raise ValueError(f"Checkpoint C schema invalid; missing columns: {', '.join(missing)}")
        rows = list(reader)
    out_rows, report = build_temporal_rows(rows, tcfg)
    columns = list(actual) + [c for c in TEMPORAL_COLUMNS if c not in actual]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(out_rows)
    tmp.replace(output_path)
    report.update({"input": str(input_path.relative_to(root)), "output": str(output_path.relative_to(root)),
                   "generated_at": datetime.now(timezone.utc).isoformat(),
                   "base_feature_count": len(actual), "temporal_feature_count": len([c for c in columns if c not in actual]),
                   "final_column_count": len(columns), "processing_version": fcfg.get("processing_version", "unknown")})
    write_json(json_report, report)
    md_report.parent.mkdir(parents=True, exist_ok=True)
    md_report.write_text(_markdown_report(report), encoding="utf-8")
    LOG.info("Temporal table rows=%d output=%s", len(out_rows), output_path)
    return out_rows, report


def _markdown_report(report):
    lines = ["# Temporal feature quality report", "", f"- Schema version: `{report['feature_schema_version']}`",
             f"- Rows: {report['temporal_rows']}", f"- Fields: {report['number_of_fields']}",
             f"- Field-season-year groups: {report['number_of_seasons']}",
             f"- Synthetic / real rows: {report['synthetic_rows']} / {report['real_rows']}",
             f"- Rows with prior observation: {report['rows_with_previous_observations']}",
             f"- Radar comparisons available: {report['rows_with_radar_temporal_comparison']}",
             f"- Radar comparisons unavailable: {report['rows_without_compatible_radar_history']}",
             f"- Large gaps: {report['large_gap_count']}", f"- Duplicate timestamp rows: {report['duplicate_timestamp_rows']}",
             f"- Base / temporal / final columns: {report['base_feature_count']} / {report['temporal_feature_count']} / {report['final_column_count']}",
             "", "## Gap days", "", "```json", json.dumps(report["temporal_gap_days"], indent=2), "```", "",
             "## NaN rates", "", "```json", json.dumps(report["nan_rate"], indent=2), "```", "",
             "## Policy and limitations", "", report["temporal_policy"], ""]
    lines.extend(f"- {warning}" for warning in report["warnings"])
    lines.extend(f"- {limitation}" for limitation in report["omitted_history"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build causal temporal features from the Checkpoint C table.")
    parser.add_argument("--config", default="config/pilot.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rows, report = run_temporal_build(args.config)
    print(f"Temporal rows: {len(rows)}; output: {report['output']}; schema: {report['feature_schema_version']}")


if __name__ == "__main__":
    main()
