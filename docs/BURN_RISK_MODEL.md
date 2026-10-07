# Burn-risk engine

## Target and current method

The future supervised target is `burned_within_next_3_days`, built retrospectively from trustworthy outcome evidence. There are currently zero burn-outcome labels, so no trained risk model or risk probability exists.

The available fallback is `RULE_ENGINE_V1`: a normalized weighted score over available components. Configured components include days since harvest (only with an explicit harvest-date state), preceding 72-hour rain, an optional timestamp-checked forecast, humidity, historical local burn rate, baler/buyer distances, straw volume, and recent nearby FIRMS activity. Missing inputs are omitted and the remaining component weights are renormalized. Availability flags distinguish absent values. DEMO facilities and unverified contextual registries must remain marked demo.

The output includes `risk_score`, `risk_level`, component scores, reasons, harvest-date state/provenance, and a score-kind marker. **The rule score is not a probability.** LOW/MEDIUM/HIGH/CRITICAL thresholds and component weights are configurable in `config/risk_model.yaml`. Forecast fields stay separate from historical weather and are used only when issuance time is no later than observation time.

Optional facility distance context is accepted by the risk engine, and `src/data/facilities.py` validates DEMO/REAL facility CSVs and calculates nearest baler/buyer distances. The checked-in demo CSV is header-only; it contains no invented businesses. Facility type and source are retained in risk output.

Optional facility distance context is accepted by the risk engine, and `src/data/facilities.py` validates DEMO/REAL facility CSVs and calculates nearest baler/buyer distances. The checked-in demo CSV is header-only; it contains no invented businesses. Facility type and source are retained in risk output.

Optional facility distance context is accepted by the risk engine, and `src/data/facilities.py` validates DEMO/REAL facility CSVs and calculates nearest baler/buyer distances. The checked-in demo CSV is header-only; it contains no invented businesses. Facility type and source are retained in risk output.

## Training architecture and limits

`src/models/burn_risk/train.py` defines a group-split, class-weighted scikit-learn GradientBoostingClassifier pipeline and ROC-AUC, PR-AUC, precision, recall, F1, and Brier score reporting. The separate burn outcome label validator requires source, A/B quality, reviewer, evidence reference, observation time, and creation time. Training requires both classes and at least three distinct field groups per class for train/validation/test; synthetic or weak labels are rejected in normal mode. A calibrated real model requires retrospective A/B labels, group-held-out evaluation, calibration assessment, and independent scientific review. No burn dates are inferred as confirmed by this engine.
