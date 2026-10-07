# ML dataset audit

- Audit passed: **True**
- Training ready: **False**
- Rows / columns: 6 / 129
- Fields / seasons: 3 / 1
- Training features: 41
- Excluded columns: 88
- Fixture counts: `{'SYNTHETIC': 6}`
- Labels: 0 ({})

## Warnings

- training feature VV_minus_VH_delta_db has 100.0% missing values
- training feature VV_VH_ratio_linear_delta has 100.0% missing values
- training feature NDVI_rolling_mean_3 has 100.0% missing values
- training feature NBR_rolling_mean_3 has 100.0% missing values
- training feature BAIS2_rolling_mean_3 has 100.0% missing values
- training feature VV_delta_db has 83.3% missing values
- training feature VH_delta_db has 100.0% missing values
- training feature NDVI_slope_last_3 has 100.0% missing values
- training feature NBR_slope_last_3 has 100.0% missing values
- training feature BAIS2_slope_last_3 has 100.0% missing values
- No labels available; model training and scientific evaluation are not ready
- No real observations: scientific performance cannot be measured

## Errors

- None

## Training contract

- Contract CSV: `data\processed\ml\field_status_dataset.csv`
- Identifiers, model inputs, labels, and provenance have separate schema roles.
