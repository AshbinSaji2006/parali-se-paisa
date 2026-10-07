"""Import, validate, repair safely, and normalize field polygons to GeoJSON."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely import get_coordinates
from shapely import make_valid
from shapely.ops import transform
from shapely.strtree import STRtree

LOG = logging.getLogger(__name__)
REQUIRED_ATTRIBUTES = ("field_id", "geometry")


def _feature_key(feature: dict[str, Any]) -> str | None:
    props = feature.get("properties") or {}
    return props.get("field_id")


def process_fields(config_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    cfg, pilot = config["fields"], config["pilot"]
    input_path, output_path, report_path = (root / cfg[k] for k in ("input", "output", "report"))
    area_crs = CRS.from_user_input(pilot["area_crs"])
    to_area = Transformer.from_crs("EPSG:4326", area_crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(area_crs, "EPSG:4326", always_xy=True).transform
    collection = json.loads(input_path.read_text(encoding="utf-8"))
    prior_created_at: dict[str, str] = {}
    if output_path.exists():
        try:
            prior = json.loads(output_path.read_text(encoding="utf-8"))
            prior_created_at = {f["properties"]["field_id"]: f["properties"]["created_at"] for f in prior.get("features", []) if f.get("properties", {}).get("field_id") and f.get("properties", {}).get("created_at")}
        except (json.JSONDecodeError, OSError, KeyError):
            LOG.warning("Existing processed GeoJSON could not be read; creation timestamps will be regenerated")
    metadata = collection.get("metadata", {})
    is_demo = metadata.get("dataset_type") == "DEMO"
    findings: list[dict[str, Any]] = []
    accepted: list[tuple[dict[str, Any], Any]] = []
    seen_ids: set[str] = set()
    seen_geometries: set[bytes] = set()
    min_area_m2 = float(cfg.get("min_area_ha", 0.01)) * 10000

    for index, feature in enumerate(collection.get("features", [])):
        fid = _feature_key(feature)
        props = dict(feature.get("properties") or {})
        issues: list[str] = []
        warnings: list[str] = []
        repaired = False
        if not fid:
            issues.append("missing_required_attribute:field_id")
        elif str(fid) in seen_ids:
            issues.append("duplicate_field_id")
        else:
            seen_ids.add(str(fid))
        if not feature.get("geometry"):
            issues.append("missing_required_attribute:geometry")
            geom = None
        else:
            try:
                geom = shape(feature["geometry"])
            except Exception:
                geom = None
                issues.append("unreadable_geometry")
        if geom is None or geom.is_empty:
            issues.append("empty_geometry")
        elif geom.geom_type not in ("Polygon", "MultiPolygon"):
            issues.append("geometry_not_polygon")
        else:
            minx, miny, maxx, maxy = geom.bounds
            coords = get_coordinates(geom)
            if not all(math.isfinite(float(value)) for row in coords for value in row[:2]) or minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
                issues.append("coordinates_outside_valid_wgs84_bounds")
            if not geom.is_valid:
                try:
                    candidate = make_valid(geom)
                    if candidate.geom_type in ("Polygon", "MultiPolygon") and not candidate.is_empty and candidate.is_valid:
                        geom, repaired = candidate, True
                        warnings.append("geometry_repaired_make_valid")
                    else:
                        issues.append("invalid_geometry_not_safely_repairable")
                except Exception:
                    issues.append("invalid_geometry_repair_failed")
            if geom.is_valid and not geom.is_empty:
                geom_hash = geom.normalize().wkb
                if geom_hash in seen_geometries:
                    if "duplicate_geometry" not in issues:
                        issues.append("duplicate_geometry")
                seen_geometries.add(geom_hash)
            if not issues:
                area_m2 = transform(to_area, geom).area
                if not (area_m2 > 0):
                    issues.append("zero_or_invalid_area")
                elif area_m2 < min_area_m2:
                    issues.append("area_below_minimum")
        findings.append({"feature_index": index, "field_id": fid, "issues": issues, "warnings": warnings, "repaired": repaired})
        if issues:
            continue
        metric_geom = transform(to_area, geom)
        area_m2 = metric_geom.area
        centroid = transform(to_wgs84, metric_geom.centroid)
        props.update({
            "field_id": str(fid), "farmer_id": props.get("farmer_id"),
            "district": props.get("district") or pilot["district"],
            "village": props.get("village"), "centroid_lat": centroid.y,
            "centroid_lon": centroid.x, "area_m2": area_m2,
            "area_ha": area_m2 / 10000, "crop": props.get("crop"),
            "season": props.get("season") or pilot["season"],
            "source": props.get("source") or "geojson_import",
            "created_at": props.get("created_at") or prior_created_at.get(str(fid)) or datetime.now(timezone.utc).isoformat(),
            "data_status": "DEMO_SYNTHETIC" if is_demo else props.get("data_status", "IMPORTED_UNVERIFIED"),
            "geometry_repaired": repaired,
        })
        accepted.append(({"type": "Feature", "properties": props, "geometry": mapping(geom)}, metric_geom))

    # Report positive-area overlaps among accepted polygons. Duplicates have already been excluded.
    overlap_pairs: list[dict[str, Any]] = []
    if accepted:
        geometries = [entry[1] for entry in accepted]
        tree = STRtree(geometries)
        for i, geom in enumerate(geometries):
            for j in tree.query(geom, predicate="intersects"):
                j = int(j)
                if j > i:
                    overlap_area = geom.intersection(geometries[j]).area
                    if overlap_area > 1.0:  # ignore sub-square-metre numerical slivers
                        overlap_pairs.append({"field_id_a": accepted[i][0]["properties"]["field_id"], "field_id_b": accepted[j][0]["properties"]["field_id"], "overlap_area_m2": overlap_area})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    out = {"type": "FeatureCollection", "name": "fields_clean", "metadata": {"dataset_type": "DEMO" if is_demo else "IMPORTED", "source": str(input_path), "warning": metadata.get("warning"), "coordinate_reference_system": "EPSG:4326 (RFC 7946)"}, "features": [entry[0] for entry in accepted]}
    output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    report = {
        "input": str(input_path), "output": str(output_path), "dataset_type": "DEMO" if is_demo else "IMPORTED",
        "input_features": len(collection.get("features", [])), "valid_features": len(accepted),
        "skipped_features": sum(bool(item["issues"]) for item in findings),
        "repaired_features": sum(item["repaired"] for item in findings),
        "duplicate_warnings": sum("duplicate_field_id" in item["issues"] or "duplicate_geometry" in item["issues"] for item in findings),
        "overlap_warnings": overlap_pairs, "findings": findings, "area_crs": area_crs.to_string(),
        "output_crs": "EPSG:4326", "area_range_ha": [min((e[0]["properties"]["area_ha"] for e in accepted), default=0), max((e[0]["properties"]["area_ha"] for e in accepted), default=0)],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    LOG.info("Fields input=%s valid=%d skipped=%d repaired=%d overlap_pairs=%d output=%s", input_path, report["valid_features"], report["skipped_features"], report["repaired_features"], len(overlap_pairs), output_path)
    return report
