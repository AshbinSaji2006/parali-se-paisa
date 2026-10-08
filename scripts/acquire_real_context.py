"""Acquire public MODIS burned-area evidence and Sentinel-1 scene metadata."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import planetary_computer as pc
from rasterio.mask import mask
from shapely.geometry import mapping
from pyproj import Transformer
from pystac_client import Client

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.acquire_real_data import REAL, TODAY, TODAY_ISO, load_state, record_dataset


def run(force: bool = False) -> None:
    saved = load_state().get("datasets", {})
    if not force and saved.get("modis_burned_area", {}).get("status") == "real_downloaded" and \
       saved.get("sentinel1", {}).get("status") == "real_remote_processed" and \
       (REAL / "burned_area" / "mcd64a1_muktsar.parquet").exists() and \
       (REAL / "sentinel1" / "sentinel1_scene_catalog.parquet").exists():
        return
    district_gdf = gpd.read_file(REAL / "boundaries" / "sri_muktsar_sahib_adm2.geojson").to_crs("EPSG:4326")
    geom = district_gdf.geometry.iloc[0]
    bbox = list(district_gdf.total_bounds)
    catalog = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")

    # Monthly MODIS MCD64A1 COGs; crop window only, no full-tile downloads.
    end = min(TODAY - timedelta(days=5), date(2026, 10, 7)).isoformat()
    burned_rows, burn_pixels = [], []
    try:
        search = catalog.search(collections=["modis-64A1-061"], bbox=bbox,
                                datetime=f"2023-09-15T00:00:00Z/{end}T23:59:59Z", max_items=1000)
        for item in search.items():
            try:
                # Monthly product item ID uses AYYYYDDD for its first day.
                product_token = item.id.split(".A", 1)[1]
                year = int(product_token[:4]); start_doy_from_id = int(product_token[4:7])
                product_start = date(year, 1, 1) + timedelta(days=start_doy_from_id-1)
                if product_start < date(year, 9, 1) or product_start > date(year, 12, 15):
                    continue
                if "Burn_Date" not in item.assets:
                    continue
                with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
                    with rasterio.open(pc.sign_url(item.assets["Burn_Date"].href)) as src:
                        district = district_gdf.to_crs(src.crs).geometry.iloc[0]
                        data, transform = mask(src, [mapping(district)], crop=True, indexes=1, filled=False)
                        vals = data.data
                        valid = ~np.ma.getmaskarray(data)
                        burned = valid & (vals > 0) & (vals <= 366)
                        # MCD64A1 reports annual day-of-year values. Product range tags
                        # limit each monthly composite to its actual observation window.
                        tags = src.tags()
                        start_doy = int(tags.get("ProductStartDay", "1"))
                        end_doy = int(tags.get("ProductEndDay", "366"))
                        burned &= (vals >= start_doy) & (vals <= end_doy)
                        yy, xx = np.where(burned)
                        if len(xx):
                            coords_x, coords_y = rasterio.transform.xy(transform, yy, xx, offset="center")
                            to_lonlat = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
                            lon, lat = to_lonlat.transform(coords_x, coords_y)
                            kept = []
                            for j in range(len(xx)):
                                doy = int(vals[yy[j], xx[j]])
                                d = date(year, 1, 1) + timedelta(days=doy-1)
                                season_end = min(date(year, 12, 15), TODAY - timedelta(days=5)) if year == TODAY.year else date(year, 12, 15)
                                if not date(year, 9, 15) <= d <= season_end:
                                    continue
                                kept.append(j)
                                burn_pixels.append({"source_item_id": item.id, "burn_date": d.isoformat(),
                                    "burn_doy": doy, "longitude": float(lon[j]), "latitude": float(lat[j]),
                                    "nominal_pixel_area_m2": 250000, "source_provider": "NASA LP DAAC / Microsoft Planetary Computer",
                                    "source_collection": "MCD64A1.061", "source_url": item.assets["Burn_Date"].href,
                                    "real_or_synthetic": "REAL"})
                        burned_rows.append({"source_item_id": item.id, "product_year": year,
                            "product_start_doy": start_doy, "product_end_doy": end_doy,
                            "tile": item.id.split(".")[2], "burned_pixels_in_aoi": int(len(kept) if len(xx) else 0),
                            "burned_area_km2_nominal": float((len(kept) if len(xx) else 0)*0.25),
                            "source_provider": "NASA LP DAAC / Microsoft Planetary Computer",
                            "source_dataset": "MCD64A1.061 Burn_Date", "source_url": item.assets["Burn_Date"].href,
                            "crs": str(src.crs), "resolution_m": 500, "real_or_synthetic": "REAL"})
            except Exception as exc:
                print(f"MODIS_ITEM_FAILED {item.id}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        record_dataset("modis_burned_area", "download_failed", source_provider="NASA LP DAAC / Microsoft Planetary Computer",
                       source_dataset="MCD64A1.061", warnings=[f"{type(exc).__name__}: {exc}"])
        burned_rows = []

    modis_path = REAL / "burned_area" / "mcd64a1_muktsar.parquet"
    pixels_path = REAL / "burned_area" / "mcd64a1_burn_pixels.parquet"
    if burned_rows:
        frame = pd.DataFrame(burned_rows)
        frame.to_parquet(modis_path, index=False)
        pd.DataFrame(burn_pixels).to_parquet(pixels_path, index=False)
        actual_dates = [r["burn_date"] for r in burn_pixels]
        product_years = sorted(frame.product_year.unique().tolist())
        warnings = [] if max(product_years, default=0) >= TODAY.year else [f"Provider season coverage ends in {max(product_years, default=0)}; later harvest composites are not yet available."]
        record_dataset("modis_burned_area", "real_downloaded", source_provider="NASA LP DAAC / Microsoft Planetary Computer",
            source_dataset="MCD64A1.061 monthly Burn_Date", date_range={"start":min(actual_dates) if actual_dates else "2023-09-15","end":max(actual_dates) if actual_dates else "2023-09-15"},
            paths=[modis_path,pixels_path], metadata={"items_processed":len(frame),"burned_pixel_records":len(burn_pixels),
            "nominal_resolution_m":500,"burn_pixel_rule":"Burn_Date valid 1..366 and within ProductStartDay..ProductEndDay",
            "source_product_years":product_years,"note":"Coarse independent burn-area evidence; not field-level ground truth."},
            warnings=warnings, license_ref="NASA LP DAAC data use policy; https://lpdaac.usgs.gov/terms-of-use/")
    else:
        record_dataset("modis_burned_area", "provider_unavailable", source_provider="NASA LP DAAC / Microsoft Planetary Computer",
                       source_dataset="MCD64A1.061 monthly Burn_Date", warnings=["No district-intersecting burn-date items could be processed."])

    # S1 scene archive is catalogued independently; no unvalidated radar metric is inferred.
    try:
        search = catalog.search(collections=["sentinel-1-rtc"], bbox=bbox,
            datetime=f"2023-09-15T00:00:00Z/{TODAY_ISO}T23:59:59Z", max_items=5000)
        rows = []
        for item in search.items():
            if not item.geometry or not geom.intersects(__import__("shapely.geometry",fromlist=["shape"]).shape(item.geometry)):
                continue
            dt = item.properties.get("datetime") or item.properties.get("start_datetime")
            if not dt: continue
            if not any(k in item.assets for k in ("vv","vh")): continue
            rows.append({"scene_id":item.id,"datetime":dt,"platform":item.properties.get("platform"),
                "orbit_state":item.properties.get("sat:orbit_state"),"relative_orbit":item.properties.get("sat:relative_orbit"),
                "tile":item.properties.get("s1:datatake_id"),"collection":"sentinel-1-rtc",
                "source_provider":"Microsoft Planetary Computer","source_item_url":item.get_self_href(),
                "assets":json.dumps({k:item.assets[k].href for k in ("vv","vh") if k in item.assets},sort_keys=True),
                "raster_bands":json.dumps({k:item.assets[k].extra_fields.get("raster:bands") for k in ("vv","vh") if k in item.assets}),
                "real_or_synthetic":"REAL"})
        s1path=REAL/"sentinel1"/"sentinel1_scene_catalog.parquet"
        pd.DataFrame(rows).to_parquet(s1path,index=False)
        record_dataset("sentinel1","real_remote_processed" if rows else "provider_unavailable",
            source_provider="Microsoft Planetary Computer",source_dataset="Sentinel-1 RTC",
            date_range={"start":"2023-09-15","end":TODAY_ISO},paths=[s1path] if rows else [],
            metadata={"scene_count":len(rows),"field_observations":0,"catalog_only":True,
                      "item_ids":[x["scene_id"] for x in rows]},
            warnings=[] if rows else ["No S1 RTC scenes matched the district/date search."])
    except Exception as exc:
        record_dataset("sentinel1","download_failed",source_provider="Microsoft Planetary Computer",
                       source_dataset="Sentinel-1 RTC",warnings=[f"{type(exc).__name__}: {exc}"])


UMD_MCD64 = "sftp://fuoco.geog.umd.edu/data/MODIS/C61/MCD64A1/TIFF/Win18"


def umd_burned_area(year: int) -> None:
    """Add Sep-Dec MCD64A1 months that Planetary Computer has not published, from the UMD archive.

    The UMD monthly GeoTIFF (sub-continental window Win18, 60-93E 5-36N) carries the same
    MCD64A1 C6.1 Burn_Date on a geographic grid (~0.0044 deg, ~420 x 490 m here) instead of
    the 500 m sinusoidal tiles, so pixel counts are not strictly comparable with earlier
    seasons; presence near a field is. Values: 1-366 burn day, 0 unburned, <0 unmapped/water.
    Months already present are kept; nothing is gap-filled.
    """
    from scripts.acquire_fire_archives import CURL
    import subprocess
    import tempfile
    modis_path = REAL / "burned_area" / "mcd64a1_muktsar.parquet"
    pixels_path = REAL / "burned_area" / "mcd64a1_burn_pixels.parquet"
    products = pd.read_parquet(modis_path)
    pixels = pd.read_parquet(pixels_path)
    have = set(zip(products.product_year, products.product_start_doy))
    district = gpd.read_file(REAL / "boundaries" / "sri_muktsar_sahib_adm2.geojson").to_crs("EPSG:4326").geometry.iloc[0]
    new_products, new_pixels = [], []
    for month in (9, 10, 11, 12):
        first = date(year, month, 1)
        last = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)) - timedelta(days=1)
        start_doy, end_doy = first.timetuple().tm_yday, last.timetuple().tm_yday
        if (year, start_doy) in have:
            continue
        name = f"MCD64monthly.A{year}{start_doy:03d}.Win18.061.burndate.tif"
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / name
            done = subprocess.run([CURL, "-s", "--max-time", "600", "-u", "fire:burnt", "-o", str(local), f"{UMD_MCD64}/{year}/{name}"])
            if done.returncode != 0 or not local.exists() or local.stat().st_size == 0:
                print(f"UMD_MCD64_MISSING {name}", flush=True)
                continue
            with rasterio.open(local) as src:
                data, transform = mask(src, [mapping(district)], crop=True, indexes=1, filled=False)
                res_x, res_y = src.res
        vals = data.data
        burned = ~np.ma.getmaskarray(data) & (vals >= start_doy) & (vals <= end_doy)
        season_end = min(date(year, 12, 15), TODAY - timedelta(days=5)) if year == TODAY.year else date(year, 12, 15)
        yy, xx = np.where(burned)
        kept = 0
        if len(xx):
            lon, lat = rasterio.transform.xy(transform, yy, xx, offset="center")
            for j in range(len(xx)):
                d = date(year, 1, 1) + timedelta(days=int(vals[yy[j], xx[j]]) - 1)
                if not date(year, 9, 15) <= d <= season_end:
                    continue
                kept += 1
                area = (res_x * 111320 * np.cos(np.deg2rad(lat[j]))) * (res_y * 110574)
                new_pixels.append({"source_item_id": name, "burn_date": d.isoformat(), "burn_doy": int(vals[yy[j], xx[j]]),
                                   "longitude": float(lon[j]), "latitude": float(lat[j]), "nominal_pixel_area_m2": round(float(area)),
                                   "source_provider": "University of Maryland fire archive (NASA MCD64A1 C6.1)",
                                   "source_collection": "MCD64A1.061 monthly GeoTIFF Win18", "source_url": f"{UMD_MCD64}/{year}/{name}",
                                   "real_or_synthetic": "REAL"})
        new_products.append({"source_item_id": name, "product_year": year, "product_start_doy": start_doy, "product_end_doy": end_doy,
                             "tile": "Win18", "burned_pixels_in_aoi": kept,
                             "burned_area_km2_nominal": round(sum(p["nominal_pixel_area_m2"] for p in new_pixels if p["source_item_id"] == name) / 1e6, 3),
                             "source_provider": "University of Maryland fire archive (NASA MCD64A1 C6.1)",
                             "source_dataset": "MCD64A1.061 monthly Burn_Date GeoTIFF (window Win18)", "source_url": f"{UMD_MCD64}/{year}/{name}",
                             "crs": "EPSG:4326", "resolution_m": 500, "real_or_synthetic": "REAL"})
        print(f"UMD_MCD64 {name} burned_pixels_in_district_window={kept}", flush=True)
    if not new_products:
        return
    products = pd.concat([products, pd.DataFrame(new_products)], ignore_index=True)
    pixels = pd.concat([pixels, pd.DataFrame(new_pixels)], ignore_index=True) if new_pixels else pixels
    products.to_parquet(modis_path, index=False)
    pixels.to_parquet(pixels_path, index=False)
    record_dataset("modis_burned_area", "real_downloaded", source_provider="NASA LP DAAC / Microsoft Planetary Computer; UMD fire archive",
                   source_dataset="MCD64A1.061 monthly Burn_Date",
                   date_range={"start": str(pd.to_datetime(pixels.burn_date).min().date()), "end": str(pd.to_datetime(pixels.burn_date).max().date())},
                   paths=[modis_path, pixels_path],
                   metadata={"items_processed": int(len(products)), "burned_pixel_records": int(len(pixels)), "nominal_resolution_m": 500,
                             "burn_pixel_rule": "Burn_Date valid 1..366 and within the product month",
                             "source_product_years": sorted(map(int, products.product_year.unique())),
                             "sources": {"Planetary Computer modis-64A1-061 (500 m sinusoidal)": sorted(map(int, products.loc[products.tile != "Win18", "product_year"].unique())),
                                         "UMD sftp MCD64monthly Win18 GeoTIFF (geographic ~0.0044 deg)": sorted(map(int, products.loc[products.tile == "Win18", "product_year"].unique()))},
                             "note": "Coarse independent burn-area evidence; not field-level ground truth. Win18 pixel counts are not strictly comparable with 500 m sinusoidal counts."},
                   license_ref="NASA LP DAAC data use policy; https://lpdaac.usgs.gov/terms-of-use/")


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--force",action="store_true")
    parser.add_argument("--umd-burned-area-year", type=int,
                        help="Only add Sep-Dec MCD64A1 months missing from Planetary Computer for this year from the UMD archive.")
    args = parser.parse_args()
    if args.umd_burned_area_year:
        umd_burned_area(args.umd_burned_area_year)
    else:
        run(args.force)
