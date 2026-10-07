"""Artifact-level provenance checks for the real-data tree.

Checksums recorded in ``data/real/acquisition_state.json`` give metadata/file
integrity only; they are not a digital signature and do not prove who produced
a file. A file is only treated as present when its bytes are the real content:
an un-fetched Git LFS pointer or a file excluded by the bulk-data policy is
reported as such, never as corruption and never as data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def is_lfs_pointer(path: Path) -> bool:
    try:
        with Path(path).open("rb") as handle:
            return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def lfs_pointer_oid(path: Path) -> str | None:
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("oid sha256:"):
            return line.split(":", 1)[1].strip()
    return None


def content_available(path: Path) -> bool:
    """True only when the real bytes are on disk (not missing, not an LFS pointer)."""
    path = Path(path)
    return path.is_file() and not is_lfs_pointer(path)


def verify_artifact(root: Path, record: dict, excluded_paths: set[str]) -> dict:
    """Classify one recorded artifact against the bytes in the working tree.

    Text artifacts acquired on Windows were checksummed with CRLF line endings
    and committed with LF; a match after CRLF re-expansion is reported
    separately so a line-ending change is not mistaken for a content change.
    """
    rel = record["path"]
    path = Path(root) / rel
    expected = record.get("sha256")
    result = {"path": rel, "expected_sha256": expected}
    if not path.exists():
        result["status"] = "EXCLUDED_BY_POLICY" if rel in excluded_paths else "MISSING_UNEXPECTED"
        return result
    if is_lfs_pointer(path):
        oid = lfs_pointer_oid(path)
        result["lfs_oid"] = oid
        result["status"] = "LFS_POINTER_NOT_FETCHED_OID_MATCH" if oid == expected else "LFS_POINTER_OID_MISMATCH"
        return result
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual == expected:
        result["status"] = "OK"
    elif b"\r\n" not in data and hashlib.sha256(data.replace(b"\n", b"\r\n")).hexdigest() == expected:
        result["status"] = "OK_LINE_ENDINGS_NORMALISED"
    else:
        result["status"] = "SHA256_MISMATCH"
        result["actual_sha256"] = actual
    return result


def verify_tree(root: Path) -> dict:
    """Verify every artifact recorded in acquisition_state.json once."""
    root = Path(root)
    state = json.loads((root / "data/real/acquisition_state.json").read_text(encoding="utf-8"))
    manifest_path = root / "DATASET_MANIFEST.json"
    excluded = set()
    if manifest_path.exists():
        excluded = {row["path"] for row in json.loads(manifest_path.read_text(encoding="utf-8")).get("excluded_datasets", [])}
    seen, rows = set(), []
    for key, dataset in state.get("datasets", {}).items():
        for record in dataset.get("artifacts", []):
            if record["path"] in seen:
                continue
            seen.add(record["path"])
            rows.append({"dataset": key, **verify_artifact(root, record, excluded)})
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    failing = {"MISSING_UNEXPECTED", "LFS_POINTER_OID_MISMATCH", "SHA256_MISMATCH"}
    return {"artifacts": rows, "status_counts": counts,
            "passed": not any(row["status"] in failing for row in rows),
            "integrity_scope": "SHA-256 file integrity against acquisition records; not a digital signature."}
