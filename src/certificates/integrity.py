from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_metadata(metadata: dict[str, Any]) -> bytes:
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def metadata_sha256(metadata: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_metadata(metadata)).hexdigest()


def qr_payload(certificate_id: str, checksum: str) -> str:
    return json.dumps({"certificate_id": certificate_id, "sha256": checksum,
                       "verification": "OFFLINE_PROTOTYPE"}, sort_keys=True, separators=(",", ":"))
