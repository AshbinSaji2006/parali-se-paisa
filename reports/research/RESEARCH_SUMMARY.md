# Parali Se Paisa: real-data research results

**Sri Muktsar Sahib, Punjab · Sentinel-2 field time series for 2023–2026 · VIIRS/MODIS active fires · ERA5**

Every number below comes from public satellite data processed by code in this repository (`scripts/run_research.py`). Methods, thresholds and limitations are in [docs/RESEARCH_METHODS.md](../../docs/RESEARCH_METHODS.md). Burn outcomes are rule-derived Sentinel-2 candidates. Human validation labels are being collected with the stratified labelling tool, and precision will be reported from them.

## What we built

- **Dense time series for the whole district.** 74 Sentinel-2 acquisitions were cut to one 20 m grid and reduced to field means for **170,623 fields** (Fields of The World boundaries). That gives **12.6 million field-date observations** across four seasons, against 3,640 in the previous version of this project.
- **Harvest-aware, smoke-robust event detection.** For every field it dates the harvest and any burn, with the uncertainty interval of each date.
- **Field-level matching with satellite fire alerts.** Burns are matched against VIIRS S-NPP, NOAA-20, NOAA-21 and MODIS for 2023, 2024 and 2025, using proximity controls.
- **A burn-risk model evaluated on an unseen season** (train 2024, test 2025), and a **season-replay digital twin** that compares baler dispatch policies on the real 2025 season.
- **A live 2026 nowcast** from this week's imagery, plus a weekly straw-supply forecast.

## Headline results

| # | Finding | Evidence |
|---|---|---|
| 1 | **VIIRS fire alerts over Muktsar fell 79% from 2023 to 2025 (2,792 → 600), but the char-confirmed burn-scar area did not fall (7,883 → 7,930 ha; loose tier 21,121 → 20,150 ha).** One VIIRS alert stood for 2.3 burned fields in 2023 and 11.9 in 2025. | `f1_alerts_vs_scars.png`, harmonised 5-day revisit |
| 2 | **Only 8% of char-confirmed burns in 2025 had any VIIRS alert within 500 m during their ≤5-day burn window,** against 34% in 2023. Unburned control fields matched 4% and 20%, so these are upper bounds. Roughly 9 in 10 confirmed field burns in 2025 went unseen by the fire satellites. This independently supports iFOREST's finding that over 90% of large Punjab fires now occur after 3 PM, after the satellites pass. | `f2_blind_spot.png` |
| 3 | **Smoke blinds optical monitoring when it matters.** From 29 Oct to 28 Nov 2023, at the burning peak, only 4–33% of fields were clear in the blue band. The SWIR-based detector kept 63–100% observable. | `f3_smoke_blindness.png` |
| 4 | **A naive dNBR mistakes the paddy harvest for a fire.** A pre/post dNBR above 0.27 flags 97.9% of crop fields. Harvest-aware detection scores only post-harvest char. | `f4_naive_vs_aware.png` |
| 5 | **The intervention window is about two weeks.** The median time from first harvested observation to first char observation is 15 days in 2023 and 2025. In 2025, 11% of burns came within 5 days of the harvest being observed, leaving a dispatcher at most one revisit to act; this is why pre-season booking matters. Only 0.5% burned before the harvest could be observed at all. | `f5_intervention_window.png` |
| 6 | **Burning persists and clusters.** A field that burned in 2024 burned again in 2025 30.0% of the time, against 11.8% otherwise (2.5×). Ranking 2025 fields by 2024 history alone, the top decile was **2.3–2.7× more likely to burn** than average on the held-out season. Pre-season AUC is 0.65–0.67; the in-season model reaches 0.67–0.69. The skill is modest and honest. | `results.json → risk_model` |
| 6b | **A small group of repeat burners does a third of the burning.** Across 2023–2025, 4.6% of fields burned in two or more seasons, and they account for 34% of all field-season burns. Fields burning in all three seasons are 7.3× more common than if burning were independent between years. Field size barely matters (10–14% across size quintiles). | `results.json → persistence` |
| 7 | **The same fleet pre-empts more burns when dispatched by risk.** With 100 balers, risk ranking pre-empts **11.4%** of observed 2025 burns, against **4.3%** for first-harvested-first-served (2.6×). With 400 balers the figures are 27.6% and 16.3%. An oracle reaches 39.7% with 100 balers, which shows what better prediction is worth. | `f6_replay.png` |
| 7b | **For dispatch, predicting early beats predicting precisely.** A dynamic hazard model re-scored at every pass predicts next-pass burns on the unseen 2025 season (AUC 0.6936, median per-pass lift 2.06×), and recent neighbour burns are its strongest signal (contagion). Yet it pre-empts only 8.3% of burns with 100 balers, against 11.4% for the history ranking, because contagion warns too late for a capacity-limited fleet. | `results.json → dynamic_hazard`, `f6_replay.png` |
| 8 | **Climate and air quality.** The 2,498 ha pre-empted by 100 risk-ranked balers ≈ **1,859 t CO₂e** (CH₄ + N₂O; 90% range 328–4,849), **85 t PM2.5**, 4.4 t black carbon and ₹1.39 crore of straw. Each 1,000 ha of burning ≈ 741 t CO₂e and 34 t PM2.5. | Andreae (2019) emission factors; IPCC AR6 GWP100 |
| 9 | **Live 2026 season, as of 3 Oct 2026:** 0.7% of 182,853 ha of crop fields are harvested (1.1%, 0.9% and 1.6% on the same date in 2023–2025). Harvest is expected to peak 17–30 Oct, with about 51,000 ha in the week of 24 Oct. The district holds about 11.5 lakh t of straw, consistent with the published 12.1 lakh t estimate. | `f7_nowcast_2026.png` |

## Why it matters

The official indicator, the count of active-fire alerts, is falling much faster than burning itself. Burning has moved to times the satellites do not observe, and its smoke hides it from optical sensors. Policy built on fire counts therefore overstates success, and fines or incentives tied to those counts miss most fields.

Parali Se Paisa measures what actually happened on every field from its burn scar. It ranks fields by burn risk before harvest, so balers can be booked in advance, and it is designed to pay for straw rather than penalise.

## What is not yet shown

- **Precision of the burn tiers.** The stratified human labels are pending. An AI-assisted visual check of 10 strict detections per year found char in about 7–8 of 10.
- **Missed burns.** Small or quickly tilled burns between revisits are missed, so burn counts are lower bounds.
- **2024 is incomplete,** because smog removed 3–21 Nov.
- **Crop type is not separated.** The cotton-growing south is not yet masked out.
- **The replay assumes** that a baled field is not burned, and ignores farmer acceptance and travel time.

## References

- iFOREST (Dec 2025). *Stubble Burning Status Report 2025*: over 90% of large Punjab fires after 3 PM in 2024–25 (3% in 2021); Sentinel-2 burnt area down 25–35% while fire counts fell more than 95%.
- NASA Earth Observatory (15 Dec 2025). *New timing for stubble burning in India*: the fire peak moved from about 1:30 PM (2020) to about 5 PM (2024).
- Walker, K. et al. (2022). *Detecting crop burning in India using satellite data*. arXiv:2209.10148: Sentinel-2 random forest, 82% accuracy against Punjab ground truth.
- Andreae, M. O. (2019). *Atmos. Chem. Phys.* 19, 8523–8546.
- Olofsson, P. et al. (2014). *Remote Sens. Environ.* 148, 42–57.
