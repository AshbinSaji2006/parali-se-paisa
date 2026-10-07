from __future__ import annotations

import json
from pathlib import Path

MODEL_STATES = {"NO_MODEL", "SYNTHETIC_TEST_MODEL", "REAL_EXPERIMENTAL_MODEL", "VALIDATED_MODEL"}


def model_trust_state(model_dir=None):
    if model_dir is None: return "NO_MODEL"
    metadata_path = Path(model_dir) / "metadata.json"
    if not metadata_path.exists(): return "NO_MODEL"
    state = json.loads(metadata_path.read_text(encoding="utf-8")).get("trust_state", "NO_MODEL")
    if state not in MODEL_STATES: raise ValueError(f"unknown model trust state: {state}")
    return state


def is_trusted_for_decision(state):
    return state == "VALIDATED_MODEL"
