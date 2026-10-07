"""Accuracy and stratified burned-area estimate from Tier-B visual labels (Olofsson et al. 2014).

Input: data/real/labels/visual_labels_<year>.csv exported by the labelling tool
(reports/research/label_tool/label_burns_<year>.html). The sample is stratified by the detector's
own output (rule_burn_strict, rule_burn_loose_only, rule_no_burn) with the population sizes stored in
sample_design_<year>.json, so every estimate below is design-unbiased for the field population.
UNCLEAR labels are reported and excluded from proportions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "real" / "labels"
TOOL = ROOT / "reports" / "research" / "label_tool"
OUT = ROOT / "reports" / "research"
MAP_BURN = {"rule_burn_strict", "rule_burn_loose_only"}


def evaluate(year: int) -> dict:
    lab = pd.read_csv(LABELS / f"visual_labels_{year}.csv")
    design = json.loads((TOOL / f"sample_design_{year}.json").read_text(encoding="utf-8"))
    pop = design["population_by_stratum"]
    N = sum(pop.values())
    rows, est, var = [], 0.0, 0.0
    burned_hat = {}
    for h, Nh in pop.items():
        s = lab[lab.stratum == h]
        decided = s[s.label.isin(["BURNT", "NOT_BURNT"])]
        n = len(decided)
        p = float((decided.label == "BURNT").mean()) if n else float("nan")
        Wh = Nh / N
        rows.append(dict(stratum=h, population_fields=Nh, labelled=len(s), decided=n, unclear=int((s.label == "UNCLEAR").sum()),
                         burnt_share=round(p, 4) if n else None))
        if n:
            est += Wh * p
            var += Wh ** 2 * p * (1 - p) / max(n - 1, 1)
            burned_hat[h] = Nh * p
    se = var ** 0.5
    total_burned = sum(burned_hat.values())
    map_burned = sum(pop[h] for h in MAP_BURN)
    ua = sum(burned_hat.get(h, 0) for h in MAP_BURN) / map_burned if map_burned else float("nan")
    pa = sum(burned_hat.get(h, 0) for h in MAP_BURN) / total_burned if total_burned else float("nan")
    strict_ua = rows[[r["stratum"] for r in rows].index("rule_burn_strict")]["burnt_share"]
    out = dict(year=year, n_labels=int(len(lab)), strata=rows,
               burned_field_share_estimate=round(est, 4), burned_field_share_ci95=[round(est - 1.96 * se, 4), round(est + 1.96 * se, 4)],
               burned_fields_estimate=round(total_burned), map_burned_fields=int(map_burned),
               precision_burn_map=round(ua, 4), recall_burn_map=round(pa, 4), precision_strict_tier=strict_ua,
               method="Stratified estimator (Olofsson et al. 2014, Remote Sens. Environ. 148:42-57) over field units; strata = detector output.",
               label_quality="B (multi-date human visual review of Sentinel-2 chips)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=[2025, 2023])
    a = ap.parse_args()
    res = {}
    for y in a.years:
        if (LABELS / f"visual_labels_{y}.csv").exists():
            res[str(y)] = evaluate(y)
            print(json.dumps(res[str(y)], indent=1))
        else:
            print(f"no labels for {y}: expected {LABELS / f'visual_labels_{y}.csv'}")
    if res:
        (OUT / "validation_visual_labels.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
