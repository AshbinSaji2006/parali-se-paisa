# Parali Se Paisa: real-data research results

**Sri Muktsar Sahib, Punjab · Sentinel-2 field time series for 2023–2026 · VIIRS/MODIS active fires · ERA5**

Every number below comes from public satellite data processed by code in this repository (`scripts/run_research.py`). Methods, thresholds and limitations are in [docs/RESEARCH_METHODS.md](../../docs/RESEARCH_METHODS.md). Burn outcomes are RULE-BASED BURN CANDIDATES from Sentinel-2 (STRICT_BURN_CANDIDATE, LOOSE_BURN_CANDIDATE), not confirmed burns. Human review labels completed: **0**. A blinded 360-item review package is ready, and precision will be estimated only after independent labels are completed. Burn risk is a normalized 0–1 score, not a probability.

## What we built

- **Dense time series for the whole district.** 74 Sentinel-2 acquisitions were cut to one 20 m grid and reduced to field means for **170,623 fields** (Fields of The World boundaries). That gives **12.6 million field-date observations** across four seasons, against 3,640 in the previous version of this project.
- **Harvest-aware, smoke-robust event detection.** For every field it dates the harvest and any burn candidate, with the uncertainty interval of each date.
- **Field-level matching with satellite fire alerts.** Burn candidates are matched against VIIRS S-NPP, NOAA-20, NOAA-21 and MODIS for 2023, 2024 and 2025, using proximity controls.
- **A burn-risk model evaluated on an unseen season** (train 2024, test 2025), and a **season-replay digital twin** that compares baler dispatch policies on the real 2025 season.
- **A live 2026 nowcast** from this week's imagery, plus a weekly straw-supply forecast.

## Headline results

| # | Finding | Evidence |
|---|---|---|
| 1 | **Rule-based burn-candidate area (non-overlapping 20 m pixels).** Loose: 21,121 ha (2023), 10,566 ha (2024), 22,941 ha (2025). Strict: 649, 1,022 and 2,269 ha. Strict is precision-first and is **not** suitable for year-to-year comparison, because haze and cloud change how many clean pre-event images each season has. These are RULE-BASED BURN CANDIDATES, not confirmed burned area, and no official burned-area statistic is implied. VIIRS alerts over Muktsar fell 78% from 2023 to 2025 (2,792 → 604). | `burn_candidate_summary.json`, `f1_alerts_vs_scars.png` (loose tier) |
| 2 | **Optical candidates without a thermal alert.** In 2025, 8.8% of strict optical candidates had a matched VIIRS active-fire detection within 500 m during the defined ≤5-day matching window. About 9 in 10 strict optical burn candidates had no matched VIIRS active-fire detection within the defined matching window. VIIRS is corroborative thermal context, not field-level confirmation, and the candidates are not ground truth. This is consistent with iFOREST's finding that most large Punjab fires now occur after 3 PM. | `burn_candidate_summary.json → thermal_context` |
| 3 | **Haze and cloud limit clear optical observations during the peak period.** From 29 Oct to 28 Nov 2023, at the burning peak, only 4–33% of fields were clear in the blue band. SWIR observations were available for 63–100% of fields; availability does not establish detector accuracy. | `f3_smoke_blindness.png` |
| 4 | **A naive dNBR change rule flags crop harvest transitions.** A pre/post dNBR above 0.27 flags 97.9% of crop fields in this analysis. That is not an independently validated fire label; the research rule evaluates post-harvest char-like change. | `f4_naive_vs_aware.png` |
| 5 | **The intervention window is about two weeks.** The median time from first harvested observation to first char observation is 15 days in 2023 and 2025. In 2025, 11% of burns came within 5 days of the harvest being observed, leaving a dispatcher at most one revisit to act; this is why pre-season booking matters. Only 0.5% burned before the harvest could be observed at all. | `f5_intervention_window.png` |
| 6 | **Rule-based candidates persist and cluster.** A field that burned in 2024 burned again in 2025 30.0% of the time, against 11.8% otherwise (2.5×). Ranking 2025 fields by 2024 history alone, the top decile had a **2.3–2.7× rule-based candidate-rate lift** over average on the held-out season; this is not a probability or human-validated accuracy. Pre-season AUC is 0.65–0.67; the in-season model reaches 0.67–0.69. The skill is modest and honest. | `results.json → risk_model` |
| 6b | **A small group of repeat burners does a third of the burning.** Across 2023–2025, 4.6% of fields burned in two or more seasons, and they account for 34% of all field-season burns. Fields burning in all three seasons are 7.3× more common than if burning were independent between years. Field size barely matters (10–14% across size quintiles). | `results.json → persistence` |
| 7 | **In the season replay, the same fleet reaches more rule-based candidates when dispatched by risk.** With 100 balers, risk ranking reaches **11.4%** of 2025 rule-based candidate events before the candidate date, against **4.3%** for first-harvested-first-served (2.6×). With 400 balers the figures are 27.6% and 16.3%. An oracle reaches 39.7% with 100 balers, which shows what better prediction is worth. | `f6_replay.png` |
| 7b | **In this replay, earlier risk ranking outperforms a dynamic candidate-risk score under a fleet-capacity constraint.** A dynamic hazard model re-scored at every pass ranks next-pass rule-based candidates on the held-out 2025 season (AUC 0.6936, median per-pass lift 2.06×), and recent neighbour burns are its strongest signal (contagion). Yet it reaches 8.3% of candidate events before the candidate date with 100 balers, against 11.4% for the history ranking, because contagion warns too late for a capacity-limited fleet. | `results.json → dynamic_hazard`, `f6_replay.png` |
| 8 | **Scenario estimate: climate and air quality.** The 2,498 ha candidate area reached in the 100-baler risk-ranked replay ≈ **1,859 t CO₂e** (CH₄ + N₂O; 90% range 328–4,849), **85 t PM2.5**, 4.4 t black carbon and ₹1.39 crore of straw. Each 1,000 ha of burning ≈ 741 t CO₂e and 34 t PM2.5. | Andreae (2019) emission factors; IPCC AR6 GWP100 |
| 9 | **Live 2026 season, as of 3 Oct 2026:** 0.7% of 182,853 ha of crop fields are harvested (1.1%, 0.9% and 1.6% on the same date in 2023–2025). Harvest is expected to peak 17–30 Oct, with about 51,000 ha in the week of 24 Oct. Our estimate of district straw is about 11.5 lakh t, close to the 12.1 lakh t reported by The Tribune ("No hike in paddy stubble price by biomass plants", tribuneindia.com). | `f7_nowcast_2026.png` |

## Why it matters

VIIRS active-fire alert counts and optical rule-based candidate areas measure different signals and have different coverage limits. These results do not establish a trend in confirmed burning or a rate of change in actual fires. Timing, smoke, cloud and sensor overpass schedules affect what each source observes.

Parali Se Paisa surfaces rule-based optical burn candidates for human review and provides a normalized risk score to explore pre-season prioritization. Dispatch and payment workflows are prototypes; operational impact and farmer outcomes have not been measured.

## What is not yet shown

- **Precision of the burn tiers.** Human labels completed: 0. The blinded review package (BURNED / NOT_BURNED / UNCERTAIN) is ready; no precision figure is claimed until it is labelled.
- **Unobserved burns.** Small or quickly tilled burns between revisits may not appear in the optical observations; candidate totals are not a complete census.
- **2024 is incomplete,** because smog removed 3–21 Nov.
- **The 2023→2025 VIIRS alert-count comparison crosses archive sources.** 2023–2024 alerts come from FIRMS yearly country archives and 2025 from UMD monthly files. The satellites are like-for-like (S-NPP + NOAA-20; NOAA-21 excluded), but processing streams differ. Candidate areas in row 1 come from `burn_candidate_summary.json` (full revisit, non-overlapping pixels). Strict figures from earlier drafts are superseded and not for presentation.
- **Crop type is not separated.** The cotton-growing south is not yet masked out.
- **The replay assumes** that a baled field is not burned, and ignores farmer acceptance and travel time.

## References

- iFOREST (Dec 2025). *Stubble Burning Status Report 2025*: over 90% of large Punjab fires after 3 PM in 2024–25 (3% in 2021); Sentinel-2 burnt area down 25–35% while fire counts fell more than 95%.
- NASA Earth Observatory (15 Dec 2025). *New timing for stubble burning in India*: the fire peak moved from about 1:30 PM (2020) to about 5 PM (2024).
- Walker, K. et al. (2022). *Detecting crop burning in India using satellite data*. arXiv:2209.10148: Sentinel-2 random forest, 82% accuracy against Punjab ground truth.
- Andreae, M. O. (2019). *Atmos. Chem. Phys.* 19, 8523–8546.
- Olofsson, P. et al. (2014). *Remote Sens. Environ.* 148, 42–57.
