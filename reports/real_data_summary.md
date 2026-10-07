# Real-data acquisition summary

Generated: 2026-10-07T17:10:21.991237+00:00
- District: PASS; source geoBoundaries gbOpen IND ADM2; area: 2633.1 km2.
- Research fields: 243,530 (from acquisition metadata; LFS Parquet not fetched in this working copy, so polygons were not re-validated); cropland fields >50% WorldCover class-40 fraction: 469.
- WorldCover: PASS; ESA WorldCover class 40 cropland; district clipped.
- Sentinel-2 scenes and field rows by season: `{"2023": {"catalog_scenes": 30, "field_observations": 1040, "processed_field_scenes": 2}, "2024": {"catalog_scenes": 27, "field_observations": 1040, "processed_field_scenes": 2}, "2025": {"catalog_scenes": 42, "field_observations": 1040, "processed_field_scenes": 2}, "2026": {"catalog_scenes": 7, "field_observations": 520, "processed_field_scenes": 1}}`.
- Index validation: `{"NDVI": true, "NBR": true, "BAIS2": true}`; feature rows/columns: 3,640/125; temporal rows/columns: 3,640/125.
- Scientific processing gates: common 20 m grid=PASS; BOA offset harmonised=PASS; BAIS2 artefacts withheld=PASS; weather availability consistent=PASS; fire-context coverage flags=PASS; weak-label evidence windows=PASS; complete observation quality=PASS; season-local temporal features=PASS; weather never after image time=PASS.
- Artifact provenance: PASS `{"EXCLUDED_BY_POLICY": 2, "LFS_POINTER_NOT_FETCHED_OID_MATCH": 1, "OK": 26, "OK_LINE_ENDINGS_NORMALISED": 2}` (SHA-256 integrity only, not a signature); unfetched LFS objects: data/real/fields/fields_of_the_world_muktsar.parquet, data/real/derived/research/paddy_mask_s1_2025.parquet, data/real/derived/timeseries/risk_features_2024.parquet, data/real/derived/timeseries/risk_features_2025.parquet, data/real/derived/timeseries/hazard_panel_2024.parquet, data/real/derived/timeseries/hazard_panel_2025.parquet.
- Model status: NO_MODEL; independent field-status ground truth and valid real-world performance metrics are unavailable.
- Sentinel-2 field sample: 520 fields with real field-date reductions (selected from the full research polygon set).
- Weather hourly reanalysis rows: 80,208; coverage: 2023-09-15 00:00:00+00:00 to 2026-10-02 23:00:00+00:00.
- FIRMS/UMD: real_downloaded (6410 Muktsar Sep-Dec detections; archive coverage 2023-2024 full years, 2025 Oct-Dec only, 2026 NRT 7-day only; joined to field rows as 1 km/30 d proximity context); MODIS burn: real_downloaded (7264 burned pixels in 14 monthly tile observations); Sentinel-1: real_remote_processed (327 scenes; 0 field observations).
- Weak labels (rule proxies, not ground truth): `{"HARVESTED": 933, "STANDING": 5, "UNKNOWN": 2702}`; showcase real fields: 100; preview assets: 5.
- Application real-data mode: PASS via `DATA_MODE=real`; existing DEMO_MODE remains available.
- Working-copy disk usage of data/real: 0.0942 GB; excluded bulk data is listed in DATASET_MANIFEST.json (details in `reports/real_data_disk_usage.json`).
- Synthetic contamination: PASS; no synthetic/demo marker values in real Parquet tables.
- Unavailable/failed sources: none.
- Research field polygons are model-derived and not cadastral; weather is coarse reanalysis; weak labels are not ground truth.
