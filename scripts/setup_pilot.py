import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.geo.fields import process_fields


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and normalize configured field GeoJSON.")
    parser.add_argument("--config", default="config/pilot.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = process_fields(args.config)
    print(f"Dataset type: {report['dataset_type']}; valid fields: {report['valid_features']}; skipped: {report['skipped_features']}")


if __name__ == "__main__":
    main()
