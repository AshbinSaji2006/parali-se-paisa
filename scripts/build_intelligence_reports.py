import json
from pathlib import Path
import yaml

def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))

audit = load("reports/ml_dataset_audit.json")
test_path = Path("reports/test_suite_summary.json")
tests = json.loads(test_path.read_text(encoding="utf-8-sig")) if test_path.exists() else None
straw_cfg = yaml.safe_load(Path("config/straw_model.yaml").read_text(encoding="utf-8"))
risk_cfg = yaml.safe_load(Path("config/risk_model.yaml").read_text(encoding="utf-8"))
Path("reports/straw_estimation_validation.json").write_text(json.dumps({
    "status": "ENGINE_IMPLEMENTED_UNCALIBRATED", "validation_scope": "formula and boundary behavior are exercised by unit tests; no measured straw validation data exist",
    "formula": "area_ha * baseline_yield_t_per_ha * clamp(1 + coefficient * (peak_NDVI - reference_peak_NDVI), adjustment_min, adjustment_max)",
    "configuration": straw_cfg, "statistical_confidence_interval": False, "uncertainty": "configurable scenario range only", "real_validation_rows": 0
}, indent=2), encoding="utf-8")
Path("reports/burn_risk_validation.json").write_text(json.dumps({
    "status": "RULE_ENGINE_IMPLEMENTED_TRAINED_MODEL_UNAVAILABLE", "target": "burned_within_next_3_days",
    "real_outcome_labels": 0, "rule_method": "weighted, available-component-normalized deterministic score",
    "score_is_probability": False, "configuration": risk_cfg, "forecast_inputs_used_by_fixture": False,
    "unavailable_inputs_are_missing_not_zero": True
}, indent=2), encoding="utf-8")
Path("reports/intelligence_block_report.md").write_text(f'''# Block 2 — Intelligence Layer status

## Current offline state

- Checkpoint E data audit: {'PASS' if audit['passed'] else 'FAIL'}; training ready: {audit['ml_training_ready']}.
- Field status model: RF and scikit-learn GradientBoost training, evaluation, serialization, feature fingerprint rejection, group-aware splits, and trust-gated inference are implemented. Active model state is `NO_MODEL`; synthetic model artifacts are separately tagged and cannot serve intelligence output.
- Straw engine: implemented as an uncalibrated area baseline with configurable conservative peak-NDVI adjustment and scenario range.
- Burn risk: deterministic configurable rule score implemented; it is not a probability. Group-aware gradient-boosting architecture targets `burned_within_next_3_days`; there are no outcome labels.
- Intelligence service: emits status candidate, eligibility-gated straw and risk, trust state, and source provenance.
- Current data: {audit['rows']} rows; REAL={audit['fixture_or_real_counts'].get('REAL',0)}, SYNTHETIC={audit['fixture_or_real_counts'].get('SYNTHETIC',0)}; status labels={audit['label_rows']}.

## Phase status

- Checkpoint E: COMPLETE offline (frozen schema, audit, label importer/tiers, training contract).
- Phase 4: COMPLETE as a software pipeline; no real model trained. Synthetic model is pipeline-test-only.
- Phase 5: COMPLETE as an uncalibrated preliminary estimator; no agronomic measurements to calibrate it.
- Phase 6: COMPLETE as a rule engine plus untrained supervised architecture; score is explicitly not a probability.
- Feature allowlist size: {audit['training_feature_count']}; excluded schema fields: {audit['excluded_column_count']}.
- Automated suite: {tests['passed']} passed, {tests['failed']} failed, {tests['skipped']} skipped ({tests['command']}).

## Readiness

Offline software verification does not establish real-world scientific performance. Real observations, reviewed labels, agronomic straw measurements, and burn outcomes are still required. Live verification remains pending. No Phase 7 or Block 3 work has been started.
''', encoding="utf-8")
