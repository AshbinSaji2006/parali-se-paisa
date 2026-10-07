"""Local validation and compact final reports for the real-data block."""
from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.provenance import content_available, is_lfs_pointer, verify_tree

REAL = ROOT / "data" / "real"
REPORTS = ROOT / "reports"
STATE = REAL / "acquisition_state.json"
MANIFEST = REAL / "DATASET_MANIFEST.json"
LOG = ROOT / "logs" / "real_data_download.log"
# Processing versions that read every band on the common 20 m B06 grid (v3 also applies
# the processing-baseline >= 04.00 BOA_ADD_OFFSET of -1000 DN).
GRID_ALIGNED_VERSIONS = {"grid-aligned-20m-v2", "grid-aligned-20m-v3-boa-offset", "grid-aligned-20m-v4-bais2-red-floor"}


def bytes_in(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def record(key: str, status: str, provider: str, dataset: str, paths: list[Path], **metadata):
    state = json.loads(STATE.read_text(encoding="utf-8"))
    state["datasets"].setdefault(key, {})
    state["datasets"][key].update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size,
                       "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths if p.is_file()],
        "metadata": metadata})
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(state, indent=2)+"\n", encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = [r for r in manifest.get("datasets", []) if r.get("dataset") != key]
    rows.append({"dataset": key, "source_provider": provider, "source_dataset": dataset,
        "aoi": "Sri Muktsar Sahib, Punjab, India", "status": status, "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "processing_version": "real-acquisition-1.0", "files": state["datasets"][key]["artifacts"], **metadata})
    manifest["datasets"] = rows
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(f"{datetime.now(timezone.utc).isoformat()} {status.upper()} {key} files={len(state['datasets'][key]['artifacts'])}\n")


def contamination_scan(unfetched: list[str] | None = None) -> list[str]:
    errors = []
    for p in REAL.rglob("*.parquet"):
        if is_lfs_pointer(p):
            # Not data and not corruption: content is in Git LFS and was not fetched.
            if unfetched is not None: unfetched.append(p.relative_to(ROOT).as_posix())
            continue
        try:
            pf = pd.read_parquet(p)
            for col in ("real_or_synthetic", "fixture_or_real", "demo_or_real"):
                if col in pf:
                    bad = pf[col].astype(str).str.casefold().isin({"synthetic", "demo", "synthetic_as_real"})
                    if bad.any(): errors.append(f"{p.relative_to(ROOT)} has {int(bad.sum())} prohibited {col} values")
        except Exception as exc:
            errors.append(f"Cannot read {p.relative_to(ROOT)}: {exc}")
    return errors


def build_reports() -> dict:
    REPORTS.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8"))
    status = {k: v.get("status", "pending") for k, v in state.get("datasets", {}).items()}
    boundary_path = REAL / "boundaries" / "sri_muktsar_sahib_adm2.geojson"
    boundary = gpd.read_file(boundary_path) if boundary_path.exists() else None
    fields_path = REAL / "fields" / "fields_of_the_world_muktsar.parquet"
    fields = gpd.read_parquet(fields_path) if content_available(fields_path) else None
    s2path = REAL / "sentinel2" / "catalog.parquet"
    scenes = pd.read_parquet(s2path) if s2path.exists() else pd.DataFrame()
    obs_path = REAL / "derived" / "features" / "sentinel2_field_observations.parquet"
    obs = pd.read_parquet(obs_path) if obs_path.exists() else pd.DataFrame()
    feat_path = REAL / "derived" / "features" / "real_field_features.parquet"
    temporal_path = REAL / "derived" / "features" / "real_temporal_features.parquet"
    labels_path = REAL / "derived" / "labels" / "real_weak_labels.parquet"
    weather_path = REAL / "weather" / "weather_hourly.parquet"
    weather = pd.read_parquet(weather_path) if weather_path.exists() else pd.DataFrame()
    firms = REAL / "firms" / "firms_muktsar.parquet"
    modis = REAL / "burned_area" / "mcd64a1_muktsar.parquet"
    modis_pixels = REAL / "burned_area" / "mcd64a1_burn_pixels.parquet"
    s1 = REAL / "sentinel1" / "sentinel1_scene_catalog.parquet"
    s1_fields = REAL / "sentinel1" / "sentinel1_field_observations.parquet"
    labels = pd.read_parquet(labels_path) if labels_path.exists() else pd.DataFrame()
    showcase_path = REAL / "derived" / "showcase" / "showcase_real_fields.geojson"
    preview_n = len(list((REAL / "derived" / "previews").glob("*.png")))

    unfetched_lfs: list[str] = []
    issues = contamination_scan(unfetched_lfs)

    wcpath = REAL / "landcover" / "worldcover_muktsar.tif"
    wc_ok = False
    if wcpath.exists():
        try:
            with rasterio.open(wcpath) as ds:
                wc_ok = ds.crs is not None and ds.count == 1 and 40 in np.unique(ds.read(1))
        except Exception: pass
    feature = pd.read_parquet(feat_path) if feat_path.exists() else pd.DataFrame()
    temporal = pd.read_parquet(temporal_path) if temporal_path.exists() else pd.DataFrame()
    grid_aligned = bool(not obs.empty and "processing_version" in obs and
                        obs.processing_version.isin(GRID_ALIGNED_VERSIONS).all())
    boa_offset_ok = bool(not obs.empty and {"processing_baseline", "boa_offset_dn"}.issubset(obs.columns) and
                         ((obs.processing_baseline.astype(float) >= 4.0) == obs.boa_offset_dn.astype(float).eq(1000.0)).all())
    bais2_stable = bool(not feature.empty and "BAIS2_quality" in feature and
                        feature.loc[feature.BAIS2_quality.ne("OK"), "BAIS2"].isna().all())
    weather_consistent = bool(not feature.empty and "weather_available" in feature and
                              feature.loc[feature.weather_available.fillna(False).astype(bool), "temperature_2m_c"].notna().all())
    fire_context = bool(not feature.empty and {"firms_coverage_status", "modis_ba_coverage_status"}.issubset(feature.columns) and
                        feature.loc[feature.firms_coverage_status.eq("NOT_COVERED"), "firms_viirs_detections_near_field"].isna().all() and
                        feature.loc[feature.modis_ba_coverage_status.eq("NOT_COVERED"), "modis_ba_burned_pixels_near_field"].isna().all())
    labels_windowed = bool(not labels.empty and "evidence_window_days" in labels and "temporal_gap_category" in labels)
    quality_complete = bool(not feature.empty and "observation_quality" in feature and
                            feature.observation_quality.isin({"GOOD", "LIMITED", "POOR"}).all())
    temporal_causal = True
    if not temporal.empty and {"field_id", "season", "year", "observation_datetime", "previous_observation_datetime"}.issubset(temporal.columns):
        for _, group in temporal.groupby(["field_id", "season", "year"]):
            stamps = pd.to_datetime(group.observation_datetime, utc=True)
            previous = pd.to_datetime(group.previous_observation_datetime, utc=True, errors="coerce")
            if (not stamps.is_monotonic_increasing or
                ((previous.notna()) & (previous >= stamps)).any() or
                (previous.dropna().dt.year != group.loc[previous.notna(), "year"].astype(int)).any()):
                temporal_causal = False
                break
    else:
        temporal_causal = False
    weather_asof = False
    if not feature.empty and {"observation_datetime", "weather_observation_datetime"}.issubset(feature.columns):
        image_time = pd.to_datetime(feature.observation_datetime, utc=True)
        weather_time = pd.to_datetime(feature.weather_observation_datetime, utc=True, errors="coerce")
        weather_asof = bool((weather_time.dropna() <= image_time.loc[weather_time.notna()]).all())
    unique_scenes = scenes.drop_duplicates(["datetime", "tile"]) if not scenes.empty and {"datetime", "tile"}.issubset(scenes.columns) else scenes
    counts = {str(y): {"catalog_scenes": int((unique_scenes.year == int(y)).sum()) if not unique_scenes.empty else 0,
                       "processed_field_scenes": int(obs.loc[obs.year == int(y), "scene_id"].nunique()) if not obs.empty and {"year", "scene_id"}.issubset(obs.columns) else 0,
                       "field_observations": int((obs.year == int(y)).sum()) if not obs.empty and "year" in obs else 0}
              for y in (2023, 2024, 2025, 2026)}
    if not obs.empty and {"NDVI", "NBR", "BAIS2"}.issubset(obs.columns):
        idx_ok = {c: bool(obs[c].notna().any() and obs[c].dropna().between(-1, 1).all()) for c in ("NDVI", "NBR")}
        idx_ok["BAIS2"] = bool(obs.BAIS2.notna().any() and np.isfinite(obs.BAIS2.dropna()).all())
    else: idx_ok = {"NDVI": False, "NBR": False, "BAIS2": False}

    # Checksum finalized source and derived artifact rows at reporting time.
    for key, p, provider, ds in [
        ("real_features", feat_path, "Derived / real-only", "Sentinel-2 + ERA5 real field features"),
        ("temporal_features", temporal_path, "Derived / real-only", "Leakage-safe real observation deltas"),
        ("weak_labels", labels_path, "Derived / real-only", "Low-confidence rule proxy labels"),
        ("showcase_fields", showcase_path, "Derived / real-only", "Observed real research fields")]:
        if p.exists(): record(key, "real_derived", provider, ds, [p], rows=(len(pd.read_parquet(p)) if p.suffix == ".parquet" else len(gpd.read_file(p))))

    app_snapshot_path = REAL / "derived" / "app_snapshot.json"
    if app_snapshot_path.exists():
        record("app_import", "real_derived", "Parali se Paisa API", "Read-only real product snapshot",
               [app_snapshot_path], mode_switch="DATA_MODE=real", ground_truth=False)

    # After derived products are re-recorded, so rebuilt outputs are checked against their new records
    # and acquired source files against the hashes recorded when they were downloaded.
    provenance_check = verify_tree(ROOT)
    (REPORTS / "real_data_provenance_check.json").write_text(json.dumps(provenance_check, indent=2) + "\n", encoding="utf-8")
    disk = {name: bytes_in(REAL / name) for name in ["fields", "landcover", "sentinel2", "weather", "firms", "burned_area", "sentinel1", "derived"]}
    disk["total_real_bytes"] = bytes_in(REAL)
    disk["total_real_gb"] = round(disk["total_real_bytes"] / 1e9, 4)
    (REPORTS / "real_data_disk_usage.json").write_text(json.dumps(disk, indent=2)+"\n", encoding="utf-8")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_md = ["# Real dataset manifest", "", f"Generated: {datetime.now(timezone.utc).isoformat()}", "",
                   "| Dataset | Status | Provider | Files |", "|---|---|---|---|"]
    for d in manifest.get("datasets", []):
        manifest_md.append(f"| {d.get('dataset')} | {d.get('status')} | {d.get('source_provider')} | {len(d.get('files', []))} |")
    (REAL / "DATASET_MANIFEST.md").write_text("\n".join(manifest_md)+"\n", encoding="utf-8")

    # Single field audit uses real band means and independently recomputed indices.
    provenance_path = REPORTS / "real_field_provenance_example.md"
    if not obs.empty:
        r = obs.sort_values("observation_datetime").iloc[0]
        g = fields.loc[fields.field_id == r.field_id].iloc[0] if fields is not None else None
        feature_row = feature.loc[(feature.field_id == r.field_id) & (pd.to_datetime(feature.observation_datetime, utc=True) == pd.to_datetime(r.observation_datetime, utc=True))].iloc[0] if not feature.empty else None
        b4,b6,b7,b8,b8a,b12 = [float(r[f"{b}_mean"]) for b in ("b04","b06","b07","b08","b8a","b12")]
        calc_ndvi=(b8-b4)/(b8+b4) if b8+b4 else np.nan
        calc_nbr=(b8-b12)/(b8+b12) if b8+b12 else np.nan
        calc_bais=(1-np.sqrt(max(b6*b7*b8a/max(b4,1e-8),0)))*((b12-b8a)/np.sqrt(max(b12+b8a,1e-8))+1)
        fr = feature_row if feature_row is not None else pd.Series(dtype=object)
        weather_line = "Weather: unavailable in the joined feature row." if feature_row is None else (
          f"Weather: Open-Meteo ERA5 coarse reanalysis, nearest grid point {fr.get('weather_grid_id')} "
          f"({float(fr.get('weather_grid_distance_km', np.nan)):.1f} km from the field centroid); last published hour "
          f"{fr.get('weather_observation_datetime')} ({float(fr.get('weather_hours_before_observation', np.nan)):.2f} h before acquisition); "
          f"temperature={fr.get('temperature_2m_c')} deg C, precipitation={fr.get('precipitation_mm')} mm, "
          f"humidity={fr.get('relative_humidity_2m_pct')} %, wind={fr.get('wind_speed_10m_ms')} m/s; available={fr.get('weather_available')}.")
        firms_line = ("FIRMS/UMD active-fire context: not joined." if "firms_coverage_status" not in fr else
          f"FIRMS/UMD active-fire context ({status.get('firms')}; no MAP_KEY was needed for the archives used): "
          f"{fr.get('firms_viirs_detections_near_field')} VIIRS and {fr.get('firms_modis_detections_near_field')} MODIS detections within "
          f"{fr.get('firms_radius_km')} km of the centroid in the {fr.get('firms_window_days')} days up to acquisition; archive coverage "
          f"{fr.get('firms_coverage_status')} ({fr.get('firms_window_covered_days')} d). Proximity context, not attribution.")
        modis_line = ("MCD64A1 context: not joined." if "modis_ba_coverage_status" not in fr else
          f"MCD64A1.061 burned-area context: {fr.get('modis_ba_burned_pixels_near_field')} burned 500 m pixels within 500 m of the centroid "
          f"with burn day in the 30 days before acquisition; product coverage {fr.get('modis_ba_coverage_status')} "
          f"({fr.get('modis_ba_window_covered_days')} d); retrospective product, not knowable at acquisition time.")
        source_field_id = g.source_field_id if g is not None else str(r.field_id).rsplit("-", 1)[-1]
        partition = (state.get("datasets", {}).get("field_boundaries", {}).get("metadata", {}) or {}).get("source_partition_url", "unavailable")
        boundary_source = "geoBoundaries gbOpen IND ADM2"
        provenance = ["# Real field provenance example", "", f"Field ID: `{r.field_id}`; source field ID: `{source_field_id}`",
          f"Field geometry source: Fields of The World / Source Cooperative; research boundary only; not cadastral. Partition URL: {g.source_url if g is not None else partition}",
          f"District geometry source: {boundary_source}; area {float(boundary.area_km2_epsg32643.iloc[0]):.1f} km2; field area {float(r.area_ha):.3f} ha.",
          f"Source scene: `{r.scene_id}`; Sentinel-2 L2A; tile {r.tile}; processing baseline {r.get('processing_baseline')}; observation {r.observation_datetime}; scene cloud metadata {r.cloud_cover_pct} %.",
          f"Area: {float(r.area_ha):.3f} ha; source URL: {r.source_item_url}",
          f"Reflectance = (DN - {float(r.get('boa_offset_dn', 0)):.0f}) x {r.reflectance_scale} (BOA_ADD_OFFSET applied for processing baseline >= 04.00); "
          f"all bands on a common 20 m grid ({r.processing_version}); SCL classes {r.scl_valid_classes} kept. "
          f"Field pixel means: B04={b4:.5f}, B06={b6:.5f}, B07={b7:.5f}, B08={b8:.5f}, B8A={b8a:.5f}, B12={b12:.5f}",
          f"NDVI calculation: ({b8:.5f}-{b4:.5f})/({b8:.5f}+{b4:.5f}) = {calc_ndvi:.5f}",
          f"NBR calculation: ({b8:.5f}-{b12:.5f})/({b8:.5f}+{b12:.5f}) = {calc_nbr:.5f}",
          f"BAIS2 calculation: (1-sqrt(B6*B7*B8A/B4))*((B12-B8A)/sqrt(B12+B8A)+1) = {calc_bais:.5f}",
          f"Stored pixel-wise field means: NDVI={float(r.NDVI):.5f}, NBR={float(r.NBR):.5f}, BAIS2={float(r.BAIS2):.5f}; formula recomputation above uses band means, so nonlinear indices differ slightly. "
          f"BAIS2 quality flag: {fr.get('BAIS2_quality', 'unavailable')}.",
          weather_line, firms_line, modis_line,
          f"Sentinel-1 context: {status.get('sentinel1')}; catalog scenes exist, but no field-level VV/VH observation is available.",
          "Labels are heuristic proxy labels and are not ground truth."]
    else: provenance = ["# Real field provenance example", "", "No Sentinel-2 field observation is yet available; provenance audit remains pending."]
    provenance_path.write_text("\n".join(provenance)+"\n", encoding="utf-8")

    label_counts = labels.weak_label.value_counts().to_dict() if not labels.empty else {}
    field_meta = state.get("datasets", {}).get("field_boundaries", {}).get("metadata", {}) or {}
    total_fields = len(fields) if fields is not None else int(field_meta.get("retained_area_filtered_fields", 0))
    fields_note = "" if fields is not None else " (from acquisition metadata; LFS Parquet not fetched in this working copy, so polygons were not re-validated)"
    cropland = int(feature.loc[feature.cropland_fraction.fillna(0) > 0.5, "field_id"].nunique()) if not feature.empty and "cropland_fraction" in feature else 0
    app_mode = bool(app_snapshot_path.exists() and "DATA_MODE" in (ROOT / "src" / "api" / "routes" / "product.py").read_text(encoding="utf-8"))
    current_state = json.loads(STATE.read_text(encoding="utf-8"))
    status = {k: v.get("status", "pending") for k, v in current_state.get("datasets", {}).items()}
    failed = [f"{k}: {v}" for k,v in status.items() if k != "reports" and v in {"download_failed", "provider_unavailable", "credential_required", "pending"}]
    summary = ["# Real-data acquisition summary", "", f"Generated: {datetime.now(timezone.utc).isoformat()}",
      f"- District: {'PASS' if boundary is not None and len(boundary)==1 else 'FAIL'}; source geoBoundaries gbOpen IND ADM2; area: {float(boundary.area_km2_epsg32643.iloc[0]):.1f} km2.",
      f"- Research fields: {total_fields:,}{fields_note}; cropland fields >50% WorldCover class-40 fraction: {cropland:,}.",
      f"- WorldCover: {'PASS' if wc_ok else 'FAIL'}; ESA WorldCover class 40 cropland; district clipped.",
      f"- Sentinel-2 scenes and field rows by season: `{json.dumps(counts, sort_keys=True)}`.",
      f"- Index validation: `{json.dumps(idx_ok)}`; feature rows/columns: {len(feature):,}/{len(feature.columns)}; temporal rows/columns: {len(temporal):,}/{len(temporal.columns)}.",
      f"- Scientific processing gates: common 20 m grid={'PASS' if grid_aligned else 'FAIL'}; BOA offset harmonised={'PASS' if boa_offset_ok else 'FAIL'}; BAIS2 artefacts withheld={'PASS' if bais2_stable else 'FAIL'}; weather availability consistent={'PASS' if weather_consistent else 'FAIL'}; fire-context coverage flags={'PASS' if fire_context else 'FAIL'}; weak-label evidence windows={'PASS' if labels_windowed else 'FAIL'}; complete observation quality={'PASS' if quality_complete else 'FAIL'}; season-local temporal features={'PASS' if temporal_causal else 'FAIL'}; weather never after image time={'PASS' if weather_asof else 'FAIL'}.",
      f"- Artifact provenance: {'PASS' if provenance_check['passed'] else 'FAIL'} `{json.dumps(provenance_check['status_counts'], sort_keys=True)}` (SHA-256 integrity only, not a signature); unfetched LFS objects: {', '.join(unfetched_lfs) if unfetched_lfs else 'none'}.",
      "- Model status: NO_MODEL; independent field-status ground truth and valid real-world performance metrics are unavailable.",
      f"- Sentinel-2 field sample: {obs.field_id.nunique() if not obs.empty else 0} fields with real field-date reductions (selected from the full research polygon set).",
      f"- Weather hourly reanalysis rows: {len(weather):,}; coverage: {weather.timestamp.min() if len(weather) else 'none'} to {weather.timestamp.max() if len(weather) else 'none'}.",
      f"- FIRMS/UMD: {status.get('firms')} ({len(pd.read_parquet(firms)) if firms.exists() else 0} Muktsar Sep-Dec detections; archive coverage 2023-2024 full years, 2025 Oct-Dec only, 2026 NRT 7-day only; joined to field rows as 1 km/30 d proximity context); MODIS burn: {status.get('modis_burned_area')} ({len(pd.read_parquet(modis_pixels)) if modis_pixels.exists() else 0} burned pixels in {len(pd.read_parquet(modis)) if modis.exists() else 0} monthly tile observations); Sentinel-1: {status.get('sentinel1')} ({len(pd.read_parquet(s1)) if s1.exists() else 0} scenes; {len(pd.read_parquet(s1_fields)) if s1_fields.exists() else 0} field observations).",
      f"- Weak labels (rule proxies, not ground truth): `{json.dumps(label_counts, sort_keys=True)}`; showcase real fields: {len(gpd.read_file(showcase_path)) if showcase_path.exists() else 0}; preview assets: {preview_n}.",
      f"- Application real-data mode: {'PASS' if app_mode else 'FAIL'} via `DATA_MODE=real`; existing DEMO_MODE remains available.",
      f"- Working-copy disk usage of data/real: {disk['total_real_gb']:.4f} GB; excluded bulk data is listed in DATASET_MANIFEST.json (details in `reports/real_data_disk_usage.json`).",
      f"- Synthetic contamination: {'FAIL: ' + '; '.join(issues) if issues else 'PASS; no synthetic/demo marker values in real Parquet tables'}.",
      f"- Unavailable/failed sources: {', '.join(failed) if failed else 'none'}.",
      "- Research field polygons are model-derived and not cadastral; weather is coarse reanalysis; weak labels are not ground truth."]
    summary_path = REPORTS / "real_data_summary.md"
    summary_path.write_text("\n".join(summary)+"\n", encoding="utf-8")
    # Simple source-level validation report retained separately from ordinary offline tests.
    checks = {"boundary": boundary is not None and len(boundary)==1,
              "field_count_ge_100": total_fields>=100,
              "worldcover": wc_ok, "sentinel2_observations": not obs.empty,
              "ndvi": idx_ok["NDVI"], "nbr": idx_ok["NBR"], "bais2": idx_ok["BAIS2"],
              "weather": len(weather)>0, "synthetic_contamination": not issues,
              "sentinel2_common_20m_grid": grid_aligned,
              "observation_quality_complete": quality_complete,
              "season_local_causal_temporal_features": temporal_causal,
              "weather_not_after_satellite_time": weather_asof,
              "sentinel2_boa_offset_harmonised": boa_offset_ok,
              "bais2_pixel_artefacts_withheld": bais2_stable,
              "weather_availability_consistent": weather_consistent,
              "fire_context_coverage_flags": fire_context,
              "weak_label_evidence_windows": labels_windowed,
              "artifact_provenance": provenance_check["passed"],
              "field_polygons_revalidated": fields is not None}
    checks["app_real_mode"] = app_mode
    (REPORTS / "real_data_validation.json").write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"checks":checks,"issues":issues,"unfetched_lfs_objects":unfetched_lfs},indent=2)+"\n",encoding="utf-8")
    record("reports", "real_derived", "Local validation", "Real data status reports", [summary_path, provenance_path, REPORTS/"real_data_disk_usage.json", REPORTS/"real_data_validation.json"])
    return {"checks": checks, "failed_sources": failed, "disk_gb": disk["total_real_gb"], "summary": str(summary_path)}


if __name__ == "__main__":
    print(json.dumps(build_reports(), indent=2))
