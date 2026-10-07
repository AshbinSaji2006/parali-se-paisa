import argparse
from src.models.field_status.labels import import_labels

parser = argparse.ArgumentParser(description="Validate and append provenance-bearing human/external field labels.")
parser.add_argument("input", help="CSV using the documented label schema")
parser.add_argument("--output", default="data/processed/labels/status_labels.csv")
args = parser.parse_args()
rows = import_labels(args.input, args.output)
print(f"Imported {len(rows)} validated labels to {args.output}")
