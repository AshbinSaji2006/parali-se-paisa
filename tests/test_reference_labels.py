"""Reference labels come only from reviewer files; the importer validates and never infers."""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import scripts.import_reference_labels as imp

ROOT = Path(__file__).resolve().parents[1]


def _setup(tmp_path, monkeypatch, rows):
    tool, labels = tmp_path / "tool", tmp_path / "labels"
    tool.mkdir(); labels.mkdir()
    items = [{"item_id": f"2025:F{i}", "field_id": f"F{i}", "year": 2025, "stratum": "rule_no_burn",
              "candidate_date": "2025-11-02", "frame_dates": []} for i in range(3)]
    (tool / "reference_package_2025.json").write_text(json.dumps({"package_version": "reference-v1", "year": 2025,
                                                                  "items": items, "item_count": 3}))
    monkeypatch.setattr(imp, "TOOL", tool); monkeypatch.setattr(imp, "LABELS", labels)
    monkeypatch.setattr(imp, "REPORT", tmp_path / "status.json"); monkeypatch.setattr(imp, "ROOT", tmp_path)
    for reviewer, data in rows.items():
        pd.DataFrame(data).to_csv(labels / f"reference_labels_2025_{reviewer}.csv", index=False)
    return labels


def _row(i, reviewer, burn, **extra):
    return {"package": "reference-v1-2025", "item_id": f"2025:F{i}", "field_id": f"F{i}", "year": 2025,
            "candidate_date": "2025-11-02", "reviewer": reviewer, "reviewed_at": "2026-10-07T10:00:00Z",
            "burn_label": burn, "state_label": "HARVESTED", "confidence": "HIGH",
            "label_before_context": burn, "context_viewed": "false", **extra}


def test_no_reviewer_files_means_no_labels(tmp_path, monkeypatch):
    labels = _setup(tmp_path, monkeypatch, {})
    status = imp.run()
    assert status["state"] == "NO_HUMAN_LABELS" and status["accepted_rows"] == 0
    assert not list(labels.glob("visual_labels_*.csv"))


def test_validation_agreement_and_consensus(tmp_path, monkeypatch):
    labels = _setup(tmp_path, monkeypatch, {
        "alice": [_row(0, "alice", "BURNED"), _row(1, "alice", "NOT_BURNED"), _row(2, "", "BURNED")],
        "bob": [_row(0, "bob", "BURNED"), _row(1, "bob", "BURNED"), {**_row(9, "bob", "BURNED")}],
    })
    status = imp.run()
    assert status["accepted_rows"] == 4 and status["rejected_rows"] == 2  # missing reviewer; item not in package
    assert status["double_reviewed_items"] == 2 and status["burn_label_agreement"] == 0.5
    assert status["unresolved_disagreements"] == 1
    out = pd.read_csv(labels / "visual_labels_2025.csv")
    assert out.field_id.tolist() == ["F0"] and out.label.tolist() == ["BURNED"]  # disagreement is not resolved silently
    assert out.stratum.tolist() == ["rule_no_burn"]


@pytest.mark.parametrize("year", [2023, 2025])
def test_review_package_is_blind_and_matches_source_chips(year):
    html_path = ROOT / "reports" / "research" / "label_tool" / f"label_reference_{year}.html"
    if not html_path.exists():
        pytest.skip("reference package not built")
    html = html_path.read_text(encoding="utf-8")
    items = json.loads(re.search(r"const ITEMS = (\[.*?\]);\n", html, re.S).group(1))
    archive = html_path.parent.parent / "internal_do_not_share" / "legacy-reviewer-artifacts"
    source = json.loads((archive / f"chips_{year}.json").read_text(encoding="utf-8"))["items"]
    assert [i["field_id"] for i in items] == [s["field_id"] for s in source]
    assert all(i["frames"] == s["frames"] for i, s in zip(items, source))
    assert not any("stratum" in i or "burn_tier" in json.dumps(i["context"]) for i in items)
    manifest = json.loads((archive / f"reference_package_{year}.json").read_text(encoding="utf-8"))
    assert manifest["item_count"] == len(items) and all("stratum" in m for m in manifest["items"])
    design = json.loads((archive / f"sample_design_{year}.json").read_text(encoding="utf-8"))
    assert {m["stratum"] for m in manifest["items"]} <= set(design["population_by_stratum"])


def test_legacy_vocabulary_is_rejected(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"carol": [_row(0, "carol", "BURNT"), _row(1, "carol", "UNCLEAR")]})
    status = imp.run()
    assert status["accepted_rows"] == 0 and status["rejected_rows"] == 2


@pytest.mark.parametrize("year", [2023, 2025])
def test_review_interface_uses_required_labels_and_captures_reviewer_fields(year):
    html_path = ROOT / "reports" / "research" / "label_tool" / f"label_reference_{year}.html"
    if not html_path.exists():
        pytest.skip("reference package not built")
    html = html_path.read_text(encoding="utf-8")
    for label in ("BURNED", "NOT_BURNED", "UNCERTAIN"):
        assert f'data-burn="{label}"' in html
    for legacy in ('data-burn="BURNT"', 'data-burn="NOT_BURNT"', 'data-burn="UNCLEAR"'):
        assert legacy not in html
    for column in ("reviewer", "reviewed_at", "confidence", "notes", "source_dates"):
        assert f'"{column}"' in html
    assert "burn_label: null" in html and "confidence: null" in html  # nothing pre-selected
    for detector_term in ("STRICT_BURN_CANDIDATE", "LOOSE_BURN_CANDIDATE", "HARVESTED_NO_BURN_CANDIDATE", "stratum"):
        assert detector_term not in html
