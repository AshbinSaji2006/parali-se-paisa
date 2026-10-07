# Parali se Paisa

**Satellite evidence and logistics tools for higher-value paddy-straw collection.**

Geospatial monitoring and an action-workflow prototype for turning paddy straw into a useful resource. The repository contains both a **read-only real-data snapshot** and a separate synthetic end-to-end operations demo. The full research panel analyzes 170,623 fields across 74 Sentinel-2 acquisitions and 12.6 million field-date rows; the source boundary dataset contains 243,530 retained model-derived research polygons. The app snapshot is deliberately smaller: 520 sampled fields and 3,640 field-date rows across seven acquisitions. It also includes ERA5 reanalysis and coarse MODIS burn context. FIRMS requires a credential, Sentinel-1 has no field observations, and the project has no independent field-status ground truth or trusted operational model.

For the hackathon story, use real mode to show traceable Muktsar satellite observations, then switch to the synthetic demo to show the full collection and buyer workflow. In real mode field eligibility is withheld and operational writes are blocked; demo operations, buyers, balers, outcomes, and generated model smoke metrics are synthetic. Do not present proxy labels as ground truth, a rule candidate as a confirmed state, or a normalized burn score as a probability. See [the real-data summary](reports/real_data_summary.md), [the model card](docs/MODEL_CARD_FIELD_STATUS.md), and [the demo guide](docs/DEMO_GUIDE.md).

## Problem

After paddy harvest, farmers need practical ways to move residue before it is burned. Satellite fire alerts can miss small or short-lived field burns, and a harvest-related spectral change can look like fire if the analysis ignores crop timing. Real buyer demand, baler availability, and farmer outcomes are not yet integrated into this prototype.

## Solution and key features

The project connects field-level satellite time series and fire context to a transparent research view, then demonstrates a separate synthetic workflow for straw collection. It includes harvest-aware burn-scar analysis, a read-only real-data dashboard, risk-prioritized dispatch research, synthetic buyer matching, chronological verification gates, and prototype certificate generation. Real observations and synthetic operations are clearly separated.

## Architecture

Sentinel and weather acquisition feeds Python geospatial processing and research tables. A read-only API snapshot exposes the sampled real observations. A separate FastAPI/SQLAlchemy action API runs deterministic synthetic demo workflows; the React client presents those workflows and their provenance. See [the architecture notes](docs/ARCHITECTURE.md) and [dataset inventory](DATASETS.md).

## Data sources

The analysis uses Sentinel-2 Level-2A, Fields of The World research boundaries, ESA WorldCover, Open-Meteo/ERA5 reanalysis, NASA FIRMS and the University of Maryland fire archive, and MODIS MCD64A1 burned-area context. Sentinel-1 is catalog-only in the current dataset and has no field observations. See [DATASETS.md](DATASETS.md) for provider references, the distribution policy, reproduction steps, and license notes recorded in the project.

## Real-data research results (October 2026)

A dense Sentinel-2 analysis now covers **every field in Sri Muktsar Sahib**: 74 acquisitions from 2023 to 2026, 170,623 Fields of The World polygons and 12.6 million field-date observations. It is matched with VIIRS/MODIS active fires and ERA5. Full results are in [reports/research/RESEARCH_SUMMARY.md](reports/research/RESEARCH_SUMMARY.md) and methods in [docs/RESEARCH_METHODS.md](docs/RESEARCH_METHODS.md). In the app, sign in as an official and open **Research Evidence**.

- **The blind spot.** VIIRS fire alerts over Muktsar fell 79% from 2023 to 2025, while the char-confirmed burn-scar area mapped by Sentinel-2 did not fall (7,883 → 7,930 ha, at a harmonised 5-day revisit). In 2025 only 8% of confirmed field burns had any VIIRS alert within 500 m; the proximity control was 4%.
- **Harvest-aware, smoke-robust detection.** A naive pre/post dNBR flags 98% of crop fields as burnt, because harvest alone triggers it. Smoke haze, which Sen2Cor does not mask, makes 67–96% of fields unusable in clear-sky terms at the burning peak. The detector therefore uses NIR/SWIR change logic and dates every harvest and burn with its uncertainty interval.
- **An intervention window of about 15 days** (median from first harvested observation to first char observation). Burning persists: a field that burned in 2024 burned again in 2025 2.5× as often.
- **Dispatch that pre-empts more burns.** On the unseen 2025 season a history-based ranking gives 2.3–2.7× lift in its top decile. In a season-replay digital twin, risk-ranked dispatch pre-empts 2.6× more burns than first-come-first-served with the same 100 balers: about 1,859 t CO₂e and 85 t PM2.5 avoided.
- **Live 2026 nowcast.** 0.7% of crop fields were harvested on 3 Oct 2026, a typical pace. A weekly straw-supply forecast and a pre-season pre-booking list are produced.

Reproduce with `python scripts/run_research.py` after the data steps listed in the methods document. GPU is not required: the whole analysis runs on a laptop CPU, and the bottleneck is data and labels rather than compute. Burn tiers are rule-derived candidates for prioritising pickups and payments. They are not enforcement evidence, and human validation labels are collected with `reports/research/label_tool/`.

**Data fix.** Sentinel-2 L2A products from processing baseline 04.00 onwards carry a −1000 DN offset. The earlier real-data pipeline omitted it, which inflated reflectance by about 0.10 and compressed NDVI (for healthy paddy, 0.55 instead of 0.80). `scripts/process_real_sentinel2.py` now harmonises it per item (`grid-aligned-20m-v3-boa-offset`).

## Greenovators Hackathon 2026

The brochure schedules project submission for **8 October at 5:00 PM** and team pitches for **9 October, 9:00 AM–12:00 PM**. It calls the hackathon 30 hours, although its printed start and end (7 October 2:00 PM to 8 October 6:00 PM) span 28 hours. A judge is listed for the Remote Sensing–GIS track, so lead with the reproducible satellite-to-field evidence and its limitations; connect it to circular use of paddy straw, and label the buyer/logistics workflow as synthetic. The brochure states broad themes and objectives, but does not give weighted judging criteria.

## Checkpoint A: field setup

Install dependencies with `python -m pip install -r requirements.txt`, configure `config/pilot.yaml`, and provide field polygons at `data/raw/fields/fields.geojson` in EPSG:4326 GeoJSON. Run:

```powershell
python scripts/setup_pilot.py
```

Run the automated suite with `python -m pytest -q`. External Earth Engine checks are opt-in: set `RUN_EXTERNAL_INTEGRATION=1` after authentication to enable the small AOI/date query.

The importer skips invalid features into `reports/field_validation_report.json` and writes valid normalized features to `data/processed/fields/fields_clean.geojson`. Areas are calculated in the configured projected CRS (the pilot uses UTM zone 43N), then output geometries remain EPSG:4326. The committed input is explicitly synthetic demo geometry and is not a real field dataset.

To replace it, preserve the GeoJSON schema and source metadata; each feature must have a unique `field_id` and valid polygon geometry. Imported boundaries are not treated as cadastral truth.

## Checkpoint B: acquisition

Run the fully offline, clearly labelled fixtures with:

```powershell
python scripts/acquire_data.py
```

To use real providers, set credentials from `.env.example` in the process environment and run `python scripts/acquire_data.py --online`. Authenticate Earth Engine first (`earthengine authenticate`, then set `EE_PROJECT`); request a NASA FIRMS MAP_KEY for `FIRMS_MAP_KEY`. Open-Meteo requires no key. Outputs and the run manifest are under `data/interim/acquisitions/` and `reports/acquisition_manifest.json`. Details and limitations are in [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md).

## Checkpoint C: offline feature validation

After the field setup above, build the synthetic test feature table with:

```powershell
python scripts/build_features.py
```

The fixture is explicitly marked synthetic and contains no labels or actual satellite/weather observations. Output is `data/processed/features/field_features.csv`; the quality summary is `reports/feature_quality_report.json`. See [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) for all columns and [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md) for formulas, joins, and limitations.

## Checkpoint D and Block 2 offline tools

Build causal field-season-year temporal features with `python scripts/build_temporal_features.py`. Then run `python scripts/validate_ml_dataset.py` to check the frozen feature schema, dataset integrity, leakage indicators, and label readiness. The training contract is `data/processed/ml/field_status_dataset.csv`; label records are imported using `python scripts/import_field_labels.py labels.csv`.

`python scripts/train_field_status.py` trains only from eligible A/B labels. With the current empty label registry it writes `NO_MODEL`. `python scripts/train_field_status.py --synthetic-smoke` exercises serialization and inference on generated patterns tagged `SYNTHETIC_TEST`; its metrics are pipeline tests only. `python scripts/run_intelligence_demo.py` runs the offline, explicitly synthetic rule-candidate demo. It never loads the synthetic smoke model as a scientific prediction.

Optional facility context uses `data/fixtures/demo/facilities.csv` as a schema-only template. Any populated record must declare `dataset_type` as `DEMO` or `REAL` and its source; output preserves this provenance.

The status rules, straw formula, and burn-risk score are preliminary decision-support interfaces. Read [the field status model card](docs/MODEL_CARD_FIELD_STATUS.md), [straw methodology](docs/STRAW_ESTIMATION.md), and [burn-risk methodology](docs/BURN_RISK_MODEL.md). Real satellite and reanalysis observations are available in the read-only snapshot; independent labels, operational buyer/baler data, and live-provider validation remain unavailable.

## Block 3: offline action platform

Block 3 adds OR-Tools baler routing, capacity-safe buyer matching, chronological post-harvest verification, gated prototype PDF/QR certificates, SQLAlchemy persistence, and a versioned FastAPI. All bundled balers, buyers, the action scenario, and verification demo observations are synthetic fixtures. No live routes, weather forecast, real buyer demand, government certificate, or incentive release is provided.

```powershell
python -m pip install -r requirements.txt
python scripts/seed_demo.py
python scripts/run_dispatch_demo.py
python scripts/run_verification_demo.py
python scripts/run_end_to_end_demo.py
python -m pytest -q
python scripts/serve_api.py
```

The API defaults to SQLite and does not seed on startup. Set `DATABASE_URL` in the environment for PostgreSQL. See [dispatch](docs/DISPATCH_OPTIMISATION.md), [buyer matching](docs/BUYER_MATCHING.md), [verification](docs/NO_BURN_VERIFICATION.md), and [API](docs/API.md) for constraints, evidence limits, and examples. React, public deployment, payments, government branding/integration, and blockchain are outside this block.

## Project structure

- `src/` — FastAPI routes, domain services, feature processing, dispatch, verification, and database migrations.
- `frontend/` — React, TypeScript, Vite, and Vitest application.
- `scripts/` — acquisition, processing, validation, research, demo, and deck-build entry points.
- `data/fixtures/demo/` — small, explicitly synthetic fixtures.
- `data/real/` — acquired and derived geospatial data; large reproducible files stay local and are documented in [DATASETS.md](DATASETS.md) and [DATASET_MANIFEST.json](DATASET_MANIFEST.json).
- `docs/`, `reports/`, `tests/` — methods, model limitations, project reports, pitch materials, and checks.

## Technology stack

Python, FastAPI, SQLAlchemy, GeoPandas, Rasterio, PyArrow, scikit-learn/LightGBM research utilities, OR-Tools, React, TypeScript, Vite, Leaflet, and SQLite (with PostgreSQL configuration). See `requirements.txt`, `requirements-real-data.txt`, and `frontend/package.json` for dependency details.

## Install and run the prototype

From the project root:

```powershell
python -m pip install -r requirements.txt
cd frontend
npm ci
cd ..
python scripts/start_demo.py
```

Open `http://127.0.0.1:5173/`. The demo launcher resets only its isolated `.demo/` database and writes local demo credentials to an ignored file under `.demo/credentials.json`.

### Real-data snapshot mode

Set `DATA_MODE=real` in the process environment, then run the same launcher. In PowerShell:

```powershell
$env:DATA_MODE = 'real'
python scripts/start_demo.py
```

The real snapshot is read-only and shows research observations with weak proxy labels. It has no independently validated field-status ground truth, verified buyer/baler registry, or operational prediction model. Clear the variable before starting the synthetic demo again:

```powershell
Remove-Item Env:DATA_MODE -ErrorAction SilentlyContinue
python scripts/start_demo.py
```

## Data acquisition and regeneration

Use `python scripts/acquire_real_data.py --help` to see supported sources, years, and resume options. Acquisition entry points and dataset status, provider references, licenses recorded by the project, and exact local exclusions are documented in [DATASETS.md](DATASETS.md). The full current-season refresh is `python scripts/update_live_2026.py`; it requires network access and provider availability. It rebuilds research outputs and the pitch deck from the local data plus any newly available acquisitions.

## Tests and frontend checks

```powershell
python -m pytest -q
cd frontend
npm run typecheck
npm test
npm run build
```

Some external-provider checks are opt-in and require their stated credentials. Report skipped checks as skipped; do not interpret synthetic smoke-test metrics as real-world model accuracy.

## Security and environment variables

`.env.example` contains blank placeholders and local defaults. Keep real `.env` files, provider keys, JWT secrets, database credentials, generated account credentials, and browser authentication state out of Git. The demo launcher is for local use; production deployment needs its own secret management, database, HTTPS, and origin configuration. See [security notes](docs/SECURITY.md).

## Limitations and prototype disclaimer

Field boundaries are satellite-derived research polygons, not cadastral truth. The 520-field app sample is not the full research panel. Labels are weak proxies unless a report explicitly identifies independent human validation; this repository currently has no completed visual-label validation. Research replay results are retrospective analyses, not live causal impact estimates. Demo buyers, balers, routes, collection outcomes, and prototype certificates are synthetic; certificates are not government documents, payment approvals, or proof of farmer income. See the [model card](docs/MODEL_CARD_FIELD_STATUS.md), [research methods](docs/RESEARCH_METHODS.md), and [real-data summary](reports/real_data_summary.md).

## Project and event context

This project was developed for Greenovators Hackathon 2026 under the themes of waste-to-wealth, smart and sustainable infrastructure, and net-zero AI. The event brochure lists a pitch and demo, but does not specify a repository, slide, or video upload format. Project code and its pitch materials are supplied as a prototype, not as an endorsed deployment. No project license has been selected; upstream data terms remain separate and are listed in [DATASETS.md](DATASETS.md).
