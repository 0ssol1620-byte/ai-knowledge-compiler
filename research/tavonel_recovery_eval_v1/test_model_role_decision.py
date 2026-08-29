from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DECISION = HERE / "MODEL_ROLE_DECISION_PRE_FREEZE.json"
SNAPSHOT = (
    REPO
    / "docs"
    / "evidence"
    / "artifacts"
    / "folynta-measured-model-evaluation-snapshot-2026-08-02.json"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def by_id(snapshot: dict) -> dict[str, dict]:
    return {item["id"]: item for item in snapshot["datasets"]}


def test_role_decision_is_prefreeze_and_has_seen_no_fresh_outcomes() -> None:
    decision = load(DECISION)
    assert decision["status"] == "PRE_FREEZE_ROLE_DECISION"
    assert decision["fresh_confirmatory_observations_seen"] is False
    assert set(decision["roles"]) == {"primary", "peer", "strong"}


def test_primary_metrics_are_copied_exactly_from_development_snapshot() -> None:
    decision = load(DECISION)
    snapshot = by_id(load(SNAPSHOT))
    role = decision["roles"]["primary"]
    source = snapshot[role["candidate_id"]]["metrics"]
    for key, value in role["historical_metrics"].items():
        assert source[key] == value


def test_strong_metrics_are_copied_exactly_from_development_snapshot() -> None:
    decision = load(DECISION)
    snapshot = by_id(load(SNAPSHOT))
    role = decision["roles"]["strong"]
    source = snapshot[role["candidate_id"]]["metrics"]
    for key, value in role["historical_metrics"].items():
        assert source[key] == value


def test_peer_is_an_independent_non_gpu_evidence_family() -> None:
    role = load(DECISION)["roles"]["peer"]
    assert role["gpu_required"] is False
    assert role["implementation_pin_required"] is True
    assert role["candidate_id"] == "repository-native-source-evidence"
