> **SUPERSEDED — INTERNAL ONLY — NOT FOR JUDGE PRESENTATION OR REVIEWER DISTRIBUTION.** Retained only as historical record. Use [current judge-facing evidence](FINAL_JUDGE_EVIDENCE.md) and [blinded human-review workflow](REVIEWERS_START_HERE.md).

# Burn-candidate tiers, haze handling and event tables: final report

Branch `claude/real-evidence-densification`, working tree only. **Not committed, staged, pushed or merged.**
Rules: `burn-candidate-rules-v2` (`src/research/events.py`). Every burn output is a **RULE-BASED BURN CANDIDATE**, never a confirmed burn and never ground truth. FIRMS/MODIS is thermal context only.

## State on resume

- **Sentinel-2:** all 74 catalogue scenes are local and pass metadata and readability checks: 2023 20/20, 2024 19/19, 2025 26/26, 2026 9/9 (latest 2026-10-03). No partial files; nothing was re-downloaded.
- **Field time series and FIRMS archives:** present. The earlier mixed FIRMS confidence types are now normalised (see "Files changed").
- No background jobs were running.

## 1–4. Scenes, haze, rows, observations

| Season | S2 scenes | Mostly usable | Mostly haze-downgraded | Mostly excluded | Field-time rows | Usable rows | Median usable obs per crop field-season |
|---|---|---|---|---|---|---|---|
| 2023 | 20 | 14 | 6 (29 Oct–28 Nov peak) | 0 | 3,412,460 | 3,134,663 | 18 |
| 2024 | 19 | 14 | 1 | 4 (3 Sep, 28 Sep, 17 Nov cloud; 7 Nov smog) | 3,241,837 | 2,634,840 | 15 |
| 2025 | 26 | 22 | 2 (3 Oct, 28 Oct) | 2 (8 Sep, 12 Dec) | 4,436,198 | 4,042,533 | 24 |
| 2026 | 9 | 9 | 0 | 0 | 1,535,607 | 1,434,521 | 9 (season in progress) |

- **Haze metric:** field-mean B02 surface reflectance.
- **Thresholds:** CLEAR < 0.10 ≤ HAZE_DOWNGRADED < 0.20 ≤ THICK_SMOKE_EXCLUDED; CLOUD_EXCLUDED when fewer than 60% of field pixels are usable.
- **Handling:** no scene is dropped. Each observation is flagged, and downgraded observations may not serve as the pre-event reference of a strict candidate.
- **Observation counts:**

  | Season | Downgraded | Excluded (smoke / cloud or no data) |
  |---|---|---|
  | 2023 | 812,070 | 3,135 / 274,662 |
  | 2024 | 369,078 | 159,783 / 447,214 |
  | 2025 | 624,074 | 1,328 / 392,337 |

- **Per-scene table:** `reports/research/haze_quality_by_scene.csv`.

## 5–7, 10. Candidates and event table (full revisit, crop fields)

| Season | Crop fields | STRICT_BURN_CANDIDATE | LOOSE_BURN_CANDIDATE (loose only) | Any burn candidate | HARVESTED_NO_BURN_CANDIDATE | No harvest observed | Strict blocked only by a hazy pre-event image | Event-table rows |
|---|---|---|---|---|---|---|---|---|
| 2023 | 164,625 | 530 (0.32%) | 16,518 | 17,048 (10.36%) | 142,121 | 5,456 | 13,631 | 159,169 |
| 2024 | 163,815 | 796 (0.49%) | 8,061 | 8,857 (5.41%) | 148,250 | 6,708 | 3,949 | 157,107 |
| 2025 | 165,384 | 2,015 (1.22%) | 18,449 | 20,464 (12.37%) | 139,770 | 5,150 | 10,212 | 160,234 |
| 2026 | 158,635 | 0 | 0 | 0 | 1,059 | 157,576 | 0 | 1,059 |

Total event-table rows: **477,569**, in `data/real/derived/research/burn_candidate_events_<year>.parquet` (64 columns). The schema and wording are covered by tests.

**Why the strict tier is small and not a trend.** It requires a CLEAR pre-event image, a dNBR of at least 0.10 with a char signature, and a post-event image that stays low. Smoke at the burning peak removes most clear references, so the strict count follows each season's smoke conditions. **Strict counts are not compared across seasons**; only the loose tier is used as a cross-season series.

## 8. Thermal context (VIIRS S-NPP + NOAA-20 within 500 m, ±1 day of the evidence window; not validation)

| Season | VIIRS in district | Strict candidates with VIIRS nearby (control) | Strict ≤5-day windows (n) | Loose candidates with VIIRS nearby (control) | VIIRS with an optical candidate nearby |
|---|---|---|---|---|---|
| 2023 | 2,792 | 43.96% (25.64%) | 40.2% (351) | 37.63% (25.92%) | 67.3% (loose) / 7.2% (strict) |
| 2024 | 1,527 | 33.29% (25.11%) | 7.1% (140) | 18.57% (13.66%) | 53.1% / 15.5% |
| 2025 (secondary, UMD archive) | 604 | 8.88% (4.23%) | 8.8% (1,965) | 7.03% (3.72%) | 65.1% / 22.7% |

Sensitivity at 375 m and 1,000 m is in `reports/research/burn_candidate_summary.json`, and the ordering holds at every setting.

**Coverage limits:**
- Overpasses come at about 13:30 and 01:30 local time, so fires lit later in the day are missed (iFOREST: over 90% after 3 PM in 2024–25).
- Smoke, cloud and small or short fires also go undetected.
- VIIRS pixels are 375 m and the match uses field centroids.
- Archives: 2023–24 FIRMS yearly SP, 2025 UMD Sep–Dec, 2026 NRT only 30 Sep–7 Oct. Uncovered windows have null counts, and partial windows are flagged.

## 11. Areas (non-overlapping 20 m pixels; polygon areas never summed)

- **Polygons:** 243,530 in total. Their overlapping polygon area sums to 345,202 ha in a 263,312 ha district. 170,623 polygons have at least 3 pixels; 44,593 have none.
- **Non-overlapping area of all fields:** 193,403 ha.

| Season | Crop pixel area | Strict candidate area | Any-candidate area (share) | Any-candidate polygon area (overlapping, for contrast only) |
|---|---|---|---|---|
| 2023 | 187,293 ha | 649 ha | 21,121 ha (11.28%) | 29,326 ha |
| 2024 | 186,778 ha | 1,022 ha | 10,566 ha (5.66%) | 14,632 ha |
| 2025 | 187,906 ha | 2,269 ha | 22,941 ha (12.21%) | 31,616 ha |

At the harmonised 5-day revisit (the cross-season basis):
- **Loose candidates:** 21,121 → 10,566 → 20,150 ha (10.4% / 5.4% / 10.9% of crop fields).
- **Strict candidates:** 649 / 1,022 / 2,531 ha, not comparable across seasons.

No official paddy-area statistic is cited in the project, and **no official-area match is claimed**. The 12.1 lakh t straw figure (The Tribune, concept-note ref. 11) is a news-reported tonnage, not an official statistic or an area.

## 12–13. Human review package

`reports/research/label_tool/label_reference_<year>.html` (package `reference-v2`):

- **Size:** 240 items for 2025 and 120 for 2023 (360 in total), 80 or 40 per stratum. The strata are STRICT / LOOSE / HARVESTED_NO_BURN candidates. Population sizes: 2025 1,449 / 13,124 / 94,730; 2023 392 / 12,120 / 96,090.
- **Labels:** BURNED / NOT_BURNED / UNCERTAIN.
- **Captured:** reviewer, timestamp, field state, confidence, evidence, notes and `source_dates`.
- **Blinding:** nothing is pre-selected; context unlocks only after the first decision; no stratum or tier appears in the page (verified by test and headless browser).
- **Human labels completed: 0** (`reports/reference_label_status.json` → `NO_HUMAN_LABELS`). No model was trained.

## 8 (scientific check). Revised numbers versus the preliminary ~11%

The earlier ~11% figure (2025) was the loose tier.

- **Loose tier (2025, full revisit):** 12.37% of crop fields and 12.21% of non-overlapping crop area; 10.9% at the 5-day harmonised revisit.
- **Strict tier:** falls from 5.4% (v1 rule) to **1.22%**, after requiring a clear pre-event reference and post-event consistency.
- **All of these are rule-based burn candidates.** Their precision is unmeasured until human labels exist.

**Statements now invalid**, to be revised before any rebuild or pitch:
- `README.md:29` and `reports/research/RESEARCH_SUMMARY.md:19`: "strict-tier burn-scar candidate area did not fall (7,883 → 7,930 ha)". Under v2 the strict area is 649 → 2,531 ha and not comparable. The loose area does hold (21,121 → 20,150 ha, −5%), but it is exploratory.
- `scripts/build_pitch_deck.py:195` and `:318`, and `docs/PITCH_AND_DEMO_GUIDE.md:21`: "Burn scars did not [fall] / burn scars unchanged". This must be reworded to the loose, exploratory tier. **The deck was not rebuilt**, so the existing PPTX/PDF still shows v1 numbers.
- **Still supported:** "9 in 10 strict candidates in 2025 raised no fire alert" (8.8% with VIIRS nearby, control 4.2%). The 2025 VIIRS count is now 604 (it was 600 before Sep 2025 was added).
- `scripts/build_pitch_deck.py:273`: "published estimate: 12.1 lakh t" should read "reported by The Tribune (not an official statistic)".

## 14. Tests and validators

- **Python:** 251 passed, 1 skipped (opt-in Earth Engine), 0 failed. New tests cover:
  - haze classes and the scene roll-up
  - a hazy pre-event image blocking the strict tier
  - one-date dips staying loose
  - event-table schema and wording, with no "confirmed burn"
  - null fire counts without archive coverage
  - reproducible field extraction that keeps dark SCL
  - the label vocabulary, blinding and export fields
  - rejection of legacy labels
- **Real-data validators:** 22/22 PASS. These cover no synthetic contamination, temporal causality (weather never after image time; radar join never uses a future pass), real/demo isolation, BOA offset, provenance hashes, fire-coverage flags and app real mode.
- **Frontend:** TypeScript pass, 12/12 tests, production build pass.

## 15. Files changed in this resumption

**New:**
- `src/research/event_table.py`
- `scripts/build_burn_candidate_events.py`
- `reports/research/burn_candidate_summary.json`
- `reports/research/haze_quality_by_scene.csv`
- `data/real/derived/research/burn_candidate_events_{2023..2026}.parquet`
- `reports/research/label_tool/chips_{2023,2025}.json`. **This internal chip store contains detector strata and must not be given to reviewers.**

**Modified:**
- **Rules and pipeline:** `src/research/events.py` (v2 tiers and haze flag), `scripts/run_research.py` (honest F1/F2), `scripts/build_fire_table.py` (typed FIRMS confidence: raw value, low/nominal/high class, MODIS %), `frontend/src/pages/research.tsx` (tile wording).
- **Label tooling:** `scripts/build_label_tool.py`, `scripts/build_reference_label_package.py`, `scripts/reference_label_template.html`, `scripts/import_reference_labels.py`, `scripts/evaluate_visual_labels.py`.
- **Docs and tests:** `docs/RESEARCH_METHODS.md`, `tests/test_research.py`, `tests/test_reference_labels.py`.
- **Regenerated outputs:** events, research results and figures, overlays, real snapshot, showcase (now 82 fields, 7 burn-like multi-signal), reports.

**Still on disk:**
- the legacy `label_burns_{2023,2025}.html` (v1 strata in the page source; superseded; must not be used for review)
- the uncommitted densification work from the previous resumption

**Git:** 0 staged. All `.tif` stacks are ignored by `.gitignore`.

## 16. Remaining scientific limitations

- **No human labels.** Precision and recall of both tiers are unknown; loose figures especially are upper-bound-like.
- **Lower bound on burns.** Char-based detection misses burns tilled before the next clear image.
- **Strict tier depends on haze**, so it cannot be compared across seasons.
- **Thermal comparison is centroid-based context**, limited by overpass times; it is not accuracy.
- **Crop types are not separated** (the cotton belt in the south). The S1 paddy mask was inconclusive.
- **2024 lost 3–21 Nov to smog** and cloud.
- **2026 is early season**: 0.7% harvested as of 3 Oct.
- **Boundaries:** Fields of The World boundaries are model-derived.

## 17. Judge-demo readiness of real-data mode

**Ready for a carefully worded demo.** Real mode passes all validators. It is read-only and withholds burn scores and eligibility. The Research Evidence page now shows only rule-candidate wording and the loose-tier trend.

**Not ready as-is:** the pitch narrative and the existing deck still contain the invalidated strict-area claim (section 8). Those must be revised and the deck rebuilt before presenting.
