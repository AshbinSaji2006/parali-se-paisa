import argparse
import json
from pathlib import Path

from src.models.field_status.dataset import read_csv
from src.intelligence.service import intelligence_for_row

parser = argparse.ArgumentParser(description="Run offline intelligence candidates over synthetic fixture rows.")
parser.add_argument("--features", default="data/processed/features/field_features_temporal.csv")
parser.add_argument("--output", default="reports/intelligence_demo_output.json")
args = parser.parse_args()
rows = read_csv(args.features)
if any(row.get("fixture_or_real") != "SYNTHETIC" for row in rows):
    raise SystemExit("demo requires an explicitly synthetic-only feature dataset")
results = [intelligence_for_row(row) for row in rows]
out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(results, indent=2), encoding="utf-8")
print("SYNTHETIC DEMO — rule-based candidates and preliminary estimates only; no real labels or validated model")
for item in results:
    print(f"{item['field_id']} {item['provenance']['observation_datetime']}: candidate={item['field_status'].get('status_candidate')}; straw={item['straw'].get('estimated_straw_tonnes')}; burn_risk={item['burn_risk'].get('risk_score')} ({item['burn_risk'].get('risk_level', item['burn_risk'].get('status'))})")
print(f"Full output: {out}")
