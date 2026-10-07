"""Causal field-season temporal features built from Checkpoint C rows."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

TEMPORAL_SCHEMA_VERSION = "1.0"
GROUP_COLUMNS = ("field_id", "season", "year")
INDEXES = ("NDVI", "NBR", "BAIS2")
TEMPORAL_COLUMNS = [
    "feature_schema_version", "temporal_duplicate_timestamp", "temporal_history_count",
    "temporal_previous_valid", "temporal_previous_quality", "previous_observation_datetime",
    "previous_source_image_id_s2", "days_since_previous_observation", "temporal_gap_category",
    "observation_number_in_season", "day_of_year", "days_since_first_observation_in_season",
    "peak_NDVI_so_far", "peak_NDVI_datetime_so_far", "days_since_peak_NDVI",
    "NDVI_drop_from_peak", "NDVI_drop_fraction_from_peak",
    "VV_minus_VH_prev_db", "VV_minus_VH_delta_db", "VV_VH_ratio_linear_prev",
    "VV_VH_ratio_linear_delta", "radar_temporal_comparison_available",
    "radar_previous_observation_datetime", "radar_previous_source_image_id_s1",
]
for _name in INDEXES:
    TEMPORAL_COLUMNS += [f"{_name}_prev", f"{_name}_delta", f"{_name}_pct_change",
                         f"{_name}_delta_2obs", f"{_name}_rolling_mean_2", f"{_name}_rolling_mean_3"]
for _name in ("VV", "VH"):
    TEMPORAL_COLUMNS += [f"{_name}_prev_db", f"{_name}_delta_db"]
for _name in ("NDVI", "NBR"):
    TEMPORAL_COLUMNS.append(f"{_name}_rolling_std_3")
for _name in INDEXES:
    TEMPORAL_COLUMNS.append(f"{_name}_slope_last_3")


def _datetime(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _compatible_radar(a, b):
    if not a or not b:
        return False
    for key in ("s1_instrument_mode", "s1_orbit_pass", "s1_relative_orbit_number"):
        av, bv = a.get(key), b.get(key)
        if av not in (None, "") and bv not in (None, "") and str(av) != str(bv):
            return False
        if key == "s1_instrument_mode" and (av in (None, "") or bv in (None, "")):
            return False
    return True


def _slope(points):
    # OLS slope in index units per elapsed day, relative to first sample.
    xs = [(p[0] - points[0][0]).total_seconds() / 86400 for p in points]
    ys = [p[1] for p in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else None


def build_temporal_rows(rows, settings=None):
    """Return a sorted copy with causal features and a quality summary.

    Same-time duplicate rows are retained and flagged; each sees only strictly earlier
    timestamps. POOR rows do not enter temporal history; LIMITED rows remain eligible.
    """
    settings = settings or {}
    epsilon = float(settings.get("pct_change_epsilon", 1e-6))
    moderate = float(settings.get("moderate_gap_days", 14))
    large = float(settings.get("large_gap_days", 30))
    grouped = defaultdict(list)
    for i, row in enumerate(rows):
        missing = [k for k in (*GROUP_COLUMNS, "observation_datetime") if row.get(k) in (None, "")]
        if missing:
            raise ValueError(f"base feature row missing required temporal keys: {', '.join(missing)}")
        dt = _datetime(row["observation_datetime"])
        grouped[tuple(str(row[k]) for k in GROUP_COLUMNS)].append((dt, str(row.get("source_image_id_s2") or ""), i, row))
    output, duplicate_count, warnings = [], 0, []
    field_row_counts = defaultdict(int)
    for key in sorted(grouped):
        entries = sorted(grouped[key], key=lambda x: (x[0], x[1], x[2]))
        field_row_counts[key[0]] += len(entries)
        by_time = defaultdict(list)
        for e in entries:
            by_time[e[0]].append(e)
        times = sorted(by_time)
        history = []
        radar_history = []
        first_time = times[0]
        observation_number = 0
        for distinct_num, dt in enumerate(times, 1):
            block = by_time[dt]
            duplicate = len(block) > 1
            if duplicate:
                duplicate_count += len(block)
                warnings.append(f"duplicate timestamp retained as a same-time block: {key} {dt.isoformat()} ({len(block)} rows)")
            eligible_history = [h for h in history if h["eligible"]]
            prev = eligible_history[-1] if eligible_history else None
            prev_dt = prev["dt"] if prev else None
            gap = (dt - prev_dt).total_seconds() / 86400 if prev else None
            for _, _, _, base in block:
                row = dict(base)
                row.update({c: None for c in TEMPORAL_COLUMNS})
                row_eligible = base.get("observation_quality") != "POOR" and (_number(base.get("valid_pixel_count")) or 0) > 0
                row.update({
                    "feature_schema_version": str(settings.get("feature_schema_version", TEMPORAL_SCHEMA_VERSION)),
                    "temporal_duplicate_timestamp": duplicate,
                    "temporal_history_count": len(eligible_history),
                    "temporal_previous_valid": bool(prev),
                    "temporal_previous_quality": prev["row"].get("observation_quality") if prev else None,
                    "previous_observation_datetime": prev_dt.isoformat() if prev_dt else None,
                    "previous_source_image_id_s2": prev["row"].get("source_image_id_s2") if prev else None,
                    "days_since_previous_observation": gap,
                    "temporal_gap_category": ("NORMAL" if gap <= moderate else "MODERATE" if gap <= large else "LARGE") if gap is not None else None,
                    "observation_number_in_season": distinct_num,
                    "day_of_year": dt.timetuple().tm_yday,
                    "days_since_first_observation_in_season": (dt - first_time).total_seconds() / 86400,
                })
                for metric in INDEXES:
                    key_metric = f"{metric}_mean"
                    curr = _number(base.get(key_metric)) if row_eligible else None
                    prev_metric = next((h for h in reversed(eligible_history) if _number(h["row"].get(key_metric)) is not None), None)
                    prior_vals = [(h["dt"], _number(h["row"].get(key_metric))) for h in eligible_history if _number(h["row"].get(key_metric)) is not None]
                    val_prev = _number(prev_metric["row"].get(key_metric)) if prev_metric else None
                    row[f"{metric}_prev"] = val_prev
                    row[f"{metric}_delta"] = curr - val_prev if curr is not None and val_prev is not None else None
                    row[f"{metric}_pct_change"] = ((curr - val_prev) / abs(val_prev)) if curr is not None and val_prev is not None and abs(val_prev) > epsilon else None
                    row[f"{metric}_delta_2obs"] = curr - prior_vals[-2][1] if curr is not None and len(prior_vals) >= 2 else None
                    sequence = [v for _, v in prior_vals] + ([curr] if curr is not None else [])
                    for n in (2, 3):
                        row[f"{metric}_rolling_mean_{n}"] = sum(sequence[-n:]) / n if len(sequence) >= n else None
                    if metric in ("NDVI", "NBR"):
                        row[f"{metric}_rolling_std_3"] = math.sqrt(sum((x - sum(sequence[-3:]) / 3) ** 2 for x in sequence[-3:]) / 3) if len(sequence) >= 3 else None
                    slope_points = prior_vals[-2:] + ([(dt, curr)] if curr is not None else [])
                    row[f"{metric}_slope_last_3"] = _slope(slope_points) if len(slope_points) == 3 else None
                peak_candidates = [(h["dt"], _number(h["row"].get("NDVI_mean"))) for h in eligible_history]
                curr_ndvi = _number(base.get("NDVI_mean")) if row_eligible else None
                peak_candidates = [(t, v) for t, v in peak_candidates if v is not None]
                if curr_ndvi is not None:
                    peak_candidates.append((dt, curr_ndvi))
                if peak_candidates:
                    peak_dt, peak = max(peak_candidates, key=lambda x: (x[1], -x[0].timestamp()))
                    row.update({"peak_NDVI_so_far": peak, "peak_NDVI_datetime_so_far": peak_dt.isoformat(),
                                "days_since_peak_NDVI": (dt - peak_dt).total_seconds() / 86400,
                                "NDVI_drop_from_peak": curr_ndvi - peak if curr_ndvi is not None else None,
                                "NDVI_drop_fraction_from_peak": ((curr_ndvi - peak) / abs(peak)) if curr_ndvi is not None and abs(peak) > epsilon else None})
                current_s1_dt = _datetime(base.get("s1_observation_datetime"))
                if current_s1_dt and current_s1_dt > dt:
                    warnings.append(f"future S1 timestamp ignored for {key} at {dt.isoformat()}")
                    current_s1_dt = None
                current_radar = row_eligible and current_s1_dt is not None and _number(base.get("VV_mean_db")) is not None
                compatible = [h for h in radar_history if h["s1dt"] < current_s1_dt and _compatible_radar(h["row"], base)] if current_radar else []
                radar_prev = max(compatible, key=lambda h: (h["s1dt"], str(h["row"].get("source_image_id_s1") or ""))) if compatible else None
                row["radar_temporal_comparison_available"] = bool(radar_prev)
                if radar_prev:
                    row["radar_previous_observation_datetime"] = radar_prev["s1dt"].isoformat()
                    row["radar_previous_source_image_id_s1"] = radar_prev["row"].get("source_image_id_s1")
                    for metric in ("VV", "VH"):
                        cur, old = _number(base.get(f"{metric}_mean_db")), _number(radar_prev["row"].get(f"{metric}_mean_db"))
                        row[f"{metric}_prev_db"] = old
                        row[f"{metric}_delta_db"] = cur - old if cur is not None and old is not None else None
                    for metric, col in (("VV_minus_VH", "VV_minus_VH_db"), ("VV_VH_ratio_linear", "VV_VH_ratio_linear")):
                        cur, old = _number(base.get(col)), _number(radar_prev["row"].get(col))
                        row[f"{metric}_prev_db" if metric == "VV_minus_VH" else f"{metric}_prev"] = old
                        row[f"{metric}_delta_db" if metric == "VV_minus_VH" else f"{metric}_delta"] = cur - old if cur is not None and old is not None else None
                output.append(row)
            # Commit this timestamp block only after features for all same-time rows are computed.
            for _, _, _, base in block:
                eligible = base.get("observation_quality") != "POOR" and (_number(base.get("valid_pixel_count")) or 0) > 0
                history.append({"dt": dt, "row": base, "eligible": eligible})
                s1dt = _datetime(base.get("s1_observation_datetime"))
                if eligible and s1dt and s1dt <= dt and _number(base.get("VV_mean_db")) is not None:
                    radar_history.append({"s1dt": s1dt, "row": base})
    # Ensure stable order and report counts.
    output.sort(key=lambda r: (str(r["field_id"]), str(r["season"]), str(r["year"]), _datetime(r["observation_datetime"]), str(r.get("source_image_id_s2") or "")))
    gaps = [r["days_since_previous_observation"] for r in output if r["days_since_previous_observation"] is not None]
    def quantile(p):
        if not gaps: return None
        ordered = sorted(gaps); return ordered[round((len(ordered)-1)*p)]
    report = {
        "feature_schema_version": str(settings.get("feature_schema_version", TEMPORAL_SCHEMA_VERSION)),
        "number_of_fields": len({str(r["field_id"]) for r in output}),
        "number_of_seasons": len({(r["field_id"], r["season"], r["year"]) for r in output}),
        "temporal_rows": len(output), "rows_with_previous_observations": sum(r["previous_observation_datetime"] is not None for r in output),
        "median_observations_per_field": _median(list(field_row_counts.values())), "min_observations_per_field": min(field_row_counts.values(), default=0), "max_observations_per_field": max(field_row_counts.values(), default=0),
        "temporal_gap_days": {"count": len(gaps), "min": min(gaps) if gaps else None, "median": quantile(.5), "max": max(gaps) if gaps else None},
        "rows_with_radar_temporal_comparison": sum(r["radar_temporal_comparison_available"] is True for r in output),
        "rows_without_compatible_radar_history": sum(r["radar_temporal_comparison_available"] is False for r in output),
        "large_gap_count": sum(r["temporal_gap_category"] == "LARGE" for r in output),
        "duplicate_timestamp_rows": duplicate_count,
        "synthetic_rows": sum(r.get("fixture_or_real") == "SYNTHETIC" for r in output), "real_rows": sum(r.get("fixture_or_real") == "REAL" for r in output),
        "nan_rate": {c: sum(r.get(c) is None for r in output) / len(output) if output else 0 for c in ("NDVI_prev", "NDVI_delta", "peak_NDVI_so_far", "NDVI_rolling_mean_3", "NDVI_slope_last_3", "VV_delta_db")},
        "leakage_test_status": "automated prefix-invariance tests are in tests/test_temporal_features.py; run pytest to execute", "warnings": warnings,
        "temporal_policy": "Within field_id+season+year; sort UTC; exclude POOR or zero-valid-pixel rows from future history; LIMITED rows are eligible; same-time duplicates are retained and see only strictly earlier timestamps.",
        "omitted_history": ["FIRMS event count histories are omitted because the C table has only as-of window summaries, not event-level detections.", "Weather rolling histories are omitted because the C table has only observation-level aggregates, not daily record histories."],
    }
    return output, report


def _median(values):
    if not values: return None
    values = sorted(values); n = len(values)
    return values[n // 2] if n % 2 else (values[n//2-1] + values[n//2]) / 2
