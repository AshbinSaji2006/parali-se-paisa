# Real field provenance example

Field ID: `FTW-IN-PB-1629045`; source field ID: `1629045`
Field geometry source: Fields of The World / Source Cooperative; research boundary only; not cadastral. Partition URL: https://data.source.coop/ftw/global-data/predictions/vectors/alpha/results-by-admin-conf/admin:country_code=IN/IN_PB.parquet
District geometry source: geoBoundaries gbOpen IND ADM2; area 2633.1 km2; field area 6.477 ha.
Source scene: `S2B_MSIL2A_20231004T053649_R005_T43RDP_20231004T112155`; Sentinel-2 L2A; tile 43RDP; observation 2023-10-04T05:36:49.024000+00:00; cloud metadata 7e-06.
Area: 6.477 ha; source URL: https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/S2B_MSIL2A_20231004T053649_R005_T43RDP_20231004T112155
Raw provider DN values were scaled by 0.0001 to unit reflectance. Field pixel means: B04=0.05213, B06=0.28350, B07=0.35790, B08=0.37273, B8A=0.38558, B12=0.10703
NDVI calculation: (0.37273-0.05213)/(0.37273+0.05213) = 0.75461
NBR calculation: (0.37273-0.10703)/(0.37273+0.10703) = 0.55383
BAIS2 calculation: (1-sqrt(B6*B7*B8A/B4))*((B12-B8A)/sqrt(B12+B8A)+1) = 0.08062
Stored pixel-wise field means: NDVI=0.73937, NBR=0.54172, BAIS2=0.07325; formula recomputation above uses band means, so nonlinear BAIS2 can differ slightly.
Weather: Open-Meteo ERA5 coarse reanalysis grid 0; temperature=None deg C, precipitation=0.0 mm, humidity=None %, wind=None m/s.
FIRMS context: real_downloaded; no field detection count is available without the FIRMS API credential. MCD64A1.061 was processed; no burn pixel dated on or before this observation was available for field comparison.
Sentinel-1 context: real_remote_processed; catalog scenes exist, but no field-level VV/VH observation is available.
Labels are heuristic proxy labels and are not ground truth.
