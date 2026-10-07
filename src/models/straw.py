from __future__ import annotations

from pathlib import Path
import yaml


def estimate_straw(row, status_result, config=None):
    cfg = config or yaml.safe_load(Path("config/straw_model.yaml").read_text(encoding="utf-8"))
    status = status_result.get("status") or status_result.get("status_candidate")
    candidate_ok = status_result.get("confidence_band") in ("MODERATE", "HIGH")
    trusted_model = status_result.get("model_trust_state") == "VALIDATED_MODEL"
    eligible = status == "HARVESTED" and (trusted_model or status_result.get("method") == "RULE-BASED STATUS CANDIDATE" and candidate_ok)
    area = _num(row.get("area_ha"))
    if not eligible:
        return {"eligible": False, "status": "NOT_ELIGIBLE", "reason": "No sufficiently credible harvested status/candidate", "is_ground_truth": False}
    if area is None or area <= 0:
        return {"eligible": False, "status": "INSUFFICIENT_INPUT", "reason": "Positive area_ha is required", "is_ground_truth": False}
    yield_t_ha = float(cfg["baseline_yield_t_per_ha"])
    baseline = area * yield_t_ha
    peak = _num(row.get("peak_NDVI_so_far"))
    if cfg.get("peak_adjustment_enabled", True) and peak is not None:
        factor = 1 + float(cfg["peak_adjustment_coefficient"]) * (peak - float(cfg["reference_peak_ndvi"]))
        factor = max(float(cfg["adjustment_min"]), min(float(cfg["adjustment_max"]), factor))
    else:
        factor = 1.0
    estimate = baseline * factor
    uncertainty = float(cfg["uncertainty_fraction"])
    return {"eligible": True, "status": "PRELIMINARY_ESTIMATE", "field_id": row.get("field_id"), "area_ha": area,
            "baseline_yield_t_per_ha": yield_t_ha, "baseline_straw_tonnes": baseline,
            "vegetation_adjustment": factor, "estimated_straw_tonnes": estimate,
            "adjusted_straw_tonnes": estimate, "lower_estimate_tonnes": estimate * (1-uncertainty),
            "upper_estimate_tonnes": estimate * (1+uncertainty),
            "estimate_method": "AREA_BASELINE_PEAK_NDVI_V1", "uncertainty_type": "configurable scenario range, not statistical interval",
            "calibration_state": "UNCALIBRATED_PRELIMINARY", "is_ground_truth": False}


def _num(x):
    try: return float(x) if x not in (None, "") else None
    except (TypeError, ValueError): return None
