"""Read-only research evidence derived from real Sentinel-2, VIIRS/MODIS and ERA5 data.

Every payload is produced offline by scripts/run_research.py and scripts/build_research_maps.py.
Field-level burn tiers are rule-derived Sentinel-2 candidates for research and pickup prioritisation;
they are not enforcement evidence and never trigger penalties. Officials and admins only.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports" / "research"
FIGURES = REPORTS / "figures"
PRODUCTS = ROOT / "data" / "real" / "derived" / "research"
OVERLAYS = PRODUCTS / "overlays"
FIRES = ROOT / "data" / "real" / "firms" / "active_fire_unified.parquet"
SAFE_NAME = re.compile(r"^[a-z0-9_]+\.png$")
USE_NOTICE = ("Research evidence from real satellite data. Burn tiers are rule-derived Sentinel-2 candidates, "
              "not ground truth; this is not enforcement evidence and is only a signal for research and human review.")

router = APIRouter(prefix="/research", tags=["research"])


def _require_official(request: Request) -> None:
    user = getattr(request.state, "user", None) or {}
    if user.get("role") not in {"ADMIN", "OFFICIAL"}:
        raise HTTPException(403, "Research evidence is limited to officials")


def _finite(obj):
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_finite(v) for v in obj]
    if isinstance(obj, float) and obj != obj or obj in (float("inf"), float("-inf")):
        return None
    return obj


def _json(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(404, f"Research product not built: {path.name}. Run scripts/run_research.py")
    return _finite(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=8)
def _events(year: int, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(PRODUCTS / f"field_events_{year}.parquet").set_index("field_id")


@router.get("/summary")
def summary(request: Request):
    _require_official(request)
    results = _json(REPORTS / "results.json")
    figures = sorted(p.name for p in FIGURES.glob("f*.png")) if FIGURES.exists() else []
    overlays = _json(OVERLAYS / "overlays.json") if (OVERLAYS / "overlays.json").exists() else {"overlays": []}
    keep = ["census", "candidate_summary", "naive_vs_aware", "latency", "persistence", "risk_model", "dynamic_hazard", "replay", "replay_impact", "emissions_burned_area",
            "emissions_per_1000_ha_burned", "nowcast_2026", "assumptions", "caveats"]
    return {"notice": USE_NOTICE, "data_mode": "REAL", "results": {k: results.get(k) for k in keep},
            "figures": figures, "overlays": overlays.get("overlays", [])}


@router.get("/figures/{name}")
def figure(name: str, request: Request):
    _require_official(request)
    path = FIGURES / name
    if not SAFE_NAME.match(name) or not path.exists():
        raise HTTPException(404, "Figure not found")
    return FileResponse(path, media_type="image/png")


@router.get("/overlays/{name}")
def overlay(name: str, request: Request):
    _require_official(request)
    path = OVERLAYS / name
    if not SAFE_NAME.match(name) or not path.exists():
        raise HTTPException(404, "Overlay not found")
    return FileResponse(path, media_type="image/png")


@router.get("/fires/{year}")
def fires(year: int, request: Request):
    _require_official(request)
    if not FIRES.exists():
        raise HTTPException(404, "Active-fire table not built")
    f = pd.read_parquet(FIRES, columns=["acq_date", "acq_time", "latitude", "longitude", "sensor", "frp", "in_muktsar", "type", "year"])
    f = f[(f.year == year) & f.in_muktsar & f.acq_date.dt.month.isin([9, 10, 11, 12]) & (f["type"].fillna(0) == 0)
          & f.sensor.str.startswith("VIIRS")]
    items = [{"date": d.strftime("%Y-%m-%d"), "time_utc": f"{int(t):04d}", "lat": round(float(la), 5), "lon": round(float(lo), 5),
              "sensor": s, "frp_mw": None if pd.isna(p) else round(float(p), 1)}
             for d, t, la, lo, s, p in zip(f.acq_date, f.acq_time, f.latitude, f.longitude, f.sensor, f.frp)]
    return {"year": year, "count": len(items), "items": items, "source": "NASA FIRMS / UMD archive, VIIRS 375 m C2 active fires (S-NPP, NOAA-20, NOAA-21)",
            "real_or_synthetic": "REAL"}


@router.get("/watchlist")
def watchlist(request: Request, limit: int = Query(default=100, ge=1, le=1000)):
    _require_official(request)
    path = PRODUCTS / "risk_2026_preseason.parquet"
    if not path.exists():
        raise HTTPException(404, "2026 risk product not built")
    r = pd.read_parquet(path).sort_values("risk_score", ascending=False).head(limit)
    return {"notice": "Relative pre-season ranking from 2024-2025 burn history; a prioritisation aid for baler pre-booking, not a probability or an accusation.",
            "count": len(r), "items": [{"field_id": x.field_id, "lat": round(float(x.centroid_lat), 5), "lon": round(float(x.centroid_lon), 5),
                                        "area_ha": round(float(x.pixel_area_ha), 2), "risk_decile": int(x.risk_decile),
                                        "relative_score": round(float(x.risk_score), 4), "burned_last_season": bool(x.prior_burn),
                                        "neighbourhood_burn_rate_last_season": round(float(x.nbhd_prior_rate), 3),
                                        "harvested_2026": bool(x.harvested)} for x in r.itertuples()]}


@router.get("/fields/{field_id}/events")
def field_events(field_id: str, request: Request):
    _require_official(request)
    out = []
    for year in (2023, 2024, 2025, 2026):
        path = PRODUCTS / f"field_events_{year}.parquet"
        if not path.exists():
            continue
        e = _events(year, path.stat().st_mtime)
        if field_id not in e.index:
            continue
        x = e.loc[field_id]
        ts = lambda v: None if pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d")
        out.append({"year": year, "harvest_observed": ts(x.harvest_date), "last_green_observation": ts(x.last_green_date),
                    "burn_tier": x.burn_tier, "burn_observed": ts(x.burn_date), "last_unburned_observation": ts(x.burn_prev_date),
                    "harvest_to_burn_days": None if pd.isna(x.harvest_to_burn_days) else int(x.harvest_to_burn_days),
                    "peak_ndvi": round(float(x.peak_ndvi), 3)})
    if not out:
        raise HTTPException(404, "No research events for this field")
    return {"field_id": field_id, "seasons": out, "notice": USE_NOTICE}
