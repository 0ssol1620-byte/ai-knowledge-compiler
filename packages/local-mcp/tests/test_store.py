"""Store behaviour: listing worlds, reading manifests, failing closed on bad input."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from akc_local_mcp import (
    LocalWorldStore,
    UnknownWorldError,
    WorldDocumentError,
)


def test_lists_the_fixture_worlds_with_manifest_fields(
    store: LocalWorldStore,
) -> None:
    worlds = store.list_worlds()

    assert {world.world_id for world in worlds} == {"atlas-aug20", "atlas-demo"}
    by_id = {world.world_id: world for world in worlds}
    assert by_id["atlas-demo"].status == "ACTIVE"
    assert by_id["atlas-demo"].workspace_id == "ws-atlas-demo"
    assert by_id["atlas-demo"].manifest_hash.startswith("sha256:")
    assert by_id["atlas-demo"].artifact_hashes
    assert by_id["atlas-aug20"].status == "SUPERSEDED"


def test_manifest_artifact_hash_matches_the_state_file_on_disk(
    store: LocalWorldStore, fixture_world_state_dir: Path
) -> None:
    import hashlib

    manifest = store.load_manifest("atlas-demo")
    state_path = fixture_world_state_dir / "atlas-demo" / "state.json"
    actual = "sha256:" + hashlib.sha256(state_path.read_bytes()).hexdigest()

    recorded = manifest.artifact_hashes["states/atlas-demo/state.json"]
    assert recorded == actual, "fixture manifest must cite the real state hash"


def test_load_snapshot_joins_topics_and_claims(store: LocalWorldStore) -> None:
    snapshot = store.load_snapshot("atlas-demo")

    topic_ids = {topic.topic_id for topic in snapshot.topics}
    assert topic_ids == {"ingest-pipeline", "source-traceability"}
    claim_ids = {claim.claim_id for claim in snapshot.claims}
    assert claim_ids == {
        "claim-source-block-evidence",
        "claim-atomic-publish",
        "claim-unresolved-final",
    }
    evidence_claim = next(
        claim for claim in snapshot.claims if claim.claim_id == "claim-source-block-evidence"
    )
    assert evidence_claim.evidence[0].source_block_ids == ("blk-014", "blk-015")


def test_unknown_world_is_a_typed_error(store: LocalWorldStore) -> None:
    with pytest.raises(UnknownWorldError):
        store.load_manifest("no-such-world")


def test_world_id_cannot_escape_the_root(store: LocalWorldStore) -> None:
    with pytest.raises(UnknownWorldError):
        store.load_manifest("../atlas-demo")


def test_missing_state_file_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "world-state"
    world = root / "lonely-world"
    world.mkdir(parents=True)
    (world / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "akc.local-world-manifest/1",
                "world_id": "lonely-world",
                "workspace_id": "ws",
                "status": "ACTIVE",
                "compiler_version": "0.1.0",
                "built_at": "2026-08-21T00:00:00Z",
                "manifest_hash": "sha256:" + "0" * 64,
                "artifact_hashes": {},
            }
        ),
        encoding="utf-8",
    )

    store = LocalWorldStore(root)
    with pytest.raises(WorldDocumentError, match="no state file"):
        store.load_snapshot("lonely-world")


def test_unsupported_schema_version_is_refused_not_guessed(tmp_path: Path) -> None:
    root = tmp_path / "world-state"
    world = root / "future-world"
    world.mkdir(parents=True)
    (world / "manifest.json").write_text(
        '{"schema": "akc.local-world-manifest/99"}', encoding="utf-8"
    )

    store = LocalWorldStore(root)
    with pytest.raises(WorldDocumentError, match="schema"):
        store.list_worlds()


def test_invalid_json_is_a_document_error(tmp_path: Path) -> None:
    root = tmp_path / "world-state"
    world = root / "broken-world"
    world.mkdir(parents=True)
    (world / "manifest.json").write_text("{not json", encoding="utf-8")

    store = LocalWorldStore(root)
    with pytest.raises(WorldDocumentError, match="invalid JSON"):
        store.load_manifest("broken-world")


def test_dangling_topic_claim_reference_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "world-state"
    world = root / "dangling-world"
    world.mkdir(parents=True)
    (world / "manifest.json").write_text(
        json.dumps(_manifest_payload("dangling-world")),
        encoding="utf-8",
    )
    (world / "state.json").write_text(
        json.dumps(
            {
                "schema": "akc.local-world-state/1",
                "world_id": "dangling-world",
                "topics": [{"topic_id": "t1", "title": "T one", "claim_ids": ["missing-claim"]}],
                "claims": [],
            }
        ),
        encoding="utf-8",
    )

    store = LocalWorldStore(root)
    with pytest.raises(WorldDocumentError, match="unknown claim"):
        store.load_snapshot("dangling-world")


def _manifest_payload(world_id: str) -> dict[str, object]:
    return {
        "schema": "akc.local-world-manifest/1",
        "world_id": world_id,
        "workspace_id": "ws-" + world_id,
        "status": "ACTIVE",
        "compiler_version": "0.1.0",
        "built_at": "2026-08-21T00:00:00Z",
        "manifest_hash": "sha256:" + "1" * 64,
        "artifact_hashes": {},
    }


def test_list_history_orders_worlds_oldest_first(store: LocalWorldStore) -> None:
    history = store.list_history()

    assert [manifest.world_id for manifest in history] == ["atlas-aug20", "atlas-demo"]
    assert history[0].built_at < history[1].built_at


def test_unparseable_built_at_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "world-state"
    for world_id, built_at in (
        ("b-world", "2026-08-21T00:00:00Z"),
        ("a-world", "the-day-before-yesterday"),
    ):
        world = root / world_id
        world.mkdir(parents=True)
        payload = _manifest_payload(world_id)
        payload["built_at"] = built_at
        (world / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    store = LocalWorldStore(root)
    with pytest.raises(WorldDocumentError, match="ISO-8601"):
        store.list_history()


def test_diff_worlds_reports_added_removed_and_value_changes(
    store: LocalWorldStore,
) -> None:
    diff = store.diff_worlds("atlas-aug20", "atlas-demo")
    document = diff.to_dict()

    assert diff.world_a == "atlas-aug20"
    assert diff.world_b == "atlas-demo"
    added = {entry["claim_id"] for entry in document["added_in_b"]}
    removed = {entry["claim_id"] for entry in document["removed_from_a"]}
    changed = {entry["claim_id"]: entry for entry in document["value_changed"]}
    assert added == {"claim-unresolved-final"}
    assert removed == {"claim-old-preflight"}
    # claim-source-block-evidence moved values between the two worlds.
    fields = {
        change["field"]: (change["before"], change["after"])
        for change in changed["claim-source-block-evidence"]["changes"]
    }
    assert fields["confidence"] == (0.9, 0.97)
    assert fields["text"][0] != fields["text"][1]
    assert "claim-atomic-publish" not in changed

    summary = document["summary"]
    assert summary == {"added": 1, "removed": 1, "changed": 1, "unchanged": 1}


def test_identical_claims_do_not_appear_as_changed(store: LocalWorldStore) -> None:
    diff = store.diff_worlds("atlas-demo", "atlas-demo")

    assert diff.summary.added == 0
    assert diff.summary.removed == 0
    assert diff.summary.changed == 0
    assert diff.summary.unchanged == len(store.load_snapshot("atlas-demo").claims)


def test_unknown_edge_type_is_refused_not_guessed(tmp_path: Path) -> None:
    root = tmp_path / "world-state"
    world = root / "edgy-world"
    world.mkdir(parents=True)
    (world / "manifest.json").write_text(
        json.dumps(_manifest_payload("edgy-world")), encoding="utf-8"
    )
    (world / "state.json").write_text(
        json.dumps(
            {
                "schema": "akc.local-world-state/1",
                "world_id": "edgy-world",
                "topics": [],
                "claims": [],
                "dependencies": [
                    {
                        "source_id": "a",
                        "target_id": "b",
                        "edge_type": "TELEPORTS_TO",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    store = LocalWorldStore(root)
    with pytest.raises(WorldDocumentError, match="edge_type"):
        store.load_snapshot("edgy-world")


def test_self_dependent_edge_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "world-state"
    world = root / "looping-world"
    world.mkdir(parents=True)
    (world / "manifest.json").write_text(
        json.dumps(_manifest_payload("looping-world")), encoding="utf-8"
    )
    (world / "state.json").write_text(
        json.dumps(
            {
                "schema": "akc.local-world-state/1",
                "world_id": "looping-world",
                "topics": [],
                "claims": [],
                "dependencies": [{"source_id": "x", "target_id": "x", "edge_type": "DEPENDS_ON"}],
            }
        ),
        encoding="utf-8",
    )

    store = LocalWorldStore(root)
    with pytest.raises(WorldDocumentError, match="depend on itself"):
        store.load_snapshot("looping-world")
