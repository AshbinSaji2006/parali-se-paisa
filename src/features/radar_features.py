from __future__ import annotations

import math
import statistics


def _mean_finite(values):
    if values is None:
        return None
    if not isinstance(values, (list, tuple)):
        values = [values]
    clean = []
    for value in values:
        try:
            v = float(value)
            if math.isfinite(v):
                clean.append(v)
        except (TypeError, ValueError):
            pass
    return statistics.fmean(clean) if clean else None


def aggregate_s1_observation(observation: dict | None) -> dict:
    if observation is None:
        return {"VV_mean_db": None, "VH_mean_db": None, "VV_minus_VH_db": None,
                "VV_VH_ratio_linear": None, "missing_vh": True}
    vv = _mean_finite(observation.get("VV_dB", observation.get("VV_mean_db")))
    vh = _mean_finite(observation.get("VH_dB", observation.get("VH_mean_db")))
    if vv is not None and vh is not None:
        if observation.get("VV_VH_ratio_linear_mean") is not None:
            ratio = _finite(observation["VV_VH_ratio_linear_mean"])
            if ratio is not None and ratio < 0:
                ratio = None
        elif observation.get("VV_linear_mean") is not None and observation.get("VH_linear_mean") is not None:
            linear_vv, linear_vh = _finite(observation["VV_linear_mean"]), _finite(observation["VH_linear_mean"])
            ratio = linear_vv / linear_vh if linear_vv is not None and linear_vh is not None and linear_vh > 0 and linear_vv >= 0 else None
        elif isinstance(observation.get("VV_dB"), (list, tuple)) and isinstance(observation.get("VH_dB"), (list, tuple)):
            vv_powers = [10 ** (float(x) / 10) for x in observation["VV_dB"] if _isfinite(x)]
            vh_powers = [10 ** (float(x) / 10) for x in observation["VH_dB"] if _isfinite(x)]
            ratio = statistics.fmean(vv_powers) / statistics.fmean(vh_powers) if vv_powers and vh_powers and statistics.fmean(vh_powers) > 0 else None
        else:
            # Do not pretend the ratio of mean dB values (or their geometric powers)
            # is the field mean ratio. A reducer must provide its linear ratio mean.
            ratio = None
    else:
        ratio = None
    return {"VV_mean_db": vv, "VH_mean_db": vh,
            "VV_minus_VH_db": vv - vh if vv is not None and vh is not None else None,
            "VV_VH_ratio_linear": ratio, "missing_vh": vh is None}


def _isfinite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _finite(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None
