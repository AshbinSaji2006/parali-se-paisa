"""Resumable acquisition of real Muktsar geospatial data.

This pipeline only writes provider-derived products under data/real. Demo fixtures are
never read here. Public APIs are retried, downloads are validated, and state/manifest
are committed after each source so a later run can resume safely.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from shapely.geometry import shape, mapping, Point
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REAL = ROOT / "data" / "real"
STATE_PATH = REAL / "acquisition_state.json"
MANIFEST_PATH = REAL / "DATASET_MANIFEST.json"
MANIFEST_MD = REAL / "DATASET_MANIFEST.md"
LOG_PATH = ROOT / "logs" / "real_data_download.log"
TODAY = date.today()
TODAY_ISO = TODAY.isoformat()
GEOM_API = "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/"
MPC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
FTW_IN_PB = ("https://data.source.coop/ftw/global-data/predictions/vectors/alpha/"
             "results-by-admin-conf/admin:country_code=IN/IN_PB.parquet")
LOG = logging.getLogger("real_data")


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=5, connect=5, read=5, status=5, backoff_factor=0.8,
                  status_forcelist=(408, 425, 429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET", "HEAD", "POST"}),
                  respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "ParaliSePaisa-RealDataPipeline/1.0"})
    return session


SESSION = make_session()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_response(response: requests.Response, expected: str | None = None) -> bytes:
    response.raise_for_status()
    content = response.content
    if not content:
        raise ValueError(f"Empty response: {response.url}")
    ctype = (response.headers.get("content-type") or "").lower()
    if "text/html" in ctype or content[:100].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError(f"HTML/error document returned instead of data: {response.url}")
    if expected == "json":
        json.loads(content)
    return content


def get_json(url: str, *, params: dict | None = None, timeout: int = 60) -> dict:
    response = SESSION.get(url, params=params, timeout=timeout)
    return json.loads(safe_response(response, "json"))


def stream_download(url: str, destination: Path, *, max_bytes: int | None = None,
                    content_types: tuple[str, ...] = ()) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    part = destination.with_suffix(destination.suffix + ".part")
    part.unlink(missing_ok=True)
    response = SESSION.get(url, timeout=(20, 180), stream=True)
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    if content_types and not any(item in content_type for item in content_types):
        raise ValueError(f"Unexpected content type {content_type!r} for {url}")
    length = int(response.headers.get("content-length") or 0)
    if max_bytes and length > max_bytes:
        raise ValueError(f"Refusing {length} byte download above limit {max_bytes}: {url}")
    actual = 0
    try:
        with part.open("wb") as stream:
            for block in response.iter_content(1024 * 1024):
                if not block:
                    continue
                actual += len(block)
                if max_bytes and actual > max_bytes:
                    raise ValueError(f"Download exceeded limit {max_bytes}: {url}")
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        if actual == 0 or (length and actual != length):
            raise ValueError(f"Incomplete download: expected={length}, actual={actual}")
        if part.read_bytes()[:100].lstrip().lower().startswith((b"<!doctype html", b"<html")):
            raise ValueError(f"HTML error page saved as data: {url}")
        part.replace(destination)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    finally:
        response.close()
    return destination


def load_state() -> dict:
    # This must remain the first project-data read at startup.
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def artifact_record(path: Path) -> dict:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": sha256(path)}


def record_dataset(key: str, status: str, *, source_provider: str, source_dataset: str,
                   date_range: dict | None = None, paths: list[Path] | None = None,
                   metadata: dict | None = None, license_ref: str | None = None,
                   warnings: list[str] | None = None) -> None:
    state = load_state()
    entry = state["datasets"].setdefault(key, {"artifacts": []})
    entry.update({"status": status, "updated_at": utc_now(),
                  "artifacts": [artifact_record(p) for p in (paths or []) if p.is_file()],
                  "date_range": date_range, "warnings": warnings or [], "metadata": metadata or {}})
    if status in ("download_failed", "provider_unavailable", "credential_required"):
        state["last_error"] = {"dataset": key, "status": status,
                               "message": (warnings or ["No details"])[-1], "at": utc_now()}
    else:
        state["last_error"] = None
    state["updated_at"] = utc_now()
    atomic_json(STATE_PATH, state)

    manifest = load_manifest()
    dataset_row = {"dataset": key, "source_provider": source_provider,
                   "source_dataset": source_dataset, "aoi": "Sri Muktsar Sahib, Punjab, India",
                   "date_range": date_range, "status": status, "license_reference": license_ref,
                   "downloaded_at": utc_now(), "processing_version": "real-acquisition-1.0",
                   "files": entry["artifacts"], "metadata": metadata or {}, "warnings": warnings or []}
    rows = [x for x in manifest.get("datasets", []) if x.get("dataset") != key]
    rows.append(dataset_row)
    manifest["datasets"] = rows
    manifest["generated_at"] = utc_now()
    manifest["warnings"] = list(dict.fromkeys(manifest.get("warnings", []) + [f"{key}: {w}" for w in warnings or []]))
    atomic_json(MANIFEST_PATH, manifest)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"{utc_now()} {status.upper()} {key} files={len(dataset_row['files'])} "
                     f"date_range={json.dumps(date_range, sort_keys=True)}\n")


def should_skip(key: str, force: bool) -> bool:
    if force:
        return False
    state = load_state()
    return state.get("datasets", {}).get(key, {}).get("status") in {
        "complete", "real_downloaded", "real_remote_processed", "real_derived", "partial_real"
    }


def boundary_gdf(force: bool = False):
    import geopandas as gpd
    output = REAL / "boundaries" / "sri_muktsar_sahib_adm2.geojson"
    metadata_path = REAL / "boundaries" / "geoboundaries_source_metadata.json"
    source_path = REAL / "cache" / "geoBoundaries-IND-ADM2.geojson"
    if should_skip("district_boundary", force) and output.exists():
        return gpd.read_file(output)
    try:
        meta = get_json(GEOM_API)
        if meta.get("boundaryType") != "ADM2" or meta.get("boundaryISO") != "IND":
            raise ValueError(f"Unexpected geoBoundaries response: {meta.get('boundaryType')}/{meta.get('boundaryISO')}")
        atomic_json(metadata_path, meta)
        stream_download(meta["gjDownloadURL"], source_path, max_bytes=100 * 1024 * 1024,
                        content_types=("json", "octet-stream", "geo+json"))
        source = gpd.read_file(source_path)
        if source.crs is None:
            raise ValueError("geoBoundaries source has no declared CRS")
        name_columns = [c for c in source.columns if c.lower() in {"shapeName".lower(), "name_2", "district", "adm2_name", "name"}]
        if not name_columns:
            raise ValueError(f"Could not locate district name field; columns={list(source.columns)}")
        name_col = name_columns[0]
        norm = source[name_col].astype(str).str.strip().str.casefold()
        aliases = {"sri muktsar sahib", "muktsar", "muktsar sahib"}
        selected = source.loc[norm.isin(aliases)].copy()
        if len(selected) != 1:
            related = source.loc[norm.str.contains("muktsar", na=False), name_col].astype(str).tolist()
            raise ValueError(f"Expected exactly one Muktsar district by exact name, found {len(selected)}; related={related}")
        selected["geometry"] = selected.geometry.map(lambda g: make_valid(g) if g is not None and not g.is_valid else g)
        selected = selected.to_crs("EPSG:4326")
        geom = selected.geometry.iloc[0]
        if geom is None or geom.is_empty or not geom.is_valid:
            raise ValueError("Selected district geometry is empty or invalid")
        projected = selected.to_crs("EPSG:32643")
        area_km2 = float(projected.geometry.area.iloc[0] / 1_000_000)
        if not 1000 <= area_km2 <= 5000:
            raise ValueError(f"Muktsar area sanity check failed: {area_km2:.1f} km2")
        selected["district_name_source"] = selected[name_col].astype(str)
        selected["district_name_normalized"] = "Sri Muktsar Sahib"
        selected["area_km2_epsg32643"] = area_km2
        selected["source_provider"] = "geoBoundaries"
        selected["source_dataset"] = "gbOpen IND ADM2"
        selected["real_or_synthetic"] = "REAL"
        output.parent.mkdir(parents=True, exist_ok=True)
        selected.to_file(output, driver="GeoJSON")
        record_dataset("district_boundary", "real_downloaded", source_provider="geoBoundaries",
                       source_dataset="gbOpen/IND/ADM2", paths=[output, source_path, metadata_path],
                       metadata={"boundary_id": meta.get("boundaryID"), "matched_name": str(selected[name_col].iloc[0]),
                                 "name_field": name_col, "crs": "EPSG:4326", "area_km2_epsg32643": area_km2,
                                 "source_license": meta.get("boundaryLicense"),
                                 "boundary_source": meta.get("boundarySource"),
                                 "download_reference": meta.get("gjDownloadURL")},
                       license_ref=meta.get("boundaryLicense"))
        return selected
    except Exception as exc:
        record_dataset("district_boundary", "download_failed", source_provider="geoBoundaries",
                       source_dataset="gbOpen/IND/ADM2", warnings=[f"{type(exc).__name__}: {exc}"])
        raise


def field_boundaries(district_gdf, force: bool = False):
    import duckdb
    import geopandas as gpd
    from shapely import wkb
    out_pq = REAL / "fields" / "fields_of_the_world_muktsar.parquet"
    out_geojson = REAL / "fields" / "fields_of_the_world_muktsar.geojson"
    if should_skip("field_boundaries", force) and out_pq.exists() and out_geojson.exists():
        return gpd.read_parquet(out_pq)
    try:
        catalog_url = "https://data.source.coop/ftw/global-data/predictions/vectors/alpha/results-by-admin-conf/admin:country_code=IN/catalog.json"
        cat = get_json(catalog_url)
        punjab = next((urljoin(catalog_url, l["href"]) for l in cat.get("links", [])
                       if l.get("rel") == "item" and l.get("title") == "IN_PB"), None)
        if not punjab:
            punjab = urljoin(catalog_url, "IN_PB.json")
        item = get_json(punjab)
        if item.get("properties", {}).get("admin:country_code") != "IN":
            raise ValueError("FTW partition country is not India")
        if not item.get("id", "").endswith("PB"):
            raise ValueError(f"FTW partition is not Punjab: {item.get('id')}")
        parquet_url = urljoin(punjab, item["assets"]["data"]["href"])
        source_geom = district_gdf.to_crs("EPSG:4326").geometry.iloc[0]
        bbox = source_geom.bounds
        con = duckdb.connect()
        con.execute("SET enable_progress_bar=false")
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
        geojson = json.dumps(mapping(source_geom), separators=(",", ":"))
        query = '''SELECT id AS source_field_id, ST_AsWKB(geometry) AS wkb,
                          "metrics:area" AS source_area_m2, confidence,
                          "determination:datetime" AS determination_datetime,
                          "determination:method" AS determination_method,
                          bbox.xmin AS xmin, bbox.ymin AS ymin, bbox.xmax AS xmax, bbox.ymax AS ymax
                   FROM read_parquet(?)
                   WHERE bbox.xmin <= ? AND bbox.xmax >= ? AND bbox.ymin <= ? AND bbox.ymax >= ?'''
        table = con.execute(query, [parquet_url, bbox[2], bbox[0], bbox[3], bbox[1]]).to_arrow_table()
        con.close()
        if table.num_rows == 0:
            raise ValueError("No FTW polygons intersect the target district")
        frame = table.to_pandas()
        frame["geometry"] = frame.pop("wkb").map(wkb.loads)
        frame = frame.loc[frame["geometry"].notna()].copy()
        gdf = gpd.GeoDataFrame(frame, geometry="geometry", crs="EPSG:4326")
        gdf = gdf.loc[~gdf.geometry.is_empty].copy()
        # Do exact clipping locally; DuckDB Spatial's GeoJSON intersection path can
        # return empty geometries on some remote GeoParquet geometry encodings.
        gdf = gdf.loc[gdf.geometry.intersects(source_geom)].copy()
        gdf.geometry = gdf.geometry.intersection(source_geom)
        gdf = gdf.loc[gdf.geometry.is_valid].copy()
        metric = gdf.to_crs("EPSG:32643")
        gdf["area_m2"] = metric.geometry.area.to_numpy()
        gdf["area_ha"] = gdf["area_m2"] / 10000
        gdf = gdf.loc[gdf["area_ha"].between(0.2, 15.0)].copy()
        gdf["field_id"] = "FTW-IN-PB-" + gdf["source_field_id"].astype(str)
        gdf["boundary_source"] = "FIELDS_OF_THE_WORLD_GLOBAL_PRUE_2024_2025"
        gdf["boundary_type"] = "RESEARCH_FIELD_BOUNDARY"
        gdf["research_boundary_disclaimer"] = "Model-derived remote-sensing field unit; not a cadastral or ownership boundary."
        gdf["source_provider"] = "Fields of The World / Source Cooperative"
        gdf["source_dataset"] = "Global Fields of The World, Punjab partition"
        gdf["source_url"] = parquet_url
        gdf["real_or_synthetic"] = "REAL"
        centroid = gdf.to_crs("EPSG:32643").geometry.centroid.to_crs("EPSG:4326")
        gdf["centroid_lon"] = centroid.x.to_numpy()
        gdf["centroid_lat"] = centroid.y.to_numpy()
        gdf["cropland_fraction"] = np.nan
        out_pq.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(out_pq, index=False)
        gdf.to_file(out_geojson, driver="GeoJSON")
        record_dataset("field_boundaries", "real_downloaded", source_provider="Fields of The World / Source Cooperative",
                       source_dataset="PRUE Global Field Boundary Predictions, Punjab GeoParquet partition",
                       date_range={"start": "2024-01-01", "end": "2025-12-31"}, paths=[out_pq, out_geojson],
                       metadata={"partition": "India/Punjab", "partition_feature_count": item.get("properties", {}).get("geoparquet:feature_count"),
                                 "muktsar_bbox_candidates": int(table.num_rows), "retained_area_filtered_fields": int(len(gdf)),
                                 "area_bounds_ha": [0.2, 15], "confidence_filter": "unavailable (provider partition values null)",
                                 "crs": "EPSG:4326", "boundary_source": "SATELLITE_DERIVED_RESEARCH",
                                 "source_partition_url": parquet_url, "license": "CC-BY-4.0"},
                       license_ref="CC-BY-4.0; https://source.coop/ftw/global-data")
        return gdf
    except Exception as exc:
        record_dataset("field_boundaries", "download_failed", source_provider="Fields of The World / Source Cooperative",
                       source_dataset="Global PRUE field polygons, Punjab partition",
                       warnings=[f"{type(exc).__name__}: {exc}"])
        raise


def stac_catalog():
    from pystac_client import Client
    return Client.open(MPC_STAC, headers={"User-Agent": "ParaliSePaisa-RealDataPipeline/1.0"})


def worldcover(district_gdf, fields_gdf=None, force: bool = False):
    import geopandas as gpd
    import rasterio
    from rasterio.mask import mask
    import planetary_computer as pc
    dst = REAL / "landcover" / "worldcover_muktsar.tif"
    mask_path = REAL / "landcover" / "worldcover_cropland_mask.tif"
    if should_skip("worldcover", force) and dst.exists() and mask_path.exists():
        return dst
    try:
        cat = stac_catalog()
        collection = cat.get_collection("esa-worldcover")
        search = cat.search(collections=[collection.id], intersects=mapping(district_gdf.geometry.iloc[0]), max_items=100)
        items = list(search.items())
        if not items:
            raise ValueError("ESA WorldCover STAC has no items intersecting Muktsar")
        item = items[0]
        asset = item.assets.get("map") or next((a for k, a in item.assets.items() if "map" in k.lower()), None)
        if asset is None:
            raise ValueError(f"WorldCover map asset not found; assets={list(item.assets)}")
        href = pc.sign(asset.href)
        with rasterio.open(href) as src:
            arrays, transform = mask(src, [mapping(district_gdf.to_crs(src.crs).geometry.iloc[0])], crop=True,
                                     filled=True, nodata=0)
            profile = src.profile.copy()
            profile.update(driver="GTiff", height=arrays.shape[1], width=arrays.shape[2], transform=transform,
                           compress="deflate", predictor=2, tiled=True, nodata=0)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(dst, "w", **profile) as target:
                target.write(arrays)
            if int(np.count_nonzero(arrays[0] == 40)) == 0:
                raise ValueError("WorldCover clipped raster contains no class 40 cropland pixels")
            cropland = (arrays == 40).astype(np.uint8)
            mask_profile = profile.copy(); mask_profile.update(dtype="uint8", nodata=0)
            with rasterio.open(mask_path, "w", **mask_profile) as target:
                target.write(cropland)
        crop_pixels = int(np.count_nonzero(cropland))
        if fields_gdf is not None:
            gdf = fields_gdf.copy()
            fractions = []
            with rasterio.open(dst) as src:
                for geom in gdf.to_crs(src.crs).geometry:
                    try:
                        one, _ = mask(src, [mapping(geom)], crop=True, filled=False)
                        vals = one[0].compressed()
                        fractions.append(float(np.count_nonzero(vals == 40) / len(vals)) if len(vals) else None)
                    except ValueError:
                        fractions.append(None)
            gdf["cropland_fraction"] = fractions
            field_out = REAL / "fields" / "fields_of_the_world_muktsar.parquet"
            gdf.to_parquet(field_out, index=False)
        record_dataset("worldcover", "real_downloaded", source_provider="Microsoft Planetary Computer / ESA",
                       source_dataset=collection.id, paths=[dst, mask_path],
                       metadata={"item_id": item.id, "collection": collection.id, "year": 2021,
                                 "class_code_cropland": 40, "cropland_pixels": crop_pixels,
                                 "crs": str(profile["crs"]), "scale_units": "categorical class code",
                                 "download_strategy": "AOI-clipped COG window"},
                       license_ref="ESA WorldCover data policy; https://esa-worldcover.org/en/data-access")
        return dst
    except Exception as exc:
        record_dataset("worldcover", "download_failed", source_provider="Microsoft Planetary Computer / ESA",
                       source_dataset="esa-worldcover", warnings=[f"{type(exc).__name__}: {exc}"])
        raise


def weather(force: bool = False):
    hourly_path = REAL / "weather" / "weather_hourly.parquet"
    daily_path = REAL / "weather" / "weather_daily.parquet"
    if should_skip("weather", force) and hourly_path.exists() and daily_path.exists():
        return pd.read_parquet(hourly_path)
    try:
        district_path = REAL / "boundaries" / "sri_muktsar_sahib_adm2.geojson"
        import geopandas as gpd
        district = gpd.read_file(district_path).to_crs("EPSG:4326").geometry.iloc[0]
        minx, miny, maxx, maxy = district.bounds
        candidates = []
        for lat in np.arange(math.floor(miny * 4) / 4, maxy + 0.125, 0.25):
            for lon in np.arange(math.floor(minx * 4) / 4, maxx + 0.125, 0.25):
                p = Point(float(lon + 0.125), float(lat + 0.125))
                if district.intersects(p): candidates.append((round(p.y, 3), round(p.x, 3)))
        if not candidates:
            p = district.representative_point(); candidates = [(round(p.y, 3), round(p.x, 3))]
        # ERA5's ~25 km grid is coarse; query no more than six representative points.
        points = candidates[:6]
        coords_lat = ",".join(str(x[0]) for x in points)
        coords_lon = ",".join(str(x[1]) for x in points)
        start = "2023-09-15"
        end = min(TODAY - timedelta(days=5), date(2026, 10, 7)).isoformat()
        params = {"latitude": coords_lat, "longitude": coords_lon, "start_date": start, "end_date": end,
                  "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
                  "models": "era5", "timezone": "UTC", "wind_speed_unit": "ms"}
        response = SESSION.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=(20, 120))
        payload = json.loads(safe_response(response, "json"))
        locations = payload if isinstance(payload, list) else [payload]
        rows = []
        for idx, loc in enumerate(locations):
            hourly = loc.get("hourly", {})
            n = len(hourly.get("time", []))
            for i in range(n):
                rows.append({"grid_id": idx, "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                             "timestamp": hourly["time"][i], "temperature_2m_c": hourly.get("temperature_2m", [None]*n)[i],
                             "relative_humidity_2m_pct": hourly.get("relative_humidity_2m", [None]*n)[i],
                             "precipitation_mm": hourly.get("precipitation", [None]*n)[i],
                             "wind_speed_10m_ms": hourly.get("wind_speed_10m", [None]*n)[i],
                             "source_provider": "Open-Meteo", "source_dataset": "ERA5 historical reanalysis",
                             "source_model": "era5", "record_type": "historical_reanalysis",
                             "real_or_synthetic": "REAL"})
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise ValueError("Open-Meteo returned no historical weather rows")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.sort_values(["grid_id", "timestamp"])
        frame["rain_previous_24h_mm"] = frame.groupby("grid_id")["precipitation_mm"].transform(lambda s: s.rolling(24, min_periods=1).sum())
        frame["rain_previous_72h_mm"] = frame.groupby("grid_id")["precipitation_mm"].transform(lambda s: s.rolling(72, min_periods=1).sum())
        frame["rain_previous_7d_mm"] = frame.groupby("grid_id")["precipitation_mm"].transform(lambda s: s.rolling(168, min_periods=1).sum())
        dry_counts = {}
        for gid, group in frame.groupby("grid_id"):
            daily_rain = group.set_index("timestamp")["precipitation_mm"].resample("1D").sum(min_count=1)
            dry_counts[gid] = (daily_rain.fillna(0).lt(1).astype("int8").rolling(7, min_periods=1).sum())
        frame["dry_days_previous_7d"] = [int(dry_counts[gid].get(ts.floor("D"), 0))
                                             for gid, ts in zip(frame.grid_id, frame.timestamp)]
        hourly_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(hourly_path, index=False)
        daily = frame.set_index("timestamp").groupby("grid_id").resample("1D").agg(
            latitude=("latitude", "first"), longitude=("longitude", "first"),
            precipitation_mm=("precipitation_mm", "sum"), temperature_mean_c=("temperature_2m_c", "mean"),
            humidity_mean_pct=("relative_humidity_2m_pct", "mean"), wind_mean_ms=("wind_speed_10m_ms", "mean"),
            rain_previous_24h_mm=("rain_previous_24h_mm", "last"), rain_previous_72h_mm=("rain_previous_72h_mm", "last"),
            rain_previous_7d_mm=("rain_previous_7d_mm", "last"), dry_days_previous_7d=("dry_days_previous_7d", "last"))
        daily = daily.reset_index()
        daily["source_provider"] = "Open-Meteo"; daily["source_dataset"] = "ERA5 historical reanalysis"
        daily["record_type"] = "historical_reanalysis"; daily["real_or_synthetic"] = "REAL"
        daily.to_parquet(daily_path, index=False)
        record_dataset("weather", "real_downloaded", source_provider="Open-Meteo",
                       source_dataset="Historical Weather API / ERA5", date_range={"start": start, "end": end},
                       paths=[hourly_path, daily_path], metadata={"hourly_records": int(len(frame)),
                           "daily_records": int(len(daily)), "grid_points": len(points), "grid_spacing_degrees": 0.25,
                           "units": {"temperature": "degC", "humidity": "%", "precipitation": "mm", "wind": "m/s"},
                           "note": "ERA5 grid-point reanalysis; not field-level station measurements."},
                       license_ref="Open-Meteo CC BY 4.0; https://open-meteo.com/en/terms")
        return frame
    except Exception as exc:
        record_dataset("weather", "download_failed", source_provider="Open-Meteo",
                       source_dataset="Historical Weather API / ERA5", warnings=[f"{type(exc).__name__}: {exc}"])
        raise


def scene_search(district_gdf, force: bool = False, year_filter: int | None = None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if should_skip("sentinel2_2023", force) and (REAL / "sentinel2" / "catalog.parquet").exists():
        return pd.read_parquet(REAL / "sentinel2" / "catalog.parquet")
    try:
        cat = stac_catalog()
        # Collection IDs are resolved from the current public catalog, not assumed silently.
        collection_ids = {c.id for c in cat.get_all_collections()}
        s2_id = "sentinel-2-l2a"
        if s2_id not in collection_ids:
            candidates = [x for x in collection_ids if "sentinel" in x.lower() and "2" in x and "l2a" in x.lower()]
            if not candidates: raise ValueError("No current Sentinel-2 L2A STAC collection found")
            s2_id = sorted(candidates)[0]
        rows = []
        years = (year_filter,) if year_filter else (2023, 2024, 2025, 2026)
        for year in years:
            start = date(year, 9, 15)
            end = min(date(year, 12, 15), TODAY) if year < 2026 else min(TODAY, date(year, 12, 15))
            if start > end:
                record_dataset(f"sentinel2_{year}", "not_applicable", source_provider="Microsoft Planetary Computer",
                               source_dataset=s2_id, date_range={"start": start.isoformat(), "end": end.isoformat()},
                               warnings=["Requested period has not begun as of acquisition date."])
                continue
            search = cat.search(collections=[s2_id], bbox=list(district_gdf.total_bounds),
                                datetime=f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
                                max_items=5000)
            items = list(search.items())
            items = [i for i in items if shape(i.geometry).intersects(district_gdf.geometry.iloc[0])
                     and (i.properties.get("eo:cloud_cover") is None or i.properties.get("eo:cloud_cover") < 31)]
            year_rows = []
            for item in items:
                props = item.properties
                dt = props.get("datetime") or props.get("start_datetime")
                if not dt: continue
                asset_meta = {}
                for key, asset in item.assets.items():
                    rb = asset.extra_fields.get("raster:bands") or [{}]
                    if isinstance(rb, list) and rb:
                        asset_meta[key] = {"scale": rb[0].get("scale"), "offset": rb[0].get("offset"),
                                           "unit": rb[0].get("unit"), "nodata": rb[0].get("nodata")}
                row = {"scene_id": item.id, "datetime": dt, "year": year,
                       "platform": props.get("platform"), "tile": props.get("s2:mgrs_tile"),
                       "cloud_cover": props.get("eo:cloud_cover"), "collection": s2_id,
                       "source_provider": "Microsoft Planetary Computer", "source_item_url": item.get_self_href(),
                       "assets": json.dumps({k: v.href for k, v in item.assets.items()}, sort_keys=True),
                       "asset_scales": json.dumps(asset_meta, sort_keys=True), "real_or_synthetic": "REAL"}
                rows.append(row); year_rows.append(row)
            status = "real_remote_processed" if year_rows else "provider_unavailable"
            record_dataset(f"sentinel2_{year}", status, source_provider="Microsoft Planetary Computer",
                           source_dataset=s2_id, date_range={"start": start.isoformat(), "end": end.isoformat()},
                           metadata={"scene_count": len(year_rows), "collection_id": s2_id,
                                     "cloud_cover_filter_pct": 30, "catalog_only": True,
                                     "item_ids": [x["scene_id"] for x in year_rows]},
                           warnings=[] if year_rows else ["No Sentinel-2 items matched the district/date/cloud query."])
        frame = pd.DataFrame(rows)
        if frame.empty: raise ValueError("No Sentinel-2 items found for requested seasons")
        dst = REAL / "sentinel2" / "catalog.parquet"; dst.parent.mkdir(parents=True, exist_ok=True)
        if year_filter and dst.exists():
            prior = pd.read_parquet(dst)
            frame = pd.concat([prior.loc[prior.year != year_filter], frame], ignore_index=True).drop_duplicates("scene_id")
        frame.to_parquet(dst, index=False)
        csv_path = dst.with_suffix(".csv"); frame.to_csv(csv_path, index=False)
        record_dataset("sentinel2_catalog", "real_remote_processed", source_provider="Microsoft Planetary Computer",
                       source_dataset=s2_id, paths=[dst, csv_path], metadata={"scene_count": len(frame),
                       "counts_by_year": {str(y): int((frame.year == y).sum()) for y in frame.year.unique()},
                       "items_are_metadata_only": True})
        return frame
    except Exception as exc:
        for year in (2023, 2024, 2025, 2026):
            record_dataset(f"sentinel2_{year}", "download_failed", source_provider="Microsoft Planetary Computer",
                           source_dataset="sentinel-2-l2a", warnings=[f"{type(exc).__name__}: {exc}"])
        raise


def unavailable_optional_sources() -> None:
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        record_dataset("firms", "credential_required", source_provider="NASA FIRMS",
                       source_dataset="VIIRS NOAA-20/21 and MODIS archive",
                       date_range={"start": "2023-09-15", "end": TODAY_ISO},
                       warnings=["FIRMS_MAP_KEY is not configured. The official Area API and historical Area API require a map key; no fixture points were copied."])
    else:
        record_dataset("firms", "pending", source_provider="NASA FIRMS", source_dataset="VIIRS archive",
                       warnings=["Key detected; source acquisition implementation pending."])
    for key, source, dataset in [("modis_burned_area", "NASA LP DAAC / Microsoft Planetary Computer", "MCD64A1.061"),
                                 ("sentinel1", "Microsoft Planetary Computer", "sentinel-1-rtc")]:
        if should_skip(key, False): continue
        record_dataset(key, "pending", source_provider=source, source_dataset=dataset,
                       warnings=["Pending this acquisition runner pass; no synthetic substitute is used."])


def run(source: str = "all", force: bool = False, year_filter: int | None = None) -> None:
    # State was read before any source/API request.
    state = load_state()
    LOG.info("Resume from state updated_at=%s", state.get("updated_at"))
    district = None
    if source in ("all", "boundary", "fields", "worldcover", "sentinel2"):
        try:
            district = boundary_gdf(force)
        except Exception:
            LOG.exception("District boundary acquisition failed; other independent sources continue")
    fields = None
    if district is not None and source in ("all", "fields", "worldcover"):
        try: fields = field_boundaries(district, force)
        except Exception: LOG.exception("Research field polygon acquisition failed")
    if district is not None and source in ("all", "worldcover"):
        try: worldcover(district, fields, force)
        except Exception: LOG.exception("ESA WorldCover acquisition failed")
    if source in ("all", "weather"):
        try: weather(force)
        except Exception: LOG.exception("Weather acquisition failed")
    if district is not None and source in ("all", "sentinel2"):
        try: scene_search(district, force, year_filter)
        except Exception: LOG.exception("Sentinel-2 search/metadata acquisition failed")
    if source in ("all", "firms", "modis", "sentinel1"):
        unavailable_optional_sources()
    if source in ("all", "modis", "sentinel1"):
        try:
            from scripts.acquire_real_context import run as acquire_context
            acquire_context(force=force)
        except Exception:
            LOG.exception("MODIS/Sentinel-1 real context acquisition failed")
    if source in ("all", "sentinel2") and (REAL / "sentinel2" / "catalog.parquet").exists():
        try:
            from scripts.process_real_sentinel2 import run as process_s2
            obs_path, sampled_fields = process_s2(year_filter=year_filter, force=force)
            observations = pd.read_parquet(obs_path)
            previews = list((REAL / "derived" / "previews").glob("*.png"))
            catalog = pd.read_parquet(REAL / "sentinel2" / "catalog.parquet")
            observed_years = set()
            for year, group in observations.groupby("year"):
                year = int(year); observed_years.add(year)
                record_dataset(f"sentinel2_{year}", "real_derived", source_provider="Microsoft Planetary Computer",
                    source_dataset="Sentinel-2 L2A field-level surface reflectance and index reductions",
                    date_range={"start":f"{year}-09-15","end":min(f"{year}-12-15",TODAY_ISO)},
                    paths=[obs_path] + previews, metadata={"catalog_item_count":int((catalog.year==year).sum()),
                    "field_observations":len(group),"observed_fields":int(group.field_id.nunique()),"scale":0.0001,
                    "cloud_mask":"SCL classes 4,5,6","sampled_field_count":len(sampled_fields),"indices":["NDVI","NBR","BAIS2"]},
                    license_ref="Copernicus Sentinel data; https://dataspace.copernicus.eu/terms-and-conditions")
            for year in ([year_filter] if year_filter else (2023,2024,2025,2026)):
                if year in observed_years: continue
                scene_count = int((catalog.year==year).sum()) if not catalog.empty else 0
                record_dataset(f"sentinel2_{year}", "partial_real" if scene_count else "provider_unavailable",
                    source_provider="Microsoft Planetary Computer", source_dataset="Sentinel-2 L2A",
                    date_range={"start":f"{year}-09-15","end":min(f"{year}-12-15",TODAY_ISO)},
                    paths=[REAL / "sentinel2" / "catalog.parquet"] if scene_count else [],
                    metadata={"catalog_item_count":scene_count,"field_observations":0},
                    warnings=["Scene metadata was available, but no validated field-level observations were produced for this season."])
            from scripts.build_real_products import build as build_products
            products = build_products()
            record_dataset("app_import", "real_derived", source_provider="Parali se Paisa API",
                source_dataset="Read-only app snapshot; enabled with DATA_MODE=real",
                paths=[REAL / "derived" / "app_snapshot.json"],
                metadata={"display_fields":int(products["fields"]),"satellite_observations":int(products["rows"]),
                          "mode_switch":"DATA_MODE=real","ground_truth":False})
        except Exception as exc:
            LOG.exception("Sentinel-2 field reduction or real derived products failed")
            for year in (2023,2024,2025,2026):
                saved=load_state().get("datasets",{}).get(f"sentinel2_{year}",{}).get("status")
                if saved not in {"real_derived","real_remote_processed"}:
                    record_dataset(f"sentinel2_{year}","download_failed",source_provider="Microsoft Planetary Computer",
                                   source_dataset="Sentinel-2 L2A",warnings=[f"{type(exc).__name__}: {exc}"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire real Muktsar data; never imports demo fixtures.")
    parser.add_argument("--resume", action="store_true", help="Resume; successfully recorded datasets are skipped (default).")
    parser.add_argument("--force", action="store_true", help="Requery/reprocess completed products.")
    parser.add_argument("--source", default="all", choices=["all", "boundary", "fields", "worldcover", "sentinel2", "weather", "firms", "modis", "sentinel1"])
    parser.add_argument("--year", type=int, choices=[2023, 2024, 2025, 2026], help="Restrict Sentinel-2 scene search and processing to one harvest season year.")
    parser.add_argument("--no-reports", action="store_true", help="Skip the final validation/report pass.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Ensure the initialized manifests exist, and strictly read acquisition state before continuing.
    if not STATE_PATH.exists() or not MANIFEST_PATH.exists():
        raise FileNotFoundError("Initialize data/real/acquisition_state.json and DATASET_MANIFEST.json before running")
    load_state()
    run(args.source, args.force, args.year)
    if not args.no_reports:
        from scripts.validate_real_data import build_reports
        build_reports()


if __name__ == "__main__":
    main()
