# Block 2 — Intelligence Layer status

## Current offline state

- Checkpoint E data audit: PASS; training ready: False.
- Field status model: RF and scikit-learn GradientBoost training, evaluation, serialization, feature fingerprint rejection, group-aware splits, and trust-gated inference are implemented. Active model state is `NO_MODEL`; synthetic model artifacts are separately tagged and cannot serve intelligence output.
- Straw engine: implemented as an uncalibrated area baseline with configurable conservative peak-NDVI adjustment and scenario range.
- Burn risk: deterministic configurable rule score implemented; it is not a probability. Group-aware gradient-boosting architecture targets `burned_within_next_3_days`; there are no outcome labels.
- Intelligence service: emits status candidate, eligibility-gated straw and risk, trust state, and source provenance.
- Current data: 6 rows; REAL=0, SYNTHETIC=6; status labels=0.

## Phase status

- Checkpoint E: COMPLETE offline (frozen schema, audit, label importer/tiers, training contract).
- Phase 4: COMPLETE as a software pipeline; no real model trained. Synthetic model is pipeline-test-only.
- Phase 5: COMPLETE as an uncalibrated preliminary estimator; no agronomic measurements to calibrate it.
- Phase 6: COMPLETE as a rule engine plus untrained supervised architecture; score is explicitly not a probability.
- Feature allowlist size: 41; excluded schema fields: 88.
- Automated suite: 85 passed, 0 failed, 1 skipped (PYTHONPATH=. pytest -q).

## Readiness

Offline software verification does not establish real-world scientific performance. Real observations, reviewed labels, agronomic straw measurements, and burn outcomes are still required. Live verification remains pending. No Phase 7 or Block 3 work has been started.
