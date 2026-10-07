import csv
import json
from pathlib import Path

import pytest
import yaml

from src.models.audit import audit_dataset
from src.models.burn_risk.rules import rule_burn_risk
from src.models.burn_risk.train import train_burn_risk
from src.models.field_status.dataset import (LABELS, eligible_label_rows, load_schema, read_csv,
                                              split_by_field, synthetic_smoke_rows)
from src.models.field_status.inference import FieldStatusModel
from src.models.field_status.labels import LABEL_COLUMNS, import_labels, validate_label
from src.models.field_status.rules import rule_status_candidate
from src.models.field_status.train import train_field_status
from src.models.straw import estimate_straw
from src.intelligence.service import intelligence_for_row
from src.data.facilities import facility_distance_context, load_facilities
from src.models.registry import model_trust_state

ROOT = Path(__file__).resolve().parents[1]


def harvest_row(**changes):
    row = {"field_id": "F-A", "season": "kharif", "year": 2026, "observation_datetime": "2026-10-10T00:00:00+00:00",
           "area_ha": 2.0, "fixture_or_real": "SYNTHETIC", "feature_schema_version": "1.0",
           "processing_version": "0.1", "source_image_id_s2": "S2-A", "source_image_id_s1": "S1-A",
           "NDVI_mean": .3, "NDVI_delta": -.35, "NDVI_drop_from_peak": -.4, "NBR_mean": .25,
           "NBR_delta": -.12, "BAIS2_delta": .03, "peak_NDVI_so_far": .7,
           "rain_72h": 1.0, "humidity_pct": 35.0, "recent_fire_72h": False,
           "observation_quality": "LIMITED"}
    row.update(changes)
    return row


def test_schema_freeze_covers_full_table_and_training_allowlist():
    schema = load_schema()
    with (ROOT / "data/processed/features/field_features_temporal.csv").open(newline="", encoding="utf-8") as f:
        cols = next(csv.reader(f))
    assert list(schema["fields"]) == cols
    assert len(cols) == 129
    assert schema["fields"]["field_id"]["training_allowed"] is False
    assert schema["fields"]["source_image_id_s2"]["training_allowed"] is False
    assert schema["fields"]["status_label"]["feature_group"] == "LABEL"
    assert all(schema["fields"][x]["training_allowed"] for x in schema["training_features"])


def test_integrated_audit_passes_structure_but_refuses_training_readiness_without_real_labels():
    report = audit_dataset()
    assert report["passed"] is True
    assert report["fixture_or_real_counts"] == {"SYNTHETIC": 6}
    assert report["label_rows"] == 0
    assert report["ml_training_ready"] is False
    assert report["future_leakage_indicators"] == {}


def test_audit_rejects_wrong_column_schema(tmp_path):
    src = ROOT / "data/processed/features/field_features_temporal.csv"
    rows = read_csv(src)
    out = tmp_path / "wrong.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])[::-1]); w.writeheader(); w.writerows(rows)
    report = audit_dataset(out)
    assert not report["passed"]
    assert any("schema" in e for e in report["errors"])


def test_audit_detects_future_temporal_feature(tmp_path):
    rows = read_csv(ROOT / "data/processed/features/field_features_temporal.csv")
    rows[0]["previous_observation_datetime"] = "2027-01-01T00:00:00+00:00"
    path = tmp_path / "future.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    result = audit_dataset(path)
    assert not result["passed"]
    assert any("future leakage indicator" in e for e in result["errors"])


def test_label_validation_requires_complete_provenance_and_tier_consistency():
    row = dict(zip(LABEL_COLUMNS, ["F", "2026-10-01T00:00:00+00:00", "HARVESTED", "FIELD_SURVEY", .9, "A", "reviewer", "field visit", "2026-10-02T00:00:00+00:00"]))
    assert validate_label(row)["label_confidence"] == .9
    bad = {**row, "label_source": "SYNTHETIC_TEST"}
    with pytest.raises(ValueError, match="inconsistent"):
        validate_label(bad)
    synthetic = {**row, "label_source": "SYNTHETIC_TEST", "label_quality": "S"}
    assert validate_label(synthetic)["label_quality"] == "S"


def test_label_importer_appends_valid_rows_and_rejects_duplicates(tmp_path):
    input_path, output = tmp_path / "new.csv", tmp_path / "registry.csv"
    row = dict(zip(LABEL_COLUMNS, ["F", "2026-10-01T00:00:00+00:00", "STANDING", "FIELD_SURVEY", .95, "A", "reviewer", "visit", "2026-10-02T00:00:00+00:00"]))
    with input_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LABEL_COLUMNS); writer.writeheader(); writer.writerow(row)
    assert len(import_labels(input_path, output)) == 1
    with pytest.raises(ValueError, match="duplicate"):
        import_labels(input_path, output)


def test_synthetic_labels_are_excluded_from_real_training_by_default():
    feature = harvest_row(fixture_or_real="REAL")
    label = {"field_id": "F-A", "observation_datetime": feature["observation_datetime"], "status_label": "HARVESTED", "label_source": "SYNTHETIC_TEST", "label_quality": "S"}
    eligible, excluded = eligible_label_rows([feature], [label], allow_synthetic=False)
    assert not eligible and excluded[0]["reason"] == "synthetic_label_not_allowed"
    allowed, _ = eligible_label_rows([feature], [label], allow_synthetic=True)
    assert not allowed
    synthetic_feature = {**feature, "fixture_or_real": "SYNTHETIC"}
    allowed, _ = eligible_label_rows([synthetic_feature], [label], allow_synthetic=True)
    assert len(allowed) == 1


def test_weak_proxy_labels_below_default_tier_are_excluded():
    feature = harvest_row()
    label = {"field_id": "F-A", "observation_datetime": feature["observation_datetime"], "status_label": "BURNT", "label_source": "FIRMS_SUPPORTED_WEAK_LABEL", "label_quality": "C"}
    eligible, excluded = eligible_label_rows([feature], [label], minimum_quality="B")
    assert not eligible and excluded[0]["reason"] == "label_quality_below_threshold"


def test_field_group_split_keeps_every_field_in_one_partition():
    rows = synthetic_smoke_rows()
    parts = split_by_field(rows)
    memberships = [{r["field_id"] for r in parts[k]} for k in ("train", "validation", "test")]
    assert not memberships[0] & memberships[1]
    assert not memberships[0] & memberships[2]
    assert not memberships[1] & memberships[2]
    assert sum(map(len, parts.values())) == len(rows)


def test_split_rejects_too_few_independent_field_groups():
    with pytest.raises(ValueError, match="at least 3"):
        split_by_field([{"field_id": "F1", "status_label": "SOWN"}, {"field_id": "F2", "status_label": "SOWN"}])


def test_feature_encoding_never_includes_identifiers_and_encodes_quality():
    schema = load_schema()
    assert "field_id" not in schema["training_features"]
    assert "source_image_id_s2" not in schema["training_features"]
    assert "fixture_or_real" not in schema["training_features"]
    row = {name: 1 for name in schema["training_features"]}
    row["observation_quality"] = "LIMITED"
    assert 1.0 in __import__("src.models.field_status.dataset", fromlist=["encode_feature_row"]).encode_feature_row(row, schema["training_features"])


def test_random_forest_and_gradient_boosting_train_and_serialize_as_synthetic_only(tmp_path):
    models, metadata, report = train_field_status(synthetic_smoke_rows(), tmp_path, dataset_provenance="SYNTHETIC_TEST")
    assert set(models) == {"random_forest", "gradient_boosting"}
    assert metadata["trust_state"] == "SYNTHETIC_TEST_MODEL"
    assert "NOT A SCIENTIFIC PERFORMANCE RESULT" in report["metric_scope"]
    assert (tmp_path / "models.pkl").exists() and (tmp_path / "metadata.json").exists()


def test_synthetic_serialized_model_is_refused_without_explicit_test_gate(tmp_path):
    train_field_status(synthetic_smoke_rows(), tmp_path, dataset_provenance="SYNTHETIC_TEST")
    with pytest.raises(ValueError, match="cannot be loaded"):
        FieldStatusModel(tmp_path)
    model = FieldStatusModel(tmp_path, allow_synthetic=True)
    assert model.metadata["trust_state"] == "SYNTHETIC_TEST_MODEL"


def test_schema_fingerprint_mismatch_is_rejected(tmp_path):
    train_field_status(synthetic_smoke_rows(), tmp_path, dataset_provenance="SYNTHETIC_TEST")
    changed = yaml.safe_load((ROOT / "config/feature_schema.yaml").read_text(encoding="utf-8"))
    changed["schema_version"] = "different"
    schema_path = tmp_path / "schema.yaml"; schema_path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="schema does not match"):
        FieldStatusModel(tmp_path, allow_synthetic=True, schema_path=schema_path)


def test_inference_probability_shape_class_mapping_and_explanation_contract(tmp_path):
    train_field_status(synthetic_smoke_rows(), tmp_path, dataset_provenance="SYNTHETIC_TEST")
    model = FieldStatusModel(tmp_path, allow_synthetic=True)
    row = synthetic_smoke_rows()[0]
    result = model.predict(row)
    assert result["status"] in LABELS
    assert set(result["probabilities"]) == set(LABELS)
    assert sum(result["probabilities"].values()) == pytest.approx(1)
    assert 0 <= result["confidence"] <= 1
    assert "uncalibrated" in result["confidence_semantics"]
    assert result["explanation"]


def test_inference_rejects_missing_schema_features(tmp_path):
    train_field_status(synthetic_smoke_rows(), tmp_path, dataset_provenance="SYNTHETIC_TEST")
    model = FieldStatusModel(tmp_path, allow_synthetic=True)
    with pytest.raises(ValueError, match="missing frozen feature"):
        model.predict({"field_id": "F"})


@pytest.mark.parametrize("row,expected", [
    ({"NDVI_mean": .8, "NDVI_delta": -.02}, "STANDING"),
    ({"NDVI_mean": .3, "NDVI_delta": -.35, "NDVI_drop_from_peak": -.4}, "HARVESTED"),
    ({"NDVI_mean": .1, "NDVI_delta": -.35, "NDVI_drop_from_peak": -.5, "NBR_delta": -.2, "BAIS2_delta": .2}, "BURNT"),
    ({"NDVI_mean": .4, "NDVI_delta": .2}, "SOWN"),
])
def test_rule_status_candidate_interpretable_scenarios(row, expected):
    result = rule_status_candidate(row)
    assert result["status_candidate"] == expected
    assert result["is_ground_truth"] is False
    assert result["method"] == "RULE-BASED STATUS CANDIDATE"
    assert result["evidence"]


def test_rule_status_insufficient_missing_ndvi():
    result = rule_status_candidate({"NDVI_mean": None})
    assert result["status_candidate"] is None
    assert result["confidence_band"] == "LOW"


def test_straw_area_baseline_peak_adjustment_and_scenario_range():
    status = {"status_candidate": "HARVESTED", "confidence_band": "MODERATE", "method": "RULE-BASED STATUS CANDIDATE"}
    result = estimate_straw(harvest_row(), status)
    assert result["baseline_straw_tonnes"] == pytest.approx(12)
    assert result["vegetation_adjustment"] == pytest.approx(.9875)
    assert result["estimated_straw_tonnes"] == pytest.approx(11.85)
    assert result["lower_estimate_tonnes"] == pytest.approx(11.85 * .7)
    assert result["upper_estimate_tonnes"] == pytest.approx(11.85 * 1.3)
    assert result["uncertainty_type"].startswith("configurable scenario")


def test_straw_missing_peak_uses_unadjusted_baseline():
    result = estimate_straw(harvest_row(peak_NDVI_so_far=None), {"status_candidate": "HARVESTED", "confidence_band": "MODERATE", "method": "RULE-BASED STATUS CANDIDATE"})
    assert result["vegetation_adjustment"] == 1
    assert result["estimated_straw_tonnes"] == pytest.approx(12)


@pytest.mark.parametrize("area", [None, 0, -2])
def test_straw_invalid_area_rejected(area):
    result = estimate_straw(harvest_row(area_ha=area), {"status_candidate": "HARVESTED", "confidence_band": "MODERATE", "method": "RULE-BASED STATUS CANDIDATE"})
    assert result["eligible"] is False
    assert result["status"] == "INSUFFICIENT_INPUT"


def test_straw_adjustment_is_clamped():
    cfg = {"baseline_yield_t_per_ha": 6, "peak_adjustment_enabled": True, "reference_peak_ndvi": .75,
           "peak_adjustment_coefficient": 10, "adjustment_min": .9, "adjustment_max": 1.1, "uncertainty_fraction": .2}
    result = estimate_straw(harvest_row(peak_NDVI_so_far=1.0), {"status_candidate": "HARVESTED", "confidence_band": "MODERATE", "method": "RULE-BASED STATUS CANDIDATE"}, cfg)
    assert result["vegetation_adjustment"] == 1.1


def test_straw_is_not_emitted_for_standing_status():
    result = estimate_straw(harvest_row(), {"status_candidate": "STANDING", "confidence_band": "LOW", "method": "RULE-BASED STATUS CANDIDATE"})
    assert not result["eligible"]


def test_risk_missing_inputs_are_not_replaced_with_zero():
    result = rule_burn_risk({}, harvest_date={"state": "UNKNOWN"}, context={})
    assert result["risk_score"] is None
    assert result["risk_level"] == "INSUFFICIENT_DATA"
    assert result["availability"]["has_weather_forecast"] is False
    assert result["score_kind"] == "NORMALIZED_RULE_SCORE_NOT_PROBABILITY"
    assert "probability" not in " ".join(result["top_factors"]).lower()


def test_risk_custom_weight_changes_score_and_reports_normalized_components():
    config = {"weights": {"dry_weather": 1}, "thresholds": {"rain_72h_mm_for_wet": 10, "forecast_rain_72h_mm_for_wet": 10,
               "days_to_deadline": 10, "baler_distance_m_for_max": 1000, "buyer_distance_m_for_max": 1000, "straw_tonnes_for_max": 10},
               "levels": {"LOW": .25, "MEDIUM": .5, "HIGH": .75}}
    result = rule_burn_risk({"rain_72h": 2}, config=config)
    assert result["component_scores"] == {"dry_weather": .8}
    assert result["risk_score"] == pytest.approx(.8)


@pytest.mark.parametrize("score,expected", [(0.1, "LOW"), (.25, "MEDIUM"), (.5, "HIGH"), (.75, "CRITICAL")])
def test_risk_level_threshold_boundaries(score, expected):
    config = {"weights": {"historical_burn_tendency": 1}, "thresholds": {"days_to_deadline": 10, "rain_72h_mm_for_wet": 10,
               "forecast_rain_72h_mm_for_wet": 10, "baler_distance_m_for_max": 1000, "buyer_distance_m_for_max": 1000, "straw_tonnes_for_max": 10},
               "levels": {"LOW": .25, "MEDIUM": .5, "HIGH": .75}}
    assert rule_burn_risk({}, context={"historical_burn_rate": score}, config=config)["risk_level"] == expected


def test_risk_unknown_harvest_date_preserves_state_without_time_pressure():
    result = rule_burn_risk({"rain_72h": 0}, harvest_date={"state": "UNKNOWN", "days_since_harvest": 5, "provenance": "unverified"})
    assert "time_pressure" not in result["component_scores"]
    assert result["harvest_date_state"] == "UNKNOWN"
    assert result["harvest_date_provenance"] == "unverified"


def test_risk_forecast_requires_issuance_no_later_than_observation():
    row = harvest_row(observation_datetime="2026-10-10T00:00:00+00:00")
    after = rule_burn_risk(row, context={"forecast_rain_next_72h": 0, "forecast_issued_at": "2026-10-10T00:01:00+00:00"})
    before = rule_burn_risk(row, context={"forecast_rain_next_72h": 0, "forecast_issued_at": "2026-10-09T23:00:00+00:00"})
    assert "forecast_dryness" not in after["component_scores"]
    assert before["component_scores"]["forecast_dryness"] == 1


def test_risk_explanation_has_top_factors_and_never_probability_claim():
    result = rule_burn_risk(harvest_row(), {"estimated_straw_tonnes": 12},
                            {"state": "CONFIRMED", "days_since_harvest": 6, "provenance": "FIELD_SURVEY"},
                            {"baler_distance_m": 19000, "buyer_distance_m": 45000, "historical_burn_rate": .8})
    assert result["top_factors"]
    assert result["score_kind"] == "NORMALIZED_RULE_SCORE_NOT_PROBABILITY"
    assert "chance" not in str(result).lower()
    assert "probability" not in str(result["top_factors"]).lower()


def test_intelligence_routes_harvest_candidate_to_straw_and_risk_with_provenance():
    row = harvest_row(BAIS2_delta=0.02, NBR_delta=-0.18)
    result = intelligence_for_row(row, harvest_date={"state": "RULE_CANDIDATE", "days_since_harvest": 4, "provenance": "rule signal"})
    assert result["field_status"]["status_candidate"] == "HARVESTED"
    assert result["straw"]["eligible"]
    assert result["burn_risk"]["method"] == "RULE_ENGINE_V1"
    assert result["provenance"]["fixture_or_real"] == "SYNTHETIC"
    assert result["provenance"]["source_image_id_s2"] == "S2-A"
    assert result["provenance"]["model_trust_state"] == "NO_MODEL"


def test_non_harvest_candidate_skips_straw_and_risk():
    result = intelligence_for_row(harvest_row(NDVI_mean=.8, NDVI_delta=-.01, NDVI_drop_from_peak=-.02))
    assert result["field_status"]["status_candidate"] == "STANDING"
    assert not result["straw"]["eligible"]
    assert result["burn_risk"]["status"] == "NOT_APPLICABLE_INSUFFICIENT_HARVEST_EVIDENCE"


def test_synthetic_trust_state_propagates_and_is_not_ground_truth():
    result = intelligence_for_row(harvest_row())
    assert result["provenance"]["model_trust_state"] == "NO_MODEL"
    assert result["field_status"]["is_ground_truth"] is False
    assert result["straw"]["is_ground_truth"] is False


def test_registry_reports_no_model_and_synthetic_test_state(tmp_path):
    assert model_trust_state() == "NO_MODEL"
    train_field_status(synthetic_smoke_rows(), tmp_path, dataset_provenance="SYNTHETIC_TEST")
    assert model_trust_state(tmp_path) == "SYNTHETIC_TEST_MODEL"


def test_intelligence_service_rejects_synthetic_model_even_if_loaded_for_test(tmp_path):
    train_field_status(synthetic_smoke_rows(), tmp_path, dataset_provenance="SYNTHETIC_TEST")
    model = FieldStatusModel(tmp_path, allow_synthetic=True)
    with pytest.raises(ValueError, match="cannot serve"):
        intelligence_for_row(harvest_row(), status_model=model)


def test_experimental_model_is_not_used_as_trusted_intelligence_prediction():
    class Experimental:
        metadata = {"trust_state": "REAL_EXPERIMENTAL_MODEL"}
        def predict(self, row): raise AssertionError("unvalidated model should not be used")
    result = intelligence_for_row(harvest_row(), status_model=Experimental())
    assert result["field_status"]["method"] == "RULE-BASED STATUS CANDIDATE"
    assert "inactive_model_reason" in result["field_status"]


def test_demo_facility_distance_interface_retains_dataset_type(tmp_path):
    path = tmp_path / "facilities.csv"
    path.write_text("facility_id,facility_type,name,latitude,longitude,dataset_type,source\nDEMO-B1,BALER,Demo Baler,30.0,74.0,DEMO,fixture\nDEMO-B2,BUYER,Demo Buyer,30.0,74.01,DEMO,fixture\n", encoding="utf-8")
    rows = load_facilities(path)
    context = facility_distance_context(30.0, 74.0, rows)
    assert context["facility_dataset_type"] == "DEMO"
    assert context["baler_distance_m"] == pytest.approx(0)
    assert context["buyer_distance_m"] > 0
    assert context["facility_source"] == "fixture"


def test_burn_risk_training_architecture_uses_field_groups_and_no_real_metrics_without_real_labels(tmp_path):
    rows = []
    for target in (0, 1):
        for group in range(3):
            for t in range(3):
                r = harvest_row(field_id=f"BURN-{target}-{group}", fixture_or_real="SYNTHETIC", label_quality="S",
                                burned_within_next_3_days=target, label_source="SYNTHETIC_TEST", reviewer="test",
                                evidence_reference="synthetic generator", created_at="2026-10-11T00:00:00+00:00",
                                NDVI_mean=.7-target*.5, rain_72h=target*0.1)
                rows.append(r)
    with pytest.raises(ValueError, match="synthetic burn labels"):
        train_burn_risk(rows, tmp_path)
    result = train_burn_risk(rows, tmp_path, allow_synthetic=True)
    assert result["status"] == "TRAINED_SYNTHETIC_PIPELINE_TEST_ONLY"
    assert "NOT A SCIENTIFIC PERFORMANCE RESULT" in result["metric_scope"]
    group_sets = [set(v) for v in result["metadata"]["split_groups"].values()]
    assert all(not group_sets[i] & group_sets[j] for i in range(3) for j in range(i+1, 3))
    assert result["metadata"]["target"] == "burned_within_next_3_days"
