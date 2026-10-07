from __future__ import annotations


def rule_status_candidate(row):
    """Descriptive candidate only; never ground truth or a trained prediction."""
    evidence = []
    ndvi = _num(row.get("NDVI_mean")); delta = _num(row.get("NDVI_delta"))
    drop = _num(row.get("NDVI_drop_from_peak")); nbr_delta = _num(row.get("NBR_delta"))
    bais_delta = _num(row.get("BAIS2_delta")); nbr = _num(row.get("NBR_mean"))
    if ndvi is None:
        return {"status_candidate": None, "method": "RULE-BASED STATUS CANDIDATE", "evidence": ["Current NDVI unavailable"], "confidence_band": "LOW", "is_ground_truth": False}
    if drop is not None and drop <= -0.25:
        evidence.append("Large NDVI decline from the observed peak")
    if delta is not None and delta <= -0.2:
        evidence.append("Sharp negative NDVI change")
    if nbr_delta is not None and nbr_delta <= -0.15:
        evidence.append("NBR decreased")
    if bais_delta is not None and bais_delta >= 0.1:
        evidence.append("BAIS2 increased")
    if row.get("recent_fire_24h") is True or str(row.get("recent_fire_24h")).lower() == "true":
        evidence.append("Recent FIRMS context is present; it is supporting evidence only")
    drop_signal = (drop is not None and drop <= -0.25) or (delta is not None and delta <= -0.2)
    nbr_signal = nbr_delta is not None and nbr_delta <= -0.15
    bais_signal = bais_delta is not None and bais_delta >= 0.1
    if drop_signal and nbr_signal and bais_signal:
        status, band = "BURNT", "MODERATE"
    elif drop_signal:
        status, band = "HARVESTED", "MODERATE" if nbr_signal else "LOW"
    elif delta is not None and delta >= 0.12 and ndvi >= 0.3:
        status, band = "SOWN", "LOW"
        evidence.append("NDVI increased; possible new vegetation growth")
    elif ndvi >= 0.55 and (delta is None or delta > -0.15):
        status, band = "STANDING", "LOW"
        evidence.append("Relatively high NDVI without a large observed drop")
    else:
        status, band = None, "LOW"
        evidence.append("Evidence is insufficient for a descriptive status candidate")
    return {"status_candidate": status, "method": "RULE-BASED STATUS CANDIDATE", "evidence": evidence,
            "confidence_band": band, "is_ground_truth": False}


def _num(x):
    try: return float(x) if x not in (None, "") else None
    except (TypeError, ValueError): return None
