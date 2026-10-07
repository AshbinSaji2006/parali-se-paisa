"""Season-replay digital twin: how many observed burns could a baler fleet have pre-empted?

The real 2025 Muktsar season is replayed day by day from Sentinel-2 field events:
- a field becomes collectable on the day its harvest is first observed (satellite-triggered) and stays
  collectable for WINDOW_DAYS or until it burns;
- a burn-candidate field counts as pre-empted only if it is baled on or before the last observation
  at which it was still unburned (conservative: the fire happened after that observation);
- each baler covers one service zone (k-means of field centroids, area weighted) and bales up to
  HA_PER_DAY of straw-bearing area per working day; days with district ERA5 rain > RAIN_MM are skipped
  because wet straw cannot be baled.
Travel inside a zone is not routed (the operational app routes with OR-Tools); this is a policy
comparison under stated assumptions, not a forecast of real interventions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans

HA_PER_DAY = 4.0      # ~10 acres/day per baler
WINDOW_DAYS = 20      # field stays collectable this long after harvest is observed
RAIN_MM = 2.0
BALED_T_PER_HA = 3.3  # 12-15 quintal/acre of bales (concept note [9])


@dataclass
class ReplayResult:
    policy: str
    fleet: int
    burned_fields: int
    preempted_fields: int
    preempted_ha: float
    preemptable_fields: int
    baled_ha: float
    baled_t: float
    preempted_t: float

    @property
    def preempted_share(self) -> float:
        return self.preempted_fields / max(self.burned_fields, 1)


def zones(f: pd.DataFrame, fleet: int, seed: int = 0) -> np.ndarray:
    km = MiniBatchKMeans(n_clusters=fleet, random_state=seed, batch_size=4096, n_init=3)
    return km.fit_predict(f[["x", "y"]].values, sample_weight=f.pixel_area_ha.values)


def priority(f: pd.DataFrame, policy: str, rng: np.random.Generator, day: pd.Timestamp) -> np.ndarray:
    age = (day - f.harvest_date).dt.days.values.astype(float)
    if policy == "random":
        return rng.random(len(f))
    if policy == "fifo":
        return age
    if policy == "largest_first":
        return f.pixel_area_ha.values
    if policy == "risk":
        return f.risk_score.values + 1e-4 * age
    if policy == "risk_urgency":
        return f.risk_score.values * (1.0 + age / 10.0)
    if policy == "dynamic":
        # hazard re-scored at the latest Sentinel-2 pass on or before `day` (see src/research/hazard.py)
        return f.dyn_score.values + 1e-4 * age
    if policy == "oracle":
        # earliest true deadline first among fields that will burn; others last
        dl = (f.burn_prev_date - day).dt.days.values.astype(float)
        return np.where(f.burned.values, 1000.0 - np.nan_to_num(dl, nan=999.0), age * 1e-3)
    raise ValueError(policy)


def replay(fields: pd.DataFrame, rain_days: set, fleet: int, policy: str, seed: int = 0,
           ha_per_day: float = HA_PER_DAY, window_days: int = WINDOW_DAYS,
           dynamic_scores: pd.DataFrame | None = None) -> ReplayResult:
    """dynamic_scores: columns field_id, t, score (needed only for policy='dynamic')."""
    f = fields.copy().reset_index(drop=True)
    if policy == "dynamic":
        piv = dynamic_scores.pivot_table(index="field_id", columns="t", values="score", aggfunc="first")
        piv = piv.reindex(f.field_id)
        pass_dates = np.array(sorted(piv.columns), dtype="datetime64[ns]")
        fallback = f.risk_score.values * 1e-3
    f["zone"] = zones(f, fleet, seed)
    rng = np.random.default_rng(seed)
    served = np.zeros(len(f), dtype=bool)
    served_day = np.full(len(f), np.datetime64("NaT"), dtype="datetime64[ns]")
    start, end = f.harvest_date.min(), f.harvest_date.max() + pd.Timedelta(days=window_days)
    for day in pd.date_range(start, end, freq="D"):
        if day.normalize() in rain_days:
            continue
        avail = (~served) & (f.harvest_date.values <= day) & \
                (f.harvest_date.values + np.timedelta64(window_days, "D") >= day) & \
                ~(f.burned.values & (f.burn_date.values <= day))
        if not avail.any():
            continue
        idx = np.flatnonzero(avail)
        if policy == "dynamic":
            k = np.searchsorted(pass_dates, np.datetime64(day), side="right") - 1
            col = piv.iloc[:, k].values if k >= 0 else np.full(len(f), np.nan)
            f["dyn_score"] = np.where(np.isnan(col), fallback, col)
        sub = f.iloc[idx]
        pr = priority(sub, policy, rng, day)
        order = np.lexsort((-pr, sub.zone.values))
        z = sub.zone.values[order]
        area = sub.pixel_area_ha.values[order]
        cum = pd.Series(area).groupby(z).cumsum().values
        take = cum <= ha_per_day
        # always allow the first field in a zone even if it exceeds a day's capacity
        first = np.r_[True, z[1:] != z[:-1]]
        take |= first
        chosen = idx[order[take]]
        served[chosen] = True
        served_day[chosen] = np.datetime64(day)
    burned = f.burned.values
    deadline = f.burn_prev_date.values
    pre = burned & served & (served_day <= deadline)
    preemptable = burned & (f.burn_prev_date.values >= f.harvest_date.values)
    baled_ha = float(f.pixel_area_ha.values[served].sum())
    return ReplayResult(policy, fleet, int(burned.sum()), int(pre.sum()), float(f.pixel_area_ha.values[pre].sum()),
                        int(preemptable.sum()), baled_ha, baled_ha * BALED_T_PER_HA,
                        float(f.pixel_area_ha.values[pre].sum()) * BALED_T_PER_HA)
