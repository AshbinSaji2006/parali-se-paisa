# Real field provenance example

Field ID: `FTW-IN-PB-1629045`; source field ID: `1629045`
Field geometry source: Fields of The World / Source Cooperative; research boundary only; not cadastral. Partition URL: https://data.source.coop/ftw/global-data/predictions/vectors/alpha/results-by-admin-conf/admin:country_code=IN/IN_PB.parquet
District geometry source: geoBoundaries gbOpen IND ADM2; area 2633.1 km2; field area 6.477 ha.
Source scene: `S2B_MSIL2A_20231004T053649_R005_T43RDP_20231004T112155`; Sentinel-2 L2A; tile 43RDP; processing baseline 5.09; observation 2023-10-04T05:36:49.024000+00:00; scene cloud metadata 7e-06 %.
Area: 6.477 ha; source URL: https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/S2B_MSIL2A_20231004T053649_R005_T43RDP_20231004T112155
Reflectance = (DN - 1000) x 0.0001 (BOA_ADD_OFFSET applied for processing baseline >= 04.00); all bands on a common 20 m grid (grid-aligned-20m-v3-boa-offset); SCL classes 4,5,6 kept. Field pixel means: B04=0.05213, B06=0.28350, B07=0.35790, B08=0.37273, B8A=0.38558, B12=0.10703
NDVI calculation: (0.37273-0.05213)/(0.37273+0.05213) = 0.75461
NBR calculation: (0.37273-0.10703)/(0.37273+0.10703) = 0.55383
BAIS2 calculation: (1-sqrt(B6*B7*B8A/B4))*((B12-B8A)/sqrt(B12+B8A)+1) = 0.08062
Stored pixel-wise field means: NDVI=0.73937, NBR=0.54172, BAIS2=0.07325; formula recomputation above uses band means, so nonlinear indices differ slightly. BAIS2 quality flag: OK.
Weather: Open-Meteo ERA5 coarse reanalysis, nearest grid point 0 (20.3 km from the field centroid); last published hour 2023-10-04T05:00:00+00:00 (0.61 h before acquisition); temperature=31.9 deg C, precipitation=0.0 mm, humidity=44.0 %, wind=0.92 m/s; available=True.
FIRMS/UMD active-fire context (real_downloaded; no MAP_KEY was needed for the archives used): 0 VIIRS and 0 MODIS detections within 1.0 km of the centroid in the 30 days up to acquisition; archive coverage COMPLETE (30.0 d). Proximity context, not attribution.
MCD64A1.061 burned-area context: 0.0 burned 500 m pixels within 500 m of the centroid with burn day in the 30 days before acquisition; product coverage PARTIAL (3.0 d); retrospective product, not knowable at acquisition time.
Sentinel-1 context: real_remote_processed; catalog scenes exist, but no field-level VV/VH observation is available.
Labels are heuristic proxy labels and are not ground truth.
