# Real field provenance example

Field ID: `FTW-IN-PB-1629045`; source field ID: `1629045`
Field geometry source: Fields of The World / Source Cooperative; research boundary only; not cadastral. Partition URL: https://data.source.coop/ftw/global-data/predictions/vectors/alpha/results-by-admin-conf/admin:country_code=IN/IN_PB.parquet
District geometry source: geoBoundaries gbOpen IND ADM2; area 2633.1 km2; field area 6.477 ha.
Source scene: `S2B_MSIL2A_20230924T053649_R005_T43RDP_20241105T155808`; Sentinel-2 L2A; tile 43RDP; processing baseline 5.1; observation 2023-09-24T05:36:49.024000+00:00; scene cloud metadata 46.665674 %.
Area: 6.477 ha; source URL: https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/S2B_MSIL2A_20230924T053649_R005_T43RDP_20241105T155808
Reflectance = (DN - 1000) x 0.0001 (BOA_ADD_OFFSET applied for processing baseline >= 04.00); all bands on a common 20 m grid (grid-aligned-20m-v5-nd-nonnegative); SCL classes 4,5,6 kept. Field pixel means: B04=0.06163, B06=0.34540, B07=0.46386, B08=0.45306, B8A=0.49815, B12=0.11513
NDVI calculation: (0.45306-0.06163)/(0.45306+0.06163) = 0.76053
NBR calculation: (0.45306-0.11513)/(0.45306+0.11513) = 0.59475
BAIS2 calculation: (1-sqrt(B6*B7*B8A/B4))*((B12-B8A)/sqrt(B12+B8A)+1) = -0.07052
Stored pixel-wise field means: NDVI=0.75679, NBR=0.59328, BAIS2=-0.08522; formula recomputation above uses band means, so nonlinear indices differ slightly. BAIS2 quality flag: OK.
Weather: Open-Meteo ERA5 coarse reanalysis, nearest grid point 4 (4.2 km from the field centroid); last published hour 2023-09-24T05:00:00+00:00 (0.61 h before acquisition); temperature=27.3 deg C, precipitation=0.5 mm, humidity=84.0 %, wind=3.31 m/s; available=True.
FIRMS/UMD active-fire context (real_downloaded; no MAP_KEY was needed for the archives used): 0.0 VIIRS and 0.0 MODIS detections within 1.0 km of the centroid in the 30 days up to acquisition; archive coverage COMPLETE (30.0 d). Proximity context, not attribution.
MCD64A1.061 burned-area context: 0.0 burned 500 m pixels within 500 m of the centroid with burn day in the 30 days before acquisition; product coverage PARTIAL (23.0 d); retrospective product, not knowable at acquisition time.
Sentinel-1 per-date context: pass S1A_IW_GRDH_1SDV_20230915T010013_20230915T010038_050331_060F48_rtc,S1A_IW_GRDH_1SDV_20230915T010038_20230915T010103_050331_060F48_rtc (DESCENDING, relative orbit 34.0, S1A) at 2023-09-15T01:00:13+00:00, 9.19 d before the optical acquisition; VV=-9.99 dB, VH=-15.80 dB, VV-VH=5.80 dB (dB = 10*log10(field-mean linear gamma0); Sentinel-1 RTC gamma0 (radiometrically terrain-corrected), Planetary Computer sentinel-1-rtc, from IW GRDH 1SDV).
Labels are heuristic proxy labels and are not ground truth.
