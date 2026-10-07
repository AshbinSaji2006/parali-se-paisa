"""One-command refresh of the live 2026 season before the demo.

Downloads any new 2026 Sentinel-2 acquisitions and the latest FIRMS 7-day NRT alerts, then rebuilds
field time series, events, results, figures, map overlays and the pitch deck. Earlier seasons are
reused unchanged. Run from the project root:  python scripts/update_live_2026.py
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NRT = {
    "SUOMI_VIIRS_C2": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_Asia_7d.csv",
    "J1_VIIRS_C2": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_Asia_7d.csv",
    "J2_VIIRS_C2": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_Asia_7d.csv",
    "MODIS_C6_1": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_South_Asia_7d.csv",
}


def run(*args: str) -> None:
    print("\n$", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def refresh_nrt() -> None:
    raw = ROOT / "data" / "real" / "firms" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    for name, url in NRT.items():
        try:
            urllib.request.urlretrieve(url, raw / f"{name}_South_Asia_7d_{stamp}.csv")
            print("NRT", name, "ok", flush=True)
        except Exception as exc:  # NRT feeds are best-effort context for the live season
            print("NRT", name, "failed:", exc, flush=True)
    # rebuild the regional FIRMS table from all raw CSVs (yearly archives + every NRT snapshot)
    import geopandas as gpd
    import pandas as pd
    rows = []
    for f in sorted(raw.glob("*.csv")):
        x = pd.read_csv(f)
        x = x[x.latitude.between(29.5, 31.0) & x.longitude.between(73.8, 75.3)].copy()
        x["source_file"] = f.name
        rows.append(x)
    a = pd.concat(rows, ignore_index=True)
    for c in ("confidence", "version", "satellite"):
        if c in a:
            a[c] = a[c].astype(str)
    d = gpd.read_file(ROOT / "data/real/boundaries/sri_muktsar_sahib_adm2.geojson").to_crs(4326).geometry.iloc[0]
    a["in_muktsar"] = gpd.GeoSeries(gpd.points_from_xy(a.longitude, a.latitude), crs=4326).within(d).values
    a["acq_date"] = pd.to_datetime(a.acq_date)
    s = a.source_file
    a["sensor"] = s.map(lambda n: "MODIS" if n.lower().startswith("modis") else "VIIRS_NOAA21" if n.startswith("J2")
                         else "VIIRS_NOAA20" if ("jpss1" in n or n.startswith("J1")) else "VIIRS_SNPP")
    a["record_type"] = s.map(lambda n: "NRT_7DAY" if "7d" in n else "ARCHIVE_YEARLY")
    a["real_or_synthetic"], a["source_provider"] = "REAL", "NASA FIRMS (public country/NRT CSV)"
    a = a.drop_duplicates(["latitude", "longitude", "acq_date", "acq_time", "sensor"])
    a.to_parquet(ROOT / "data" / "real" / "firms" / "firms_muktsar_region.parquet")


if __name__ == "__main__":
    run("scripts/download_s2_stack.py", "--years", "2026", "--item-workers", "3")
    run("scripts/extract_field_timeseries.py", "--years", "2026")
    run("scripts/run_event_detection.py", "2026")
    refresh_nrt()
    run("scripts/build_fire_table.py")
    run("scripts/run_research.py")
    run("scripts/build_research_maps.py")
    run("scripts/build_pitch_deck.py")
    print("\nLive 2026 refresh complete. Restart the API (python scripts/start_demo.py) to serve the new products.")
