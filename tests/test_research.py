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


def test_char_after_harvest_is_detected_and_dated():
    rows = [("2025-10-01", *GREEN), ("2025-10-06", *GREEN), ("2025-10-11", *STRAW), ("2025-10-16", *STRAW),
            ("2025-10-21", 0.03, 0.05, 0.05, 0.05, 0.07, 0.06, 0.8), ("2025-10-26", *STRAW)]
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
    rows = ([("a%d" % i, "rule_burn_strict", "BURNT") for i in range(8)] + [("b%d" % i, "rule_burn_strict", "NOT_BURNT") for i in range(2)]
            + [("c%d" % i, "rule_burn_loose_only", "BURNT") for i in range(5)] + [("d%d" % i, "rule_burn_loose_only", "NOT_BURNT") for i in range(5)]
            + [("e%d" % i, "rule_no_burn", "BURNT") for i in range(1)] + [("f%d" % i, "rule_no_burn", "NOT_BURNT") for i in range(9)]
            + [("g0", "rule_no_burn", "UNCLEAR")])
    pd.DataFrame(rows, columns=["field_id", "stratum", "label"]).to_csv(tmp_path / "labels" / "visual_labels_2025.csv", index=False)
    (tmp_path / "tool" / "sample_design_2025.json").write_text(_json.dumps({"population_by_stratum": {
        "rule_burn_strict": 100, "rule_burn_loose_only": 100, "rule_no_burn": 800}}))
    monkeypatch.setattr(ev, "LABELS", tmp_path / "labels"); monkeypatch.setattr(ev, "TOOL", tmp_path / "tool")
    r = ev.evaluate(2025)
    # burned = 0.1*0.8 + 0.1*0.5 + 0.8*0.1 = 0.21 ; precision = (80+50)/200 ; recall = 130/210
    assert r["burned_field_share_estimate"] == pytest.approx(0.21)
    assert r["precision_burn_map"] == pytest.approx(0.65)
    assert r["recall_burn_map"] == pytest.approx(130 / 210, abs=1e-4)
    assert r["strata"][2]["unclear"] == 1
    lo, hi = r["burned_field_share_ci95"]
    assert lo < 0.21 < hi
