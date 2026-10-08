"""Harmonise active-fire detections (FIRMS yearly CSVs 2023-2024, UMD monthly 2025, FIRMS NRT 2026)."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIRMS = ROOT / "data" / "real" / "firms"
VIIRS_CLASSES = {"l": "low", "low": "low", "n": "nominal", "nominal": "nominal", "h": "high", "high": "high"}


def normalise_confidence(raw: pd.Series, sensor: pd.Series) -> pd.DataFrame:
    """Typed confidence from mixed sources, keeping the published value.

    VIIRS publishes a class (l/n/h in archives, L/N/H in UMD monthly files, low/nominal/high in
    NRT); MODIS publishes a 0-100 percentage. MODIS classes follow the C6.1 user guide bands:
    0-29 low, 30-79 nominal, 80-100 high. Unparseable values stay null.
    """
    text = raw.astype("string").str.strip()
    is_modis = sensor.astype(str).eq("MODIS")
    pct = pd.to_numeric(text.where(is_modis), errors="coerce")
    modis_class = pd.cut(pct, bins=[-0.1, 29.5, 79.5, 100.1], labels=["low", "nominal", "high"]).astype("string")
    viirs_class = text.where(~is_modis).str.lower().map(VIIRS_CLASSES)
    out = pd.DataFrame(index=raw.index)
    # One canonical published form: MODIS integers without a float suffix, VIIRS letters as published.
    out["confidence"] = text.where(~is_modis, pct.round().astype("Int64").astype("string"))
    out["confidence_class"] = viirs_class.where(~is_modis, modis_class).astype("string")
    out["confidence_pct"] = pct.astype(float)
    return out


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
    u[["confidence", "confidence_class", "confidence_pct"]] = normalise_confidence(u.confidence, u.sensor)
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
