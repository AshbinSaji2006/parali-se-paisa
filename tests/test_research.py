import numpy as np
import pandas as pd
import pytest

from src.research.events import detect_events
from src.research.risk import precision_at
from src.research.replay import replay
from tests.test_block4_security import make_client, token


def _series(field_id, rows):
    """rows: (date, B02, B04, B08, B8A, B11, B12, char_frac)"""
    out = []
    for d, b02, b04, b08, b8a, b11, b12, char in rows:
        out.append(dict(field_id=field_id, date=pd.Timestamp(d), n_valid=40, n_cloud=0, n_scl2=0, B02=b02, B03=b02,
                        B04=b04, B05=b04, B06=b08, B07=b08, B08=b08, B8A=b8a, B11=b11, B12=b12, char_frac=char,
                        green_frac=0.0))
    return out


GREEN = (0.03, 0.04, 0.40, 0.41, 0.20, 0.09, 0.0)
STRAW = (0.06, 0.15, 0.27, 0.27, 0.30, 0.22, 0.0)
TILLED = (0.07, 0.14, 0.20, 0.20, 0.26, 0.24, 0.0)   # bare tilled soil after burning: NBR stays low
CHAR = (0.03, 0.05, 0.05, 0.05, 0.07, 0.06, 0.8)


def test_char_after_harvest_is_detected_and_dated():
    rows = [("2025-10-01", *GREEN), ("2025-10-06", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *STRAW),
            ("2025-10-21", 0.03, 0.05, 0.05, 0.05, 0.07, 0.06, 0.8), ("2025-10-26", *TILLED)]
    e = detect_events(pd.DataFrame(_series("F1", rows))).set_index("field_id").loc["F1"]
    assert e.harvest_date == pd.Timestamp("2025-10-11")
    assert e.burned and e.burned_strict
    assert e.burn_date == pd.Timestamp("2025-10-21")
    assert e.burn_prev_date == pd.Timestamp("2025-10-16")
    assert e.harvest_to_burn_days == 10


def test_wet_soil_after_rain_is_not_a_burn():
    # Irrigated/wet soil darkens SWIR more than NIR, so NBR stays positive.
    wet = (0.04, 0.07, 0.14, 0.14, 0.09, 0.05, 0.0)
    rows = [("2025-10-01", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *STRAW), ("2025-10-21", *wet)]
    e = detect_events(pd.DataFrame(_series("F2", rows))).set_index("field_id").loc["F2"]
    assert e.harvested and not e.burned


def test_smoke_haze_keeps_swir_logic_usable_but_thick_smoke_is_dropped():
    hazy_char = (0.13, 0.12, 0.10, 0.08, 0.10, 0.09, 0.6)        # moderate smoke, char underneath
    thick = (0.26, 0.30, 0.10, 0.08, 0.10, 0.09, 0.6)            # opaque smoke: unusable
    rows = [("2025-10-01", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *thick), ("2025-10-21", *hazy_char)]
    e = detect_events(pd.DataFrame(_series("F3", rows))).set_index("field_id").loc["F3"]
    assert e.burned and e.burn_date == pd.Timestamp("2025-10-21")
    assert e.burn_prev_date == pd.Timestamp("2025-10-11")  # the thick-smoke date is skipped


def test_harvest_and_burn_within_one_revisit_share_the_observation():
    # Paddy is not burned standing: green -> char means harvest and fire both fell between two passes.
    rows = [("2025-10-01", *GREEN), ("2025-10-06", 0.03, 0.05, 0.05, 0.05, 0.07, 0.06, 0.8)]
    e = detect_events(pd.DataFrame(_series("F4", rows))).set_index("field_id").loc["F4"]
    assert e.burned and e.harvest_date == e.burn_date and e.harvest_to_burn_days == 0
    assert e.burn_prev_date < e.harvest_date  # never collectable after detection


def test_green_crop_without_harvest_signal_is_never_burned():
    rows = [("2025-10-01", *GREEN), ("2025-10-06", *GREEN), ("2025-10-11", *GREEN)]
    e = detect_events(pd.DataFrame(_series("F5", rows))).set_index("field_id").loc["F5"]
    assert not e.harvested and not e.burned


def test_precision_at_top_fraction():
    y = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    s = np.array([.9, .8, .7, .1, .1, .1, .1, .1, .1, .1])
    assert precision_at(y, s, 0.2) == 0.5


def test_replay_preempts_only_before_last_unburned_observation():
    f = pd.DataFrame({"field_id": ["a", "b"], "x": [0.0, 10.0], "y": [0.0, 0.0], "pixel_area_ha": [1.0, 1.0],
                      "harvest_date": pd.to_datetime(["2025-10-10", "2025-10-10"]), "burned": [True, True],
                      "burn_date": pd.to_datetime(["2025-10-20", "2025-10-10"]),
                      "burn_prev_date": pd.to_datetime(["2025-10-15", "2025-10-05"]), "risk_score": [0.9, 0.1]})
    r = replay(f, set(), fleet=1, policy="risk", ha_per_day=1.0)
    assert r.burned_fields == 2 and r.preempted_fields == 1  # field b burned before it was ever collectable


@pytest.mark.parametrize("role,user,pw", [("FARMER", "farmer", "farmer-password"), ("BUYER", "buyer", "buyer-password")])
def test_research_api_is_officials_only(tmp_path, role, user, pw):
    app, c = make_client(tmp_path)
    assert c.get("/api/v1/research/summary").status_code == 401
    c.headers["Authorization"] = f"Bearer {token(c, user, pw)}"
    assert c.get("/api/v1/research/summary").status_code == 403
    c.close(); app.state.engine.dispose()


def test_research_api_official_reads_and_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    app, c = make_client(tmp_path)
    c.headers["Authorization"] = f"Bearer {token(c, 'official', 'right-password')}"
    res = c.get("/api/v1/research/summary")
    assert res.status_code in (200, 404)  # 404 only when research products were not built
    if res.status_code == 200:
        body = res.json()
        assert body["data_mode"] == "REAL" and "not enforcement evidence" in body["notice"]
        for name in body["figures"][:2]:
            assert c.get(f"/api/v1/research/figures/{name}").headers["content-type"] == "image/png"
    assert c.get("/api/v1/research/figures/..%2F..%2Fresults.json").status_code == 404
    assert c.get("/api/v1/research/overlays/overlays.json").status_code == 404
    assert c.post("/api/v1/research/summary").status_code in (405, 503)
    c.close(); app.state.engine.dispose()


def test_stratified_label_evaluation(tmp_path, monkeypatch):
    import json as _json
    import scripts.evaluate_visual_labels as ev
    (tmp_path / "labels").mkdir(); (tmp_path / "tool").mkdir()
    rows = ([("a%d" % i, "STRICT_BURN_CANDIDATE", "BURNED") for i in range(8)] + [("b%d" % i, "STRICT_BURN_CANDIDATE", "NOT_BURNED") for i in range(2)]
            + [("c%d" % i, "LOOSE_BURN_CANDIDATE", "BURNED") for i in range(5)] + [("d%d" % i, "LOOSE_BURN_CANDIDATE", "NOT_BURNED") for i in range(5)]
            + [("e%d" % i, "HARVESTED_NO_BURN_CANDIDATE", "BURNED") for i in range(1)] + [("f%d" % i, "HARVESTED_NO_BURN_CANDIDATE", "NOT_BURNED") for i in range(9)]
            + [("g0", "HARVESTED_NO_BURN_CANDIDATE", "UNCERTAIN")])
    pd.DataFrame(rows, columns=["field_id", "stratum", "label"]).to_csv(tmp_path / "labels" / "visual_labels_2025.csv", index=False)
    (tmp_path / "tool" / "sample_design_2025.json").write_text(_json.dumps({"population_by_stratum": {
        "STRICT_BURN_CANDIDATE": 100, "LOOSE_BURN_CANDIDATE": 100, "HARVESTED_NO_BURN_CANDIDATE": 800}}))
    monkeypatch.setattr(ev, "LABELS", tmp_path / "labels"); monkeypatch.setattr(ev, "TOOL", tmp_path / "tool")
    r = ev.evaluate(2025)
    # burned = 0.1*0.8 + 0.1*0.5 + 0.8*0.1 = 0.21 ; precision = (80+50)/200 ; recall = 130/210
    assert r["burned_field_share_estimate"] == pytest.approx(0.21)
    assert r["precision_burn_map"] == pytest.approx(0.65)
    assert r["recall_burn_map"] == pytest.approx(130 / 210, abs=1e-4)
    assert r["strata"][2]["uncertain"] == 1
    lo, hi = r["burned_field_share_ci95"]
    assert lo < 0.21 < hi


def test_hazy_pre_event_reference_blocks_the_strict_tier():
    hazy_straw = (0.13, 0.17, 0.29, 0.29, 0.31, 0.23, 0.0)
    rows = [("2025-10-01", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *hazy_straw), ("2025-10-21", *CHAR), ("2025-10-26", *TILLED)]
    e = detect_events(pd.DataFrame(_series("H1", rows))).set_index("field_id").loc["H1"]
    assert e.burned and not e.burned_strict and e.burn_tier == "LOOSE_BURN_CANDIDATE"
    assert bool(e.strict_blocked_by_haze)


def test_one_date_dip_that_reverts_stays_loose():
    rows = [("2025-10-01", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *STRAW), ("2025-10-21", *CHAR), ("2025-10-26", *STRAW)]
    e = detect_events(pd.DataFrame(_series("R1", rows))).set_index("field_id").loc["R1"]
    assert e.burned and not e.burned_strict


def test_haze_classes_follow_documented_thresholds():
    from src.research.events import add_indices
    rows = _series("Q", [("2025-10-01", *GREEN), ("2025-10-02", 0.12, .04, .4, .41, .2, .09, 0), ("2025-10-03", 0.21, .04, .4, .41, .2, .09, 0)])
    rows.append({**rows[0], "date": pd.Timestamp("2025-10-04"), "n_valid": 10, "n_cloud": 30})
    d = add_indices(pd.DataFrame(rows))
    assert d.haze_class.tolist() == ["CLEAR", "HAZE_DOWNGRADED", "THICK_SMOKE_EXCLUDED", "CLOUD_EXCLUDED"]
    assert d.usable.tolist() == [True, True, False, False]


def _event_inputs():
    from src.research.events import annotate_observations
    rows = _series("B1", [("2025-10-01", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *STRAW), ("2025-10-21", *CHAR), ("2025-10-26", *TILLED)])
    rows += _series("N1", [("2025-10-01", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *TILLED), ("2025-10-21", *TILLED)])
    d = pd.DataFrame(rows)
    d["item_id"] = "S2_TEST"
    u = annotate_observations(d)
    ids = pd.DataFrame({"field_id": ["B1", "N1"], "n_px": [30, 20], "area_ha": [1.3, 0.9],
                        "centroid_lon": [74.50, 74.60], "centroid_lat": [30.30, 30.30]})
    ev = detect_events(d, u).merge(ids, on="field_id")
    ev["pixel_area_ha"] = ev.n_px * 0.04
    return u, ev, ids


def test_event_table_schema_wording_and_thermal_context():
    from src.research.event_table import build_event_table
    u, ev, ids = _event_inputs()
    firms = pd.DataFrame({"acq_date": pd.to_datetime(["2025-10-19", "2025-03-01"]), "latitude": [30.3005, 30.30],
                          "longitude": [74.5005, 74.0], "sensor": ["VIIRS_SNPP", "MODIS"], "type": [0, 0],
                          "record_type": ["ARCHIVE_YEARLY", "ARCHIVE_YEARLY"]})
    t = build_event_table(u, ev, ids, firms, 2025)
    required = ["field_id", "season", "candidate_event_date", "candidate_type", "strict_or_loose_tier", "pre_event_date",
                "post_event_date", "ndvi_pre", "ndvi_event", "nbr_pre", "nbr_event", "dnbr", "bais2_pre", "bais2_event",
                "b8a_pre", "b8a_event", "b12_pre", "b12_event", "nir_drop", "swir2_drop", "haze_flag_pre", "haze_flag_event",
                "firms_nearest_km", "firms_time_diff_days", "firms_coverage_status", "observation_quality",
                "evidence_reasons", "uncertainty_caution", "pixel_area_ha", "polygon_area_ha", "label", "is_ground_truth"]
    assert not [c for c in required if c not in t]
    t = t.set_index("field_id")
    assert t.loc["B1", "candidate_type"] == "STRICT_BURN_CANDIDATE" and t.loc["B1", "label"] == "RULE-BASED BURN CANDIDATE"
    assert t.loc["N1", "candidate_type"] == "HARVESTED_NO_BURN_CANDIDATE"
    assert t.loc["B1", "firms_viirs_1km"] == 1 and t.loc["B1", "firms_time_diff_days"] == -2
    assert t.loc["B1", "firms_coverage_status"] == "COMPLETE" and not t.is_ground_truth.any()
    text = " ".join(t.select_dtypes(include=["object", "string"]).astype(str).values.ravel()).upper()
    assert "CONFIRMED BURN" not in text.replace("NOT A CONFIRMED BURN", "")


def test_event_table_leaves_fire_counts_null_without_archive_coverage():
    from src.research.event_table import build_event_table
    u, ev, ids = _event_inputs()
    firms = pd.DataFrame({"acq_date": pd.to_datetime(["2026-10-01"]), "latitude": [30.30], "longitude": [74.50],
                          "sensor": ["VIIRS_NOAA21"], "type": [0], "record_type": ["NRT_7DAY"]})
    t = build_event_table(u, ev, ids, firms, 2025)
    assert t.firms_coverage_status.eq("NOT_COVERED").all()
    assert t.firms_viirs_1km.isna().all() and t.firms_modis_1km.isna().all()


def test_field_extraction_is_reproducible_and_keeps_dark_scl(tmp_path):
    import json
    import rasterio
    from rasterio.transform import from_origin
    from scripts.extract_field_timeseries import process
    bands = np.full((11, 2, 3), 1500, dtype=np.int16)
    bands[-1] = np.array([[4, 2, 5], [9, 4, 0]])           # SCL: veg, dark area, soil / cloud, veg, nodata
    bands[7] = np.array([[3000, 600, 2500], [3000, 3100, 3000]])   # B8A
    path = tmp_path / "S2_20251021T053700_43RDP.tif"
    with rasterio.open(path, "w", driver="GTiff", width=3, height=2, count=11, dtype="int16", crs="EPSG:32643",
                       transform=from_origin(0, 40, 20, 20), nodata=-32768) as dst:
        dst.write(bands)
    path.with_suffix(".json").write_text(json.dumps({"datetime": "2025-10-21T05:37:00+00:00", "item_id": "TEST"}))
    zones = np.array([[1, 1, 1], [1, 2, 2]]).ravel()
    keep = np.array([True, True])
    a, b = process(path, zones, 3, keep), process(path, zones, 3, keep)
    pd.testing.assert_frame_equal(a, b)
    z1 = a.set_index("zone").loc[1]
    assert z1.n_valid == 3 and z1.n_cloud == 1 and z1.n_scl2 == 1      # dark-area pixel kept, cloud counted
    assert np.isclose(z1.B8A, (0.3 + 0.06 + 0.25) / 3)


def test_haze_scene_rollup_counts_cloud_without_valid_pixels_as_excluded():
    from scripts.build_burn_candidate_events import scene_status
    t = pd.DataFrame({"field_observations": [100, 100, 100], "n_thick_smoke_excluded": [0, 0, 0], "n_cloud_excluded": [10, 0, 0],
                      "n_no_data_excluded": [60, 0, 0], "share_haze_downgraded": [0.0, 0.7, 0.1]})
    s = scene_status(t)
    assert s.scene_status.tolist() == ["MOSTLY_EXCLUDED_OBSERVATIONS", "MOSTLY_HAZE_DOWNGRADED", "MOSTLY_USABLE"]
    assert s.scene_handling.str.contains("never silently dropped").all()
