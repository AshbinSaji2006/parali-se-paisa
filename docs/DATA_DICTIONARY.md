# Field-time feature table

Output: `data/processed/features/field_features.csv`. One row represents one field at a Sentinel-2 reference acquisition time. Empty CSV values mean unavailable/undefined (`NULL`); none are replaced with 0 unless the definition is a count or Boolean flag. All rows from the current fixture are synthetic.

| Name | Description | Type | Unit | Source | Expected range / NULL |
|---|---|---|---|---|---|
| `field_id` | Stable field identifier | string | — | Clean fields GeoJSON | Required |
| `district` | Configured/admin district | string | — | Clean fields GeoJSON | Nullable |
| `village` | Locality name | string | — | Clean fields GeoJSON | Nullable |
| `season` | Crop season metadata | string | — | Clean fields GeoJSON | Nullable |
| `year` | Calendar year of reference acquisition | integer | year | Observation datetime | Required |
| `observation_date` | Sentinel-2 reference date | date | ISO date | Sentinel-2 | Required |
| `observation_datetime` | Sentinel-2 reference timestamp, UTC | datetime | ISO-8601 UTC | Sentinel-2 | Required |
| `area_ha` | Validated field area | float | ha | Clean fields; EPSG:32643 area | >0; nullable only if absent |
| `NDVI_mean` | Mean per-pixel normalized vegetation difference | float | dimensionless | Sentinel-2 B8/B4 | Normally [-1,1]; NULL if undefined |
| `NDVI_median` | Median per-pixel NDVI | float | dimensionless | Sentinel-2 B8/B4 | Normally [-1,1]; NULL if undefined |
| `NDVI_std` | Population standard deviation of per-pixel NDVI | float | dimensionless | Sentinel-2 B8/B4 | >=0; NULL if undefined |
| `NDVI_min` | Minimum per-pixel NDVI | float | dimensionless | Sentinel-2 B8/B4 | Normally [-1,1]; NULL if undefined |
| `NDVI_max` | Maximum per-pixel NDVI | float | dimensionless | Sentinel-2 B8/B4 | Normally [-1,1]; NULL if undefined |
| `NBR_mean` | Mean per-pixel normalized burn ratio | float | dimensionless | Sentinel-2 B8A/B12 | Normally [-1,1]; NULL if undefined |
| `NBR_median` | Median per-pixel NBR | float | dimensionless | Sentinel-2 B8A/B12 | Normally [-1,1]; NULL if undefined |
| `NBR_std` | Population standard deviation of per-pixel NBR | float | dimensionless | Sentinel-2 B8A/B12 | >=0; NULL if undefined |
| `NBR_min` | Minimum per-pixel NBR | float | dimensionless | Sentinel-2 B8A/B12 | Normally [-1,1]; NULL if undefined |
| `NBR_max` | Maximum per-pixel NBR | float | dimensionless | Sentinel-2 B8A/B12 | Normally [-1,1]; NULL if undefined |
| `BAIS2_mean` | Mean per-pixel Sentinel-2 burned-area index | float | dimensionless | Sentinel-2 B4/B6/B7/B8A/B12 | Formula domain; may be negative or >1; NULL if undefined |
| `BAIS2_median` | Median per-pixel BAIS2 | float | dimensionless | Sentinel-2 B4/B6/B7/B8A/B12 | Formula domain; may be negative or >1; NULL if undefined |
| `BAIS2_std` | Population standard deviation of per-pixel BAIS2 | float | dimensionless | Sentinel-2 B4/B6/B7/B8A/B12 | >=0; NULL if undefined |
| `BAIS2_min` | Minimum per-pixel BAIS2 | float | dimensionless | Sentinel-2 B4/B6/B7/B8A/B12 | Formula domain; NULL if undefined |
| `BAIS2_max` | Maximum per-pixel BAIS2 | float | dimensionless | Sentinel-2 B4/B6/B7/B8A/B12 | Formula domain; NULL if undefined |
| `B2_mean` | Mean scaled blue reflectance | float | reflectance (0–1 scale) | Sentinel-2 B2 | Usually 0–1; NULL if unavailable |
| `B3_mean` | Mean scaled green reflectance | float | reflectance (0–1 scale) | Sentinel-2 B3 | Usually 0–1; NULL if unavailable |
| `B4_mean` | Mean scaled red reflectance | float | reflectance (0–1 scale) | Sentinel-2 B4 | Usually 0–1; NULL if unavailable |
| `B6_mean` | Mean scaled red-edge 2 reflectance (included for BAIS2) | float | reflectance (0–1 scale) | Sentinel-2 B6 | Usually 0–1; NULL if unavailable |
| `B7_mean` | Mean scaled red-edge 3 reflectance (included for BAIS2) | float | reflectance (0–1 scale) | Sentinel-2 B7 | Usually 0–1; NULL if unavailable |
| `B8_mean` | Mean scaled NIR reflectance | float | reflectance (0–1 scale) | Sentinel-2 B8 | Usually 0–1; NULL if unavailable |
| `B8A_mean` | Mean scaled narrow NIR reflectance | float | reflectance (0–1 scale) | Sentinel-2 B8A | Usually 0–1; NULL if unavailable |
| `B11_mean` | Mean scaled SWIR-1 reflectance | float | reflectance (0–1 scale) | Sentinel-2 B11 | Usually 0–1; NULL if unavailable |
| `B12_mean` | Mean scaled SWIR-2 reflectance | float | reflectance (0–1 scale) | Sentinel-2 B12 | Usually 0–1; NULL if unavailable |
| `valid_pixel_count` | Non-cloudy, valid pixels with all required optical bands | integer | pixels | Sentinel-2 pixel mask | >=0; 0 when none |
| `total_pixel_count` | Pixels presented to the field reducer | integer | pixels | Sentinel-2 reducer | >=0 |
| `valid_pixel_fraction` | Valid count divided by total count | float | fraction | Sentinel-2 reducer | [0,1]; NULL if total=0 |
| `cloud_fraction` | Cloud/shadow/cirrus/snow pixels divided by total | float | fraction | Sentinel-2 SCL mask | [0,1]; NULL if total=0 |
| `VV_mean_db` | Mean Sentinel-1 VV backscatter in dB | float | dB | Sentinel-1 VV | Sensor range; NULL if no S1 |
| `VH_mean_db` | Mean Sentinel-1 VH backscatter in dB | float | dB | Sentinel-1 VH | Sensor range; NULL if absent |
| `VV_minus_VH_db` | Mean VV dB minus mean VH dB | float | dB | Sentinel-1 | NULL if either polarization missing |
| `VV_VH_ratio_linear` | Ratio of mean linear VV and VH power; pixel arrays are converted from dB before averaging | float | dimensionless | Sentinel-1 | >0; NULL if VH missing |
| `missing_vh` | Selected S1 acquisition lacks usable VH | boolean | — | Sentinel-1 | True/False; True when no S1 |
| `firms_points_within_field` | Past/equal-time FIRMS detections covered by field geometry | integer | points | FIRMS + field polygon | >=0; NULL if provider unavailable |
| `firms_points_within_500m` | Past/equal-time detections within 500 m of field boundary | integer | points | FIRMS + local metric projection | >=0; NULL if unavailable |
| `firms_points_within_1km` | Past/equal-time detections within 1 km of field boundary | integer | points | FIRMS + local metric projection | >=0; NULL if unavailable |
| `nearest_firms_distance_m` | Minimum prior/equal-time distance to field polygon | float | m | FIRMS + local metric projection | >=0; NULL if no detections/provider |
| `recent_fire_24h` | Any prior/equal-time FIRMS point within 1 km in `(t-24h,t]` | boolean | — | FIRMS timestamps + field geometry | NULL if provider unavailable |
| `recent_fire_72h` | Any prior/equal-time FIRMS point within 1 km in `(t-72h,t]` | boolean | — | FIRMS timestamps + field geometry | NULL if provider unavailable |
| `precipitation_mm` | Latest precipitation value in available preceding weather window | float | mm/hour interval | Weather provider | >=0 normally; NULL if missing |
| `rain_24h` | Sum of non-null hourly precipitation in `(t-24h,t]` | float | mm | Weather provider | >=0; NULL if no measurements |
| `rain_72h` | Sum of non-null hourly precipitation in `(t-72h,t]` | float | mm | Weather provider | >=0; NULL if no measurements |
| `humidity_pct` | Latest available relative humidity in preceding 72 h | float | % | Weather provider | [0,100]; NULL if missing |
| `temperature_c` | Latest available temperature in preceding 72 h | float | °C | Weather provider | Physical/provider range; NULL if missing |
| `wind_speed` | Latest available wind speed in preceding 72 h | float | km/h (Open-Meteo default) | Weather provider | >=0; NULL if missing |
| `s2_available` | A reference Sentinel-2 observation exists | boolean | — | Observation join | Always True for emitted rows |
| `s1_available` | Compatible prior S1 observation selected | boolean | — | Sentinel-1 as-of join | True/False |
| `weather_available` | Provider data exists in lookback interval | boolean | — | Weather as-of join | True/False |
| `firms_available` | FIRMS source was supplied for the build | boolean | — | FIRMS input metadata | True/False |
| `observation_quality` | Overall completeness category | category | — | Quality rules | GOOD / LIMITED / POOR |
| `observation_quality_flags` | Pipe-delimited reasons for reduced quality | string | — | Quality rules | Empty or one/more flags |
| `s2_observation_datetime` | Optical reference timestamp | datetime | UTC | Sentinel-2 metadata | Required |
| `s1_observation_datetime` | Selected radar acquisition timestamp | datetime | UTC | Sentinel-1 metadata | NULL if no compatible S1 |
| `s1_age_days` | Elapsed time from selected S1 to S2 reference | float | days | Timestamp difference | [0, configured lookback]; NULL if no S1 |
| `weather_window_end` | Reference timestamp used for weather as-of aggregation | datetime | UTC | Join logic | NULL if no in-window records |
| `firms_window_end` | Reference timestamp used to exclude future FIRMS points | datetime | UTC | Join logic | Reference datetime |
| `source_image_id_s2` | Sentinel-2 source asset ID | string | — | Sentinel-2 metadata | Required |
| `source_image_id_s1` | Selected Sentinel-1 source asset ID | string | — | Sentinel-1 metadata | NULL if no S1 |
| `s2_collection` | Sentinel-2 collection identifier | string | — | Sentinel-2 metadata | Nullable |
| `s1_collection` | Sentinel-1 collection identifier | string | — | Sentinel-1 metadata | Nullable |
| `s1_orbit_pass` | Selected S1 ascending/descending pass | string | — | Sentinel-1 metadata | NULL if no S1 |
| `s1_relative_orbit_number` | Selected S1 relative orbit number | integer | orbit | Sentinel-1 metadata | NULL if unavailable |
| `s1_instrument_mode` | Selected S1 acquisition mode | string | — | Sentinel-1 metadata | Usually IW; NULL if no S1 |
| `s1_polarizations` | Polarizations present in selected S1 acquisition | string | — | Sentinel-1 metadata | NULL if no S1 |
| `weather_source` | Weather provider identifier | string | — | Weather input | NULL if no data |
| `weather_record_type` | Historical/reanalysis or forecast provenance | string | — | Weather input | Nullable |
| `firms_source` | FIRMS feed/source identifier | string | — | FIRMS input | NULL if no points/provider |
| `fixture_or_real` | Provenance class of the observation bundle | category | — | Input declaration | SYNTHETIC / REAL |
| `processing_version` | Feature pipeline version | string | — | Config | Required |
| `status_label` | Future ground-truth label slot; never inferred here | string | — | Label importer (later phase) | Always NULL in this checkpoint |

`std` is population standard deviation (`ddof=0`). Radar ratios are computed in linear power, never by dividing dB values. Contextual timestamps are constrained to be no later than the Sentinel-2 reference time.

## Temporal feature engineering (Checkpoint D)

The temporal output is `data/processed/features/field_features_temporal.csv`; the Checkpoint C base CSV remains unchanged. Rows are UTC-sorted and grouped by `field_id`, `season`, and `year`, so history resets at a new field, season, or year. `feature_schema_version` identifies the added schema (`1.0`). All feature formulas are causal: only the current row and earlier observations can contribute.

| Feature | Meaning / formula | Availability and policy |
|---|---|---|
| `*_prev`, `*_prev_db` | Most recent valid earlier metric value; optical metrics search backward for a non-null metric | First/unavailable value is NULL; POOR rows are excluded from history, LIMITED rows included |
| `*_delta`, `*_delta_db` | Current minus previous; negative means the index or radar value decreased | NULL if either operand is unavailable |
| `NDVI_pct_change`, `NBR_pct_change` | `(current - previous) / abs(previous)` | NULL if previous is null or `abs(previous) <= pct_change_epsilon` |
| `*_delta_2obs` | Current minus the value two valid metric observations earlier | Requires two earlier valid values and current value |
| `*_rolling_mean_2/3` | Mean of latest 2/3 valid metric values, including current | Requires a full count window; no imputation |
| `NDVI_rolling_std_3`, `NBR_rolling_std_3` | Population standard deviation (`ddof=0`) over latest 3 valid values including current | Requires three values |
| `*_slope_last_3` | OLS slope over latest three valid values using actual UTC elapsed days | Index units per day; requires three values and nonzero elapsed time |
| `peak_NDVI_so_far` | Maximum valid NDVI through current timestamp | Ties choose earliest timestamp; never uses a future seasonal maximum |
| `peak_NDVI_datetime_so_far`, `days_since_peak_NDVI` | Time of causal peak and elapsed days to it | NULL until an NDVI value exists |
| `NDVI_drop_from_peak` | `current NDVI - peak NDVI` | Negative indicates decline; NULL if current NDVI is missing |
| `NDVI_drop_fraction_from_peak` | `(current NDVI - peak NDVI) / abs(peak NDVI)` | Signed fraction; NULL for missing current or near-zero peak |
| `previous_observation_datetime`, `previous_source_image_id_s2` | Provenance of the prior eligible field-season-year observation | POOR and zero-valid-pixel observations do not enter this history |
| `days_since_previous_observation`, `temporal_gap_category` | UTC elapsed days and NORMAL/MODERATE/LARGE category | Thresholds in `features.temporal`; defaults 14 and 30 days |
| `temporal_history_count`, `temporal_previous_valid`, `temporal_previous_quality` | Eligible history size and prior-row validity/quality | LIMITED is explicitly eligible |
| `VV_prev_db`, `VH_prev_db`, `VV_minus_VH_prev_db`, `VV_VH_ratio_linear_prev` | Previous compatible Sentinel-1 measurement | Requires earlier S1 datetime, matching instrument mode, and matching pass/orbit when both are supplied |
| `VV_delta_db`, `VH_delta_db`, `VV_minus_VH_delta_db`, `VV_VH_ratio_linear_delta` | Current minus compatible prior S1 measurement | NULL and `radar_temporal_comparison_available=false` when no compatible comparison exists |
| `observation_number_in_season`, `day_of_year`, `days_since_first_observation_in_season` | Chronological group position and calendar progression | Duplicate timestamps share a position; seasons/years reset |
| `temporal_duplicate_timestamp` | Marks rows sharing an exact field-season-year timestamp | Retained and reported; same-time rows do not use each other as history |

Checkpoint C exposes only causal as-of FIRMS and weather summaries, not the event-level detections or daily weather series needed to correctly derive historical event counts, dry-day counts, or rolling weather histories. Checkpoint D does not reconstruct or duplicate those summaries as new history features. The temporal test suite verifies prefix invariance after appending future rows, including spectral, radar, weather/fire base fields, peak, rolling windows, and slopes. No temporal feature is a harvest, burn, sowing, or other status label.

## Frozen ML training contract (Block 2)

`config/feature_schema.yaml` is authoritative for all temporal columns. Each field records type, nullable, unit, feature group, `training_allowed`, `inference_required`, provenance, and status. The curated numeric/encoded model allowlist is `training_features`. Identifiers (`field_id`, `season`, `year`, observation time), labels, provenance IDs/text, fixture markers, and processing metadata are retained separately and are not model inputs. `observation_quality` uses an explicit POOR=0, LIMITED=1, GOOD=2 encoding. The serialized model stores this feature list and a schema fingerprint; inference rejects a changed schema.

The training contract CSV stores identifiers first, model inputs next, then target/label metadata and non-feature provenance metadata. `label_group` supports field-group splits. No row-level random split is used. Synthetic test rows are not part of the real training contract.

## Labels and intelligence outputs

The label registry is `data/processed/labels/status_labels.csv`. Supported status values are STANDING, HARVESTED, BURNT, and SOWN. Provenance sources and tiers are constrained: FIELD_SURVEY is A; MANUAL_SATELLITE_REVIEW and TRUSTED_EXTERNAL may be A/B; FIRMS_SUPPORTED_WEAK_LABEL is C; SYNTHETIC_TEST is S only. Every record also requires confidence, reviewer, notes, observation time, and creation time. Default training uses A/B labels only. Weak C and synthetic S labels are excluded by default.

The rule status engine emits `status_candidate`, evidence strings, and a qualitative confidence band; it sets `is_ground_truth=false`. Straw values are preliminary tonnes with configurable input assumptions and a non-statistical scenario range. The burn-risk fallback is a weighted normalized score tagged `NORMALIZED_RULE_SCORE_NOT_PROBABILITY`; missing risk inputs remain absent and component availability is reported. No current data support a real status model, straw calibration, or burn-risk probability.

## Real-data quality and fire-context columns (`real_field_features.parquet`)

Built by `scripts/build_real_products.py`; see `reports/research/FINAL_JUDGE_EVIDENCE.md`.

| Column | Meaning |
|---|---|
| `BAIS2_quality` | `OK` or `UNSTABLE_PIXEL_ARTEFACT` when the pixel-mean BAIS2 differs from BAIS2 of the band means by more than 0.25 (a near-zero red pixel dominates). Unstable values are removed from `BAIS2`/`BAIS2_mean`. |
| `BAIS2_from_band_means`, `BAIS2_pixel_vs_band_mean_abs_diff`, `BAIS2_pixel_mean_raw` | Recomputation used for the flag and the original stored pixel mean (provenance only). |
| `weather_grid_distance_km` | Distance from field centroid to the nearest acquired ERA5 grid point. Reanalysis is not a field measurement. |
| `weather_available` | True only when a published reanalysis hour no more than 24 h before acquisition supplied non-null values. |
| `firms_coverage_status`, `firms_window_covered_days` | `COMPLETE`/`PARTIAL`/`NOT_COVERED` coverage of the 30-day look-back by the acquired FIRMS/UMD archive. |
| `firms_viirs_detections_near_field`, `firms_modis_detections_near_field`, `firms_nearest_detection_km`, `firms_latest_detection_datetime` | Active-fire detections (type 0 or NRT) within 1 km of the centroid, timestamped at or before acquisition. Null when the window is not covered; a `PARTIAL` zero is not evidence of no fire. Proximity context, not attribution. |
| `modis_ba_coverage_status`, `modis_ba_burned_pixels_near_field`, `modis_ba_latest_burn_date`, `modis_ba_availability` | MCD64A1 500 m burned pixels within 500 m with burn day in the 30 days before the acquisition day. Retrospective product, not knowable at acquisition time. |

Weak labels (`real_weak_labels.parquet`) carry `evidence_window_start`, `evidence_window_days`, `temporal_gap_category` and `is_ground_truth=False`. A transition label means the change happened somewhere in the window; with a `LARGE` window the state on the labelled date is ambiguous. The app shows them as a `RULE-BASED STATUS CANDIDATE`.

### Sentinel-1 radar season context

`s1_context_status` is `SEASON_SUMMARY_AVAILABLE`, `INSUFFICIENT_RADAR_PIXELS` or `NOT_ACQUIRED_FOR_SEASON`. Values are filled only for 2025 rows acquired after the last radar pass (2025-09-28):

* `s1_vh_min_transplant_db`: minimum VH from 25 May to 31 Jul;
* `s1_vh_canopy_db`: mean VH from 15 Aug to 30 Sep;
* `s1_vh_rise_db`: the difference between the two;
* `s1_paddy_signature`: true when the transplanting minimum is below −20 dB and the rise is at least 4 dB.

The provenance columns (`s1_product`, `s1_orbit_pass`, `s1_relative_orbit`, `s1_polarization`, `s1_units`, `s1_passes`, `s1_window`) describe the source: Sentinel-1A RTC gamma0, IW GRDH 1SDV, descending, relative orbit 34, with field means taken in linear power and then converted to dB. These are season summaries, not per-date VV/VH observations.

### Reference labels

The human review packages are `reports/research/label_tool/label_reference_<year>.html` with manifest `reference_package_<year>.json`. Reviewer exports go in `data/real/labels/reference_labels_<year>_<reviewer>.csv`, with these columns:

| Column(s) | Content |
|---|---|
| `package`, `item_id`, `field_id`, `year`, `candidate_date` | Which item was reviewed |
| `reviewer`, `reviewed_at` | Who reviewed it and when |
| `burn_label` | BURNT, NOT_BURNT or UNCLEAR |
| `state_label` | STANDING, HARVESTED, BURNT, SOWN or UNKNOWN |
| `confidence` | HIGH, MEDIUM or LOW |
| `evidence`, `notes` | Evidence checkboxes and free-text notes |
| `label_before_context`, `context_viewed`, `context_viewed_at` | The answer before the reviewer opened ancillary context, and when they opened it |
| `source_images` | Dates of the image chips shown |
| `label_quality`, `label_source` | `B` and `HUMAN_MULTI_DATE_VISUAL_REVIEW` |

`scripts/import_reference_labels.py` validates the exports and reports agreement. It writes consensus labels only where reviewers agree.
