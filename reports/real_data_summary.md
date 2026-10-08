# Real-data acquisition summary

Generated: 2026-10-07T22:36:18.384570+00:00
- District: PASS; source geoBoundaries gbOpen IND ADM2; area: 2633.1 km2.
- Research fields: 243,530; cropland fields >50% WorldCover class-40 fraction: 469.
- WorldCover: PASS; ESA WorldCover class 40 cropland; district clipped.
- Sentinel-2 scenes and field rows by season: `{"2023": {"catalog_scenes": 30, "field_observations": 7802, "processed_field_scenes": 16}, "2024": {"catalog_scenes": 27, "field_observations": 7480, "processed_field_scenes": 16}, "2025": {"catalog_scenes": 42, "field_observations": 10927, "processed_field_scenes": 22}, "2026": {"catalog_scenes": 7, "field_observations": 2487, "processed_field_scenes": 5}}`.
- Index validation: `{"NDVI": true, "NBR": true, "BAIS2": true}`; feature rows/columns: 28,696/166; temporal rows/columns: 28,696/166.
- Scientific processing gates: common 20 m grid=PASS; BOA offset harmonised=PASS; BAIS2 artefacts withheld=PASS; weather availability consistent=PASS; fire-context coverage flags=PASS; weak-label evidence windows=PASS; complete observation quality=PASS; season-local temporal features=PASS; weather never after image time=PASS.
- Artifact provenance: PASS `{"OK": 27}` (SHA-256 integrity only, not a signature); unfetched LFS objects: none.
- Model status: NO_MODEL; independent field-status ground truth and valid real-world performance metrics are unavailable.
- Sentinel-2 field sample: 520 fields with real field-date reductions (selected from the full research polygon set).
- Weather hourly reanalysis rows: 268,560; coverage: 2023-09-15 00:00:00+00:00 to 2026-10-07 23:00:00+00:00.
- FIRMS/UMD: real_downloaded (6417 Muktsar Sep-Dec detections; archive coverage 2023-01-01..2024-12-31; 2025-09-01..2025-12-31; 2026-09-30..2026-10-07; joined to field rows as 1 km/30 d proximity context; uncovered windows are null, not zero); MODIS burn: real_downloaded (8977 burned pixels in 19 monthly tile observations; product months 2023-09-01..2023-12-31; 2024-09-01..2024-12-31; 2025-09-01..2025-12-31); Sentinel-1: real_remote_processed (327 catalogued scenes; 16,974 per-date field VV/VH observations from 34 passes (DESCENDING orbit 34)).
- Weak labels (rule proxies, not ground truth): `{"HARVESTED": 1397, "SOWN": 153, "STANDING": 8194, "UNKNOWN": 18952}`; showcase real fields: 82; preview assets: 5.
- Application real-data mode: PASS via `DATA_MODE=real`; existing DEMO_MODE remains available.
- Working-copy disk usage of data/real: 11.1051 GB; excluded bulk data is listed in DATASET_MANIFEST.json (details in `reports/real_data_disk_usage.json`).
- Synthetic contamination: PASS; no synthetic/demo marker values in real Parquet tables.
- Unavailable/failed sources: none.
- Research field polygons are model-derived and not cadastral; weather is coarse reanalysis; weak labels are not ground truth.
