# Research methods: field-level burn census, fire-alert blind spot, risk and season replay

This document describes how every number in `reports/research/results.json` and on the app's **Research Evidence** page is produced. All inputs are real, public data. No result uses synthetic records.

## 1. Study area and units

- **District:** Sri Muktsar Sahib, Punjab (geoBoundaries ADM2, 2,633 km²).
- **Field units:** 243,530 Fields of The World (FTW) model-derived polygons (Kerner et al., 2024). They are research boundaries, not cadastral parcels. FTW polygons overlap: their stated areas sum to 345,202 ha in a 263,312 ha district. All areas here therefore come from **non-overlapping 20 m pixels**: each pixel belongs to exactly one field. 170,623 fields have at least 3 pixels and are analysed. Crop fields are those with a clear-sky peak NDVI ≥ 0.60, about 165,000 per season, totalling about 187,000 ha.
- **Seasons:** 1 Sep–20 Dec of 2023, 2024 and 2025, plus 1 Sep–3 Oct 2026 for the live season.

## 2. Data

| Source | Use | Access |
|---|---|---|
| Sentinel-2 L2A, tile 43RDP (contains the whole district) | 74 acquisitions (2023: 20, 2024: 19, 2025: 26, 2026: 9), ≤90% tile cloud | Microsoft Planetary Computer STAC, no account |
| VIIRS 375 m active fires (S-NPP, NOAA-20; NOAA-21 in 2025) and MODIS C6.1 | Thermal fire alerts | NASA FIRMS yearly country CSVs (2023–24); UMD fire archive monthly VNP14IMGML / VJ114IMGML / VJ214IMGML / MCD14ML (2025); FIRMS 7-day NRT (2026) |
| MODIS MCD64A1 C6.1 burned area | Coarse burned-area comparison | Planetary Computer |
| ERA5 reanalysis (Open-Meteo) | Rain days in the replay | Open-Meteo |

**Reflectance harmonisation (a bug fix).** Since processing baseline 04.00 (25 January 2022), Sentinel-2 L2A digital numbers carry `BOA_ADD_OFFSET = −1000`, so reflectance = (DN − 1000) / 10000. Planetary Computer serves the original DN. Every 2023–2026 item used here has baseline ≥ 05.00. The project's earlier real-data pipeline divided by 10000 without the offset. That raised every reflectance by about 0.10 and compressed NDVI: for healthy paddy on 4 Oct 2023 it gave 0.55 instead of 0.80. `scripts/download_s2_stack.py` and the patched `scripts/process_real_sentinel2.py` (version `grid-aligned-20m-v3-boa-offset`) both apply the offset per item and record the baseline.

## 3. Processing

1. **District stacks** (`scripts/download_s2_stack.py`): every acquisition is cropped to one fixed EPSG:32643 20 m grid (2,800 × 4,298 pixels). The 10 m bands are averaged to 20 m and all 10 reflective bands plus SCL are stored as int16. The 20 m grid aligns exactly with the native Sentinel-2 grid, so nothing is resampled across a sub-pixel shift.
2. **Field time series** (`scripts/extract_field_timeseries.py`): all fields are rasterised once on the same grid. For every date it records the per-field mean of each band over usable pixels, counts of usable, cloud and SCL-2 pixels, and two pixel-level fractions:
   - **char_frac:** pixels with B8A < 0.12, B12 < 0.14 and NBR < 0
   - **green_frac:** pixels with NDVI > 0.5

   SCL classes 2 (dark area), 4, 5, 6 and 7 count as usable. Fresh char is very dark, so a 4/5/6-only mask risks discarding the very signal being sought. In practice Sen2Cor labelled char as bare soil (class 5).
3. **Smoke-robust usability.** Sen2Cor does not flag smoke haze. In 2023, blue reflectance stayed at 0.11–0.13 from 29 Oct to 28 Nov, exactly the peak burning weeks, and a clear-sky rule (B02 < 0.10) would have discarded 87–96% of fields on those dates (`f3_smoke_blindness.png`). Smoke scatters strongly at 490 nm but little at 2.2 µm, so the event logic uses only NIR (B8A) and SWIR (B11, B12). A field-date is **usable** when at least 60% of its pixels are usable and its blue reflectance is below 0.20, which drops only opaque smoke (for example 7 Nov 2024, when the median B02 was 0.265). NDVI from clear dates (B02 < 0.10) is used only for the crop peak.

## 4. Harvest-aware event detection (`src/research/events.py`)

- **Harvest:** the first usable observation with NBR < 0.30 after the running NBR maximum has reached 0.50. On clear 2025 dates this agrees with NDVI < 0.40 for 91% of observations.
- **Burn candidate (loose tier):** at or after harvest, an observation where the field turns char-dark relative to the previous usable observation, or where at least 25% of its pixels are char-like:
  - darkness: B8A < 0.15, B12 < 0.17 and NBR < 0.03
  - drop: B8A falls by more than 0.06, B12 by more than 0.03 and NBR by more than 0.08
- **Strict tier (char-like signature; an unverified rule candidate, not a confirmation):** darker char (B8A < 0.12, B12 < 0.14, NBR < 0) together with the drop, or at least 40% char-like pixels.
- **Wet-soil rejection:** irrigated or rained-on soil darkens SWIR more than NIR, so its NBR stays positive and is rejected. After the 20–21 Nov 2025 rain the whole landscape was dark in true colour, yet it was not flagged.
- **Event dating:** events are interval-censored between the last usable observation before the event and the first one after. Both bounds are stored (`last_green_date`/`harvest_date`, `burn_prev_date`/`burn_date`). The median interval is 5 days.
- **Revisit harmonisation:** 2025 had three Sentinel-2 satellites. For cross-year comparisons every season is thinned to one acquisition per 5-day slot before detection (`census_and_blindspot` in `scripts/run_research.py`).

**Why harvest-aware?** Paddy harvest alone moves NBR from about 0.67 to about 0.1. A naive pre-season vs post-season dNBR, using the Key and Benson (2006) "moderate severity" threshold of 0.27, therefore flags 97.9% of Muktsar's crop fields in 2023 (184,801 ha) (`f4_naive_vs_aware.png`). MODIS MCD64A1 sums to about 90,400 ha (4,209 burned 463 m pixels × nominal pixel area). The harvest-aware detector gives 7,883 ha (strict) and 21,121 ha (loose).

## 5. Thermal comparison (`src/research/firms_match.py`)

- Only VIIRS vegetation-fire detections (`type = 0`) inside the district, Sep–Dec, are used. S-NPP + NOAA-20 are used in every year for comparability. NOAA-21 (2025 only) is reported separately.
- **Blind spot:** for every strict burn field with a burn interval of 5 days or less, check whether any VIIRS detection lies within 500 m of the field centroid between `burn_prev_date − 1 day` and `burn_date + 1 day`.
- **Proximity control:** 20,000 random harvested, unburned fields are given burn intervals sampled from the burned fields, and the same match is computed. Spatially clustered burning makes this control non-zero, so the burned-field match rate is an **upper bound** on the share of burns with their own fire alert.
- **Thermal-anchored recall:** for each VIIRS detection, check for a loose burn field within 500 m whose interval brackets the detection date.
- **Sensitivity:** radii of 375 / 500 / 750 / 1,000 m and tolerances of 0 / 1 / 2 days were tested. The ordering of years and the gap between burned and control fields hold at every setting.

## 6. Burn-risk model (`src/research/risk.py`)

- **Unit:** a harvested crop field in one season. **Outcome:** a loose burn candidate later that season, a rule label rather than ground truth.
- **Pre-season model:** logistic regression on two features known before harvest:
  - whether the field burned last season
  - the burn rate of its 1.5 km block (3 × 3 cells of 500 m) last season
- **In-season model:** monotone gradient boosting that also adds harvest timing, harvest progress in the block, burns already observed in the block, field size and peak NDVI.
- **Evaluation:** trained on 2024 with 2023 history and tested on the unseen 2025 season with 2024 history. Metrics are ROC-AUC, average precision, precision in the top 10% and lift. The scores are relative ranks, not probabilities.

**Persistence profile** (`persistence_profile()` in `scripts/run_research.py`): 159,836 fields are crop fields in all three seasons. Their observed counts of seasons burned (loose tier) are compared with the counts expected if each season were independent. 4.6% burned in at least two seasons, against 2.5% expected.

### 6b. Dynamic hazard (`src/research/hazard.py`)

This model re-scores every harvested, unburned field at each Sentinel-2 pass, using only information available at that pass:
- days since harvest
- burn history
- the share of block crop fields whose burn was observed in the last 10 days, in 1.5 km and 4.5 km blocks (contagion)
- the share of block fields with straw on the ground
- field size and peak NDVI
- ERA5 rain over the previous 3 days and the next 5 days (the next-5-day rain stands in for a forecast)

The label is a burn first observed at the next pass. Day-of-year is excluded because it hurts transfer between seasons whose timing shifts.

Trained on the 2024 panel (918,972 field-passes) and tested on the 2025 panel (1,274,902), it reaches AUC 0.6936 with a median per-pass top-10% lift of 2.06×. Removing the recent-neighbour-burn features costs the most (AUC 0.6253).

## 7. Season-replay digital twin (`src/research/replay.py`)

- Each 2025 crop field becomes collectable on the day its harvest is first observed, and stays collectable for 20 days or until it burns.
- Each baler serves one service zone (area-weighted k-means of field centroids) at 4 ha/day, about 10 acres/day.
- Days with district ERA5 rain above 2 mm are skipped because wet straw cannot be baled.
- A burn counts as pre-empted only if the field is baled on or before its last observation still unburned, which is conservative.
- **Policies compared:** random, first-harvested-first-served, risk-ranked (pre-season model), dynamic hazard re-scored at each pass, and an oracle that knows the burn dates.
- **Early beats precise.** With 100 balers the dynamic hazard pre-empts 8.3% of burns against 11.4% for the pre-season ranking. A contagion signal arrives only days before a burn, while history flags would-burn fields from the day of harvest, and capacity-limited dispatch needs that lead time.
- **Assumptions:** baling prevents burning, and travel within a zone is not routed. The operational app routes daily plans with OR-Tools; the replay compares policies and does not forecast impact.

## 8. Emissions (`emissions()` in `scripts/run_research.py`)

Burned dry matter = area × straw load × dry-matter fraction × combustion factor. A Monte Carlo of 20,000 draws samples:
- straw load: U(5.0, 7.5) t/ha, around the Punjab average of 6.3 t/ha
- dry-matter fraction: U(0.80, 0.90)
- combustion factor: U(0.70, 0.90); the IPCC default for crop residue is 0.80
- emission factors: normal draws from Andreae (2019), Table 1, "Agricultural residues (open)", in g/kg dry matter: CO₂ 1430 ± 230, CH₄ 5.7 ± 6.0, N₂O 0.09 ± 0.04, CO 76 ± 55, PM2.5 8.2 ± 4.4, BC 0.42 ± 0.28, OC 4.9 ± 3.6

CO₂e counts only CH₄ (GWP100 27.0, non-fossil) and N₂O (273), following IPCC AR6 WG1 Table 7.15. Biogenic CO₂ is reported separately and not counted as a net emission. Per 1,000 ha burned the medians are 741 t CO₂e (90% range 132–1,941), 34 t PM2.5 and 1.8 t black carbon.

## 9. Live 2026 nowcast

- **Harvest share:** the share of 2026 crop fields with an observed harvest is compared with the same day of year in 2023–2025.
- **Weekly harvest forecast:** district crop area × the weekly increment of the 2023–2025 mean harvest-progress curve. The min/max years give the range. Baleable straw uses 3.3 t/ha (12–15 quintal of bales per acre) and total straw uses 6.27 t/ha.
- **Pre-season risk:** the 2026 ranking applies the history model, retrained on 2024 history → 2025 outcomes, to 2025 history.

## 9b. Exploratory: Sentinel-1 radar paddy mask (inconclusive, not used)

The aim was to separate paddy from dry-land crops such as cotton, using the flooding at transplanting. `scripts/download_s1_stack.py` downloaded 10 Sentinel-1 RTC passes (relative orbit 34, descending, 31 May–28 Sep 2025, full district coverage) onto the 20 m grid. `scripts/build_paddy_mask.py` computed per-field minimum VH over the transplanting window and the canopy rise.

Both distributions are **unimodal**: minimum VH peaks at −21 to −20.5 dB and the rise at 4.5–5 dB. No threshold separates two populations, and the paddy share moves from 57% to 84% of crop area as the threshold goes from −20 to −18 dB. With a single orbit at 12-day revisit and field-mean backscatter, a defensible paddy/cotton split needs crop-type labels, pixel-level flood detection and denser radar revisit (two orbits, or Sentinel-1C from 2025). The mask is therefore **not** applied anywhere in the results. Outputs are kept in `reports/research/paddy_mask_s1_2025.json` for transparency.

## 10. Validation design

- **Detector labels are not ground truth.** Precision and recall come from **Tier-B human labels**. `scripts/build_label_tool.py` draws a stratified random sample by detector output (strict, loose only, no burn). For 2025 that is 80 fields per stratum; for 2023, 40 per stratum. Each sample field gets before, candidate and after Sentinel-2 chips in true colour and SWIR, with the detector's decision hidden.
- **Estimation:** `scripts/evaluate_visual_labels.py` applies the stratified estimator of Olofsson et al. (2014) to give precision, recall and the district burned-field share with a 95% confidence interval.
- **Independent thermal evidence:** VIIRS-anchored recall, 67% (2023), 53% (2024) and 64% (2025).
- **Preliminary AI visual audit:** a model-assisted look at 10 strict detections per year found visible char in about 8 of 10 (2023) and 7 of 10 (2025). This is not a substitute for human labels.

## 11. Limitations

- **Char is short-lived.** Small, partial or quickly tilled burns between revisits are missed, so field burn counts are lower bounds. VIIRS alerts with no nearby Sentinel-2 burn (33–47%) bound how much is missed.
- **2024 is a lower bound** because opaque smog removed the 3–21 Nov acquisitions.
- **Crop types are mixed.** The south of the district grows cotton, and crop type is not yet separated; a Sentinel-1 flooding-based paddy mask is planned.
- **Boundaries:** FTW boundaries are model-derived.
- **Thermal matching** uses field centroids and a 500 m tolerance.
- **The replay is not an impact forecast.** It assumes baling prevents burning and ignores farmer acceptance and travel.
- **Ethics:** burn tiers are not evidence for penalties, and the platform's purpose is payment for straw. The API restricts field-level research data to officials.

## 12. Reproduce

```powershell
python scripts/download_s2_stack.py          # ~45 min, 74 scenes, ~8 GB
python scripts/extract_field_timeseries.py   # ~5 min
python scripts/run_event_detection.py
python scripts/acquire_fire_archives.py --months 202510 202511 202512
python scripts/build_fire_table.py
python scripts/run_research.py               # ~70 s: results.json, CSVs, figures
python scripts/build_research_maps.py        # overlays for the app
python scripts/build_label_tool.py --year 2025
python scripts/evaluate_visual_labels.py     # after labels are exported
python -m pytest -q tests/test_research.py --basetemp=data/tmp/pytest-research
```

## References

- Andreae, M. O. (2019). Emission of trace gases and aerosols from biomass burning – an updated assessment. *Atmos. Chem. Phys.* 19, 8523–8546.
- iFOREST (2025). *Stubble Burning Status Report 2025*. https://iforest.global/wp-content/uploads/2025/12/StubbleBurning_StatusReport_2025_Website.pdf
- NASA Earth Observatory (15 Dec 2025). New timing for stubble burning in India.
- IPCC (2021). AR6 WG1, Chapter 7, Table 7.15 (GWP100).
- Kerner, H. et al. (2024). Fields of The World: a machine learning benchmark dataset for global agricultural field boundary segmentation. arXiv:2409.16252.
- Key, C. H. & Benson, N. C. (2006). Landscape assessment: the Normalized Burn Ratio. USDA FS RMRS-GTR-164-CD.
- Olofsson, P. et al. (2014). Good practices for estimating area and assessing accuracy of land change. *Remote Sens. Environ.* 148, 42–57.
- Walker, K. et al. (2022). Detecting crop burning in India using satellite data. arXiv:2209.10148.
