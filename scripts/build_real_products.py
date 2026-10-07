"""Build traceable real-only feature, temporal, weak-label and showcase products."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping
import rasterio
from src.features.temporal_features import build_temporal_rows
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data" / "real"


def _asof_weather(hourly: pd.DataFrame, grid_id: int, reference: pd.Timestamp) -> dict:
    """Return weather measured no later than the satellite acquisition time."""
    rows = hourly.loc[(hourly.grid_id == grid_id) & (hourly.timestamp <= reference)]
    rows = rows.loc[rows.timestamp > reference - pd.Timedelta(days=7)]
    if rows.empty:
        return {"weather_available": False, "weather_observation_datetime": None}
    last = rows.iloc[-1]
    result = {
        "weather_available": bool(reference - last.timestamp <= pd.Timedelta(hours=24)),
        "weather_observation_datetime": last.timestamp.isoformat(),
        "weather_hours_before_observation": (reference - last.timestamp).total_seconds() / 3600,
        "temperature_2m_c": last.temperature_2m_c,
        "relative_humidity_2m_pct": last.relative_humidity_2m_pct,
        "wind_speed_10m_ms": last.wind_speed_10m_ms,
        "precipitation_mm": last.precipitation_mm,
        "rain_previous_24h_mm": last.rain_previous_24h_mm,
        "rain_previous_72h_mm": last.rain_previous_72h_mm,
        "rain_previous_7d_mm": last.rain_previous_7d_mm,
        "dry_days_previous_7d": None,
        "weather_source": "Open-Meteo ERA5 historical reanalysis",
        "weather_window_end": last.timestamp.isoformat(),
        "weather_record_type": last.record_type,
    }
    # Count only complete days before the acquisition date. The acquisition day's
    # unfinished precipitation must never be interpreted as a full dry/wet day.
    day_end = reference.floor("D")
    complete = hourly.loc[(hourly.grid_id == grid_id) & (hourly.timestamp < day_end) &
                          (hourly.timestamp >= day_end - pd.Timedelta(days=7))]
    per_day = complete.groupby(complete.timestamp.dt.floor("D")).precipitation_mm.agg(
        lambda values: values.sum(min_count=24) if values.notna().sum() == 24 else np.nan)
    if len(per_day) == 7 and per_day.notna().all():
        result["dry_days_previous_7d"] = int(per_day.lt(1.0).sum())
    return result


def _build_proxy_labels(obs: pd.DataFrame) -> pd.DataFrame:
    """Conservative season-local candidates; all remain unverified weak proxies."""
    labels = []
    for (field_id, year), group in obs.groupby(["field_id", "year"], sort=True):
        group = group.sort_values("observation_datetime")
        for pos, (_, row) in enumerate(group.iterrows()):
            label, reason = "UNKNOWN", "Insufficient same-season evidence; review required."
            eligible = (row.get("observation_quality") in {"GOOD", "LIMITED"} and
                        pd.notna(row.get("NDVI")) and pd.notna(row.get("cropland_fraction")) and
                        row.cropland_fraction >= .5)
            previous = group.iloc[pos - 1] if pos >= 1 else None
            prior2 = group.iloc[pos - 2] if pos >= 2 else None
            if eligible and previous is not None:
                gap = (row.observation_datetime - previous.observation_datetime).total_seconds() / 86400
                delta = row.NDVI - previous.NDVI if pd.notna(previous.NDVI) else None
                # Large gaps across crop stages are ambiguous and do not create labels.
                eligible = 0 < gap <= 75 and previous.get("observation_quality") in {"GOOD", "LIMITED"}
                if eligible and delta is not None:
                    if previous.NDVI >= .55 and row.NDVI <= .35 and delta <= -.20:
                        label, reason = "HARVESTED", "Large same-season vegetation decline after a high-NDVI observation; harvest proxy only."
                    elif (prior2 is not None and pd.notna(prior2.NDVI) and prior2.NDVI >= .55 and
                          previous.NDVI <= .30 and delta >= .15 and row.NDVI > previous.NDVI):
                        label, reason = "SOWN", "High-to-bare-to-green sequence within one season; sowing proxy only."
                    elif row.NDVI >= .55 and abs(delta) < .15:
                        label, reason = "STANDING", "High NDVI stable against previous same-season observation; weak vegetation proxy only."
                    else:
                        reason = "Observed transition is ambiguous or lacks independent evidence; review required."
            labels.append({"field_id": field_id, "observation_datetime": row.observation_datetime,
                           "weak_label": label, "confidence": "LOW", "label_quality": "WEAK",
                           "reason": reason, "label_source": "REAL_S2_HEURISTIC_PROXY",
                           "real_or_synthetic": "REAL"})
    return pd.DataFrame(labels)


def build() -> dict:
    observations_path = REAL / "derived" / "features" / "sentinel2_field_observations.parquet"
    obs = pd.read_parquet(observations_path)
    obs["observation_datetime"] = pd.to_datetime(obs["observation_datetime"], utc=True)
    for metric in ("NDVI", "NBR", "BAIS2"):
        obs[f"{metric}_mean"] = obs[metric]
    estimated_pixels = obs["area_ha"].clip(lower=0) * 25.0  # 20 m nominal pixels per hectare
    estimated_fraction = (obs["valid_pixel_count"] / estimated_pixels.clip(lower=1)).clip(upper=1)
    if "valid_pixel_fraction" not in obs:
        obs["valid_pixel_fraction"] = estimated_fraction
    else:
        obs["valid_pixel_fraction"] = pd.to_numeric(obs["valid_pixel_fraction"], errors="coerce").fillna(estimated_fraction)
    if "cloud_fraction" not in obs:
        obs["cloud_fraction"] = 1 - obs["valid_pixel_fraction"]
    else:
        obs["cloud_fraction"] = pd.to_numeric(obs["cloud_fraction"], errors="coerce").fillna(1 - obs["valid_pixel_fraction"])
    quality = np.select(
        [obs.valid_pixel_count.ge(10) & obs.valid_pixel_fraction.ge(.5),
         obs.valid_pixel_count.ge(5) & obs.valid_pixel_fraction.ge(.25)],
        ["GOOD", "LIMITED"], default="POOR")
    obs["observation_quality"] = np.where(obs.valid_pixel_fraction.notna(), quality, "POOR")
    obs["season"] = "kharif"
    weather = pd.read_parquet(REAL / "weather" / "weather_daily.parquet")
    weather["timestamp"] = pd.to_datetime(weather["timestamp"], utc=True)
    fields = gpd.read_parquet(REAL / "fields" / "fields_of_the_world_muktsar.parquet")
    # WorldCover fractions for the actually observed field subset, at 20 m nearest
    # neighbour sampling to keep the reduction memory-bounded.
    observed_ids = set(obs.field_id.astype(str))
    subset = fields.loc[fields.field_id.astype(str).isin(observed_ids)].copy()
    worldcover_path = REAL / "landcover" / "worldcover_muktsar.tif"
    fraction_map = {}
    if not subset.empty and worldcover_path.exists():
        with rasterio.open(worldcover_path) as src:
            # This WorldCover mosaic is in geographic degrees; about 8 m/pixel at
            # Muktsar, so 2x nearest-neighbour yields an approximately 16–19 m grid.
            factor = 2
            h, w = max(1, src.height // factor), max(1, src.width // factor)
            classes = src.read(1, out_shape=(h, w), resampling=Resampling.nearest)
            transform = src.transform * Affine.scale(src.width / w, src.height / h)
            projected = subset.to_crs(src.crs)
            zones = rasterize(((geom, i) for i, geom in enumerate(projected.geometry, start=1)),
                              out_shape=(h, w), transform=transform, fill=0, dtype="int32")
            valid = (zones > 0) & (classes > 0)
            denominators = np.bincount(zones[valid], minlength=len(subset)+1)
            cropland = np.bincount(zones[valid & (classes == 40)], minlength=len(subset)+1)
            for i, field_id in enumerate(subset.field_id.astype(str), start=1):
                fraction_map[field_id] = float(cropland[i]/denominators[i]) if denominators[i] else None
    obs["cropland_fraction"] = obs.field_id.astype(str).map(fraction_map)
    cent = fields.set_index("field_id")[["centroid_lon", "centroid_lat"]]
    obs = obs.merge(cent, left_on="field_id", right_index=True, how="left", validate="many_to_one")
    # ERA5 is a coarse reanalysis grid, so associate the nearest provider grid point explicitly.
    grid = weather[["grid_id", "latitude", "longitude"]].drop_duplicates()
    dx = (obs["centroid_lon"].to_numpy()[:, None] - grid.longitude.to_numpy()[None, :]) * np.cos(np.deg2rad(obs.centroid_lat.to_numpy()[:, None]))
    dy = obs.centroid_lat.to_numpy()[:, None] - grid.latitude.to_numpy()[None, :]
    obs["weather_grid_id"] = grid.grid_id.to_numpy()[np.sqrt(dx*dx + dy*dy).argmin(axis=1)]
    hourly_weather = pd.read_parquet(REAL / "weather" / "weather_hourly.parquet")
    hourly_weather["timestamp"] = pd.to_datetime(hourly_weather["timestamp"], utc=True)
    weather_by_grid = {int(k): group.sort_values("timestamp") for k, group in hourly_weather.groupby("grid_id")}
    weather_cache = {}
    for idx, row in obs.iterrows():
        key = (int(row.weather_grid_id), row.observation_datetime)
        if key not in weather_cache:
            weather_cache[key] = _asof_weather(weather_by_grid.get(key[0], hourly_weather.iloc[:0]), key[0], key[1])
        for col, value in weather_cache[key].items():
            obs.at[idx, col] = value

    obs = obs.sort_values(["field_id", "observation_datetime"]).reset_index(drop=True)
    obs["days_since_previous_observation"] = obs.groupby("field_id").observation_datetime.diff().dt.total_seconds() / 86400
    temporal_rows, temporal_report = build_temporal_rows(obs.to_dict("records"))
    temporal = pd.DataFrame(temporal_rows)
    temporal_report_path = ROOT / "reports" / "real_temporal_feature_quality_report.json"
    temporal_report_path.write_text(json.dumps(temporal_report, indent=2, default=str) + "\n", encoding="utf-8")
    obs = temporal
    for col in ("NDVI", "NBR", "BAIS2"):
        obs[f"{col.lower()}_delta"] = obs[f"{col}_delta"]
    obs["source_provider"] = "Microsoft Planetary Computer + Open-Meteo"
    obs["record_type"] = "REAL_SATELLITE_FIELD_OBSERVATION"
    obs["real_or_synthetic"] = "REAL"
    feature_path = REAL / "derived" / "features" / "real_field_features.parquet"
    obs.to_parquet(feature_path, index=False)

    temporal_path = REAL / "derived" / "features" / "real_temporal_features.parquet"
    temporal.to_parquet(temporal_path, index=False)

    # These low-confidence proxies are audit/triage aids; never train or report them
    # as independent ground-truth validation labels.
    labels_df = _build_proxy_labels(obs)
    label_path = REAL / "derived" / "labels" / "real_weak_labels.parquet"
    labels_df.to_parquet(label_path, index=False)

    # Showcase only fields with real processed observations; preserve full source geometry.
    selected_ids = set(obs.groupby("field_id").size().sort_values(ascending=False).head(100).index)
    showcase = fields.loc[fields.field_id.isin(selected_ids)].copy()
    showcase["cropland_fraction"] = showcase.field_id.astype(str).map(fraction_map)
    showcase["data_status"] = "REAL_SATELLITE_OBSERVATIONS"
    showcase["ground_truth_status"] = "NO_GROUND_TRUTH_WEAK_PROXY_LABELS_ONLY"
    showcase_path = REAL / "derived" / "showcase" / "showcase_real_fields.geojson"
    showcase_path.parent.mkdir(parents=True, exist_ok=True)
    showcase.to_file(showcase_path, driver="GeoJSON")

    snapshot_fields = []
    for _, f in showcase.iterrows():
        hist = obs.loc[obs.field_id == f.field_id].sort_values("observation_datetime")
        if hist.empty:
            continue
        def feature_values(r):
            excluded = {"field_id", "observation_datetime", "scene_id", "collection", "tile", "source_provider",
                        "source_item_url", "source_asset_urls", "real_or_synthetic"}
            return {k: (v.item() if isinstance(v, np.generic) else v) for k,v in r.items() if k not in excluded and pd.notna(v)}
        last = hist.iloc[-1]
        snapshot_fields.append({
            "field_id": f.field_id, "district": "Sri Muktsar Sahib", "village": None,
            "area_ha": float(f.area_ha), "centroid": {"latitude": float(f.centroid_lat), "longitude": float(f.centroid_lon)},
            "geometry": mapping(f.geometry), "provenance": "REAL_RESEARCH_BOUNDARY",
            "source": "Fields of The World / Source Cooperative",
            "properties": {"latest_features": feature_values(last), "ground_truth_status": "WEAK_PROXY_ONLY"},
            "intelligence": {"field_status": {"status_candidate": None, "method": "REAL SATELLITE OBSERVATION; NO TRAINED FIELD-STATUS MODEL", "confidence_band": "LOW", "evidence": ["Sentinel-2 observations available; no ground truth labels"]},
                    "straw": {"eligible": False, "reason": "No verified residue or yield data; estimates withheld."},
                "burn_risk": {"risk_score": None, "risk_level": "UNKNOWN", "method": "NO INDEPENDENT FIRE EVIDENCE", "score_kind": "UNAVAILABLE", "top_factors": [], "availability": {"weather": True, "firms": False, "modis": False}},
                "provenance": {"observation_datetime": pd.Timestamp(last.observation_datetime).isoformat(), "fixture_or_real": "REAL", "model_trust_state": "NO_MODEL"}},
            "eligibility": {"eligible": False, "reasons": ["REAL_DATA_ONLY_NO_OPERATIONAL_VALIDATION"], "warnings": ["Research boundary; field status and burn evidence are unverified proxies."]},
            "history": [{"observation_datetime": pd.Timestamp(r.observation_datetime).isoformat(), "features": feature_values(r), "provenance": "REAL"} for _,r in hist.iterrows()]})
    snapshot = {"fields": snapshot_fields, "balers": [], "buyers": [], "jobs": [], "runs": [], "verification": [],
        "certificates": [], "allocations": [], "pickup_requests": [],
        "read_only": True,
        "stats": {"fields": len(snapshot_fields), "harvested_candidates": 0, "high_risk": 0,
                  "estimated_straw_tonnes": 0, "assigned_fields": 0, "collected_tonnes": 0,
                  "active_verification": 0, "certificates": 0, "manual_review": 0},
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(), "data_mode": "REAL",
        "notice": "Read-only real satellite and reanalysis observations; research field boundaries; weak proxy labels only; no ground truth.",
        "real_data_summary": {"fields": len(snapshot_fields), "observations": int(len(obs)), "years": sorted(map(int, obs.year.unique()))}}
    snapshot_path = REAL / "derived" / "app_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, default=str)+"\n", encoding="utf-8")

    return {"features": feature_path, "temporal": temporal_path, "labels": label_path,
            "showcase": showcase_path, "app_snapshot": snapshot_path, "rows": len(obs), "fields": int(obs.field_id.nunique()),
            "label_counts": labels_df.weak_label.value_counts().to_dict()}


if __name__ == "__main__":
    print(json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in build().items()}, indent=2))
