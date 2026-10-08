"""Artifact provenance distinguishes missing bulk data and LFS pointers from corruption."""
import hashlib

from src.data.provenance import is_lfs_pointer, verify_artifact


def test_artifact_classification(tmp_path):
    crlf = b"a,b\r\n1,2\r\n"
    (tmp_path / "lf.csv").write_bytes(crlf.replace(b"\r\n", b"\n"))
    (tmp_path / "changed.csv").write_bytes(b"a,b\n9,9\n")
    oid = hashlib.sha256(b"parquet bytes").hexdigest()
    (tmp_path / "big.parquet").write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize 13\n")
    expected = hashlib.sha256(crlf).hexdigest()
    check = lambda path, sha, excluded=(): verify_artifact(tmp_path, {"path": path, "sha256": sha}, set(excluded))["status"]
    assert check("lf.csv", expected) == "OK_LINE_ENDINGS_NORMALISED"
    # Recorded with LF, checked out with CRLF (Git autocrlf on Windows).
    (tmp_path / "crlf.csv").write_bytes(crlf)
    assert check("crlf.csv", hashlib.sha256(crlf.replace(b"\r\n", b"\n")).hexdigest()) == "OK_LINE_ENDINGS_NORMALISED"
    assert check("changed.csv", expected) == "SHA256_MISMATCH"
    assert is_lfs_pointer(tmp_path / "big.parquet")
    assert check("big.parquet", oid) == "LFS_POINTER_NOT_FETCHED_OID_MATCH"
    assert check("big.parquet", "0" * 64) == "LFS_POINTER_OID_MISMATCH"
    assert check("raw.tif", "0" * 64, ["raw.tif"]) == "EXCLUDED_BY_POLICY"
    assert check("gone.tif", "0" * 64) == "MISSING_UNEXPECTED"
