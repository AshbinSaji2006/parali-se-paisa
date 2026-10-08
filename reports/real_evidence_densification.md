# Real evidence densification and reference labelling: block report

Branch `claude/real-evidence-densification` (from `claude/real-data-hardening`; PR #1 is not merged). Date: 2026-10-07.

## Execution environment and what it allowed

This block ran in the remote Claude Code container, not on the machine that acquired the data.

* **`git lfs pull` succeeded.** All six LFS objects are now real Parquet: the 243,530-polygon field boundaries, the Sentinel-1 2025 VH season summary, and the hazard/risk panels.
* **Excluded bulk data is not present.** That covers the raw Sentinel-2 and Sentinel-1 GeoTIFF stacks, `field_timeseries_*.parquet`, the raw FIRMS CSVs and the geoBoundaries cache.
* **The egress policy denies every data provider.** Planetary Computer (and its Azure blob storage), source.coop, Open-Meteo and NASA FIRMS all return 403. Earth Engine answers, but no credentials are configured (`EE_PROJECT` and `GOOGLE_APPLICATION_CREDENTIALS` are empty).

So nothing new could be observed. All work below uses data committed to or stored in the repository.

## Done

| Task | Result |
|---|---|
| 3. Sentinel-1 | **Partial.** Real field-level Sentinel-1 context is now joined to features and the snapshot: a VH season summary from `paddy_mask_s1_2025.parquet`, covering 518 of 520 fields and 1,036 field-date rows of 2025 (4 rows lack enough radar pixels). Source: S1A IW GRDH 1SDV RTC gamma0, descending, relative orbit 34, 10 passes 2025-05-31..09-28. Field means were taken in linear power and converted to dB, never divided. The summary is attached only after the last pass, so the join is causal. **No per-date VV/VH observations exist.** |
| 6. Reference labels | `label_reference_2023.html` (120 field-seasons) and `label_reference_2025.html` (240) reuse the real Sentinel-2 true-colour/SWIR chips already embedded in the label tool, unchanged. Each item has before, candidate and after dates with the field outline. A blind stratified design is kept: the detector stratum and burn tiers never reach the interface. Reviewers record name, timestamp, burn decision, field state (STANDING / HARVESTED / BURNT / SOWN / UNKNOWN), confidence, evidence checkboxes, notes and source image dates. Ancillary context opens only after a first decision, and the pre-context answer is exported: dense-series dates, FIRMS 1 km/30 d, MCD64A1, and S1 VH. `scripts/import_reference_labels.py` validates exports against `reference_package_<year>.json`, keeps every reviewer, reports agreement and Cohen's kappa, and writes consensus labels in the format read by `scripts/evaluate_visual_labels.py`. **Human-reviewed labels: 0** (`reports/reference_label_status.json` → `NO_HUMAN_LABELS`). |
| 7. Showcase | Ranked across all 520 observed fields using real polygons (`field_context_source = FIELDS_OF_THE_WORLD_PARQUET`) and selected by group quota, 92 fields in all. Pool sizes in brackets: A burn-like with multiple signals 20 (20), B harvest-no-burn 16 (16), C post-harvest green-up 16 (16), D stable standing 20 (338), E ambiguous / system caution 20 (119). Ranking uses observation quality, cloud, fire-window coverage, radar and weather availability. `reports/real_showcase_selection.json` documents it. This is not a burn-risk ranking. |
| 9. App data | Real mode now carries radar season context, a `radar_season_summary` availability flag, the regrouped showcase and coverage metadata. The status method remains RULE-BASED STATUS CANDIDATE; burn score, straw estimates and eligibility remain withheld. |
| 10. Validation | All validator checks pass. The field polygons are now re-validated and no LFS objects are missing. 234 Python tests pass and 1 is skipped (Earth Engine, opt-in). Frontend: typecheck, 12/12 tests and build pass. Demo-mode code is unchanged. |

## Blocked, with exact missing inputs

| Task | Blocker | Needed |
|---|---|---|
| 1–2. Sentinel-2 densification and temporal rebuild | No raw stacks or field time series, and Planetary Computer is denied. The 520 fields keep 7 acquisitions (at most 2 per season). Gaps: 520 at 11–20 d, 1,040 over 45 d, none at 10 d or less. | `data/real/s2_stack/{2023..2026}/*.tif` (74 scenes, about 7.6 GiB) or `data/real/derived/timeseries/field_timeseries_{2023..2026}.parquet` (about 610 MB). Alternatively, network access to `planetarycomputer.microsoft.com` and `*.blob.core.windows.net` to rerun `scripts/process_real_sentinel2.py` (v4) over all catalog scenes. |
| 3. Per-date VV/VH | Raw S1 stack excluded, and Planetary Computer denied. The local stack window (May–Sep 2025) is also mostly pre-harvest: only 2 passes fall in the 15 Sep–15 Dec target. | `data/real/s1_stack/2025/*.tif` plus new RTC acquisitions for Sep–Dec 2023–2026 (`scripts/download_s1_stack.py --start 09-15 --end 12-15`). |
| 4. FIRMS / MCD64A1 gaps | FIRMS and Planetary Computer are denied. | FIRMS Sep 2025 (UMD monthly or FIRMS archive; a MAP_KEY for the API) and the MCD64A1 2025 granules (`modis-64A1-061`, h24v05/h24v06). |
| 5. ERA5 | Open-Meteo denied. | The 6 remaining 0.25° grid points over the district bbox, plus hours after 2026-10-01. |
| 8. Experimental model | 0 human labels. | At least about 30 decided labels per class from at least one reviewer, ideally double-reviewed. |

## Temporal gap distribution (unchanged; no new observations)

| Gap | Transitions |
|---|---|
| 10 days or less | 0 |
| 11–20 days | 520 (33%) |
| 21–30 days | 0 |
| 31–45 days | 0 |
| More than 45 days | 1,040 (67%) |
