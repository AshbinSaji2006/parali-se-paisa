import json
from pathlib import Path

from src.geo.fields import process_fields

ROOT = Path(__file__).resolve().parents[1]


def test_demo_fixture_validates_repairs_and_reports_overlaps():
    report = process_fields(ROOT / "config/pilot.yaml")
    output = json.loads((ROOT / "data/processed/fields/fields_clean.geojson").read_text(encoding="utf-8"))
    assert report["dataset_type"] == "DEMO"
    assert report["valid_features"] == 4
    assert report["skipped_features"] == 3
    assert report["repaired_features"] == 1
    assert report["duplicate_warnings"] == 1
    assert report["overlap_warnings"]
    assert report["output_crs"] == "EPSG:4326"
    assert output["metadata"]["coordinate_reference_system"].startswith("EPSG:4326")
    assert all(f["properties"]["data_status"] == "DEMO_SYNTHETIC" for f in output["features"])
    assert any(f["properties"]["geometry_repaired"] for f in output["features"])


def test_setup_is_idempotent_and_multiple_valid_fields_survive():
    first = process_fields(ROOT / "config/pilot.yaml")
    output_path = ROOT / "data/processed/fields/fields_clean.geojson"
    content1 = json.loads(output_path.read_text(encoding="utf-8"))
    bytes1 = output_path.read_bytes()
    second = process_fields(ROOT / "config/pilot.yaml")
    content2 = json.loads(output_path.read_text(encoding="utf-8"))
    assert first["valid_features"] == second["valid_features"] == 4
    assert [f["properties"]["field_id"] for f in content1["features"]] == [f["properties"]["field_id"] for f in content2["features"]]
    assert [f["properties"]["area_ha"] for f in content1["features"]] == [f["properties"]["area_ha"] for f in content2["features"]]
    assert output_path.read_bytes() == bytes1


def test_validation_flags_duplicate_id_missing_id_and_out_of_bounds(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "data/raw/fields").mkdir(parents=True)
    (tmp_path / "config/pilot.yaml").write_text(
        "pilot:\n  district: X\n  season: kharif\n  area_crs: EPSG:32643\nfields:\n  input: data/raw/fields/in.geojson\n  output: data/processed/out.geojson\n  report: reports/report.json\n  min_area_ha: 0.001\n",
        encoding="utf-8",
    )
    polygon = lambda fid, coordinates: {"type": "Feature", "properties": {"field_id": fid} if fid else {}, "geometry": {"type": "Polygon", "coordinates": [coordinates]}}
    ring = [[74.5, 30], [74.501, 30], [74.501, 30.001], [74.5, 30.001], [74.5, 30]]
    fc = {"type": "FeatureCollection", "features": [polygon("same", ring), polygon("same", ring), polygon(None, ring), polygon("outside", [[181, 30], [182, 30], [182, 31], [181, 30]])]}
    (tmp_path / "data/raw/fields/in.geojson").write_text(json.dumps(fc), encoding="utf-8")
    report = process_fields(tmp_path / "config/pilot.yaml")
    reasons = [reason for item in report["findings"] for reason in item["issues"]]
    assert "duplicate_field_id" in reasons
    assert "duplicate_geometry" in reasons
    assert "missing_required_attribute:field_id" in reasons
    assert "coordinates_outside_valid_wgs84_bounds" in reasons
    assert report["valid_features"] == 1


def test_projected_area_is_reasonable_and_multipolygon_supported(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "data/raw/fields").mkdir(parents=True)
    (tmp_path / "config/pilot.yaml").write_text(
        "pilot:\n  district: X\n  season: kharif\n  area_crs: EPSG:32643\nfields:\n  input: data/raw/fields/in.geojson\n  output: data/processed/out.geojson\n  report: reports/report.json\n  min_area_ha: 0.001\n",
        encoding="utf-8",
    )
    ring1 = [[74.5, 30], [74.501, 30], [74.501, 30.001], [74.5, 30.001], [74.5, 30]]
    ring2 = [[74.51, 30], [74.511, 30], [74.511, 30.001], [74.51, 30.001], [74.51, 30]]
    feat = {"type": "Feature", "properties": {"field_id": "multi"}, "geometry": {"type": "MultiPolygon", "coordinates": [[ring1], [ring2]]}}
    (tmp_path / "data/raw/fields/in.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [feat]}), encoding="utf-8")
    report = process_fields(tmp_path / "config/pilot.yaml")
    props = json.loads((tmp_path / "data/processed/out.geojson").read_text(encoding="utf-8"))["features"][0]["properties"]
    assert report["valid_features"] == 1
    assert 2.0 < props["area_ha"] < 2.3
