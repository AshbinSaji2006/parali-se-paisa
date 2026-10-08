"""Windowed COG Sentinel-2 processing for Muktsar research fields."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import planetary_computer as pc
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data" / "real"
PROCESSING_VERSION = "grid-aligned-20m-v5-nd-nonnegative"
# Reflectance floor for BAIS2 pixels (see BAIS2 comment in field_statistics()); applies to new reductions only.
BAIS2_MIN_B04 = 0.005
INDEX_BANDS = ["B04", "B06", "B07", "B08", "B8A", "B12"]
SCL_VALID = (4, 5, 6)
# Harvest-season window per year; the live season runs to the latest local acquisition.
SEASON_WINDOW = ("09-15", "12-15")
STACK = REAL / "s2_stack"
STACK_NODATA = -32768


def _read_aligned_band(src, reference_crs, transform, width, height, *, categorical=False):
    """Read a band on the exact 20 m reference grid used to rasterize fields."""
    method = Resampling.nearest if categorical else Resampling.average
    with WarpedVRT(src, crs=reference_crs, transform=transform, width=width, height=height,
                   resampling=method, dtype=src.dtypes[0]) as vrt:
        return vrt.read(1)


def field_statistics(refl: dict[str, np.ndarray], valid: np.ndarray, zones: np.ndarray, n_zones: int) -> dict:
    """Per-field v5 means for one scene, shared by the remote and local-stack paths.

    ``refl`` holds harmonised B04/B06/B07/B08/B8A/B12 reflectance on one 20 m grid and
    ``valid`` already excludes nodata and SCL classes other than 4/5/6. Arrays may be the
    full window or only the field pixels; zone 0 is background.
    """
    valid = valid & (zones > 0)
    valid &= np.logical_and.reduce([np.isfinite(v) & (v > -0.05) & (v <= 1.5) for v in refl.values()])
    b4, b6, b7, b8, b8a, b12 = (refl[k] for k in INDEX_BANDS)
    ndvi_den = b8 + b4; nbr_den = b8 + b12; bais_den = np.sqrt(np.maximum(b12 + b8a, 0))
    # v5: a normalized difference is only bounded to [-1, 1] when both bands are non-negative.
    # Slightly negative post-offset reflectance (atmospheric over-correction of dark pixels) is
    # kept for the band means, but such pixels do not enter the NDVI/NBR means.
    ndvi_ok = (b8 >= 0) & (b4 >= 0) & (ndvi_den > 0)
    nbr_ok = (b8 >= 0) & (b12 >= 0) & (nbr_den > 0)
    ndvi = np.divide(b8-b4, ndvi_den, out=np.full_like(b8, np.nan), where=ndvi_ok)
    nbr = np.divide(b8-b12, nbr_den, out=np.full_like(b8, np.nan), where=nbr_ok)
    # BAIS2 divides by B04. The valid mask admits slightly negative post-offset
    # reflectance, and a near-zero red pixel would dominate the field mean, so
    # BAIS2 is only computed where B04 is physically meaningful.
    bais2_ok = b4 >= BAIS2_MIN_B04
    bais2 = np.where(bais2_ok, (1-np.sqrt(np.maximum(b6*b7*b8a/np.maximum(b4, BAIS2_MIN_B04), 0))) * ((b12-b8a)/np.maximum(bais_den, 1e-8)+1), np.nan)
    size = n_zones + 1

    def means(a):
        finite = valid & np.isfinite(a)
        zz = zones[finite].ravel().astype(np.int64)
        n = np.bincount(zz, minlength=size)
        return np.divide(np.bincount(zz, weights=a[finite].ravel(), minlength=size), n,
                         out=np.full(size, np.nan), where=n > 0)

    return {"counts": np.bincount(zones[valid].ravel().astype(np.int64), minlength=size),
            "zone_pixels": np.bincount(zones.ravel().astype(np.int64), minlength=size),
            "bais2_counts": np.bincount(zones[valid & bais2_ok].ravel().astype(np.int64), minlength=size),
            "means": {key: means(arr) for key, arr in {"B04": b4, "B06": b6, "B07": b7, "B08": b8, "B8A": b8a, "B12": b12,
                                                       "ndvi": ndvi, "nbr": nbr, "bais2": bais2}.items()}}


def observation_row(field, idx: int, stats: dict, provenance: dict) -> dict | None:
    """One v5 field-date row, or None when fewer than 3 clear pixels were observed."""
    count, total = int(stats["counts"][idx]), int(stats["zone_pixels"][idx])
    if count < 3:
        return None
    row = {"field_id": field.field_id, **provenance, "processing_version": PROCESSING_VERSION,
           "valid_pixel_count": count, "area_ha": float(field.area_ha),
           "valid_pixel_fraction": float(count / total) if total else None,
           "cloud_fraction": float(1 - count / total) if total else None,
           "observation_quality": "GOOD" if count >= 10 and count / max(total, 1) >= 0.5 else "POOR",
           "cropland_fraction": field.get("cropland_fraction", None),
           "reflectance_scale": 0.0001, "scl_valid_classes": ",".join(map(str, SCL_VALID)),
           "bais2_valid_pixel_count": int(stats["bais2_counts"][idx]), "bais2_min_b04": BAIS2_MIN_B04,
           "real_or_synthetic": "REAL"}
    row.update({f"{k.lower()}_mean": float(v[idx]) for k, v in stats["means"].items()})
    row["NDVI"] = row.pop("ndvi_mean"); row["NBR"] = row.pop("nbr_mean"); row["BAIS2"] = row.pop("bais2_mean")
    row["NDVI_mean"] = row["NDVI"]; row["NBR_mean"] = row["NBR"]; row["BAIS2_mean"] = row["BAIS2"]
    return row


def sample_fields(fields: gpd.GeoDataFrame, limit: int = 600) -> gpd.GeoDataFrame:
    """Choose a spatially spread, deterministic subset to bound zonal work."""
    g = fields.to_crs("EPSG:4326").copy()
    cent = g.to_crs("EPSG:32643").geometry.centroid.to_crs("EPSG:4326")
    # 0.05 degree cells; choose up to 4 fields/cell by real area.
    g["_cell"] = (np.floor(cent.y * 20).astype(int).astype(str) + ":" +
                  np.floor(cent.x * 20).astype(int).astype(str))
    g = g.sort_values(["_cell", "area_ha", "field_id"], ascending=[True, False, True])
    g["_cell_rank"] = g.groupby("_cell").cumcount()
    g = g[g["_cell_rank"] < 4]
    if len(g) > limit:
        g = g.sort_values("field_id").iloc[np.linspace(0, len(g) - 1, limit, dtype=int)]
    return g.drop(columns=["_cell", "_cell_rank"]).reset_index(drop=True)


def choose_scenes(catalog: pd.DataFrame) -> pd.DataFrame:
    f = catalog.copy()
    f["datetime"] = pd.to_datetime(f["datetime"], utc=True)
    f["day"] = f["datetime"].dt.strftime("%Y-%m-%d")
    # Duplicate L2A reprocessings share acquisition time and tile. Keep the lowest-cloud item.
    f = (f.sort_values(["cloud_cover", "scene_id"], na_position="last")
           .drop_duplicates(["day", "tile"], keep="first"))
    chosen = []
    for year, rows in f.groupby("year"):
        rows = rows.sort_values("datetime").copy()
        # Two acquisition windows per season keep live COG access bounded while
        # preserving an early-season and post-harvest observation.
        rows["season_bin"] = np.where(rows.datetime.dt.dayofyear < 300, "early", "late")
        for _, group in rows.groupby("season_bin"):
            chosen.extend(group.sort_values("cloud_cover", na_position="last").head(1).index.tolist())
    return f.loc[chosen].sort_values(["year", "datetime", "tile"]).drop(columns=["day", "season_bin"], errors="ignore")


def run(year_filter: int | None = None, force: bool = False) -> tuple[Path, gpd.GeoDataFrame]:
    status_path = REAL / "acquisition_state.json"
    output_path = REAL / "derived" / "features" / "sentinel2_field_observations.parquet"
    if not force and output_path.exists() and status_path.exists():
        state = json.loads(status_path.read_text(encoding="utf-8")).get("datasets", {})
        requested = [year_filter] if year_filter else [2023, 2024, 2025, 2026]
        if all(state.get(f"sentinel2_{y}", {}).get("status") == "real_derived" for y in requested):
            fields = gpd.read_parquet(REAL / "fields" / "fields_of_the_world_muktsar.parquet")
            return output_path, sample_fields(fields)
    fields = gpd.read_parquet(REAL / "fields" / "fields_of_the_world_muktsar.parquet")
    fields = sample_fields(fields)
    catalog = pd.read_parquet(REAL / "sentinel2" / "catalog.parquet")
    scenes = choose_scenes(catalog)
    if year_filter is not None:
        scenes = scenes.loc[scenes.year == year_filter].copy()
    rows: list[dict] = []
    done_ids: set[str] = set()
    if year_filter is not None and output_path.exists():
        try:
            previous = pd.read_parquet(output_path)
            other_years = previous.loc[previous.year != year_filter]
            if "processing_version" in other_years:
                other_years = other_years.loc[other_years.processing_version == PROCESSING_VERSION]
            else:
                other_years = other_years.iloc[:0]
            rows.extend(other_years.to_dict("records"))
            done_ids.update(other_years.scene_id.astype(str))
        except Exception:
            pass
    partial_path = REAL / "derived" / "features" / "sentinel2_field_observations.partial.parquet"
    if partial_path.exists():
        try:
            old = pd.read_parquet(partial_path)
            if "processing_version" in old:
                old = old.loc[old.processing_version == PROCESSING_VERSION]
            else:
                # Cached v1 observations mixed 10 m B08 with a 20 m zone mask.
                # Do not reuse them after introducing a common reference grid.
                old = old.iloc[:0]
            rows.extend(old.to_dict("records"))
            done_ids.update(old.scene_id.astype(str))
        except Exception:
            done_ids = set()
    else:
        done_ids = set()
    # Rehydrate only the selected scene items. Searching every scene over four
    # seasons makes a small cached rebuild needlessly slow and increases API load.
    from pystac_client import Client
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    collection = cat.get_collection("sentinel-2-l2a")
    ids = set(scenes.scene_id.astype(str))
    items = {}
    for scene_id in sorted(ids):
        try:
            items[scene_id] = collection.get_item(scene_id)
        except Exception as exc:
            print(f"ITEM_FAILED {scene_id} {type(exc).__name__}: {exc}", flush=True)

    preview_count = 0
    for _, scene in scenes.iterrows():
        if str(scene.scene_id) in done_ids:
            continue
        item = items.get(str(scene.scene_id))
        if item is None:
            print(f"ITEM_UNAVAILABLE {scene.scene_id}", flush=True)
            continue
        print(f"PROCESSING_SCENE {scene.scene_id}", flush=True)
        required = ["B04", "B06", "B07", "B08", "B8A", "B12", "SCL"]
        missing = [k for k in required if k not in item.assets]
        if missing:
            continue
        try:
            # Sentinel-2 assets are stored in a protected Azure blob container;
            # use short-lived provider-issued SAS URLs and never persist the token.
            source_hrefs = {k: item.assets[k].href for k in required}
            hrefs = {k: pc.sign_url(url) for k, url in source_hrefs.items()}
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
                with rasterio.open(hrefs["B06"]) as ref:
                    field_proj = fields.to_crs(ref.crs)
                    district = gpd.read_file(REAL / "boundaries" / "sri_muktsar_sahib_adm2.geojson").to_crs(ref.crs).geometry.iloc[0]
                    bounds = district.bounds
                    win = from_bounds(*bounds, transform=ref.transform).round_offsets().round_lengths()
                    x0, y0 = max(0, int(win.col_off)), max(0, int(win.row_off))
                    x1, y1 = min(ref.width, int(win.col_off + win.width)), min(ref.height, int(win.row_off + win.height))
                    if x1 <= x0 or y1 <= y0:
                        continue
                    win = Window(x0, y0, x1-x0, y1-y0)
                    transform = window_transform(win, ref.transform)
                    h, w = int(win.height), int(win.width)
                    tile_geom = box(*rasterio.transform.array_bounds(h, w, transform))
                    local = field_proj[field_proj.geometry.intersects(tile_geom)].copy()
                    if local.empty:
                        continue
                    local["_zid"] = np.arange(1, len(local) + 1, dtype=np.int32)
                    zones = rasterize(((geom, int(zid)) for geom, zid in zip(local.geometry, local._zid)),
                                      out_shape=(h, w), transform=transform, fill=0, dtype="int32", all_touched=False)
                    data: dict[str, np.ndarray] = {}
                    for band in required:
                        with rasterio.open(hrefs[band]) as src:
                            # B04/B08 are native 10 m; B06/B07/B8A/B12/SCL are
                            # native 20 m. All must align to B06's 20 m grid before
                            # pixel-wise indices or zonal masks are computed.
                            data[band] = _read_aligned_band(
                                src, ref.crs, transform, w, h, categorical=(band == "SCL"))
                    # Sentinel-2 L2A reflectance = (DN + BOA_ADD_OFFSET) / 10000. Since processing
                    # baseline 04.00 (25 Jan 2022) BOA_ADD_OFFSET is -1000; earlier products have no
                    # offset. Planetary Computer serves the original DN, so harmonise per item.
                    scl = data.pop("SCL")
                    baseline = float(item.properties.get("s2:processing_baseline", "0") or 0)
                    boa_offset = 1000.0 if baseline >= 4.0 else 0.0
                    valid = np.isin(scl, SCL_VALID) & np.logical_and.reduce([v > 0 for v in data.values()])  # DN 0 = nodata
                    refl = {k: (v.astype(np.float32) - boa_offset) / 10000.0 for k, v in data.items()}
                    stats = field_statistics(refl, valid, zones, len(local))
                    provenance = {"observation_datetime": pd.Timestamp(item.datetime).isoformat(), "year": int(scene.year),
                                  "scene_id": item.id, "collection": "sentinel-2-l2a", "tile": scene.tile,
                                  "source_provider": "Microsoft Planetary Computer", "source_item_url": item.get_self_href(),
                                  "source_asset_urls": json.dumps(source_hrefs, sort_keys=True), "cloud_cover_pct": scene.cloud_cover,
                                  "processing_baseline": baseline, "boa_offset_dn": boa_offset,
                                  "processing_source": "REMOTE_COG_WINDOW"}
                    for idx, (_, field) in enumerate(local.iterrows(), start=1):
                        row = observation_row(field, idx, stats, provenance)
                        if row is not None:
                            rows.append(row)
                    # Keep one true pixel-derived, district-window NDVI preview per year.
                    if preview_count < 4:
                        import matplotlib.pyplot as plt
                        b4, b8 = refl["B04"], refl["B08"]
                        ndvi = np.divide(b8-b4, b8+b4, out=np.full_like(b8, np.nan), where=(b8+b4) != 0)
                        img = np.where(valid & (zones > 0), ndvi, np.nan)
                        out = REAL / "derived" / "previews" / f"ndvi_{scene.year}_{str(scene.scene_id)[:32]}.png"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        fig, ax = plt.subplots(figsize=(6, 5)); ax.imshow(img, cmap="RdYlGn", vmin=-1, vmax=1); ax.set_axis_off()
                        fig.savefig(out, dpi=120, bbox_inches="tight"); plt.close(fig); preview_count += 1
                    if rows:
                        partial_path.parent.mkdir(parents=True, exist_ok=True)
                        tmp = partial_path.with_suffix(".tmp.parquet")
                        pd.DataFrame(rows).to_parquet(tmp, index=False)
                        os.replace(tmp, partial_path)
                        done_ids.add(str(scene.scene_id))
        except Exception as exc:
            print(f"SCENE_FAILED {scene.scene_id} {type(exc).__name__}: {exc}")

    if not rows:
        raise RuntimeError("No valid Sentinel-2 field observations were produced")
    result = pd.DataFrame(rows).sort_values(["field_id", "observation_datetime"]).drop_duplicates(["field_id", "observation_datetime"], keep="first")
    out = REAL / "derived" / "features" / "sentinel2_field_observations.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(out, index=False)
    partial_path.unlink(missing_ok=True)
    return out, fields


def local_stack_scenes(years=(2023, 2024, 2025, 2026)) -> pd.DataFrame:
    """Harmonised local acquisitions (download_s2_stack.py) inside each season window."""
    rows = []
    for year in years:
        start, end = (pd.Timestamp(f"{year}-{d}", tz="UTC") for d in SEASON_WINDOW)
        for meta_path in sorted((STACK / str(year)).glob("S2_*_43RDP.json")):
            tif = meta_path.with_suffix(".tif")
            if not tif.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            when = pd.Timestamp(meta["datetime"]).tz_convert("UTC")
            if start <= when < end + pd.Timedelta(days=1):
                rows.append({"year": year, "datetime": when, "path": tif, "meta": meta})
    return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True) if rows else pd.DataFrame()


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_local_stack(years=(2023, 2024, 2025, 2026)) -> tuple[Path, pd.DataFrame]:
    """Reduce every local harmonised scene in the season windows with the v5 rules.

    The stacks already hold (DN - BOA_ADD_OFFSET) on the district 20 m grid, whose origin
    lies on tile 43RDP's 20 m B06 lattice, so the reflectance, SCL 4/5/6 mask, BAIS2 red
    floor and zonal means are the same as the remote path. No scene is interpolated or
    gap-filled: a field only gets a row when it has >= 3 clear pixels on that date.
    """
    scenes = local_stack_scenes(years)
    if scenes.empty:
        raise FileNotFoundError(f"No local Sentinel-2 stacks in {STACK.relative_to(ROOT)}; run scripts/download_s2_stack.py")
    with rasterio.open(scenes.path.iloc[0]) as ref:
        crs, transform, width, height = ref.crs, ref.transform, ref.width, ref.height
        names = list(ref.descriptions)
    band_index = {name: names.index(name) + 1 for name in [*INDEX_BANDS, "SCL"]}
    fields = sample_fields(gpd.read_parquet(REAL / "fields" / "fields_of_the_world_muktsar.parquet")).to_crs(crs)
    grid = np.zeros((height, width), dtype=np.int32)
    zones = rasterize(((geom, i) for i, geom in enumerate(fields.geometry, start=1)), out=grid,
                      transform=transform, fill=0, all_touched=False)
    pixels = np.flatnonzero(zones.ravel())
    zone_vector = zones.ravel()[pixels]
    rows: list[dict] = []
    for scene in scenes.itertuples():
        meta = scene.meta
        with rasterio.open(scene.path) as src:
            if src.crs != crs or src.transform != transform or (src.width, src.height) != (width, height):
                raise ValueError(f"{scene.path.name} is not on the common stack grid")
            data = {name: src.read(i).ravel()[pixels] for name, i in band_index.items()}
        scl = data.pop("SCL")
        valid = np.isin(scl, SCL_VALID) & np.logical_and.reduce([v != STACK_NODATA for v in data.values()])
        refl = {k: v.astype(np.float32) / 10000.0 for k, v in data.items()}
        stats = field_statistics(refl, valid, zone_vector, len(fields))
        provenance = {"observation_datetime": scene.datetime.isoformat(), "year": int(scene.year),
                      "scene_id": meta["item_id"], "collection": "sentinel-2-l2a", "tile": meta["tile"],
                      "source_provider": "Microsoft Planetary Computer", "source_item_url": meta["source_item_url"],
                      "source_asset_urls": json.dumps(meta["source_asset_urls"], sort_keys=True),
                      "cloud_cover_pct": meta["tile_cloud_cover"], "platform": meta.get("platform"),
                      "processing_baseline": float(meta["processing_baseline"]), "boa_offset_dn": float(meta["harmonised_offset_dn"]),
                      "processing_source": "LOCAL_HARMONISED_STACK",
                      "source_raster": scene.path.relative_to(ROOT).as_posix(), "source_raster_sha256": _sha256(scene.path)}
        before = len(rows)
        for idx, (_, field) in enumerate(fields.iterrows(), start=1):
            row = observation_row(field, idx, stats, provenance)
            if row is not None:
                rows.append(row)
        print(f"LOCAL_SCENE {meta['item_id']} rows={len(rows) - before}", flush=True)
    result = (pd.DataFrame(rows).sort_values(["field_id", "observation_datetime"])
              .drop_duplicates(["field_id", "observation_datetime"], keep="first").reset_index(drop=True))
    out = REAL / "derived" / "features" / "sentinel2_field_observations.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(out, index=False)
    return out, scenes


def record_local_stack(out: Path, scenes: pd.DataFrame) -> None:
    """Record per-season acquisition state for a local-stack reduction."""
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.acquire_real_data import record_dataset
    obs = pd.read_parquet(out)
    for year, group in obs.groupby("year"):
        season = scenes.loc[scenes.year == year]
        record_dataset(f"sentinel2_{int(year)}", "real_derived", source_provider="Microsoft Planetary Computer",
                       source_dataset="Sentinel-2 L2A field-level surface reflectance and index reductions",
                       date_range={"start": f"{int(year)}-{SEASON_WINDOW[0]}", "end": season.datetime.max().date().isoformat()},
                       paths=[out], metadata={"processing_version": PROCESSING_VERSION, "processing_source": "LOCAL_HARMONISED_STACK",
                                              "scenes_processed": int(len(season)), "scene_ids": [m["item_id"] for m in season.meta],
                                              "field_observations": int(len(group)), "observed_fields": int(group.field_id.nunique()),
                                              "scale": 0.0001, "cloud_mask": "SCL classes 4,5,6", "indices": ["NDVI", "NBR", "BAIS2"],
                                              "minimum_clear_pixels": 3},
                       license_ref="Copernicus Sentinel data; https://dataspace.copernicus.eu/terms-and-conditions")


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",type=int,choices=[2023,2024,2025,2026])
    parser.add_argument("--local-stack", action="store_true",
                        help="Reduce every local harmonised scene (data/real/s2_stack) in the season windows instead of two remote scenes per season.")
    args=parser.parse_args()
    if args.local_stack and args.year:
        parser.error("--local-stack rewrites every season; omit --year")
    if args.local_stack:
        p, used = run_local_stack()
        record_local_stack(p, used)
        obs = pd.read_parquet(p)
        print(f"Wrote {p}: scenes={len(used)} fields={obs.field_id.nunique()} observations={len(obs)}")
    else:
        p, f = run(args.year)
        print(f"Wrote {p}: fields={f.field_id.nunique()} observations={pd.read_parquet(p).shape[0]}")
