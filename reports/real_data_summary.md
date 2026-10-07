# Real-data acquisition summary

Generated: 2026-10-07T15:10:38.695377+00:00
- District: PASS; source geoBoundaries gbOpen IND ADM2; area: 2633.1 km2.
- Research fields: 243,530; cropland fields >50% WorldCover class-40 fraction: 469.
- WorldCover: PASS; ESA WorldCover class 40 cropland; district clipped.
- Sentinel-2 scenes and field rows by season: `{"2023": {"catalog_scenes": 30, "field_observations": 1040, "processed_field_scenes": 2}, "2024": {"catalog_scenes": 27, "field_observations": 1040, "processed_field_scenes": 2}, "2025": {"catalog_scenes": 42, "field_observations": 1040, "processed_field_scenes": 2}, "2026": {"catalog_scenes": 7, "field_observations": 520, "processed_field_scenes": 1}}`.
- Index validation: `{"NDVI": true, "NBR": true, "BAIS2": true}`; feature rows/columns: 3,640/107; temporal rows/columns: 3,640/107.
- Scientific processing gates: common 20 m grid=FAIL; complete observation quality=PASS; season-local temporal features=PASS; weather never after image time=PASS.
- Model status: NO_MODEL; independent field-status ground truth and valid real-world performance metrics are unavailable.
- Sentinel-2 field sample: 520 fields with real field-date reductions (selected from the full research polygon set).
- Weather hourly reanalysis rows: 80,208; coverage: 2023-09-15 00:00:00+00:00 to 2026-10-02 23:00:00+00:00.
- FIRMS: real_downloaded (6410 detections); MODIS burn: real_downloaded (7264 burned pixels in 14 monthly tile observations); Sentinel-1: real_remote_processed (327 scenes; 0 field observations).
- Weak labels: `{"HARVESTED": 933, "STANDING": 5, "UNKNOWN": 2702}`; showcase real fields: 100; preview assets: 5.
- Application real-data mode: PASS via `DATA_MODE=real`; existing DEMO_MODE remains available.
- Disk usage: 10.1701 GB (details in `reports/real_data_disk_usage.json`).
- Synthetic contamination: PASS; no synthetic/demo marker values in real Parquet tables.
- Unavailable/failed sources: none.
- Research field polygons are model-derived and not cadastral; weather is coarse reanalysis; weak labels are not ground truth.
