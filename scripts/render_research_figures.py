"""Re-render research figures from the saved result tables (no recomputation of experiments)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("run_research", ROOT / "scripts" / "run_research.py")
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

if __name__ == "__main__":
    rep_dir = ROOT / "reports" / "research"
    census = pd.read_csv(rep_dir / "census_blindspot_harmonised.csv")
    naive = pd.read_csv(rep_dir / "naive_dnbr_vs_harvest_aware.csv")
    smoke = pd.read_csv(rep_dir / "smoke_blindness_by_date.csv", parse_dates=["date"])
    rep = pd.read_csv(rep_dir / "replay_2025.csv")
    te = pd.read_parquet(ROOT / "data" / "real" / "derived" / "timeseries" / "risk_features_2025.parquet")
    now = rr.nowcast_2026(te)
    rr.figures(census, naive, smoke, None, None, rep, now)
