# Straw estimation engine

## Formula

`baseline_straw_tonnes = area_ha × baseline_yield_t_per_ha` (default configurable Punjab baseline: 6.0 t/ha).

When peak NDVI is available and the adjustment is enabled:

`vegetation_adjustment = clamp(1 + coefficient × (peak_NDVI - reference_peak_NDVI), min, max)`

`adjusted_straw_tonnes = baseline_straw_tonnes × vegetation_adjustment`.

The current defaults use reference peak NDVI 0.75, coefficient 0.25, and factor limits 0.85–1.10. Missing peak NDVI yields factor 1.0. A configurable ±30% display range is a scenario range, not a statistical confidence interval.

## Eligibility and limitations

An estimate is emitted only for a sufficiently credible harvested candidate or a real/validated model's harvested output. Standing, burnt, sown, and insufficient-evidence cases are ineligible. Current rule-based status candidates are descriptive and not ground truth. The baseline and NDVI adjustment are preliminary assumptions, not calibrated agronomy. They require local harvested-straw measurements, crop/variety and management metadata, moisture basis, and held-out seasonal validation before operational interpretation.
