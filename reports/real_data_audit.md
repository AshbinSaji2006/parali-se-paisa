> **SUPERSEDED — INTERNAL ONLY — NOT FOR JUDGE PRESENTATION OR REVIEWER DISTRIBUTION.** Retained only as historical record. Use [current judge-facing evidence](research/FINAL_JUDGE_EVIDENCE.md) and [blinded human-review workflow](research/REVIEWERS_START_HERE.md).

# Real-data credibility audit (branch `claude/real-data-hardening`)

Audit date: 2026-10-07. Scope: everything served or reported as REAL DATA. The repository excludes about 9.3 GiB of reproducible raw data by policy (`DATASET_MANIFEST.json`); absent excluded files are not treated as corruption. Six Parquet files are Git LFS objects that this working copy could not fetch. They are reported as missing content, not as data.

## Verdict

The real snapshot uses real public data and is traceable. Every committed source and derived artifact matches its recorded SHA-256 or differs only by CRLF→LF normalisation. The single unfetched LFS boundary file has a pointer oid equal to the recorded hash. The checksum is file integrity only, not a digital signature. The scientific scope is narrow:

* 520 sampled research fields, 7 Sentinel-2 acquisitions, 3,640 field-date rows (2 per season for 2023–2025, 1 for 2026);
* field status comes from a rule-based status candidate built on weak proxy labels; there is no trained or validated model and no ground truth;
* fire products are proximity context, not attribution.

Before this branch, the snapshot also had four correctness defects and one wrong status message. They are fixed below.

## Findings by area

| # | Area | Finding | Evidence | Action |
|---|---|---|---|---|
| 1 | Field boundaries | Fields of The World polygons (CC-BY-4.0), 243,530 kept after a 0.2–15 ha filter; the provider confidence is null, so no confidence filter could be applied. These are model-derived research polygons, not cadastral. | `acquisition_state.json` → `field_boundaries`; the LFS pointer oid `264820cd…` equals the recorded SHA-256 | The builder and validator now detect LFS pointers. The builder falls back to committed derived centroids, cropland fractions and showcase geometry, and records `field_context_source`. |
| 2 | Sentinel-2 | Real L2A items from Planetary Computer, tile 43RDP, processing baselines 05.09–05.13. The BOA −1000 DN offset is applied, all bands use a common 20 m grid, and SCL 4/5/6 is the mask. Smoke haze is not masked by Sen2Cor. | `processing_version = grid-aligned-20m-v3-boa-offset` on all 3,640 rows | The validator checked for `…-v2` and reported a **false FAIL** on the 20 m grid gate. It now accepts v2/v3/v4 and adds a BOA-offset gate. |
| 3 | Sentinel-1 | Catalog only: 327 RTC scene records and 10 stack sidecars (May–Sep 2025, pre-harvest). There are 0 field observations, and every radar temporal feature is null. `paddy_mask_s1_2025.parquet` is an unfetched LFS object. | `sentinel1_scene_catalog.parquet`, `s1_stack/2025/*.json` | No change, because the data needed is absent. Real-mode status now says "CATALOG ONLY". |
| 4 | NDVI | Recomputed from the stored band means: median absolute gap to the pixel mean is 0.002 (max 0.14, from heterogeneous fields). Healthy paddy on 2023-10-04 has a median of 0.80. | recomputation in this audit; `test_reflectance_harmonisation.py` | Verified |
| 5 | NBR | Same check: median gap 0.002, max 0.11; every value is in [−1, 1]. | — | Verified |
| 6 | BAIS2 | One field mean was **−16.32** (FTW-IN-PB-1919038, 2025-10-20) against 0.086 from the band means. A second had a 0.26 gap. The valid mask admits reflectance down to −0.05 and BAIS2 clamped B04 to 1e-8, so one near-zero red pixel dominated the mean. | `BAIS2_pixel_vs_band_mean_abs_diff` | Rows with a gap above 0.25 get `BAIS2_quality = UNSTABLE_PIXEL_ARTEFACT`. Their BAIS2 is withheld from features, and the raw value is kept as `BAIS2_pixel_mean_raw`. The processor now computes BAIS2 only where B04 ≥ 0.005 (`grid-aligned-20m-v4-bais2-red-floor`, which applies to new reductions only). |
| 7 | Weather | Open-Meteo ERA5 at 3 grid points spaced 0.25°, with 26,736 hours each and no gaps. The join is as-of, and rolling rain totals are internally consistent. A field is 1.5–43.8 km from its grid point (median 17 km). The 9 grid points covering the district bbox were not all acquired. **Defect:** all 520 rows dated 2026-10-03 joined a 2026-10-02 hour with null values (ERA5 latency) and were marked `weather_available=True`, with rain totals that treated nulls as zero. | `weather_hourly.parquet` | The as-of join now skips unpublished hours. Those rows now use the last published hour (2026-10-01 23:00, 30.6 h earlier) and are marked unavailable. Added `weather_grid_distance_km`. |
| 8 | FIRMS / MODIS | The data is real: FIRMS yearly archives for 2023–2024, UMD monthly files for Oct–Dec 2025, and NRT 7-day for 2026, with no MAP_KEY needed. There are 6,410 Muktsar Sep–Dec detections, all inside the district polygon, with 0 duplicates. MCD64A1 covers only Oct–Dec 2023 and Sep–Dec 2024. **The data was never joined to fields.** The app said FIRMS "CREDENTIAL REQUIRED", and the provenance report said no count was possible without a credential. The 2025 data is not comparable to 2023–2024: it comes from a different source and includes NOAA-21. | `active_fire_unified.parquet`, `mcd64a1_*.parquet` | New `src/features/fire_context.py` joins causal proximity context (VIIRS/MODIS within 1 km over 30 days; MCD64A1 within 500 m over 30 days, retrospective) with `*_coverage_status` flags. When the window is uncovered the count is null, not 0. Status text corrected. |
| 9 | Feature table | 3,640 rows (now 125 columns). `real_field_features` and `real_temporal_features` are byte-identical duplicates by design. | — | Columns added (see DATA_DICTIONARY). |
| 10 | Temporal features | Season-local and causal, but very sparse. With at most 2 observations per season, rolling-3, slope-3 and delta-2obs are 100% null. 1,040 of 1,560 deltas span LARGE gaps (45 and 60 days). The quality report counted `real_rows = 0` because it only read `fixture_or_real`. | `real_temporal_feature_quality_report.json` | Counter fixed. Density cannot be fixed without the excluded raw stack (see the next block). |
| 11 | Weak labels | 933 HARVESTED, 5 STANDING, 2,702 UNKNOWN; all low confidence and not ground truth. 875 of the 933 HARVESTED labels come from 45- or 60-day windows, so the state on the labelled date is ambiguous. As a consistency check, not validation, against the dense research series: 436 of 437 (2023), 436 of 436 (2024) and 54 of 58 (2025) agree that harvest happened by the label date. Both products are rule-derived from the same sensor. | this audit | Each label now records `evidence_window_start`, `evidence_window_days`, `temporal_gap_category` and `is_ground_truth = False`. LARGE-window reasons state the ambiguity. |
| 12 | Real/synthetic isolation | No synthetic or demo markers in any readable real Parquet. Real mode serves only the snapshot, all writes return 503, and the field ORM list is empty. | `test_real_mode_api_safety.py` | Contamination scan now skips LFS pointers explicitly instead of reporting "cannot read". |
| 13 | Provenance | Source records are complete: STAC item URL, asset hrefs, processing baseline, offset, grid version and SCL classes. The previous provenance example omitted the BOA offset, read non-existent weather columns (printing `None`), and gave the false FIRMS credential claim. | `real_field_provenance_example.md` | Example rewritten from the real joined row. New `scripts/validate_real_data.py` → `reports/real_data_provenance_check.json` covers every recorded artifact. |
| 14 | App REAL mode | Read-only and isolated. Status candidate was always `null` with a non-standard method label, burn context said "no independent fire evidence" although FIRMS had been acquired, and the showcase was 100 arbitrary fields (a tie on the observation count). | `app_snapshot.json` | The method is now `RULE-BASED STATUS CANDIDATE`, with a per-observation candidate in history. The latest status is still `null`, because the single 2026 observation cannot support a transition. Fire-context availability and dense-series season summaries are included. The snapshot is strict JSON (NaN rejected). Showcase fields are ranked by a documented demo-suitability score. Straw, eligibility and burn risk remain withheld. |
| 15 | Showcase | 100 fields with committed geometry, all at least 0.96 cropland. Ranked in `reports/real_showcase_selection.json`: 8 burn-scar candidates with fire-product corroboration, 4 harvested/no-burn candidates with no detections, 1 uncorroborated, 87 other. Only these 100 have geometry in Git, so the pool cannot widen to all 520 until the LFS Parquet is fetched. | — | — |

## Data genuinely missing for the next steps

* `data/real/fields/fields_of_the_world_muktsar.parquet` (LFS, 40.3 MB): needed to re-validate polygons and to widen the showcase.
* `paddy_mask_s1_2025`, `hazard_panel_2024/25` and `risk_features_2024/25` (LFS): research inputs, not used by the app snapshot.
* Raw S2 stacks (`data/real/s2_stack/**/*.tif`, about 7.6 GiB) or the excluded `field_timeseries_*.parquet`: needed to densify the 520-field sample from 7 to about 74 acquisitions. Re-reducing pixel BAIS2 with the v4 red floor also needs the raw stacks or Planetary Computer access.
* MCD64A1 for 2025, the remaining ERA5 grid points over the district, and FIRMS for Sep 2025: needed to remove the PARTIAL/NOT_COVERED windows.
* Independent field-level reference labels (for example from `reports/research/label_tool/`): there are none, so no accuracy can be claimed.

## Follow-up (same branch)

* **Current status candidate.** The latest (2026-10-03) status is now a `RULE-BASED STATUS CANDIDATE` only when two independent reductions of real Sentinel-2 data agree on the same acquisition:
  * the dense harvest-aware series (`timeseries/events_2026.parquet`, 9 acquisitions);
  * the sparse field NDVI.

  For example, STANDING needs no harvest transition through that date, season peak NBR ≥ 0.50 and NDVI ≥ 0.55. Disagreement stays UNKNOWN. Result: all 100 showcase fields are STANDING candidates (`candidate_source = DENSE_S2_SERIES_AND_SPARSE_NDVI_AGREE`). This is consistent with the research nowcast (0.7% of crop fields harvested by 3 Oct 2026). It is still a weak proxy, not ground truth.
* **Research claims re-checked against committed products.** The 2023 and 2024 census reproduces exactly from `field_events_*.parquet` and `firms_muktsar.parquet`: crop fields, strict and loose fields and hectares, and VIIRS S-NPP + NOAA-20 alert counts. The 2025 headline (7,930 ha) uses the 5-day harmonised subset and needs the excluded full time series to reproduce; the all-date value (9,137 ha) reproduces. The summary now states the cross-archive caveat for the 2023→2025 alert comparison.
* **Wording.** "Char-confirmed" and "confirmed burns" implied verification of unvalidated rule candidates. They are renamed to "strict-tier burn(-scar) candidate" in the README, research summary, methods, demo guide, overlay legend, figure, map and deck generators, and four research-page labels. The committed PNG figures and the pitch PDF/PPTX keep their old titles until they are re-rendered with the full data; the figure render needs the LFS `risk_features_2025` and the excluded time series.
* **Network.** This environment's egress policy denies Planetary Computer, source.coop, Open-Meteo, FIRMS and Azure blob hosts. Git LFS content is unreachable from it. Densification, polygon re-validation and coverage-gap filling therefore remain blocked here.
* **Pitch deck.** `Parali_Se_Paisa_Greenovators2026.pptx` was edited in place (8 paragraphs, run formatting kept), and `scripts/build_pitch_deck.py` carries the same strings:
  * "confirmed burns" became strict-tier burn candidates;
  * "verified farmer income" became "helps turn paddy straw into farmer income", because the project does not verify income;
  * "No-burn certificate with QR verification" became "Prototype no-burn certificate with QR metadata check".

  Still stale until a full rebuild:
  * the PDF export, which was made with PowerPoint/Segoe UI and should be re-exported from the PPTX;
  * the embedded figure PNGs (f1, f2, f8 legend);
  * the slide-10 app screenshot.

  The deck generator also needs the git-ignored `.demo/visual-audit` screenshots.
