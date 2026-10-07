# Field status model card

## Purpose

Provide a reusable structured-data classification pipeline for field-time observations. The target classes are `STANDING`, `HARVESTED`, `BURNT`, and `SOWN`. No classifier is currently trusted or active because the repository contains no real labels.

## Inputs and outputs

Inputs are the numeric/explicitly encoded columns listed in `config/feature_schema.yaml`. Field, season, year, observation time, image IDs, fixture status, processing versions, free text, and labels are not model features. Inference returns class scores, their maximum, model trust state, and an uncalibrated score disclaimer. It does not return a confirmed field state.

## Algorithms

The training module provides a class-weighted Random Forest and scikit-learn GradientBoostingClassifier. LightGBM is not installed in this environment; scikit-learn gradient boosting is the documented substitution. Missing numeric values use median imputation inside the training pipeline. Splits are stratified by field group; all observations for one field remain in one partition. The pipeline reports accuracy, macro/weighted F1, macro precision/recall, per-class precision/recall/F1, confusion matrix, HARVESTED recall, and BURNT recall. It also stores Random Forest global feature importance.

## Training data and labels

Current feature rows are synthetic fixtures; there are zero real rows and zero field-status labels. No project metrics are available. Label CSV imports require source, confidence, quality tier, reviewer, notes, timestamps, and one of the four class names. Tiers are A (field verified), B (clear multi-date human review), C (proxy/weak), and S (synthetic test). Default training excludes C and S. `SYNTHETIC_TEST` is only accepted at tier S when a caller explicitly enables test mode. A generated smoke model is tagged `SYNTHETIC_TEST_MODEL`, stored separately, and refused by normal inference.

## Trust state and metrics

Current state: `NO_MODEL`. Any metrics produced from synthetic pipeline smoke data must be headed `SYNTHETIC PIPELINE TEST ONLY — NOT A SCIENTIFIC PERFORMANCE RESULT`. Experimental scores on real labels are not validated performance until the labels, groups, and test protocol receive review. Classifier maximum probabilities are not calibrated confidence intervals.

## Intended use

Offline software integration tests and, after independent validation, decision support requiring human review.

## Non-intended use and limitations

Do not use this pipeline to assert confirmed harvest, burn, sowing, or standing status; issue enforcement decisions; or claim real-world accuracy. Remote-sensing indices, FIRMS context, and rules are indirect signals. Real field observations and A/B quality labels for every class are required. Classifier calibration, geographic transfer, season transfer, and sensor/processing drift have not been evaluated.
