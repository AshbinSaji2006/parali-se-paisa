# Temporal feature quality report

- Schema version: `1.0`
- Leakage test status: PASS: 85 passed, 0 failed, 1 skipped; includes future-append prefix invariance, future peak, rolling, slope, field/year/season isolation, and radar causal tests.
- Rows: 6
- Fields: 3
- Field-season-year groups: 3
- Synthetic / real rows: 6 / 0
- Rows with prior observation: 3
- Radar comparisons available: 1
- Radar comparisons unavailable: 5
- Large gaps: 0
- Duplicate timestamp rows: 0
- Base / temporal / final columns: 78 / 51 / 129

## Gap days

```json
{
  "count": 3,
  "min": 5.0,
  "median": 5.0,
  "max": 5.0
}
```

## NaN rates

```json
{
  "NDVI_prev": 0.5,
  "NDVI_delta": 0.5,
  "peak_NDVI_so_far": 0.0,
  "NDVI_rolling_mean_3": 1.0,
  "NDVI_slope_last_3": 1.0,
  "VV_delta_db": 0.8333333333333334
}
```

## Policy and limitations

Within field_id+season+year; sort UTC; exclude POOR or zero-valid-pixel rows from future history; LIMITED rows are eligible; same-time duplicates are retained and see only strictly earlier timestamps.

- FIRMS event count histories are omitted because the C table has only as-of window summaries, not event-level detections.
- Weather rolling histories are omitted because the C table has only observation-level aggregates, not daily record histories.