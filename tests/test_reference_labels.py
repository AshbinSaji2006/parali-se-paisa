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
        "alice": [_row(0, "alice", "BURNT"), _row(1, "alice", "NOT_BURNT"), _row(2, "", "BURNT")],
        "bob": [_row(0, "bob", "BURNT"), _row(1, "bob", "BURNT"), {**_row(9, "bob", "BURNT")}],
    })
    status = imp.run()
    assert status["accepted_rows"] == 4 and status["rejected_rows"] == 2  # missing reviewer; item not in package
    assert status["double_reviewed_items"] == 2 and status["burn_label_agreement"] == 0.5
    assert status["unresolved_disagreements"] == 1
    out = pd.read_csv(labels / "visual_labels_2025.csv")
    assert out.field_id.tolist() == ["F0"] and out.label.tolist() == ["BURNT"]  # disagreement is not resolved silently
    assert out.stratum.tolist() == ["rule_no_burn"]


@pytest.mark.parametrize("year", [2023, 2025])
def test_review_package_is_blind_and_matches_source_chips(year):
    html_path = ROOT / "reports" / "research" / "label_tool" / f"label_reference_{year}.html"
    if not html_path.exists():
        pytest.skip("reference package not built")
    html = html_path.read_text(encoding="utf-8")
    items = json.loads(re.search(r"const ITEMS = (\[.*?\]);\n", html, re.S).group(1))
    source = json.loads(re.search(r"const ITEMS = (\[.*?\]);\s*\n",
                                  (html_path.parent / f"label_burns_{year}.html").read_text(encoding="utf-8"), re.S).group(1))
    assert [i["field_id"] for i in items] == [s["field_id"] for s in source]
    assert all(i["frames"] == s["frames"] for i, s in zip(items, source))
    assert not any("stratum" in i or "burn_tier" in json.dumps(i["context"]) for i in items)
    manifest = json.loads((html_path.parent / f"reference_package_{year}.json").read_text(encoding="utf-8"))
    assert manifest["item_count"] == len(items) and all("stratum" in m for m in manifest["items"])
