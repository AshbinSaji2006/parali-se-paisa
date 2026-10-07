"""Causal, coverage-aware fire context for real field-date observations.

Active-fire detections (FIRMS/UMD VIIRS and MODIS) and MODIS MCD64A1 burned-area
pixels are attached as *proximity context* around a field centroid. They are not
parcel attribution, not burn labels and not ground truth. Two rules keep the
context honest:

* causality: only detections timestamped at or before the satellite acquisition
  (burned-area days strictly before the acquisition day) are counted;
* coverage: a zero count is only reported when the archive covers the whole
  look-back window. Uncovered windows give ``None``; partly covered windows keep
  their count but are flagged ``PARTIAL`` so a zero is never read as "no fire".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0088
FIRMS_RADIUS_KM = 1.0
MODIS_BA_RADIUS_KM = 0.5
LOOKBACK_DAYS = 30
# Pixel-mean BAIS2 differing from BAIS2 of the band means by more than this is
# dominated by a few near-zero-red pixels (BAIS2 divides by B04); see audit report.
BAIS2_INSTABILITY_THRESHOLD = 0.25


def _haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.deg2rad, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _utc(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _naive(t: pd.Timestamp) -> np.datetime64:
    return t.tz_convert("UTC").tz_localize(None).to_datetime64()


def _merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _covered_days(intervals, start, end) -> float:
    total = pd.Timedelta(0)
    for a, b in intervals:
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            total += hi - lo
    return total.total_seconds() / 86400


def firms_coverage_intervals(firms: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Archive time coverage implied by each source granule type.

    Yearly FIRMS archives cover whole calendar years, UMD monthly files whole
    months, and the NRT feed only the span of detections it returned.
    """
    intervals = []
    dates = pd.to_datetime(firms["acq_date"])
    for (year, record_type), d in dates.groupby([dates.dt.year, firms["record_type"]]):
        if record_type == "ARCHIVE_YEARLY":
            start, end = pd.Timestamp(year=int(year), month=1, day=1), pd.Timestamp(year=int(year) + 1, month=1, day=1)
        elif record_type == "ARCHIVE_MONTHLY_UMD":
            start = d.min().to_period("M").to_timestamp()
            end = (d.max().to_period("M") + 1).to_timestamp()
        else:
            start, end = d.min().normalize(), d.max().normalize() + pd.Timedelta(days=1)
        intervals.append((start.tz_localize("UTC"), end.tz_localize("UTC")))
    return _merge_intervals(intervals)


def modis_burned_area_coverage(products: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Coverage of processed MCD64A1 monthly granules (ProductStartDay..ProductEndDay)."""
    intervals = []
    for row in products.itertuples():
        start = pd.Timestamp(year=int(row.product_year), month=1, day=1, tz="UTC") + pd.Timedelta(days=int(row.product_start_doy) - 1)
        end = pd.Timestamp(year=int(row.product_year), month=1, day=1, tz="UTC") + pd.Timedelta(days=int(row.product_end_doy))
        intervals.append((start, end))
    return _merge_intervals(intervals)


def _coverage_status(covered: float, window: float) -> str:
    if covered <= 0:
        return "NOT_COVERED"
    return "COMPLETE" if covered >= window - 1e-9 else "PARTIAL"


def firms_context(obs: pd.DataFrame, firms: pd.DataFrame, *, radius_km: float = FIRMS_RADIUS_KM,
                  lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Per-observation active-fire counts near the field centroid in (t - lookback, t]."""
    fires = firms.copy()
    # type 2 (static land source) and 3 (offshore) are not vegetation fires; NRT rows carry no type.
    fires = fires.loc[pd.to_numeric(fires.get("type"), errors="coerce").fillna(0).eq(0)]
    # acq_date/acq_time are UTC; keep naive UTC datetime64 arrays for vectorised comparison.
    fires["detection_time"] = (pd.to_datetime(fires.acq_date) +
                               pd.to_timedelta(fires.acq_time.astype(int) // 100, unit="h") +
                               pd.to_timedelta(fires.acq_time.astype(int) % 100, unit="m"))
    intervals = firms_coverage_intervals(firms)
    times = fires.detection_time.to_numpy()
    lat, lon = fires.latitude.to_numpy(), fires.longitude.to_numpy()
    is_viirs = fires.sensor.astype(str).str.startswith("VIIRS").to_numpy()
    window = pd.Timedelta(days=lookback_days)
    out = []
    for row in obs[["observation_datetime", "centroid_lat", "centroid_lon"]].itertuples(index=False):
        t = _utc(row.observation_datetime)
        covered = _covered_days(intervals, t - window, t)
        status = _coverage_status(covered, lookback_days)
        record = {"firms_window_days": lookback_days, "firms_radius_km": radius_km,
                  "firms_coverage_status": status, "firms_window_covered_days": round(covered, 3),
                  "firms_viirs_detections_near_field": None, "firms_modis_detections_near_field": None,
                  "firms_nearest_detection_km": None, "firms_latest_detection_datetime": None}
        if status != "NOT_COVERED" and pd.notna(row.centroid_lat) and pd.notna(row.centroid_lon):
            in_time = (times > _naive(t - window)) & (times <= _naive(t))
            if in_time.any():
                d = _haversine_km(row.centroid_lat, row.centroid_lon, lat[in_time], lon[in_time])
                near = d <= radius_km
                record["firms_viirs_detections_near_field"] = int((near & is_viirs[in_time]).sum())
                record["firms_modis_detections_near_field"] = int((near & ~is_viirs[in_time]).sum())
                record["firms_nearest_detection_km"] = float(d.min())
                if near.any():
                    record["firms_latest_detection_datetime"] = pd.Timestamp(times[in_time][near].max(), tz="UTC").isoformat()
            else:
                record["firms_viirs_detections_near_field"] = 0
                record["firms_modis_detections_near_field"] = 0
        out.append(record)
    return pd.DataFrame(out, index=obs.index)


def modis_burned_area_context(obs: pd.DataFrame, pixels: pd.DataFrame, products: pd.DataFrame, *,
                              radius_km: float = MODIS_BA_RADIUS_KM, lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """MCD64A1 burned 500 m pixels near the centroid with burn day strictly before the acquisition day.

    MCD64A1 is published months after the fact, so this is retrospective context:
    it was not knowable at acquisition time and must not feed a real-time decision.
    """
    intervals = modis_burned_area_coverage(products)
    burn_day = pd.to_datetime(pixels.burn_date).to_numpy()
    lat, lon = pixels.latitude.to_numpy(), pixels.longitude.to_numpy()
    out = []
    for row in obs[["observation_datetime", "centroid_lat", "centroid_lon"]].itertuples(index=False):
        day = _utc(row.observation_datetime).floor("D")
        start = day - pd.Timedelta(days=lookback_days)
        covered = _covered_days(intervals, start, day)
        status = _coverage_status(covered, lookback_days)
        record = {"modis_ba_coverage_status": status, "modis_ba_window_covered_days": round(covered, 3),
                  "modis_ba_burned_pixels_near_field": None, "modis_ba_latest_burn_date": None,
                  "modis_ba_availability": "RETROSPECTIVE_NOT_AVAILABLE_AT_ACQUISITION"}
        if status != "NOT_COVERED" and pd.notna(row.centroid_lat):
            in_time = (burn_day >= _naive(start)) & (burn_day < _naive(day))
            near = np.zeros(len(burn_day), dtype=bool)
            if in_time.any():
                near[in_time] = _haversine_km(row.centroid_lat, row.centroid_lon, lat[in_time], lon[in_time]) <= radius_km
            record["modis_ba_burned_pixels_near_field"] = int(near.sum())
            if near.any():
                record["modis_ba_latest_burn_date"] = pd.Timestamp(burn_day[near].max()).date().isoformat()
        out.append(record)
    return pd.DataFrame(out, index=obs.index)


def bais2_stability(obs: pd.DataFrame, threshold: float = BAIS2_INSTABILITY_THRESHOLD) -> pd.DataFrame:
    """Flag field-mean BAIS2 values dominated by pixel-level division artefacts.

    BAIS2 = (1 - sqrt(B6*B7*B8A/B4)) * ((B12-B8A)/sqrt(B12+B8A) + 1) explodes as B04 -> 0.
    The pixel-mean is compared with BAIS2 recomputed from the stored field band means;
    for a homogeneous field the two agree closely, so a large gap marks an outlier pixel.
    """
    b4, b6, b7, b8a, b12 = (obs[f"{b}_mean"].astype(float) for b in ("b04", "b06", "b07", "b8a", "b12"))
    with np.errstate(divide="ignore", invalid="ignore"):
        recomputed = (1 - np.sqrt((b6 * b7 * b8a / b4).clip(lower=0))) * ((b12 - b8a) / np.sqrt((b12 + b8a).clip(lower=1e-8)) + 1)
    recomputed = recomputed.where(b4 > 0)
    diff = (obs["BAIS2"].astype(float) - recomputed).abs()
    unstable = diff.gt(threshold)
    return pd.DataFrame({"BAIS2_from_band_means": recomputed,
                         "BAIS2_pixel_vs_band_mean_abs_diff": diff,
                         "BAIS2_quality": np.where(unstable, "UNSTABLE_PIXEL_ARTEFACT", np.where(diff.notna(), "OK", "UNVERIFIED"))},
                        index=obs.index)
