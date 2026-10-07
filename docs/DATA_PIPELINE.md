# Data acquisition foundation (Checkpoint B)

## Configuration and outputs

`config/pilot.yaml` is the source of truth for the pilot AOI, date interval, scene cloud threshold, collection IDs, and cache/output paths. AOI coordinates use `[west, south, east, north]` in EPSG:4326. Dates are inclusive in project configuration; Earth Engine's exclusive end-date filter is advanced by one day. Secrets are read from environment variables and are not stored in YAML.

`python scripts/acquire_data.py` processes only `data/fixtures/demo/` and marks every source as `DEMO`. The fixtures contain synthetic satellite metadata, one synthetic FIRMS point plus a malformed row, and weather timestamps with null measurements. They contain no satellite measurements or weather values. `python scripts/acquire_data.py --online` uses real providers where credentials and network are available. Each source is written separately under `data/interim/acquisitions/`; `reports/acquisition_manifest.json` describes the run, source status, rejected items, warnings, and outputs. A SHA-256 keyed JSON cache avoids repeating an identical request/input. Delete the relevant cache file to force a refresh.

## Sentinel-2

The adapter queries `COPERNICUS/S2_SR_HARMONIZED`, spatially and temporally filters, then applies the configured `CLOUDY_PIXEL_PERCENTAGE` only as a coarse scene prefilter. Before any future field reducer, `mask_s2_clouds` masks SCL classes 3 (cloud shadow), 8/9 (cloud), 10 (cirrus), and 11 (snow/ice), selects B2/B3/B4/B6/B7/B8/B8A/B11/B12, and scales surface reflectance by 0.0001. B6/B7 are required by BAIS2. The adapter retains image ID, UTC acquisition time, cloud percentage, collection, bands, and sensor. Phase B saves acquisition metadata; it does not download rasters or compute field statistics.

## Sentinel-1

The adapter queries `COPERNICUS/S1_GRD` with `instrumentMode=IW` and VV availability. It leaves each image separate and records pass direction, relative orbit, acquisition time, polarization list, and whether VH is present. Do not combine observations across orbit pass or relative orbit without an explicit later compositing policy. Missing VH is represented as `has_vh=false`.

## FIRMS

The CSV adapter accepts NASA FIRMS fields and supplied files, normalizes acquisition date/time to UTC, validates coordinates and required time values, rejects malformed and duplicate rows, and retains confidence, satellite, instrument, FRP, and source. Online requests use the FIRMS area CSV endpoint, configured VIIRS product, pilot bounding box, and date chunks no larger than five days. A MAP_KEY is read from `FIRMS_MAP_KEY`. Detections remain supporting observations and do not create burn labels.

## Weather

The replaceable provider interface currently uses Open-Meteo. Past dates use its Historical Weather API (ERA5 reanalysis); current/future dates use its Forecast API. Rows carry `record_type` (`historical_reanalysis` or `forecast`) and provider source. Temperature, relative humidity, precipitation, and 10 m wind speed are normalized to Celsius, percent, millimetres, and provider units (km/h by Open-Meteo default). Missing values stay null. Requests beyond the available forecast horizon are omitted and reported in warnings.

## Credentials and offline operation

For Earth Engine, install `requirements.txt`, authenticate the local user with `earthengine authenticate`, set `EE_PROJECT` to a registered Earth Engine Cloud project, then run `python scripts/acquire_data.py --online`. A service account can instead set `GOOGLE_APPLICATION_CREDENTIALS` to its local key file and `EE_PROJECT` to its project; never commit that key. For FIRMS, request a MAP_KEY from NASA and set `FIRMS_MAP_KEY`. Open-Meteo needs no API key. The offline fixture run needs no credentials or network access.

## Limitations

No external service was contacted by the offline pipeline. Checkpoint B online acquisitions are metadata/context ingestion only; they do not download imagery or perform field-level raster reduction. Checkpoint C now joins controlled observations into a feature table, but no real field-level observation inputs exist yet. Earth Engine auth, network, FIRMS MAP_KEY, provider terms/limits, and actual pilot boundary quality must be resolved/checked before interpreting real observations.

## Checkpoint C: field-time features

`python scripts/build_features.py` reads the cleaned EPSG:4326 field polygons and the normalized observation-bundle schema. The committed `data/fixtures/demo/feature_observations.json` is synthetic raw-value input only. `aggregate_s2_observation` is the common feature function for either controlled pixel arrays (fixture or tiled/reducer input) or a server-side field-statistics bundle. For raw Sentinel-2 DN input, `value_scale=0.0001` is applied before indices or band means; cloud/invalid pixels are excluded. Stats are population standard deviation (ddof=0). Undefined index math remains null.

The formulas are NDVI=(B8-B4)/(B8+B4), NBR=(B8A-B12)/(B8A+B12), and BAIS2=(1-sqrt(B6*B7*B8A/B4))*((B12-B8A)/sqrt(B12+B8A)). The BAIS2 equation is Filipponi (2018), [BAIS2: Burned Area Index for Sentinel-2](https://www.mdpi.com/2504-3900/2/7/364). B4/B6/B7/B8A/B12 are unit reflectance at formula time; using raw integer DNs in the term that adds 1 would change the index. Negative radicands and zero denominators produce null rather than a fabricated index.

Sentinel-1 VV/VH input is in dB. VV/VH is never calculated by dividing dB values. Per-pixel powers are converted using 10^(dB/10), and the ratio is mean linear VV power divided by mean linear VH power. VH missing yields null VH-derived features and a flag. Each output row selects one latest compatible IW/VV S1 observation for that same field, at or before the Sentinel-2 timestamp and no older than the configured lookback; orbit/pass metadata is preserved and acquisitions are not composited.

FIRMS distances use a local azimuthal-equidistant projection centered on each field. Counts use only detections at/before the reference time. Recent-fire flags mean any detection within 1 km during `(t-24h,t]` or `(t-72h,t]`; these remain evidence, never a status label. Weather sums use timestamped preceding-hour precipitation in the corresponding `(t-window,t]`; latest available temperature/humidity/wind within the 72-hour window are retained. Forecast weather is eligible only if its issuance time was already known at the row timestamp, and weather timestamps after the reference are always excluded.

Quality rules are explicit in code: `POOR` means zero valid optical pixels; `LIMITED` means an input is missing, VH is absent, valid optical fraction is below 0.5, or cloud fraction is above 0.5; otherwise `GOOD`. Flags expose each limiting condition. Poor rows remain in the output. No status labels are generated. The feature quality report counts missing values, sensor availability, fixture/real rows, and quality categories.

The feature input fixture schema allows `fixture_type: real` as well as `synthetic`; the feature functions and output schema are shared. However, Checkpoint B currently has no real field-level pixel/reducer observations, so current output and tests are synthetic and live compatibility remains unverified. A real observation adapter must deliver the documented `pixels` or `field_statistics` values before a real feature table can be built.

Scientific limitations: these controlled vectors are not representative labeled crop measurements; BAIS2 is a spectral index and does not confirm a burn; FIRMS detections can be absent or spatially offset and are not ground truth; the demo polygons intentionally overlap; and future real field reducers must define a consistent scale/resampling policy for Sentinel-2 bands with 10 m and 20 m native resolutions. No classifier or status label is produced.

## Checkpoint D: temporal feature engineering

Run `python scripts/build_temporal_features.py` after the Checkpoint C build. It reads `field_features.csv`, validates the C schema, sorts observations in UTC within `field_id + season + year`, and writes `data/processed/features/field_features_temporal.csv`. The C CSV is not modified. The temporal table contains the C columns plus derived features and `feature_schema_version` (currently `1.0`). Paths and thresholds live under `features.temporal` in `config/pilot.yaml`; repeated runs are deterministic apart from the report generation timestamp.

Lags and changes use prior eligible observations only. A row is eligible for later history when it is not `POOR` and has positive `valid_pixel_count`; `LIMITED` rows are retained. Missing measurements stay null and are not imputed. The current observation is included in rolling means and standard deviations. Windows require all 2 or 3 valid metric observations, respectively. Slopes are OLS index units per elapsed day over the latest three valid values. Peak NDVI is the maximum through the current observation; the drop is signed as `current - peak`, and the fractional drop is `(current - peak) / abs(peak)`.

Exact same-group timestamp duplicates are retained and flagged. Rows in a duplicate timestamp block use only strictly earlier time blocks; the next timestamp sees duplicate rows in stable source-image-ID order and the report contains a warning. Radar history requires an earlier Sentinel-1 acquisition and a matching non-null instrument mode; pass direction and relative orbit must also match when both values are present. Unavailable compatible radar history results in null radar changes and a false availability flag. Gap categories use configurable moderate and large thresholds (defaults 14 and 30 days).

Temporal history resets for every field, season, and year. The appending-future test compares every temporal output on prefix rows before and after later observations are appended. Checkpoint C's feature construction already applies as-of constraints to Sentinel-1, FIRMS, and weather; Checkpoint D does not reconstruct raw event histories. It therefore does not create FIRMS 7/14-day event counts or weather rolling/dry-day histories from C's lossy as-of summaries. Existing causal FIRMS/weather summaries remain in the base columns. These are synthetic-only offline fixtures; there are no real observations or labels.

## Block 2: data audit and intelligence interfaces

`config/feature_schema.yaml` freezes all 129 temporal output columns, groups, types, nullability, units, provenance, and explicit training/inference permission. Its `training_features` list is an allowlist; identifiers, image IDs, quality metadata not selected for modeling, fixture indicators, free text, processing versions, and labels cannot silently enter model matrices. Run `python scripts/validate_ml_dataset.py` to validate the integrated A–D outputs and write `reports/ml_dataset_audit.json` / `.md`. It also materializes the labelled training contract at `data/processed/ml/field_status_dataset.csv`; identifiers, features, labels, and provenance have explicit separate roles. `python scripts/import_field_labels.py` validates a source CSV before appending it to `data/processed/labels/status_labels.csv`.

Status labels require field/time, one of STANDING/HARVESTED/BURNT/SOWN, source, confidence, reviewer, notes, created-at time, and tier A/B/C/S. Synthetic labels must be source `SYNTHETIC_TEST` and tier S; normal training excludes them and tier C proxy labels. The Random Forest and scikit-learn GradientBoostingClassifier pipelines use field-grouped train/validation/test splits. The latter substitutes for unavailable LightGBM. `--synthetic-smoke` tests training and serialization only; stored artifacts are trust-tagged and normal inference rejects them.

The intelligence service runs a transparent `RULE-BASED STATUS CANDIDATE` only when no model is supplied. The straw interface uses a configurable 6 t/ha area baseline, optional bounded peak-NDVI adjustment, and scenario uncertainty range; it requires a sufficiently credible HARVESTED candidate. The burn engine returns a configurable, normalized weighted rule score with availability flags and reasons. It is not a calibrated probability. A supervised architecture targets burn within three days but cannot train without reviewed retrospective outcomes. Forecasts remain separately represented and are eligible only with known-at-observation issuance. No dispatch optimization, buyer matching, certificate workflow, app, or deployment is part of this block.

Optional facility-distance context is accepted by the risk engine, and `src/data/facilities.py` validates DEMO/REAL facility CSVs and calculates nearest baler/buyer distances. The checked-in demo CSV is schema-only and contains no invented businesses. Type and source provenance are retained in risk output.
