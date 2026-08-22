"""Tool logic called directly, including every UNRESOLVED path (Contract A)."""

from __future__ import annotations

import json
from pathlib import Path

from akc_local_mcp import (
    LocalWorldStore,
    ReasonCode,
    ToolResponse,
    get_current_truth,
    get_evidence,
    search_world,
)


class TestGetCurrentTruth:
    def test_resolves_a_topic_with_claims_and_world_ref(self, store: LocalWorldStore) -> None:
        response = get_current_truth(store, "ingest-pipeline")

        assert response.resolved is True
        payload = response.to_dict()
        assert payload["status"] == "CURRENT"
        assert payload["topic"]["topic_id"] == "ingest-pipeline"
        claim_ids = {claim["claim_id"] for claim in payload["claims"]}
        assert claim_ids == {"claim-source-block-evidence", "claim-atomic-publish"}
        assert payload["world"] == {
            "world_id": "atlas-demo",
            "manifest_hash": store.load_manifest("atlas-demo").manifest_hash,
        }

    def test_matches_title_case_insensitively(self, store: LocalWorldStore) -> None:
        response = get_current_truth(store, "  SOURCE TRACEABILITY  ")

        assert response.resolved is True
        assert response.to_dict()["topic"]["topic_id"] == "source-traceability"

    def test_unknown_topic_is_unresolved(self, store: LocalWorldStore) -> None:
        response = get_current_truth(store, "nonexistent-topic")

        assert response.status == "UNRESOLVED"
        assert response.reason_code is ReasonCode.TOPIC_NOT_FOUND

    def test_missing_world_state_dir_is_unresolved(self, empty_world_state_dir: Path) -> None:
        store = LocalWorldStore(empty_world_state_dir)

        for call in (
            lambda: get_current_truth(store, "anything"),
            lambda: get_evidence(store, "claim-x"),
            lambda: search_world(store, "anything"),
        ):
            response = call()
            assert response.status == "UNRESOLVED"
            assert response.reason_code is ReasonCode.WORLD_STATE_UNAVAILABLE

    def test_world_without_active_status_is_unresolved(self, tmp_path: Path) -> None:
        root = tmp_path / "world-state"
        world = root / "draft-world"
        world.mkdir(parents=True)
        (world / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": "akc.local-world-manifest/1",
                    "world_id": "draft-world",
                    "workspace_id": "ws-draft",
                    "status": "BUILDING",
                    "compiler_version": "0.1.0",
                    "built_at": "2026-08-21T00:00:00Z",
                    "manifest_hash": "sha256:" + "2" * 64,
                    "artifact_hashes": {},
                }
            ),
            encoding="utf-8",
        )
        (world / "state.json").write_text(
            json.dumps(
                {
                    "schema": "akc.local-world-state/1",
                    "world_id": "draft-world",
                    "topics": [],
                    "claims": [],
                }
            ),
            encoding="utf-8",
        )

        store = LocalWorldStore(root)
        response = get_current_truth(store, "anything")
        assert response.reason_code is ReasonCode.WORLD_STATE_UNAVAILABLE
        assert "no ACTIVE world" in response.message

    def test_empty_topic_is_invalid_input(self, store: LocalWorldStore) -> None:
        response = get_current_truth(store, "   ")
        assert response.reason_code is ReasonCode.INVALID_INPUT


class TestGetEvidence:
    def test_returns_the_claim_with_its_evidence_chain(self, store: LocalWorldStore) -> None:
        response = get_evidence(store, "claim-source-block-evidence")

        assert response.resolved is True
        payload = response.to_dict()
        assert payload["claim"]["claim_id"] == "claim-source-block-evidence"
        evidence_items = payload["claim"]["evidence"]
        assert len(evidence_items) == 2
        assert evidence_items[0]["source_block_ids"] == ["blk-014", "blk-015"]
        assert payload["world"]["world_id"] == "atlas-demo"

    def test_unknown_claim_is_unresolved(self, store: LocalWorldStore) -> None:
        response = get_evidence(store, "claim-that-does-not-exist")

        assert response.status == "UNRESOLVED"
        assert response.reason_code is ReasonCode.CLAIM_NOT_FOUND
        assert "known claims" in response.message

    def test_empty_claim_id_is_invalid_input(self, store: LocalWorldStore) -> None:
        assert get_evidence(store, "").reason_code is ReasonCode.INVALID_INPUT


class TestSearchWorld:
    def test_finds_claims_and_topics_by_substring(self, store: LocalWorldStore) -> None:
        response = search_world(store, "atomically")

        assert response.resolved is True
        hits = response.to_dict()["hits"]
        kinds = {(entry["kind"], entry["id"]) for entry in hits}
        assert ("claim", "claim-atomic-publish") in kinds

    def test_no_matches_is_explicitly_unresolved(self, store: LocalWorldStore) -> None:
        response = search_world(store, "zzz-nothing-matches-this")

        assert response.status == "UNRESOLVED"
        assert response.reason_code is ReasonCode.NO_MATCHES

    def test_limit_caps_results_deterministically(self, store: LocalWorldStore) -> None:
        broad = search_world(store, "source", limit=100)
        capped = search_world(store, "source", limit=1)

        assert isinstance(broad, ToolResponse) and broad.resolved
        assert capped.resolved
        assert len(capped.to_dict()["hits"]) == 1
        assert capped.to_dict()["hits"][0] == broad.to_dict()["hits"][0]

    def test_empty_query_and_bad_limit_are_invalid_input(self, store: LocalWorldStore) -> None:
        assert search_world(store, "  ").reason_code is ReasonCode.INVALID_INPUT
        assert search_world(store, "ok", limit=0).reason_code is ReasonCode.INVALID_INPUT
