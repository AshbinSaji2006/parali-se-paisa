"""Validate and import human reference labels exported by label_reference_<year>.html.

Reads every ``data/real/labels/reference_labels_<year>_*.csv``, rejects rows that do not match
the package manifest or lack a reviewer, keeps every reviewer's row (no silent merging), and
reports inter-reviewer agreement. A consensus label exists only where all reviewers of an
item agree; disagreements stay unresolved for adjudication.

Outputs (only from real reviewer files; nothing is inferred):
* ``data/real/labels/reference_labels.parquet``: all accepted reviewer rows;
* ``data/real/labels/visual_labels_<year>.csv``: consensus burn labels in the format read by
  ``scripts/evaluate_visual_labels.py`` (design-based detector accuracy);
* ``reports/reference_label_status.json``: counts, rejections and agreement.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "real" / "labels"
TOOL = ROOT / "reports" / "research" / "label_tool"
REPORT = ROOT / "reports" / "reference_label_status.json"
BURN = {"BURNED", "NOT_BURNED", "UNCERTAIN"}
STATE = {"STANDING", "HARVESTED", "BURNED", "SOWN", "UNKNOWN"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
REQUIRED = ["package", "item_id", "field_id", "year", "candidate_date", "reviewer", "reviewed_at",
            "burn_label", "state_label", "confidence"]


def _kappa(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) == 0:
        return None
    po = float((a.values == b.values).mean())
    cats = set(a) | set(b)
    pe = sum(float((a == c).mean()) * float((b == c).mean()) for c in cats)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 4)


def validate(frame: pd.DataFrame, manifests: dict[int, dict]) -> tuple[pd.DataFrame, list[str]]:
    errors = []
    missing = [c for c in REQUIRED if c not in frame]
    if missing:
        return frame.iloc[:0], [f"missing columns: {', '.join(missing)}"]
    frame = frame.copy()
    frame["year"] = pd.to_numeric(frame.year, errors="coerce")
    ok = pd.Series(True, index=frame.index)
    for idx, row in frame.iterrows():
        manifest = manifests.get(int(row.year)) if pd.notna(row.year) else None
        problems = []
        if manifest is None:
            problems.append("unknown package year")
        else:
            item = manifest["by_id"].get(row.item_id)
            if item is None:
                problems.append("item not in package")
            elif item["field_id"] != row.field_id or item["candidate_date"] != str(row.candidate_date):
                problems.append("field/candidate date does not match package")
            if row.package != f"{manifest['package_version']}-{int(row.year)}":
                problems.append("package version mismatch")
        if not isinstance(row.reviewer, str) or not row.reviewer.strip():
            problems.append("no reviewer")
        if row.burn_label not in BURN: problems.append("invalid burn_label")
        if row.state_label not in STATE: problems.append("invalid state_label")
        if row.confidence not in CONFIDENCE: problems.append("invalid confidence")
        if pd.isna(pd.to_datetime(row.reviewed_at, errors="coerce", utc=True)): problems.append("invalid reviewed_at")
        if problems:
            ok[idx] = False
            errors.append(f"{row.get('item_id')}: {'; '.join(problems)}")
    return frame.loc[ok], errors


def run() -> dict:
    manifests = {}
    for path in sorted(TOOL.glob("reference_package_*.json")):
        m = json.loads(path.read_text(encoding="utf-8"))
        m["by_id"] = {it["item_id"]: it for it in m["items"]}
        manifests[int(m["year"])] = m
    files = sorted(LABELS.glob("reference_labels_*_*.csv")) if LABELS.exists() else []
    accepted, rejected = [], []
    for path in files:
        good, errors = validate(pd.read_csv(path, dtype=str, keep_default_na=False), manifests)
        accepted.append(good.assign(source_file=path.relative_to(ROOT).as_posix()))
        rejected += [f"{path.name}: {e}" for e in errors]
    labels = pd.concat(accepted, ignore_index=True) if accepted else pd.DataFrame(columns=REQUIRED)
    labels = labels.drop_duplicates(["item_id", "reviewer"], keep="last")
    status = {"generated_at": datetime.now(timezone.utc).isoformat(), "reviewer_files": [p.name for p in files],
              "packages": {str(y): m["item_count"] for y, m in manifests.items()},
              "accepted_rows": int(len(labels)), "rejected_rows": len(rejected), "rejections": rejected[:50],
              "reviewers": sorted(labels.reviewer.unique().tolist()) if len(labels) else [],
              "reviewed_items": int(labels.item_id.nunique()) if len(labels) else 0,
              "is_ground_truth": "Human Tier-B visual reference labels; not field surveys."}
    if labels.empty:
        status["state"] = "NO_HUMAN_LABELS"
        REPORT.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        return status
    status["burn_labels"] = labels.burn_label.value_counts().to_dict()
    status["state_labels"] = labels.state_label.value_counts().to_dict()
    status["confidence"] = labels.confidence.value_counts().to_dict()
    status["context_viewed_share"] = round(float(labels.context_viewed.astype(str).str.lower().eq("true").mean()), 4)
    status["changed_after_context"] = int((labels.label_before_context.astype(str) != labels.burn_label.astype(str)).sum())
    multi = labels.groupby("item_id").filter(lambda g: g.reviewer.nunique() >= 2)
    if not multi.empty:
        pairs = multi.sort_values("reviewer").groupby("item_id").head(2).groupby("item_id").burn_label.agg(list)
        a = pd.Series([p[0] for p in pairs]); b = pd.Series([p[1] for p in pairs])
        status["double_reviewed_items"] = int(len(pairs))
        status["burn_label_agreement"] = round(float((a == b).mean()), 4)
        status["burn_label_cohens_kappa"] = _kappa(a, b)
    consensus = labels.groupby("item_id").agg(burn_label=("burn_label", lambda s: s.iloc[0] if s.nunique() == 1 else "DISAGREE"),
                                              reviewers=("reviewer", "nunique"), field_id=("field_id", "first"),
                                              year=("year", "first"), candidate_date=("candidate_date", "first")).reset_index()
    status["unresolved_disagreements"] = int(consensus.burn_label.eq("DISAGREE").sum())
    LABELS.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(LABELS / "reference_labels.parquet", index=False)
    for year, manifest in manifests.items():
        c = consensus.loc[consensus.year.astype(int).eq(year) & consensus.burn_label.ne("DISAGREE")]
        if c.empty:
            continue
        strata = {it["item_id"]: it["stratum"] for it in manifest["items"]}
        out = pd.DataFrame({"field_id": c.field_id, "year": year, "stratum": c.item_id.map(strata),
                            "candidate_date": c.candidate_date, "label": c.burn_label,
                            "label_quality": "B", "label_source": "HUMAN_MULTI_DATE_VISUAL_REVIEW"})
        out.to_csv(LABELS / f"visual_labels_{year}.csv", index=False)
    status["state"] = "HUMAN_LABELS_IMPORTED"
    REPORT.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: v for k, v in result.items() if k != "rejections"}, indent=2))
    sys.exit(0)
