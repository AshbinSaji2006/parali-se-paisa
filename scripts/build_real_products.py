"""Build traceable real-only feature, temporal, weak-label and showcase products."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.provenance import content_available
from src.features.radar_context import S1_SEASON, radar_observation_context, radar_season_context
from src.features.fire_context import bais2_stability, firms_context, modis_burned_area_context
from src.features.temporal_features import build_temporal_rows

REAL = ROOT / "data" / "real"
FIELDS_PATH = REAL / "fields" / "fields_of_the_world_muktsar.parquet"
FEATURES_PATH = REAL / "derived" / "features" / "real_field_features.parquet"
SHOWCASE_PATH = REAL / "derived" / "showcase" / "showcase_real_fields.geojson"
S1_PASSES_PATH = REAL / "sentinel1" / "sentinel1_field_observations.parquet"
# Same thresholds as src.features.temporal_features (moderate/large gap days).
MODERATE_GAP_DAYS, LARGE_GAP_DAYS = 14, 30
WEATHER_CORE = ("temperature_2m_c", "precipitation_mm")
STATUS_METHOD = "RULE-BASED STATUS CANDIDATE"
USABLE_QUALITY = {"GOOD", "LIMITED"}
HARVEST_DATE_TOLERANCE_DAYS = 10
# Snapshot history rows carry this compact subset; the latest row keeps every feature.
HISTORY_FEATURES = [
    "year", "scene_id", "observation_quality", "valid_pixel_count", "valid_pixel_fraction", "cloud_fraction",
    "NDVI_mean", "NBR_mean", "BAIS2_mean", "BAIS2_quality", "days_since_previous_observation", "temporal_gap_category",
    "weather_status", "weather_hours_before_observation", "temperature_2m_c", "relative_humidity_2m_pct", "rain_previous_72h_mm",
    "firms_coverage_status", "firms_viirs_detections_near_field", "firms_modis_detections_near_field",
    "modis_ba_coverage_status", "modis_ba_burned_pixels_near_field",
    "s1_observation_status", "s1_observation_datetime", "s1_age_days", "VV_mean_db", "VH_mean_db", "VV_minus_VH_db",
]


def _asof_weather(hourly: pd.DataFrame, grid_id: int, reference: pd.Timestamp) -> dict:
    """Return weather measured no later than the satellite acquisition time.

    Hours whose core reanalysis values are not yet published (ERA5 latency leaves
    trailing null rows) are not observations and are skipped; otherwise a null
    hour would be reported as available weather with zero-filled rain totals.
    """
    rows = hourly.loc[(hourly.grid_id == grid_id) & (hourly.timestamp <= reference)]
    rows = rows.loc[rows.timestamp > reference - pd.Timedelta(days=7)]
    rows = rows.dropna(subset=[c for c in WEATHER_CORE if c in rows])
    if rows.empty:
        return {"weather_available": False, "weather_status": "NOT_PUBLISHED_WITHIN_7D", "weather_observation_datetime": None}
    last = rows.iloc[-1]
    fresh = bool(reference - last.timestamp <= pd.Timedelta(hours=24))
    result = {
        "weather_available": fresh,
        # STALE rows keep the last published values for transparency but are not "available".
        "weather_status": "AVAILABLE" if fresh else "STALE_OVER_24H",
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


def _gap_category(gap: float | None) -> str | None:
    if gap is None:
        return None
    return "NORMAL" if gap <= MODERATE_GAP_DAYS else "MODERATE" if gap <= LARGE_GAP_DAYS else "LARGE"


def _build_proxy_labels(obs: pd.DataFrame) -> pd.DataFrame:
    """Conservative season-local candidates; all remain unverified weak proxies.

    A transition label describes a change somewhere inside the evidence window
    (previous observation, this observation]. With a LARGE gap the field's state
    on the labelled date is ambiguous (it may already be burnt, tilled or sown),
    so the window is recorded with every label.
    """
    labels = []
    for (field_id, year), group in obs.groupby(["field_id", "year"], sort=True):
        group = group.sort_values("observation_datetime")
        usable = []  # earlier same-season observations with usable quality and an NDVI value
        for _, row in group.iterrows():
            label, reason = "UNKNOWN", "Insufficient same-season evidence; review required."
            eligible = (row.get("observation_quality") in USABLE_QUALITY and
                        pd.notna(row.get("NDVI")) and pd.notna(row.get("cropland_fraction")) and
                        row.cropland_fraction >= .5)
            # Compare with the previous usable observation: a cloudy (POOR) date in a dense
            # series is not evidence and must not break or create a transition.
            previous = usable[-1] if usable else None
            window_start = previous
            earlier_high = any(r.NDVI >= .55 for r in usable[:-1])
            # Harvest is often spread over two or three 5-day acquisitions (senescence, then
            # cutting), so the decline is measured from the last high-NDVI usable observation
            # and labelled once, on the first low date after it.
            last_high = next((r for r in reversed(usable) if r.NDVI >= .55), None)
            first_low = last_high is not None and not any(
                r.NDVI <= .35 for r in usable if r.observation_datetime > last_high.observation_datetime)
            gap = ((row.observation_datetime - previous.observation_datetime).total_seconds() / 86400
                   if previous is not None else None)
            if eligible and previous is not None:
                delta = row.NDVI - previous.NDVI
                high_window = ((row.observation_datetime - last_high.observation_datetime).total_seconds() / 86400
                               if last_high is not None else None)
                # Large gaps across crop stages are ambiguous and do not create labels.
                if first_low and row.NDVI <= .35 and 0 < high_window <= 75:
                    label, reason = "HARVESTED", ("Same-season decline from NDVI >= 0.55 to <= 0.35 (first low date after the "
                                                  "last high observation); harvest proxy only.")
                    window_start, gap = last_high, high_window
                elif 0 < gap <= 75:
                    if (earlier_high and previous.NDVI <= .30 and delta >= .15 and row.NDVI > previous.NDVI):
                        label, reason = "SOWN", "High-to-bare-to-green sequence within one season; sowing proxy only."
                    elif row.NDVI >= .55 and abs(delta) < .15:
                        label, reason = "STANDING", "High NDVI stable against previous same-season observation; weak vegetation proxy only."
                    else:
                        reason = "Observed transition is ambiguous or lacks independent evidence; review required."
            category = _gap_category(gap)
            if label != "UNKNOWN" and category == "LARGE":
                reason += (f" Transition lies somewhere in a {gap:.0f}-day window; the state on this date is "
                           "ambiguous (the field may already be burnt, tilled or sown).")
            labels.append({"field_id": field_id, "observation_datetime": row.observation_datetime,
                           "weak_label": label, "confidence": "LOW", "label_quality": "WEAK",
                           "reason": reason, "label_source": "REAL_S2_HEURISTIC_PROXY",
                           "evidence_window_start": window_start.observation_datetime if window_start is not None else pd.NaT,
                           "evidence_window_days": gap, "temporal_gap_category": category,
                           "is_ground_truth": False, "real_or_synthetic": "REAL"})
            if row.get("observation_quality") in USABLE_QUALITY and pd.notna(row.get("NDVI")):
                usable.append(row)
    return pd.DataFrame(labels)


def _field_context(observed_ids: set[str]) -> dict:
    """Centroids, WorldCover cropland fractions and geometries for observed fields.

    The full Fields of The World Parquet is a Git LFS object. When only its pointer
    is present, previously derived values from the same source are reused and the
    showcase is restricted to fields whose source geometry is already committed.
    """
    if content_available(FIELDS_PATH):
        fields = gpd.read_parquet(FIELDS_PATH)
        subset = fields.loc[fields.field_id.astype(str).isin(observed_ids)].copy()
        fraction_map = {}
        worldcover_path = REAL / "landcover" / "worldcover_muktsar.tif"
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
        centroids = subset.set_index("field_id")[["centroid_lon", "centroid_lat"]]
        return {"source": "FIELDS_OF_THE_WORLD_PARQUET", "centroids": centroids,
                "cropland": fraction_map, "geometries": subset}
    if not FEATURES_PATH.exists() or not SHOWCASE_PATH.exists():
        raise FileNotFoundError(
            f"{FIELDS_PATH.relative_to(ROOT)} is a Git LFS pointer or missing; run `git lfs pull` "
            "(no derived fallback is available).")
    previous = pd.read_parquet(FEATURES_PATH, columns=["field_id", "centroid_lon", "centroid_lat", "cropland_fraction"])
    previous = previous.drop_duplicates("field_id").set_index("field_id")
    return {"source": "DERIVED_FALLBACK_LFS_FIELD_PARQUET_NOT_FETCHED",
            "centroids": previous[["centroid_lon", "centroid_lat"]],
            "cropland": previous.cropland_fraction.dropna().to_dict(),
            "geometries": gpd.read_file(SHOWCASE_PATH)}


def _research_events(field_ids: set[str]) -> dict[str, dict[int, dict]]:
    """Dense-series season summaries (rule candidates) for the given fields."""
    out: dict[str, dict[int, dict]] = {}
    for year in (2023, 2024, 2025, 2026):
        path = REAL / "derived" / "research" / f"field_events_{year}.parquet"
        if not content_available(path):
            continue
        events = pd.read_parquet(path, columns=["field_id", "harvested", "harvest_date", "burn_tier", "burn_date", "burn_prev_date"])
        for row in events.loc[events.field_id.isin(field_ids)].itertuples():
            day = lambda v: None if pd.isna(v) else pd.Timestamp(v).date().isoformat()
            out.setdefault(row.field_id, {})[year] = {
                "harvested": bool(row.harvested), "harvest_observed": day(row.harvest_date),
                "burn_tier": row.burn_tier, "burn_observed": day(row.burn_date), "last_unburned_observation": day(row.burn_prev_date)}
    return out


def _dense_series_state(field_ids: set[str], year: int) -> dict[str, dict]:
    """Per-field dense-series state for one season (timeseries/events_<year>.parquet)."""
    path = REAL / "derived" / "timeseries" / f"events_{year}.parquet"
    if not content_available(path):
        return {}
    events = pd.read_parquet(path, columns=["field_id", "n_usable", "last_date", "peak_nbr", "harvested",
                                           "harvest_date", "last_green_date", "harvest_window_days"])
    return {r.field_id: r._asdict() for r in events.loc[events.field_id.isin(field_ids)].itertuples(index=False)}


def _current_candidate(last: pd.Series, dense: dict | None, weak: dict) -> dict:
    """Latest-date RULE-BASED STATUS CANDIDATE.

    A sparse weak label is used when it exists. Otherwise the candidate needs two
    reductions of real Sentinel-2 data to agree on the same acquisition: the dense
    harvest-aware series (harvest = first usable NBR < 0.30 after NBR reached 0.50)
    and the sparse field NDVI. Disagreement or missing evidence stays UNKNOWN.
    """
    if weak["candidate"]:
        return {**weak, "candidate_source": "SPARSE_S2_WEAK_LABEL"}
    day = pd.Timestamp(last.observation_datetime).tz_convert("UTC").tz_localize(None).normalize()
    unknown = {"candidate": None, "evidence_window_days": None, "temporal_gap_category": None,
               "candidate_source": None, "reason": weak["reason"]}
    if not dense or pd.isna(dense.get("last_date")) or pd.Timestamp(dense["last_date"]).normalize() != day:
        return {**unknown, "reason": weak["reason"] + " Dense series has no usable observation on this date."}
    ndvi = last.get("NDVI")
    if dense["harvested"] and pd.Timestamp(dense["harvest_date"]) <= day:
        if pd.notna(ndvi) and ndvi <= .40:
            return {"candidate": "HARVESTED", "evidence_window_days": dense.get("harvest_window_days"),
                    "temporal_gap_category": None, "candidate_source": "DENSE_S2_SERIES_AND_SPARSE_NDVI_AGREE",
                    "reason": f"Dense series harvest transition observed {pd.Timestamp(dense['harvest_date']).date()} "
                              f"(last green {pd.Timestamp(dense['last_green_date']).date()}); field NDVI {ndvi:.2f} on this date. Harvest proxy only."}
        return {**unknown, "reason": "Dense series and field NDVI disagree on harvest; review required."}
    if not dense["harvested"] and dense["peak_nbr"] >= .50:
        if pd.notna(ndvi) and ndvi >= .55:
            return {"candidate": "STANDING", "evidence_window_days": None, "temporal_gap_category": None,
                    "candidate_source": "DENSE_S2_SERIES_AND_SPARSE_NDVI_AGREE",
                    "reason": f"No harvest transition in {int(dense['n_usable'])} usable dense-series observations through "
                              f"{day.date()} (season peak NBR {dense['peak_nbr']:.2f}); field NDVI {ndvi:.2f}. Standing-crop proxy only."}
        return {**unknown, "reason": "Dense series shows no harvest but field NDVI is low; ambiguous, review required."}
    return {**unknown, "reason": "No established crop in the dense series this season; insufficient evidence."}


GROUP_QUOTAS = {
    "A_BURN_LIKE_MULTI_SIGNAL": 40,
    "C_POST_HARVEST_GREEN_UP": 30,
    "B_HARVEST_NO_BURN": 30,
    "D_STABLE_STANDING": 20,
    "E_AMBIGUOUS_SYSTEM_CAUTION": 20,
}


def _demo_suitability(obs: pd.DataFrame, labels: pd.DataFrame, events: dict, dense_latest: dict) -> pd.DataFrame:
    """Group and rank fields for a transparent demonstration; not a scientific or burn-risk ranking.

    Groups (first match wins): A burn-like season with a strict Sentinel-2 burn-scar candidate and
    FIRMS/MODIS proximity; C a post-harvest observation whose NDVI has recovered (sowing-like);
    B harvested in at least two seasons with no burn candidate and no fire detections in covered
    windows; D a current standing-crop candidate with no burn candidate in any season; E cases
    where sources disagree or quality is weak, useful for showing the system's caution.
    Agreement between sources is corroboration, not ground truth.
    """
    rows = []
    weak = labels.set_index(["field_id", "observation_datetime"]).weak_label
    for field_id, group in obs.groupby("field_id"):
        group = group.sort_values("observation_datetime")
        ev = events.get(field_id, {})
        strict = sorted(y for y, e in ev.items() if e.get("burn_tier") == "CHAR_STRICT")
        loose_only = sorted(y for y, e in ev.items() if e.get("burn_tier") == "CHAR_LOOSE")
        no_burn = sorted(y for y, e in ev.items() if e.get("harvested") and e.get("burn_tier") == "NONE")
        viirs = pd.to_numeric(group.firms_viirs_detections_near_field, errors="coerce").fillna(0)
        firms_years = sorted(map(int, group.loc[viirs.gt(0), "year"].unique()))
        modis_years = sorted(map(int, group.loc[pd.to_numeric(group.modis_ba_burned_pixels_near_field, errors="coerce").fillna(0).gt(0), "year"].unique()))
        corroborated = sorted(set(strict) & (set(firms_years) | set(modis_years)))
        green_up = []
        conflicts = []
        usable = group.loc[group.observation_quality.isin(USABLE_QUALITY)]
        for _, r in usable.iterrows():
            e = ev.get(int(r.year), {})
            harvest = pd.Timestamp(e["harvest_observed"]) if e.get("harvest_observed") else None
            day = pd.Timestamp(r.observation_datetime).tz_convert("UTC").tz_localize(None)
            if harvest is not None and e.get("burn_tier") == "NONE" and day - harvest >= pd.Timedelta(days=20) and r.NDVI >= .40:
                green_up.append(int(r.year))
            label = weak.get((field_id, r.observation_datetime))
            # NDVI <= 0.35 and the research NBR < 0.30 rule cross on different dates; within two
            # revisits that is a threshold difference, not a disagreement about the harvest.
            if label == "HARVESTED" and e and (harvest is None or harvest > day + pd.Timedelta(days=HARVEST_DATE_TOLERANCE_DAYS)):
                conflicts.append(f"{int(r.year)}: weak HARVESTED proxy on {day.date()} but the dense NBR series shows "
                                 + ("no harvest that season" if harvest is None else f"harvest only on {harvest.date()}"))
        dense = dense_latest.get(field_id) or {}
        last = usable.iloc[-1] if not usable.empty else group.iloc[-1]
        standing_now = bool(dense and not dense.get("harvested") and (dense.get("peak_nbr") or 0) >= .5 and last.NDVI >= .55)
        good_obs = int(group.observation_quality.eq("GOOD").sum())
        # A dense series always has a few cloud-edge dates; "clean" needs >= 90% GOOD dates and
        # artefact-free BAIS2 on every usable date.
        clean = bool(good_obs >= .9 * len(group) and not usable.empty and usable.BAIS2_quality.eq("OK").all()
                     and pd.to_numeric(group.cropland_fraction, errors="coerce").fillna(0).ge(.9).all())
        fire_covered = int(group.firms_coverage_status.eq("COMPLETE").sum())
        radar = bool(group.get("s1_context_status", pd.Series(dtype=object)).eq("SEASON_SUMMARY_AVAILABLE").any()
                     or group.get("s1_available", pd.Series(dtype=bool)).fillna(False).astype(bool).any())
        weather_ok = int(group.weather_available.fillna(False).astype(bool).sum())
        if corroborated:
            category = "A_BURN_LIKE_MULTI_SIGNAL"
        elif green_up:
            category = "C_POST_HARVEST_GREEN_UP"
        elif len(no_burn) >= 2 and not strict and not loose_only and not firms_years and not modis_years:
            category = "B_HARVEST_NO_BURN"
        elif standing_now and clean and not strict and not loose_only and not conflicts:
            category = "D_STABLE_STANDING"
        else:
            category = "E_AMBIGUOUS_SYSTEM_CAUTION"
        if category == "E_AMBIGUOUS_SYSTEM_CAUTION" and not (conflicts or loose_only or strict or not clean):
            category = "OTHER"
        score = (good_obs / len(group) * 4 + (1 - float(group.cloud_fraction.mean())) * 2
                 + fire_covered / len(group) * 2 + (1 if radar else 0) + weather_ok / len(group)
                 + 2 * len(corroborated) + (2 if clean else 0) + min(float(group.area_ha.iloc[0]), 10) / 5)
        rows.append({"field_id": field_id, "demo_category": category, "demo_score": round(score, 3),
                     "demo_clean_observations": clean, "good_observations": good_obs, "observations": int(len(group)),
                     "mean_cloud_fraction": round(float(group.cloud_fraction.mean()), 4),
                     "fire_windows_complete": fire_covered, "radar_context": radar, "weather_available_rows": weather_ok,
                     "strict_burn_candidate_years": strict, "loose_only_burn_candidate_years": loose_only,
                     "harvested_no_burn_candidate_years": no_burn, "post_harvest_green_up_years": sorted(set(green_up)),
                     "firms_near_field_years": firms_years, "modis_ba_near_field_years": modis_years,
                     "corroborated_burn_years": corroborated, "current_standing_candidate": standing_now,
                     "source_conflicts": conflicts})
    return pd.DataFrame(rows).sort_values(["demo_score", "field_id"], ascending=[False, True]).reset_index(drop=True)


def _select_showcase(candidates: pd.DataFrame) -> pd.DataFrame:
    picks = [candidates.loc[candidates.demo_category.eq(group)].head(quota) for group, quota in GROUP_QUOTAS.items()]
    order = {group: i for i, group in enumerate(GROUP_QUOTAS)}
    ranked = pd.concat(picks).assign(_g=lambda d: d.demo_category.map(order))
    return ranked.sort_values(["_g", "demo_score", "field_id"], ascending=[True, False, True]).drop(columns="_g").reset_index(drop=True)


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is pd.NaT:
        return None
    return value


def build() -> dict:
    observations_path = REAL / "derived" / "features" / "sentinel2_field_observations.parquet"
    obs = pd.read_parquet(observations_path)
    obs["observation_datetime"] = pd.to_datetime(obs["observation_datetime"], utc=True)
    # A field-mean BAIS2 dominated by a near-zero-red pixel is not a usable index value.
    obs = obs.join(bais2_stability(obs))
    obs["BAIS2_pixel_mean_raw"] = obs["BAIS2"]
    obs.loc[obs.BAIS2_quality.ne("OK"), "BAIS2"] = np.nan
    # A non-positive field-mean red reflectance (Sen2Cor over-correction, e.g. under smoke) or a
    # normalised index outside [-1, 1] is not a physical observation: flag it and withhold the indices.
    obs["reflectance_quality"] = np.select(
        [obs.b04_mean.le(0), ~obs.NDVI.between(-1, 1) | ~obs.NBR.between(-1, 1)],
        ["NON_POSITIVE_MEAN_RED", "INDEX_OUT_OF_PHYSICAL_RANGE"], default="OK")
    unphysical = obs.reflectance_quality.ne("OK")
    obs.loc[unphysical, ["NDVI", "NBR", "BAIS2"]] = np.nan
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
    obs["observation_quality"] = np.where(obs.valid_pixel_fraction.notna() & ~unphysical, quality, "POOR")
    obs["season"] = "kharif"
    weather = pd.read_parquet(REAL / "weather" / "weather_daily.parquet")
    weather["timestamp"] = pd.to_datetime(weather["timestamp"], utc=True)
    context = _field_context(set(obs.field_id.astype(str)))
    obs["cropland_fraction"] = obs.field_id.astype(str).map(context["cropland"])
    obs = obs.drop(columns=["centroid_lon", "centroid_lat"], errors="ignore").merge(
        context["centroids"], left_on="field_id", right_index=True, how="left", validate="many_to_one")
    # ERA5 is a coarse reanalysis grid, so associate the nearest provider grid point explicitly.
    grid = weather[["grid_id", "latitude", "longitude"]].drop_duplicates()
    dx = (obs["centroid_lon"].to_numpy()[:, None] - grid.longitude.to_numpy()[None, :]) * np.cos(np.deg2rad(obs.centroid_lat.to_numpy()[:, None]))
    dy = obs.centroid_lat.to_numpy()[:, None] - grid.latitude.to_numpy()[None, :]
    nearest = np.sqrt(dx*dx + dy*dy).argmin(axis=1)
    obs["weather_grid_id"] = grid.grid_id.to_numpy()[nearest]
    obs["weather_grid_latitude"] = grid.latitude.to_numpy()[nearest]
    obs["weather_grid_longitude"] = grid.longitude.to_numpy()[nearest]
    obs["weather_grid_distance_km"] = np.sqrt(dx*dx + dy*dy)[np.arange(len(obs)), nearest] * 111.2
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

    # Fire products are proximity context with explicit archive coverage, never labels.
    firms = pd.read_parquet(REAL / "firms" / "active_fire_unified.parquet")
    obs = obs.join(firms_context(obs, firms))
    obs = obs.join(modis_burned_area_context(obs, pd.read_parquet(REAL / "burned_area" / "mcd64a1_burn_pixels.parquet"),
                                             pd.read_parquet(REAL / "burned_area" / "mcd64a1_muktsar.parquet")))
    radar_path = REAL / "derived" / "research" / f"paddy_mask_s1_{S1_SEASON}.parquet"
    obs = obs.join(radar_season_context(obs, pd.read_parquet(radar_path) if content_available(radar_path) else None))
    obs = obs.join(radar_observation_context(obs, pd.read_parquet(S1_PASSES_PATH) if content_available(S1_PASSES_PATH) else None))

    obs = obs.sort_values(["field_id", "observation_datetime"]).reset_index(drop=True)
    obs["days_since_previous_observation"] = obs.groupby("field_id").observation_datetime.diff().dt.total_seconds() / 86400
    temporal_rows, temporal_report = build_temporal_rows(obs.to_dict("records"))
    temporal = pd.DataFrame(temporal_rows)
    # Gaps are between consecutive usable (non-POOR) observations of one field-season.
    gaps = temporal.days_since_previous_observation.dropna()
    bins = [("<=10", gaps.le(10)), ("11-20", gaps.gt(10) & gaps.le(20)), ("21-30", gaps.gt(20) & gaps.le(30)),
            ("31-45", gaps.gt(30) & gaps.le(45)), (">45", gaps.gt(45))]
    temporal_report["gap_distribution_days"] = {k: {"count": int(m.sum()), "share": round(float(m.mean()), 4) if len(gaps) else None} for k, m in bins}
    per_field = temporal.groupby("field_id").size()
    temporal_report["fields_with_ge_3_observations"] = int(per_field.ge(3).sum())
    temporal_report["fields_with_ge_5_observations"] = int(per_field.ge(5).sum())
    temporal_report["max_observations_per_field_season"] = int(temporal.groupby(["field_id", "year"]).size().max())
    usable = temporal.loc[temporal.observation_quality.isin(USABLE_QUALITY)].groupby(["year", "field_id"]).size()
    usable = usable.unstack("year").reindex(sorted(temporal.field_id.unique())).fillna(0).astype(int)
    temporal_report["usable_observations_per_field_season"] = {
        str(y): {"median": float(usable[y].median()), "min": int(usable[y].min()), "max": int(usable[y].max()),
                 "fields_ge_3": int(usable[y].ge(3).sum()), "fields_ge_5": int(usable[y].ge(5).sum()),
                 "scenes": int(temporal.loc[temporal.year == y, "scene_id"].nunique())} for y in usable.columns}
    temporal_report["fields_with_ge_3_usable_observations_in_every_season"] = int(usable.ge(3).all(axis=1).sum())
    temporal_report["fields_with_ge_5_usable_observations_in_every_season"] = int(usable.ge(5).all(axis=1).sum())
    temporal_report["observation_quality_counts"] = temporal.observation_quality.value_counts().to_dict()
    temporal_report["s1_per_date_rows"] = {k: int(v) for k, v in temporal.s1_observation_status.value_counts().items()}
    temporal_report_path = ROOT / "reports" / "real_temporal_feature_quality_report.json"
    temporal_report_path.write_text(json.dumps(temporal_report, indent=2, default=str) + "\n", encoding="utf-8")
    obs = temporal
    for col in ("NDVI", "NBR", "BAIS2"):
        obs[f"{col.lower()}_delta"] = obs[f"{col}_delta"]
    obs["source_provider"] = "Microsoft Planetary Computer + Open-Meteo + NASA FIRMS/UMD + NASA LP DAAC"
    obs["record_type"] = "REAL_SATELLITE_FIELD_OBSERVATION"
    obs["real_or_synthetic"] = "REAL"
    obs.to_parquet(FEATURES_PATH, index=False)

    temporal_path = REAL / "derived" / "features" / "real_temporal_features.parquet"
    temporal.to_parquet(temporal_path, index=False)

    # These low-confidence proxies are audit/triage aids; never train or report them
    # as independent ground-truth validation labels.
    labels_df = _build_proxy_labels(obs)
    label_path = REAL / "derived" / "labels" / "real_weak_labels.parquet"
    labels_df.to_parquet(label_path, index=False)

    events = _research_events(set(obs.field_id))
    latest_year = int(obs.year.max())
    dense_latest = _dense_series_state(set(obs.field_id), latest_year)
    suitability = _demo_suitability(obs, labels_df, events, dense_latest)
    # Showcase only fields with real processed observations and committed source geometry.
    geometries = context["geometries"]
    candidates = suitability.loc[suitability.field_id.isin(set(geometries.field_id))]
    ranked = _select_showcase(candidates)
    ranked["demo_rank"] = np.arange(1, len(ranked) + 1)
    showcase = geometries.loc[geometries.field_id.isin(set(ranked.field_id))].copy()
    showcase = showcase.drop(columns=[c for c in ("cropland_fraction", "demo_rank", "demo_category", "demo_score") if c in showcase])
    showcase = showcase.merge(ranked[["field_id", "demo_rank", "demo_category", "demo_score"]], on="field_id").sort_values("demo_rank")
    showcase["cropland_fraction"] = showcase.field_id.astype(str).map(context["cropland"])
    showcase["data_status"] = "REAL_SATELLITE_OBSERVATIONS"
    showcase["ground_truth_status"] = "NO_GROUND_TRUTH_WEAK_PROXY_LABELS_ONLY"
    SHOWCASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    showcase.to_file(SHOWCASE_PATH, driver="GeoJSON")
    selection_path = ROOT / "reports" / "real_showcase_selection.json"
    selection_path.write_text(json.dumps({
        "notice": "Demonstration suitability ranking only; not a burn ranking, a probability, or ground truth. "
                  "Agreement between Sentinel-2 rule candidates and FIRMS/MODIS proximity is corroboration, not verification.",
        "field_context_source": context["source"],
        "candidate_pool": int(len(candidates)), "observed_fields": int(len(suitability)),
        "category_counts_in_pool": candidates.demo_category.value_counts().to_dict(),
        "category_counts_selected": ranked.demo_category.value_counts().to_dict(), "group_quotas": GROUP_QUOTAS,
        "fields": json.loads(ranked.to_json(orient="records"))}, indent=2) + "\n", encoding="utf-8")

    labels_by_key = labels_df.set_index(["field_id", "observation_datetime"])
    excluded = {"field_id", "observation_datetime", "scene_id", "collection", "tile", "source_provider",
                "source_item_url", "source_asset_urls", "real_or_synthetic"}

    def feature_values(r, keys=None):
        return {k: (v.item() if isinstance(v, np.generic) else v) for k, v in r.items()
                if k not in excluded and (keys is None or k in keys) and pd.notna(v)}

    def candidate_runs(hist):
        """Collapse consecutive identical rule candidates into one evidence line per run."""
        runs = []
        for _, r in hist.iterrows():
            entry = status_entry(r.field_id, r.observation_datetime)
            if not entry["candidate"]:
                continue
            day = pd.Timestamp(r.observation_datetime).date()
            if runs and runs[-1]["candidate"] == entry["candidate"] and runs[-1]["year"] == int(r.year):
                runs[-1].update(end=day, n=runs[-1]["n"] + 1)
            else:
                runs.append({"candidate": entry["candidate"], "year": int(r.year), "start": day, "end": day, "n": 1,
                             "window": entry["evidence_window_days"]})
        lines = []
        for run in runs:
            if run["n"] == 1:
                window = f" over a {run['window']:.0f}-day window" if run["window"] else ""
                lines.append(f"{run['start']}: {run['candidate']} rule candidate{window}")
            else:
                lines.append(f"{run['start']} to {run['end']}: {run['candidate']} rule candidate on {run['n']} consecutive candidate dates")
        return lines

    def status_entry(field_id, when):
        label = labels_by_key.loc[(field_id, when)]
        return {"candidate": None if label.weak_label == "UNKNOWN" else label.weak_label, "reason": label.reason,
                "evidence_window_days": None if pd.isna(label.evidence_window_days) else float(label.evidence_window_days),
                "temporal_gap_category": label.temporal_gap_category}

    snapshot_fields = []
    for _, f in showcase.iterrows():
        hist = obs.loc[obs.field_id == f.field_id].sort_values("observation_datetime")
        if hist.empty:
            continue
        # The status describes the latest usable acquisition; a cloud-edge (POOR) date is not evidence.
        usable_hist = hist.loc[hist.observation_quality.isin(USABLE_QUALITY)]
        last = usable_hist.iloc[-1] if not usable_hist.empty else hist.iloc[-1]
        latest_status = _current_candidate(last, dense_latest.get(f.field_id) if int(last.year) == latest_year else None,
                                           status_entry(f.field_id, last.observation_datetime))
        season_candidates = candidate_runs(hist)
        firms_status = last.get("firms_coverage_status")
        modis_status = last.get("modis_ba_coverage_status")
        snapshot_fields.append({
            "field_id": f.field_id, "district": "Sri Muktsar Sahib", "village": None,
            "area_ha": float(f.area_ha), "centroid": {"latitude": float(f.centroid_lat), "longitude": float(f.centroid_lon)},
            "geometry": mapping(f.geometry), "provenance": "REAL_RESEARCH_BOUNDARY",
            "source": "Fields of The World / Source Cooperative",
            "properties": {"latest_features": feature_values(last), "ground_truth_status": "WEAK_PROXY_ONLY",
                           "demo_rank": int(f.demo_rank), "demo_category": f.demo_category,
                           "research_season_summaries": {str(y): e for y, e in sorted(events.get(f.field_id, {}).items())},
                           "research_season_summary_notice": "Dense Sentinel-2 harvest-aware rule candidates; retrospective season summaries; not ground truth."},
            "intelligence": {
                "field_status": {"status_candidate": latest_status["candidate"], "method": STATUS_METHOD, "confidence_band": "LOW",
                                 "is_ground_truth": False, "label_source": "REAL_S2_HEURISTIC_PROXY",
                                 "candidate_source": latest_status["candidate_source"],
                                 "evidence": [f"Latest observation {pd.Timestamp(last.observation_datetime).date()}: {latest_status['reason']}",
                                              *season_candidates,
                                              "No trained or validated field-status model; weak proxy labels are not ground truth."]},
                "straw": {"eligible": False, "reason": "No verified residue or yield data; estimates withheld."},
                "burn_risk": {"risk_score": None, "risk_level": "UNKNOWN", "method": "NOT COMPUTED; NO VALIDATED BURN-RISK MODEL IN REAL MODE",
                              "score_kind": "UNAVAILABLE", "top_factors": [],
                              "availability": {"weather": bool(last.get("weather_available")),
                                               "firms": firms_status in {"COMPLETE", "PARTIAL"},
                                               "modis": modis_status in {"COMPLETE", "PARTIAL"},
                                               "radar_season_summary": bool(hist.s1_context_status.eq("SEASON_SUMMARY_AVAILABLE").any()),
                                               "radar_per_date": bool(last.get("s1_available"))},
                              "fire_context_notice": "FIRMS/MODIS detections near the field centroid are proximity context, not attribution or ground truth."},
                "provenance": {"observation_datetime": pd.Timestamp(last.observation_datetime).isoformat(), "fixture_or_real": "REAL",
                               "model_trust_state": "NO_MODEL", "processing_version": last.get("processing_version"),
                               "source_image_id_s2": last.get("scene_id"), "field_context_source": context["source"]}},
            "eligibility": {"eligible": False, "reasons": ["REAL_DATA_ONLY_NO_OPERATIONAL_VALIDATION"], "warnings": ["Research boundary; field status and burn evidence are unverified proxies."]},
            "history": [{"observation_datetime": pd.Timestamp(r.observation_datetime).isoformat(), "features": feature_values(r, HISTORY_FEATURES),
                         "rule_status_candidate": status_entry(f.field_id, r.observation_datetime), "provenance": "REAL"} for _, r in hist.iterrows()]})
    snapshot = {"fields": snapshot_fields, "balers": [], "buyers": [], "jobs": [], "runs": [], "verification": [],
        "certificates": [], "allocations": [], "pickup_requests": [],
        "read_only": True,
        "stats": {"fields": len(snapshot_fields),
                  "standing_candidates": sum(f["intelligence"]["field_status"]["status_candidate"] == "STANDING" for f in snapshot_fields),
                  "harvested_candidates": sum(f["intelligence"]["field_status"]["status_candidate"] == "HARVESTED" for f in snapshot_fields),
                  "high_risk": 0, "estimated_straw_tonnes": 0, "assigned_fields": 0, "collected_tonnes": 0,
                  "active_verification": 0, "certificates": 0, "manual_review": 0},
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(), "data_mode": "REAL",
        "notice": "Read-only real satellite and reanalysis observations; research field boundaries; rule-based status candidates and weak proxy labels only; no ground truth.",
        "real_data_summary": {"fields": len(snapshot_fields), "observed_fields": int(obs.field_id.nunique()),
                              "observations": int(len(obs)), "years": sorted(map(int, obs.year.unique())),
                              "observations_by_season": {str(int(y)): int(n) for y, n in obs.groupby("year").size().items()},
                              "usable_observations_per_field_season": temporal_report["usable_observations_per_field_season"],
                              "s1_per_date_rows": temporal_report["s1_per_date_rows"],
                              "history_feature_subset": HISTORY_FEATURES,
                              "field_context_source": context["source"],
                              "status_method": STATUS_METHOD, "fire_context": "FIRMS/UMD active fire (1 km, 30 d) and MCD64A1 (500 m, 30 d, retrospective) proximity context with coverage flags"}}
    snapshot_path = REAL / "derived" / "app_snapshot.json"
    # Browsers reject NaN in JSON; allow_nan=False makes any leak a build failure.
    snapshot_path.write_text(json.dumps(_json_safe(snapshot), ensure_ascii=False, default=str, allow_nan=False)+"\n", encoding="utf-8")

    return {"features": FEATURES_PATH, "temporal": temporal_path, "labels": label_path,
            "showcase": SHOWCASE_PATH, "app_snapshot": snapshot_path, "rows": len(obs), "fields": int(obs.field_id.nunique()),
            "field_context_source": context["source"], "label_counts": labels_df.weak_label.value_counts().to_dict()}


if __name__ == "__main__":
    print(json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in build().items()}, indent=2))
