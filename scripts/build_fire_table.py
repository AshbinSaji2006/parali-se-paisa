"""Harmonise active-fire detections (FIRMS yearly CSVs 2023-2024, UMD monthly 2025, FIRMS NRT 2026)."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIRMS = ROOT / "data" / "real" / "firms"


def main() -> None:
    a = pd.read_parquet(FIRMS / "firms_muktsar_region.parquet")
    a = a[(a.record_type == "NRT_7DAY") | (a.acq_date.dt.year < 2025)].copy()
    a = pd.DataFrame({
        "acq_date": pd.to_datetime(a.acq_date), "acq_time": a.acq_time.astype(int),
        "latitude": a.latitude, "longitude": a.longitude, "sensor": a.sensor,
        "confidence": a.confidence.astype(str), "frp": a.frp, "daynight": a.daynight.astype(str),
        "type": pd.to_numeric(a.get("type"), errors="coerce"), "source": a.source_file, "record_type": a.record_type})
    m = pd.read_parquet(FIRMS / "active_fire_monthly_punjab_box.parquet")
    is_modis = m["product"] == "MCD14ML"
    m = pd.DataFrame({
        "acq_date": pd.to_datetime(m.yyyymmdd.astype(str), format="%Y%m%d"), "acq_time": m.hhmm.astype(int),
        "latitude": m.lat, "longitude": m.lon, "sensor": m.sensor,
        "confidence": m.conf.where(is_modis, m.confidence).astype(str), "frp": m.frp,
        "daynight": m.dn.where(is_modis, m.dnflag).astype(str), "type": pd.to_numeric(m["type"], errors="coerce"),
        "source": m.source_file, "record_type": "ARCHIVE_MONTHLY_UMD"})
    u = pd.concat([a, m], ignore_index=True)
    d = gpd.read_file(ROOT / "data" / "real" / "boundaries" / "sri_muktsar_sahib_adm2.geojson").to_crs(4326).geometry.iloc[0]
    pts = gpd.GeoSeries(gpd.points_from_xy(u.longitude, u.latitude), crs=4326)
    u["in_muktsar"] = pts.within(d).values
    u["hour_ist"] = ((u.acq_time // 100) + (u.acq_time % 100) / 60 + 5.5) % 24
    u["year"] = u.acq_date.dt.year
    u["real_or_synthetic"] = "REAL"
    u.to_parquet(FIRMS / "active_fire_unified.parquet", index=False)
    s = u[u.in_muktsar & u.acq_date.dt.month.isin([9, 10, 11, 12])]
    s.to_parquet(FIRMS / "firms_muktsar.parquet", index=False)
    counts = s.groupby(["year", "sensor"]).size().unstack(fill_value=0)
    print(counts.to_string())
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts.acquire_real_data import record_dataset
    record_dataset("firms", "real_downloaded", source_provider="NASA FIRMS / University of Maryland fire archive",
                   source_dataset="VIIRS 375 m C2 (S-NPP, NOAA-20, NOAA-21) and MODIS C6.1 active fire locations",
                   date_range={"start": "2023-09-01", "end": str(u.acq_date.max().date())},
                   paths=[FIRMS / "active_fire_unified.parquet", FIRMS / "firms_muktsar.parquet"],
                   metadata={"district_detections_sep_dec": {str(k): {c: int(v) for c, v in row.items()} for k, row in counts.iterrows()},
                             "sources": ["FIRMS yearly country CSV 2023-2024 (public)", "UMD sftp monthly VNP14IMGML/VJ114IMGML/VJ214IMGML/MCD14ML 2025",
                                         "FIRMS 7-day NRT CSV (2026)"], "no_map_key_required": True},
                   license_ref="NASA Earthdata open data policy",
                   warnings=["Polar-orbit active fires miss fires lit after the ~13:30 overpass; see docs/RESEARCH_METHODS.md"])


if __name__ == "__main__":
    main()
