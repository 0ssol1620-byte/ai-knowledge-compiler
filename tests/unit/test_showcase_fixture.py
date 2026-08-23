"""Contract tests for the recorded cinematic showcase fixture.

The fixture must be a real compiler run: manifest hashes match the recorded
world snapshots, every envelope validates against the canonical contract, and
the v1 -> v2 story answers the launch-date question CURRENT both times with
the edited value winning in v2.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "apps/web/src/fixtures/showcase-world/v1"
)


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _manifest_hash(world: dict) -> str:
    """Re-derive the publication hash with the pipeline's own canonical formula."""
    payload = json.dumps(
        {
            "compiler_version": world["manifest"]["compiler_version"],
            "artifacts": dict(sorted(world["manifest"]["artifact_hashes"].items())),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_manifest_hashes_match_recorded_worlds() -> None:
    for name in ("world-v1.json", "world-v2.json"):
        world = _load(name)
        assert world["manifest"]["world_state_id"] == world["world_state_id"]
        assert (
            _manifest_hash(world)
            == world["manifest"]["manifest_hash"]
        ), f"{name} publication hash must reproduce from its artifact hashes"


def test_every_event_line_is_a_canonical_demo_envelope() -> None:
    lines = (FIXTURE_DIR / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines
    seen_types: set[str] = set()
    last_sequence = 0
    for line in lines:
        event = json.loads(line)
        assert event["schema_version"] == "1.0"
        assert event["mode"] == "demo"
        assert event["scope"]["kind"] == "demo"
        assert event["scope"]["fixture_id"] == "showcase-world-v1"
        assert isinstance(event["sequence"], int)
        assert event["sequence"] > last_sequence, "sequence must be monotonic"
        last_sequence = event["sequence"]
        seen_types.add(event["event_type"])
    assert "world_state.activated.v1" in seen_types
    assert "source.revision.created.v1" in seen_types
    assert "impact.detected.v1" in seen_types
    assert "recompile.completed.v1" in seen_types


def test_v1_answers_october_15_as_current() -> None:
    world = _load("world-v1.json")
    answer = world["answers"][0]
    assert answer["outcome"] == "CURRENT"
    assert "October 15, 2026" in answer["value"]
    assert answer["world_state_id"] == "WS-1"


def test_v2_answers_november_3_as_current() -> None:
    world = _load("world-v2.json")
    answer = world["answers"][0]
    assert answer["outcome"] == "CURRENT"
    assert "November 3, 2026" in answer["value"]
    assert answer["world_state_id"] == "WS-2"
    assert world["parent_world_state_id"] == "WS-1"


def test_sample_notice_is_present() -> None:
    for name in ("world-v1.json", "world-v2.json", "manifest.json"):
        data = _load(name)
        text = json.dumps(data)
        assert "SAMPLE WORLD" in text, f"{name} must carry the sample notice"
