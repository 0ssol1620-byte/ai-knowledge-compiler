"""The seven-surface read tools: positive paths, UNRESOLVED paths, world stamps.

Every tool must (a) answer from the published world when it can, (b) answer
UNRESOLVED with a reason when it cannot, and (c) stamp every response —
CURRENT or UNRESOLVED — with `world_state_id`, `freshness`, and
`limitations`, so an answer is always citable and a refusal always explains
what was missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akc_local_mcp import (
    LocalWorldStore,
    ReasonCode,
    ToolResponse,
    ask_as_of,
    compare_worlds,
    get_change,
    get_claim,
    get_current_truth,
    get_entity,
    get_evidence,
    get_world,
    search_world,
    trace_impact,
)

STAMP_FIELDS = ("world_state_id", "freshness", "limitations")


def _assert_world_stamped(document: dict[str, Any]) -> None:
    for field in STAMP_FIELDS:
        assert field in document, f"response is not world-stamped: missing {field!r}"
    assert isinstance(document["limitations"], list)
    assert "status" in document


def _write_world(
    root: Path,
    world_id: str,
    *,
    status: str = "ACTIVE",
    built_at: str = "2026-08-21T00:00:00Z",
    state: dict[str, Any],
) -> LocalWorldStore:
    world = root / world_id
    world.mkdir(parents=True, exist_ok=True)
    (world / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "akc.local-world-manifest/1",
                "world_id": world_id,
                "workspace_id": "ws-" + world_id,
                "status": status,
                "compiler_version": "0.1.0",
                "built_at": built_at,
                "manifest_hash": "sha256:" + abs(hash(world_id)).to_bytes(32, "big").hex()[:64],
                "artifact_hashes": {},
            }
        ),
        encoding="utf-8",
    )
    (world / "state.json").write_text(
        json.dumps({"schema": "akc.local-world-state/1", "world_id": world_id, **state}),
        encoding="utf-8",
    )
    return LocalWorldStore(root)


def _empty_state() -> dict[str, Any]:
    return {"topics": [], "claims": []}


# ---------------------------------------------------------------------------
# ask_as_of
# ---------------------------------------------------------------------------


class TestAskAsOf:
    def test_bare_date_includes_everything_built_that_day(self, store: LocalWorldStore) -> None:
        # atlas-demo (ACTIVE, built 2026-08-21T09:30Z) is the newest world on
        # or before 2026-08-21 once the whole day is included.
        response = ask_as_of(store, "ingest-pipeline", "2026-08-21")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert document["world_state_id"] == "atlas-demo"
        assert document["freshness"] == "2026-08-21T09:30:00Z"
        claim_ids = {claim["claim_id"] for claim in document["claims"]}
        # atlas-demo's ingest-pipeline carries exactly these two claims; the
        # older atlas-aug20 copy would have brought claim-old-preflight.
        assert claim_ids == {"claim-source-block-evidence", "claim-atomic-publish"}
        assert document["as_of"]["as_of_date"] == "2026-08-21"

    def test_exact_timestamp_answers_from_the_older_superseded_world(
        self, store: LocalWorldStore
    ) -> None:
        response = ask_as_of(store, "ingest-pipeline", "2026-08-20T12:00:00Z")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert document["world_state_id"] == "atlas-aug20"
        claim_ids = {claim["claim_id"] for claim in document["claims"]}
        assert "claim-old-preflight" in claim_ids
        assert "claim-unresolved-final" not in claim_ids
        assert any("superseded" in note for note in document["limitations"])

    def test_before_any_publication_is_explicitly_unresolved(self, store: LocalWorldStore) -> None:
        response = ask_as_of(store, "ingest-pipeline", "2026-01-01")
        document = response.to_dict()

        assert response.status == "UNRESOLVED"
        _assert_world_stamped(document)
        assert document["world_state_id"] is None
        assert document["freshness"] is None
        assert document["reason"]["code"] == ReasonCode.NO_WORLD_AT_DATE.value

    def test_unpublishable_worlds_are_never_quoted(self, tmp_path: Path) -> None:
        store = _write_world(
            tmp_path / "ws",
            "draft-world",
            status="BUILDING",
            built_at="2026-08-21T00:00:00Z",
            state={
                "topics": [
                    {
                        "topic_id": "t1",
                        "title": "T one",
                        "claim_ids": [],
                        "keywords": [],
                        "summary": "",
                    }
                ],
                "claims": [],
            },
        )

        response = ask_as_of(store, "t1", "2026-08-22")

        assert response.status == "UNRESOLVED"
        assert response.reason_code is ReasonCode.NO_WORLD_AT_DATE

    def test_malformed_dates_are_invalid_input(self, store: LocalWorldStore) -> None:
        for bad in ("august fifteenth", "2026-13-40", "2026-08-20T12:00:00"):
            response = ask_as_of(store, "ingest-pipeline", bad)
            assert response.status == "UNRESOLVED"
            assert response.reason_code is ReasonCode.INVALID_INPUT

    def test_unknown_topic_in_the_chosen_world_is_unresolved(self, store: LocalWorldStore) -> None:
        response = ask_as_of(store, "no-such-topic", "2026-08-20T12:00:00Z")
        document = response.to_dict()

        assert response.reason_code is ReasonCode.TOPIC_NOT_FOUND
        _assert_world_stamped(document)
        assert document["world_state_id"] == "atlas-aug20"


# ---------------------------------------------------------------------------
# get_entity
# ---------------------------------------------------------------------------


class TestGetEntity:
    def test_resolves_by_exact_id_with_its_claims(self, store: LocalWorldStore) -> None:
        response = get_entity(store, "ent-acme-corp")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert document["entity"]["entity_id"] == "ent-acme-corp"
        assert [claim["claim_id"] for claim in document["claims"]] == [
            "claim-source-block-evidence"
        ]

    def test_resolves_by_alias(self, store: LocalWorldStore) -> None:
        response = get_entity(store, "Acme Corporation")

        assert response.resolved is True
        assert response.to_dict()["entity"]["entity_id"] == "ent-acme-corp"

    def test_unknown_entity_is_unresolved(self, store: LocalWorldStore) -> None:
        response = get_entity(store, "ent-nobody")
        document = response.to_dict()

        assert response.reason_code is ReasonCode.ENTITY_NOT_FOUND
        _assert_world_stamped(document)
        assert document["world_state_id"] == "atlas-demo"

    def test_world_without_entities_refuses_rather_than_guessing(self, tmp_path: Path) -> None:
        store = _write_world(tmp_path / "ws", "entity-free", state=_empty_state())

        response = get_entity(store, "ent-acme-corp")

        assert response.status == "UNRESOLVED"
        assert response.reason_code is ReasonCode.ENTITY_NOT_FOUND
        assert "records no entities" in response.message

    def test_empty_entity_id_is_invalid_input(self, store: LocalWorldStore) -> None:
        assert get_entity(store, "  ").reason_code is ReasonCode.INVALID_INPUT


# ---------------------------------------------------------------------------
# get_claim
# ---------------------------------------------------------------------------


class TestGetClaim:
    def test_returns_the_compiled_claim_record(self, store: LocalWorldStore) -> None:
        response = get_claim(store, "claim-atomic-publish")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert document["claim"]["confidence"] == 0.93
        assert document["world"]["world_id"] == "atlas-demo"

    def test_unknown_claim_is_unresolved(self, store: LocalWorldStore) -> None:
        response = get_claim(store, "claim-ghost")

        assert response.reason_code is ReasonCode.CLAIM_NOT_FOUND
        _assert_world_stamped(response.to_dict())

    def test_empty_claim_id_is_invalid_input(self, store: LocalWorldStore) -> None:
        assert get_claim(store, "").reason_code is ReasonCode.INVALID_INPUT


# ---------------------------------------------------------------------------
# get_change
# ---------------------------------------------------------------------------


class TestGetChange:
    def test_resolves_by_change_id(self, store: LocalWorldStore) -> None:
        response = get_change(store, "chg-2026-08-19-acme")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert document["change"]["source_path"] == "contracts/acme-msa.docx"
        assert document["claims"][0]["claim_id"] == "claim-source-block-evidence"

    def test_resolves_by_source_path(self, store: LocalWorldStore) -> None:
        response = get_change(store, source_path="policies/refund-v2.pdf")
        document = response.to_dict()

        assert response.resolved is True
        assert document["change"]["change_id"] == "chg-2026-08-18-refund"

    def test_unknown_change_id_is_unresolved(self, store: LocalWorldStore) -> None:
        response = get_change(store, "chg-nope")

        assert response.reason_code is ReasonCode.CHANGE_NOT_FOUND
        _assert_world_stamped(response.to_dict())

    def test_unknown_source_path_lists_known_paths(self, store: LocalWorldStore) -> None:
        response = get_change(store, source_path="docs/never-seen.pdf")

        assert response.reason_code is ReasonCode.CHANGE_NOT_FOUND
        assert "known source paths" in response.message

    def test_selector_must_be_exactly_one(self, store: LocalWorldStore) -> None:
        neither = get_change(store)
        both = get_change(store, "chg-2026-08-19-acme", source_path="contracts/acme-msa.docx")

        assert neither.reason_code is ReasonCode.INVALID_INPUT
        assert both.reason_code is ReasonCode.INVALID_INPUT

    def test_ambiguous_source_path_refuses_to_choose(self, tmp_path: Path) -> None:
        store = _write_world(
            tmp_path / "ws",
            "ambiguous-world",
            state={
                "topics": [],
                "claims": [],
                "changes": [
                    {"change_id": "chg-1", "source_path": "same.docx"},
                    {"change_id": "chg-2", "source_path": "same.docx"},
                ],
            },
        )

        response = get_change(store, source_path="same.docx")

        assert response.status == "UNRESOLVED"
        assert response.reason_code is ReasonCode.CHANGE_NOT_FOUND
        assert "refusing to choose silently" in response.message


# ---------------------------------------------------------------------------
# trace_impact
# ---------------------------------------------------------------------------


class TestTraceImpact:
    def test_downstream_walks_the_blast_radius_with_paths(self, store: LocalWorldStore) -> None:
        response = trace_impact(store, "claim-source-block-evidence")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        affected = document["affected"]
        assert [entry["node_id"] for entry in affected] == ["ingest-pipeline"]
        assert affected[0]["via"] == [
            {"node": "claim-source-block-evidence", "edge": "CONSUMED_BY"}
        ]
        assert document["affected_count"] == 1

    def test_upstream_walks_provenance(self, store: LocalWorldStore) -> None:
        response = trace_impact(store, "claim-source-block-evidence", direction="upstream")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert [entry["node_id"] for entry in document["provenance"]] == ["docver-9f21c3"]

    def test_dependson_impact_runs_backwards(self, store: LocalWorldStore) -> None:
        # report-quarterly DEPENDS_ON ent-acme-corp: changing the entity
        # invalidates the report, even though the arrow points the other way.
        response = trace_impact(store, "ent-acme-corp")
        document = response.to_dict()

        assert [entry["node_id"] for entry in document["affected"]] == ["report-quarterly"]

    def test_inert_edges_do_not_propagate(self, store: LocalWorldStore) -> None:
        # ent-acme-corp REFERENCES claim-source-block-evidence: a pointer, not
        # a dependence — the claim must not show up in the entity's radius.
        response = trace_impact(store, "ent-acme-corp")
        affected_ids = [entry["node_id"] for entry in response.to_dict()["affected"]]

        assert "claim-source-block-evidence" not in affected_ids

    def test_edge_free_node_answers_honestly_empty(self, store: LocalWorldStore) -> None:
        response = trace_impact(store, "claim-atomic-publish")
        document = response.to_dict()

        assert response.resolved is True
        assert document["affected"] == []
        assert any("no dependency edge references" in note for note in document["limitations"])

    def test_unknown_node_is_unresolved(self, store: LocalWorldStore) -> None:
        response = trace_impact(store, "node-in-the-void")
        document = response.to_dict()

        assert response.reason_code is ReasonCode.NODE_NOT_FOUND
        _assert_world_stamped(document)

    def test_bad_direction_is_invalid_input(self, store: LocalWorldStore) -> None:
        response = trace_impact(store, "ent-acme-corp", direction="sideways")

        assert response.reason_code is ReasonCode.INVALID_INPUT

    def test_world_without_edges_says_so(self, tmp_path: Path) -> None:
        store = _write_world(
            tmp_path / "ws",
            "edge-free",
            state={
                "topics": [
                    {
                        "topic_id": "t1",
                        "title": "T one",
                        "claim_ids": [],
                        "keywords": [],
                        "summary": "",
                    }
                ],
                "claims": [],
            },
        )

        response = trace_impact(store, "t1")
        document = response.to_dict()

        assert response.resolved is True
        assert document["affected"] == []
        assert any("no dependency edges" in note for note in document["limitations"])


# ---------------------------------------------------------------------------
# get_world
# ---------------------------------------------------------------------------


class TestGetWorld:
    def test_defaults_to_the_active_world(self, store: LocalWorldStore) -> None:
        response = get_world(store)
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert document["world_state_id"] == "atlas-demo"
        assert document["manifest"]["status"] == "ACTIVE"
        assert document["composition"] == {
            "topics": 2,
            "claims": 3,
            "entities": 1,
            "changes": 2,
            "dependencies": 4,
        }

    def test_explicit_world_id_can_be_superseded(self, store: LocalWorldStore) -> None:
        response = get_world(store, "atlas-aug20")
        document = response.to_dict()

        assert response.resolved is True
        assert document["manifest"]["status"] == "SUPERSEDED"
        assert document["world_state_id"] == "atlas-aug20"
        assert any("explicitly requested" in note for note in document["limitations"])

    def test_unknown_world_is_unresolved(self, store: LocalWorldStore) -> None:
        response = get_world(store, "world-that-never-was")

        assert response.reason_code is ReasonCode.WORLD_NOT_FOUND
        _assert_world_stamped(response.to_dict())

    def test_blank_world_id_is_invalid_input(self, store: LocalWorldStore) -> None:
        assert get_world(store, "   ").reason_code is ReasonCode.INVALID_INPUT


# ---------------------------------------------------------------------------
# compare_worlds
# ---------------------------------------------------------------------------


class TestCompareWorlds:
    def test_diff_catches_added_removed_and_value_changes(self, store: LocalWorldStore) -> None:
        response = compare_worlds(store, "atlas-aug20", "atlas-demo")
        document = response.to_dict()

        assert response.resolved is True
        _assert_world_stamped(document)
        assert document["world_state_id"] == "atlas-demo"
        assert document["freshness"] == "2026-08-21T09:30:00Z"
        added = {entry["claim_id"] for entry in document["added_in_b"]}
        removed = {entry["claim_id"] for entry in document["removed_from_a"]}
        changed = document["value_changed"]
        assert added == {"claim-unresolved-final"}
        assert removed == {"claim-old-preflight"}
        assert [entry["claim_id"] for entry in changed] == ["claim-source-block-evidence"]
        moved_fields = {change["field"] for change in changed[0]["changes"]}
        assert "confidence" in moved_fields
        assert "text" in moved_fields
        assert document["comparison"]["world_a"]["status"] == "SUPERSEDED"
        assert document["comparison"]["world_b"]["status"] == "ACTIVE"
        assert document["summary"] == {
            "added": 1,
            "removed": 1,
            "changed": 1,
            "unchanged": 1,
        }

    def test_direction_of_the_diff_follows_argument_order(self, store: LocalWorldStore) -> None:
        response = compare_worlds(store, "atlas-demo", "atlas-aug20")
        document = response.to_dict()

        assert document["world_state_id"] == "atlas-aug20"
        assert {entry["claim_id"] for entry in document["added_in_b"]} == {"claim-old-preflight"}
        assert {entry["claim_id"] for entry in document["removed_from_a"]} == {
            "claim-unresolved-final"
        }

    def test_unknown_world_is_unresolved(self, store: LocalWorldStore) -> None:
        response = compare_worlds(store, "atlas-demo", "ghost-world")

        assert response.reason_code is ReasonCode.WORLD_NOT_FOUND
        _assert_world_stamped(response.to_dict())

    def test_blank_ids_are_invalid_input(self, store: LocalWorldStore) -> None:
        assert compare_worlds(store, "", "atlas-demo").reason_code is (ReasonCode.INVALID_INPUT)


# ---------------------------------------------------------------------------
# the stamp is universal, not per-tool decoration
# ---------------------------------------------------------------------------


class TestEveryResponseIsWorldStamped:
    def test_current_and_unresolved_answers_across_the_surface(
        self, store: LocalWorldStore, tmp_path: Path
    ) -> None:
        empty_store = LocalWorldStore(tmp_path / "no-worlds-here")

        battery: list[ToolResponse] = [
            get_current_truth(store, "ingest-pipeline"),
            get_current_truth(store, "missing-topic"),
            get_evidence(store, "claim-atomic-publish"),
            get_evidence(store, "missing-claim"),
            search_world(store, "atomically"),
            search_world(store, "zzz-nothing"),
            ask_as_of(store, "ingest-pipeline", "2026-08-20T12:00:00Z"),
            ask_as_of(store, "ingest-pipeline", "2020-01-01"),
            get_entity(store, "ent-acme-corp"),
            get_entity(store, "ent-missing"),
            get_claim(store, "claim-atomic-publish"),
            get_claim(store, "claim-missing"),
            get_change(store, "chg-2026-08-19-acme"),
            get_change(store, "chg-missing"),
            trace_impact(store, "ent-acme-corp"),
            trace_impact(store, "node-missing"),
            get_world(store),
            get_world(store, "missing-world"),
            compare_worlds(store, "atlas-aug20", "atlas-demo"),
            compare_worlds(store, "atlas-demo", "missing-world"),
            # No world at all: the stamp survives with nulls.
            get_current_truth(empty_store, "anything"),
            get_world(empty_store),
            compare_worlds(empty_store, "a", "b"),
        ]

        for response in battery:
            document = response.to_dict()
            _assert_world_stamped(document)
            if response.resolved:
                assert document["world_state_id"] is not None
                assert document["freshness"] is not None
