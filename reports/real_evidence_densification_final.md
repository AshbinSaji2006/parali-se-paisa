> **SUPERSEDED — INTERNAL ONLY — NOT FOR JUDGE PRESENTATION OR REVIEWER DISTRIBUTION.** Retained only as historical record. Use [current judge-facing evidence](research/FINAL_JUDGE_EVIDENCE.md) and [blinded human-review workflow](research/REVIEWERS_START_HERE.md).

# Real evidence densification: local completion and before/after report

Branch `claude/real-evidence-densification`, working tree only. **Nothing is committed, staged or pushed.** Completed locally on 2026-10-08 (IST), resuming the interrupted local session that followed the remote, network-blocked block in [real_evidence_densification.md](real_evidence_densification.md).

"Before" is the committed `HEAD` (11012e0). "After" is the current working tree.

## 1. State found on resume

The interrupted session had already finished the inputs listed below. Nothing was reset, restored, stashed or cleaned.

| Input | State on resume | Verification |
|---|---|---|
| Sentinel-2 (local harmonised stacks, 520 sampled fields) | Reduced (v4), 59 scenes | All scene IDs match local stack sidecars |
| Sentinel-1 RTC, relative orbit 34 descending | 34 passes downloaded and reduced | **Complete against the live Planetary Computer catalogue**: 2023 8/8, 2024 8/8, 2025 16/16, 2026 2/2 days. The partial passes 2024-11-20 and 2024-12-14 (38% coverage) are single-slice in the catalogue itself, not failed downloads. All 34 raster SHA-256 values match the rows. |
| FIRMS / UMD | Sep 2025 monthly VIIRS (S-NPP, NOAA-20, NOAA-21) and MODIS added | 16 UMD monthly files, Sep–Dec 2025 |
| MCD64A1 | 2025 product months added (UMD Win18), and Sep 2023 | 19 monthly tile items covering Sep–Dec of 2023, 2024 and 2025 |
| ERA5 (Open-Meteo) | 10 grid nodes | Re-probed at 00:53 IST: ERA5 is still published only to **2026-10-01 23:00 UTC**, so nothing further can be acquired yet. Later hours are null. |
| Products and reports | Rebuilt at 00:24–00:28 IST, after every input finished | — |

## 2. Problems found and fixed

1. **Validator false failure ("Synthetic contamination: FAIL").** The scan loaded every column of the multi-million-row local `field_timeseries_*.parquet` files and ran out of memory, so it never actually checked anything. It now reads only the provenance marker columns (`scripts/validate_real_data.py`). The check is unchanged and now passes.
2. **Unphysical NDVI in raw observations, which failed an existing integration test.** One field-date (FTW-IN-PB-6168354, 2025-11-22) had NDVI = 1.012. v4 admits slightly negative post-offset reflectance (> −0.05) as valid, and pixel NDVI with negative red exceeds 1. This is atmospheric over-correction of dark pixels on the 22 Nov 2025 scene. The derived feature row was already withheld (`reflectance_quality = NON_POSITIVE_MEAN_RED`), but the raw observation table kept the value, and `test_worldcover_and_sentinel2_measurements_are_real_and_plausible` failed.
   - **Fix (`grid-aligned-20m-v5-nd-nonnegative`):** a pixel enters the NDVI or NBR mean only when both of its bands are non-negative, matching v4's existing BAIS2 red floor. Band means, pixel counts and BAIS2 are unchanged.
   - **Re-reduced from the local stacks only** (no download). The v4 → v5 diff covers the same 28,696 rows: **120 NDVI and 3 NBR values changed**, almost all from the 22 Nov 2025 scene. 0 band-mean, BAIS2 or pixel-count changes.
   - Unit test added in `tests/test_real_densification.py`. The version allow-lists were updated in the validator and in `tests/integration/test_reflectance_harmonisation.py`.
   - A pre-change copy of the v4 outputs is kept outside the repository, in the session scratchpad `v4_backup/`.

## 3. Before / after

| Measure | Before (HEAD) | After |
|---|---|---|
| Sentinel-2 field observations (520 fields) | 3,640 | **28,696** |
| Sentinel-2 acquisitions used | 7 (2 / 2 / 2 / 1) | **59** (16 / 16 / 22 / 5 for 2023 / 24 / 25 / 26) |
| Median observations per field-season | 2 | **15** |
| Revisit gaps ≤ 10 d / 11–20 d / 21–45 d / > 45 d | 0 / 520 / 520 / 520 | **26,037** / 579 / 0 / 0 |
| Sentinel-2 processing version | v3 (BOA offset) | v5 (BOA offset, BAIS2 red floor, non-negative normalized differences) |
| Sentinel-1 per-date field VV/VH rows | 0 | **16,974** (34 passes, S1A + S1D, orbit 34 descending) |
| Feature rows with a causal S1 pass (≤ 12 d before) | 0 | **27,990** (706 rows have no pass within 12 d, so the radar columns are null) |
| Feature rows × columns | 3,640 × 138 | 28,696 × 166 |
| ERA5 grid nodes / hourly rows | 3 / 80,208 | **10** / 268,560 |
| ERA5 last published hour | 2026-10-01 23:00 UTC | 2026-10-01 23:00 UTC (latency; later hours null) |
| District VIIRS + MODIS detections, Sep–Dec 2025 | 1,146 | 1,153 (Sep 2025 added) |
| MCD64A1 product years | 2023, 2024 | 2023, 2024, **2025** |
| MCD64A1 burned-pixel records | 7,264 | 8,977 |
| Weak proxy labels | UNKNOWN 2,702 · HARVESTED 933 · STANDING 5 | UNKNOWN 18,952 · STANDING 8,194 · HARVESTED 1,397 · SOWN 153 |
| Real-mode snapshot fields / observations | 92 / 3,640 | 100 / 28,696 |

## 4. Scientific consistency (independent checks on the final products)

- **Sentinel-1:** dB is computed once from field-mean linear power; VV−VH (dB) equals 10·log10 of the linear ratio for every row; there are no zero or non-finite values; all 34 raster hashes match. In the radar join, **no row uses a future pass**, the maximum age is 11.2 days, and rows without a pass carry no values.
- **Sentinel-2:**
  - NDVI and NBR now lie within [−1, 1].
  - Standing paddy on 2023-10-04 has a median NDVI of 0.803, a check on the BOA offset.
  - Every scene ID resolves to a local stack sidecar.
- **Weather:**
  - No weather value is taken after the image time.
  - Unpublished ERA5 hours stay null and are never zero.
  - Rolling and daily values need complete windows.
- **Fire context:**
  - `NOT_COVERED` rows have null detection counts (1,967 rows).
  - `PARTIAL` rows record their covered days (2,598 rows).
  - Zero counts appear only inside covered windows.
- **Labels and models:**
  - The weak labels are 100% `REAL_S2_HEURISTIC_PROXY` and `WEAK`, with `is_ground_truth` false everywhere.
  - Model state is `NO_MODEL`, and no model was trained: 0 human-reviewed labels exist, and the only model files are the pre-existing synthetic smoke test.
  - In the real-mode snapshot, burn scores are absent (`score_kind = UNAVAILABLE`) and 0 fields are eligible.
- **Demo mode:** no demo-mode code, fixture or launcher is modified.

## 5. Validation results

| Check | Result |
|---|---|
| Real-data validators (`scripts/validate_real_data.py`) | **22/22 checks PASS**, including synthetic contamination, BOA offset, BAIS2 and unphysical-reflectance withholding, weather causality and availability, fire-coverage flags, artifact provenance (27 OK) and app real mode |
| Python tests (complete suite) | **241 passed, 1 skipped** (Earth Engine, opt-in), 0 failed |
| Frontend | TypeScript check pass · **12/12** unit tests · production build pass |

## 6. Remaining gaps (not fillable now; left null)

- **FIRMS 2026-09-15..29:** NRT covers only the last 7 days, and the UMD monthly archive is not yet published. Closing the gap needs a FIRMS `MAP_KEY` (area API).
- **ERA5 after 2026-10-01 23:00 UTC:** publication latency. Rows on 2026-10-03 carry the last published hour (30.6 h earlier), with `weather_available = False` and `weather_status = STALE_OVER_24H`. **Reviewer decision:** keep these flagged values, or null the value columns too.
- **MCD64A1 2026:** not yet published.
- **Sentinel-1 orbit 100 (ascending):** catalogued but deliberately not used. Radar deltas compare only same-orbit, same-pass acquisitions.
- **Human reference labels:** 0. Experimental model training stays blocked until at least about 30 decided labels per class exist.

## 7. Files changed by this resumption

- `scripts/validate_real_data.py`: memory-safe contamination scan; v5 added to the allowed versions.
- `scripts/process_real_sentinel2.py`: v5 normalized-difference guard and docstrings.
- `tests/test_real_densification.py`: new guard test (now 6 tests).
- `tests/integration/test_reflectance_harmonisation.py`: v5 allowed.
- **Regenerated:** Sentinel-2 observations, features, temporal features, weak labels, showcase, app snapshot, acquisition state, manifest and real-data reports.
- `reports/acquisition_manifest.json` and `reports/feature_quality_report.json` changed **only in their timestamps**, because the test suite regenerates these synthetic-pipeline reports. They are left as found.

**Git:** 0 staged files. All 34 Sentinel-1 `.tif` stacks (and the Sentinel-2 stacks) are ignored by `.gitignore` (`data/real/s1_stack/**/*.tif`). The 24 untracked Sentinel-1 JSON sidecars are small provenance files that are meant to be versioned.
