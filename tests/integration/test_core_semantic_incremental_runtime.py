"""Runtime incremental recompile, judged by full-rebuild oracles.

Unlike ``tests/unit/test_core_semantic_incremental_fixtures.py`` (a test-only
builder over hand-made specs), this drives the production spine,
``akc_compiler_runtime.Pipeline``, over real files on disk:

1. initial ``compile_workspace`` -> WS-1;
2. one source edited, ``recompile`` -> WS-2 through the selective path;
3. two oracles judge WS-2:
   * a forced full compile from a copy of the WS-1 store (same previous
     world, every document re-resolved) -- must be identical, ids included;
   * a from-scratch compile with no previous world -- must agree on every
     row except the logical ids identity continuity is allowed to keep.

Resolver and parser invocations are counted with spies on the real
functions. The counts are a record of what the runtime does, not a cost
claim: a recompile parses only dirty files when sealed outputs are available.
Its built-in §44 oracle still re-resolves every document, so it does *more*
resolver work than a full compile. That gap remains a strict xfail below.

The ACL tests drive a source's front-matter ``required_permission`` through
the same spine: it reaches compiled rows, gates the next ask, an ACL-only
edit recompiles selectively, and an ACL the runtime cannot map fails closed.
"""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from akc_cir.answer_compiler import AnswerOutcome
from akc_compiler_runtime import DEMO_FILES, Pipeline, WorldResult, write_demo_workspace
from akc_compiler_runtime import extraction as runtime_extraction
from akc_compiler_runtime.demo import LAUNCH_PLAN
from akc_compiler_runtime.extraction import UNMAPPED_ACL

LAUNCH_QUESTION = "What is the current launch date?"
ALL_DOCUMENTS = sorted(DEMO_FILES)
UNTOUCHED = sorted(set(ALL_DOCUMENTS) - {LAUNCH_PLAN})

# A deliberately small, 13-document source tree for the runtime oracle. The
# graph contains a two-hop dependency path so deleting its middle document
# exercises transitive invalidation through Pipeline rather than a test-only
# graph builder. Keep this separate from the 9-file public demo: the ACL
# compatibility cases below still exercise that fixture unchanged.
RUNTIME_FILES: dict[str, str] = {
    "projects/launch-plan.md": """\
# Project Phoenix - Launch Plan

## Launch date

The current confirmed launch date for Project Phoenix is October 15, 2026.

## Dependencies

- Depends on: policies/launch-governance.md - readiness gate compliance.

## Scope

The plan covers the go-to-market workstream for the Phoenix platform.
""",
    "policies/launch-governance.md": """\
# Launch Governance

## Readiness gate

The launch readiness gate requires sign-off from legal and finance before any public announcement.
""",
    "specs/launch-spec.md": """\
# Launch Readiness Spec

## Dependencies

- Depends on: projects/launch-plan.md - dates and scope.

## Go or no-go criteria

Go criterion: the marketing site must be live one week before day one.
""",
    "projects/rollout.md": """\
# Rollout

## Dependencies

- Depends on: policies/launch-bridge.md - bridge approval.

## Checklist

The rollout checklist is ready for the Phoenix launch.
""",
    "policies/launch-bridge.md": """\
# Launch Bridge

## Dependencies

- Depends on: policies/launch-authority.md - approval chain.

## Decision

The launch bridge is approved for the Phoenix release.
""",
    "policies/launch-authority.md": """\
# Launch Authority

## Approval

Launch authority requires approval from the release chair.
""",
    "policies/access-policy.md": """\
# Access Policy

## Review

The access policy requires quarterly review by the security team.
""",
    "policies/support-policy.md": """\
# Support Policy

## Support hours

Current support coverage is Monday through Friday from nine to five until December 31, 2026.

- Effective January 1, 2027: support coverage extends to weekends.
""",
    "notes/roadmap-hints.md": """\
# Roadmap hints

## Later

The companion mobile app is planned for next quarter.
""",
    "notes/pricing-note.md": """\
# Pricing notes

## Warranty

- The three-year extended warranty commitment is superseded by policies/warranty-policy.md.
""",
    "projects/quality.md": """\
# Quality

## Exit criteria

The quality review requires a signed release checklist.
""",
    "projects/board-budget.md": """\
# Board Budget

## Acquisition budget

The current board acquisition budget is four million dollars.
""",
    "meetings/2026-09-30-kickoff.md": """\
Date: 2026-09-30

# Kickoff Meeting

## Decisions

The kickoff meeting recorded a tentative launch date pending board approval.
""",
}
RUNTIME_DOCUMENTS = sorted(RUNTIME_FILES)
ALL_DOCUMENTS = RUNTIME_DOCUMENTS
UNTOUCHED = sorted(set(RUNTIME_DOCUMENTS) - {LAUNCH_PLAN})


@dataclass
class Invocations:
    """Real parser / resolver calls, split by who made them."""

    parsed: Counter[str] = field(default_factory=Counter)
    resolved: list[tuple[str, str]] = field(default_factory=list)  # (phase, rel_path)
    phase: str = "build"

    def reset(self) -> None:
        self.parsed.clear()
        self.resolved.clear()
        self.phase = "build"

    def resolved_in(self, phase: str) -> Counter[str]:
        return Counter(path for seen, path in self.resolved if seen == phase)


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[Invocations]:
    record = Invocations()
    real_parse = runtime_extraction.parse_file
    real_resolve = Pipeline._resolve_document
    real_oracle = Pipeline._verify_oracle

    def parse_spy(file: Any, **kwargs: Any) -> Any:
        record.parsed[file.rel_path] += 1
        return real_parse(file, **kwargs)

    def resolve_spy(self: Pipeline, document: Any, *args: Any, **kwargs: Any) -> Any:
        record.resolved.append((record.phase, document.file.rel_path))
        return real_resolve(self, document, *args, **kwargs)

    def oracle_spy(self: Pipeline, *args: Any, **kwargs: Any) -> Any:
        record.phase = "oracle"
        try:
            return real_oracle(self, *args, **kwargs)
        finally:
            record.phase = "build"

    monkeypatch.setattr(runtime_extraction, "parse_file", parse_spy)
    monkeypatch.setattr(Pipeline, "_resolve_document", resolve_spy)
    monkeypatch.setattr(Pipeline, "_verify_oracle", oracle_spy)
    yield record


@dataclass(frozen=True)
class Run:
    source: Path
    previous_store_copy: Path
    initial: WorldResult
    incremental: WorldResult
    pipeline: Pipeline


def _edit_launch_plan(source: Path) -> None:
    path = source / LAUNCH_PLAN
    text = path.read_text(encoding="utf-8")
    assert "October 15" in text
    path.write_text(text.replace("October 15", "November 3"), encoding="utf-8", newline="\n")


def _write_runtime_workspace(source: Path) -> None:
    for rel_path, content in RUNTIME_FILES.items():
        path = source / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def _run(tmp_path: Path, calls: Invocations) -> Run:
    source = tmp_path / "source"
    _write_runtime_workspace(source)
    store = tmp_path / "store"
    pipeline = Pipeline(store)
    initial = pipeline.compile_workspace(source)
    # Freeze the WS-1 store so a full-rebuild oracle can start from it.
    previous_store_copy = tmp_path / "store-ws1"
    shutil.copytree(store, previous_store_copy)
    _edit_launch_plan(source)
    calls.reset()
    incremental = pipeline.recompile(source)
    return Run(source, previous_store_copy, initial, incremental, pipeline)


def _without_logical_ids(claims: Mapping[str, Mapping[str, object]]) -> list[str]:
    return sorted(
        json.dumps({k: v for k, v in row.items() if k != "logical_id"}, sort_keys=True)
        for row in claims.values()
    )


def _without_lineage_metadata(
    claims: Mapping[str, Mapping[str, object]],
    *,
    include_invalidated_by: bool = True,
) -> list[str]:
    """Compare claims, retaining answer-affecting invalidation by default."""
    ignored = {"logical_id", "moved_from", "doc_node", "dependencies"}
    if not include_invalidated_by:
        ignored.add("invalidated_by")
    return sorted(
        json.dumps(
            {k: v for k, v in row.items() if k not in ignored},
            sort_keys=True,
        )
        for row in claims.values()
    )


def _mutate_runtime_workspace(source: Path, mutation: str) -> None:
    if mutation == "add":
        path = source / "notes/contingency.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Contingency\n\nThe contingency plan requires daily review.\n",
            encoding="utf-8",
            newline="\n",
        )
    elif mutation == "modify":
        _edit_launch_plan(source)
    elif mutation == "delete":
        (source / "notes/roadmap-hints.md").unlink()
    elif mutation == "rename":
        old = source / "notes/roadmap-hints.md"
        old.rename(source / "notes/roadmap.md")
    elif mutation == "bridge-delete":
        (source / "policies/launch-bridge.md").unlink()
    elif mutation == "authority-delete":
        (source / "policies/launch-authority.md").unlink()
    elif mutation == "acl-only":
        path = source / "projects/board-budget.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            "---\nrequired_permission: board:budget\n---\n" + text,
            encoding="utf-8",
            newline="\n",
        )
    elif mutation == "temporal":
        path = source / "policies/support-policy.md"
        text = path.read_text(encoding="utf-8")
        assert "Effective January 1, 2027" in text
        path.write_text(
            text.replace("Effective January 1, 2027", "Effective February 1, 2027"),
            encoding="utf-8",
            newline="\n",
        )
    else:  # pragma: no cover - parametrization is the only caller
        raise AssertionError(f"unknown mutation: {mutation}")


# ---------------------------------------------------------------------------
# Equivalence against full-rebuild oracles
# ---------------------------------------------------------------------------


def test_incremental_recompile_equals_full_rebuild_oracles(
    tmp_path: Path, calls: Invocations
) -> None:
    run = _run(tmp_path, calls)
    result = run.incremental

    assert run.initial.world_state_id == "WS-1"
    assert result.world_state_id == "WS-2"
    assert result.published and not result.no_op
    # It took the selective path, and its own §44 oracle signed off.
    assert result.equivalence is not None and result.equivalence.equivalent

    # Oracle 1: full compile from the same previous world. Identical.
    calls.reset()
    full = Pipeline(run.previous_store_copy).compile_workspace(run.source)
    assert full.world_state_id == result.world_state_id
    assert dict(full.claims) == dict(result.claims)
    assert dict(full.evidence_index) == dict(result.evidence_index)
    assert full.manifest_hash == result.manifest_hash

    # Oracle 2: from scratch, no previous outputs at all. Every row agrees
    # except logical ids, and only the edited document's ids may differ --
    # that is identity continuity, not drift.
    scratch = Pipeline(tmp_path / "scratch-store").compile_workspace(run.source)
    assert _without_logical_ids(scratch.claims) == _without_logical_ids(result.claims)
    assert dict(scratch.evidence_index) == dict(result.evidence_index)
    differing = set(scratch.claims) ^ set(result.claims)
    assert {
        str(row["rel_path"])
        for table in (scratch.claims, result.claims)
        for logical_id, row in table.items()
        if logical_id in differing
    } <= {LAUNCH_PLAN}

    for world in (result, full, scratch):
        answer = world.answer(LAUNCH_QUESTION)
        assert answer.outcome is AnswerOutcome.CURRENT
        assert "November 3" in str(world.claims[answer.claim_ids[0]]["value"])


@pytest.mark.parametrize(
    ("mutation", "build_resolves", "changed_paths"),
    [
        ("add", ["notes/contingency.md"], {"notes/contingency.md"}),
        ("delete", [], {"notes/roadmap-hints.md"}),
        (
            "rename",
            ["notes/roadmap.md"],
            {"notes/roadmap-hints.md", "notes/roadmap.md"},
        ),
        ("bridge-delete", [], {"policies/launch-bridge.md"}),
        ("authority-delete", [], {"policies/launch-authority.md"}),
        ("acl-only", ["projects/board-budget.md"], {"projects/board-budget.md"}),
        ("temporal", ["policies/support-policy.md"], {"policies/support-policy.md"}),
    ],
    ids=["add", "delete", "rename", "bridge-delete", "authority-two-hop-delete", "acl-only", "temporal-change"],
)
def test_mutations_match_same_prior_and_clean_rebuilds(
    tmp_path: Path,
    calls: Invocations,
    mutation: str,
    build_resolves: list[str],
    changed_paths: set[str],
) -> None:
    source = tmp_path / "source"
    _write_runtime_workspace(source)
    store = tmp_path / "store"
    pipeline = Pipeline(store)
    prior = pipeline.compile_workspace(source)
    prior_snapshot = (
        deepcopy(prior.claims),
        deepcopy(prior.evidence_index),
        prior.manifest_hash,
    )
    temporal_question = "What is the current support coverage weekends?"
    as_of_january = datetime(2027, 1, 15, tzinfo=UTC)
    temporal_before = (
        pipeline.answer(temporal_question, as_of=as_of_january)
        if mutation == "temporal"
        else None
    )
    if temporal_before is not None:
        assert temporal_before.outcome is AnswerOutcome.CURRENT
    prior_store_copy = tmp_path / "store-ws1"
    shutil.copytree(store, prior_store_copy)

    _mutate_runtime_workspace(source, mutation)
    current_paths = sorted(
        path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()
    )
    calls.reset()
    incremental = pipeline.recompile(source)

    assert incremental.world_state_id == "WS-2"
    assert incremental.published and not incremental.no_op
    assert incremental.equivalence is not None and incremental.equivalence.equivalent
    assert calls.parsed == Counter(dict.fromkeys(build_resolves, 1))
    assert calls.resolved_in("build") == Counter(dict.fromkeys(build_resolves, 1))
    assert calls.resolved_in("oracle") == Counter(dict.fromkeys(current_paths, 1))

    # The initial in-memory result remains a frozen view of WS-1 while the
    # active store advances to WS-2.
    assert prior.world_state_id == "WS-1"
    assert dict(prior.claims) == prior_snapshot[0]
    assert dict(prior.evidence_index) == prior_snapshot[1]
    assert prior.manifest_hash == prior_snapshot[2]

    calls.reset()
    same_prior = Pipeline(prior_store_copy).compile_workspace(source)
    assert same_prior.world_state_id == incremental.world_state_id
    assert dict(same_prior.claims) == dict(incremental.claims)
    assert dict(same_prior.evidence_index) == dict(incremental.evidence_index)
    assert same_prior.manifest_hash == incremental.manifest_hash

    clean = Pipeline(tmp_path / "clean-store").compile_workspace(source)
    if mutation in {"bridge-delete", "authority-delete"}:
        # A clean compile has no prior-world tombstones, so it does not know
        # that these still-present dependents were invalidated by deletion.
        # Keep that answer-affecting history visible as an explicit divergence.
        assert _without_lineage_metadata(clean.claims) != _without_lineage_metadata(
            incremental.claims
        )
        assert _without_lineage_metadata(
            clean.claims, include_invalidated_by=False
        ) == _without_lineage_metadata(incremental.claims, include_invalidated_by=False)
    else:
        assert _without_lineage_metadata(clean.claims) == _without_lineage_metadata(
            incremental.claims
        )
    assert dict(clean.evidence_index) == dict(incremental.evidence_index)
    differing_ids = set(clean.claims) ^ set(incremental.claims)
    assert {
        str(row["rel_path"])
        for table in (clean.claims, incremental.claims)
        for logical_id, row in table.items()
        if logical_id in differing_ids
    } <= changed_paths

    if mutation == "add":
        assert any(row["rel_path"] == "notes/contingency.md" for row in incremental.claims.values())
    elif mutation == "delete":
        assert all(row["rel_path"] != "notes/roadmap-hints.md" for row in incremental.claims.values())
    elif mutation == "rename":
        renamed = [row for row in incremental.claims.values() if row["rel_path"] == "notes/roadmap.md"]
        assert renamed
        assert {row["moved_from"] for row in renamed} == {"notes/roadmap-hints.md"}
        old_ids = {
            str(row["logical_id"])
            for row in prior.claims.values()
            if row["rel_path"] == "notes/roadmap-hints.md"
        }
        assert {str(row["logical_id"]) for row in renamed} == old_ids
    elif mutation == "bridge-delete":
        dependent = [row for row in incremental.claims.values() if row["rel_path"] == "projects/rollout.md"]
        assert dependent and all(row["invalidated_by"] for row in dependent)
        assert clean.answer("What is the rollout checklist?").outcome is AnswerOutcome.CURRENT
        assert pipeline.answer("What is the rollout checklist?").outcome is AnswerOutcome.UNRESOLVED
    elif mutation == "authority-delete":
        bridge = [row for row in incremental.claims.values() if row["rel_path"] == "policies/launch-bridge.md"]
        rollout = [row for row in incremental.claims.values() if row["rel_path"] == "projects/rollout.md"]
        assert bridge and all(row["invalidated_by"] for row in bridge)
        assert rollout and all(row["invalidated_by"] for row in rollout)
        for question in ("What is the launch bridge approved for?", "What is the rollout checklist?"):
            assert clean.answer(question).outcome is AnswerOutcome.CURRENT
            assert pipeline.answer(question).outcome is AnswerOutcome.UNRESOLVED
    elif mutation == "acl-only":
        budget_rows = [
            row for row in incremental.claims.values() if row["rel_path"] == "projects/board-budget.md"
        ]
        assert budget_rows and {row["required_permission"] for row in budget_rows} == {"board:budget"}
        budget_question = "What is the current board acquisition budget?"
        _assert_refused(pipeline.answer(budget_question))
        _assert_refused(pipeline.answer(budget_question, permissions={"board:chair"}))
        assert pipeline.answer(budget_question, permissions={"board:budget"}).outcome is AnswerOutcome.CURRENT
    elif mutation == "temporal":
        weekend_rows = [
            row
            for row in incremental.claims.values()
            if row["rel_path"] == "policies/support-policy.md" and "extends to weekends" in str(row["value"])
        ]
        assert weekend_rows and {row["valid_from"] for row in weekend_rows} == {
            "2027-02-01T00:00:00+00:00"
        }
        assert pipeline.answer(temporal_question, as_of=as_of_january).outcome is AnswerOutcome.UNRESOLVED


def test_recompile_with_no_change_is_a_no_op(tmp_path: Path, calls: Invocations) -> None:
    source = tmp_path / "source"
    _write_runtime_workspace(source)
    pipeline = Pipeline(tmp_path / "store")
    pipeline.compile_workspace(source)
    stored_bytes = {
        path.relative_to(pipeline.store.base): path.read_bytes()
        for path in pipeline.store.base.rglob("*") if path.is_file()
    }
    calls.reset()

    again = pipeline.recompile(source)

    assert again.no_op and not again.published
    assert again.world_state_id == "WS-1"
    assert calls.resolved == []
    assert calls.parsed == Counter()
    assert {
        path.relative_to(pipeline.store.base): path.read_bytes()
        for path in pipeline.store.base.rglob("*") if path.is_file()
    } == stored_bytes


# ---------------------------------------------------------------------------
# What the runtime actually invokes (a record, not a cost claim)
# ---------------------------------------------------------------------------


def test_recompile_invocation_counts_are_what_the_runtime_does(
    tmp_path: Path, calls: Invocations
) -> None:
    source = tmp_path / "source"
    _write_runtime_workspace(source)
    pipeline = Pipeline(tmp_path / "store")
    pipeline.compile_workspace(source)
    full_compile_resolves = Counter(path for _, path in calls.resolved)
    assert full_compile_resolves == Counter(dict.fromkeys(ALL_DOCUMENTS, 1))

    _edit_launch_plan(source)
    calls.reset()
    pipeline.recompile(source)

    # The selective build itself touches only the edited document ...
    assert calls.resolved_in("build") == Counter({LAUNCH_PLAN: 1})
    # ... but the §44 oracle still re-resolves every document.
    # Total resolver work exceeds a full compile; parser work is dirty-only.
    assert calls.resolved_in("oracle") == Counter(dict.fromkeys(ALL_DOCUMENTS, 1))
    assert calls.parsed == Counter({LAUNCH_PLAN: 1})
    assert len(calls.resolved) == len(ALL_DOCUMENTS) + 1


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "known gap: Pipeline._verify_oracle re-resolves every document on each "
        "non-no-op recompile, so untouched documents are resolved again"
    ),
)
def test_recompile_does_not_reresolve_untouched_documents(
    tmp_path: Path, calls: Invocations
) -> None:
    _run(tmp_path, calls)
    resolved = Counter(path for _, path in calls.resolved)
    assert all(resolved[path] == 0 for path in UNTOUCHED)


def test_recompile_does_not_reparse_untouched_documents(tmp_path: Path, calls: Invocations) -> None:
    _run(tmp_path, calls)
    assert all(calls.parsed[path] == 0 for path in UNTOUCHED)


# ---------------------------------------------------------------------------
# ACL: a source-declared restriction reaches compiled rows and gates answers
# ---------------------------------------------------------------------------

RESTRICTED_DOC = "policies/board-minutes.md"
BUDGET_QUESTION = "What is the current acquisition budget?"
BOARD_BODY = """\
# Board minutes

## Decision

The current acquisition budget approved by the board is four million dollars.
"""


def _front_matter(*lines: str) -> str:
    return "---\n" + "".join(f"{line}\n" for line in lines) + "---\n" + BOARD_BODY


RESTRICTED_SOURCE = _front_matter("required_permission: board:minuted")


def _write_board(source: Path, text: str) -> None:
    (source / RESTRICTED_DOC).write_text(text, encoding="utf-8", newline="\n")


def _board_rows(result: WorldResult) -> list[Mapping[str, object]]:
    rows = [row for row in result.claims.values() if row["rel_path"] == RESTRICTED_DOC]
    assert rows, "the restricted document compiled no claim"
    return rows


def _assert_refused(answer: Any) -> None:
    assert answer.outcome is AnswerOutcome.NOT_AUTHORIZED
    assert answer.claim_ids == ()
    assert answer.evidence_occurrences == ()


def _assert_board_answer(result: WorldResult, answer: Any) -> None:
    assert answer.outcome is AnswerOutcome.CURRENT
    assert result.claims[answer.claim_ids[0]]["rel_path"] == RESTRICTED_DOC


def _compiled(tmp_path: Path, board_text: str) -> tuple[Path, Pipeline, WorldResult]:
    source = tmp_path / "source"
    write_demo_workspace(source)
    _write_board(source, board_text)
    pipeline = Pipeline(tmp_path / "store")
    return source, pipeline, pipeline.compile_workspace(source)


def test_restricted_source_is_answered_only_to_a_permitted_asker(
    tmp_path: Path, calls: Invocations
) -> None:
    _, pipeline, result = _compiled(tmp_path, RESTRICTED_SOURCE)

    assert {row["required_permission"] for row in _board_rows(result)} == {"board:minuted"}
    # Only the restricted document is restricted.
    assert all(
        row["required_permission"] is None
        for row in result.claims.values()
        if row["rel_path"] != RESTRICTED_DOC
    )

    _assert_refused(pipeline.answer(BUDGET_QUESTION))
    _assert_refused(pipeline.answer(BUDGET_QUESTION, permissions={"board:chair"}))
    _assert_board_answer(result, pipeline.answer(BUDGET_QUESTION, permissions={"board:minuted"}))
    # Public claims stay public to an asker with no permission.
    assert pipeline.answer(LAUNCH_QUESTION).outcome is AnswerOutcome.CURRENT


def test_acl_only_change_is_recompiled_selectively_and_gates_the_next_ask(
    tmp_path: Path, calls: Invocations
) -> None:
    source, pipeline, before = _compiled(tmp_path, BOARD_BODY)
    assert all(row["required_permission"] is None for row in _board_rows(before))
    _assert_board_answer(before, pipeline.answer(BUDGET_QUESTION))

    # Same body, new front matter: only the access requirement changes.
    _write_board(source, RESTRICTED_SOURCE)
    calls.reset()
    after = pipeline.recompile(source)

    assert after.published and after.world_state_id == "WS-2"
    assert after.equivalence is not None and after.equivalence.equivalent
    # Selective, not a reindex: the build resolved the one edited document.
    assert calls.resolved_in("build") == Counter({RESTRICTED_DOC: 1})
    board_ids = {str(row["logical_id"]) for row in _board_rows(after)}
    assert board_ids == {str(row["logical_id"]) for row in _board_rows(before)}
    assert {row["required_permission"] for row in _board_rows(after)} == {"board:minuted"}
    # The diff registers the ACL change (PERMISSION_CHANGED); without it the
    # bytes-changed-but-units-equal edit planned as "content did not change".
    assert after.plan is not None
    assert all(
        target.reason != "the source content did not change" for target in after.plan.targets
    )

    _assert_refused(pipeline.answer(BUDGET_QUESTION))
    _assert_board_answer(after, pipeline.answer(BUDGET_QUESTION, permissions={"board:minuted"}))


def test_revoking_or_changing_a_source_permission_applies_on_the_next_ask(
    tmp_path: Path, calls: Invocations
) -> None:
    source, pipeline, _ = _compiled(tmp_path, RESTRICTED_SOURCE)
    holder = {"board:minuted"}

    # Asker-side revoke: no recompile, no new world; the next ask is refused.
    granted = pipeline.answer(BUDGET_QUESTION, permissions=holder)
    assert granted.outcome is AnswerOutcome.CURRENT
    _assert_refused(pipeline.answer(BUDGET_QUESTION, permissions=set()))

    # Source-side change: board:minuted -> board:chair. The old holder loses it.
    _write_board(source, _front_matter("required_permission: board:chair"))
    changed = pipeline.recompile(source)
    assert changed.equivalence is not None and changed.equivalence.equivalent
    _assert_refused(pipeline.answer(BUDGET_QUESTION, permissions=holder))
    _assert_board_answer(changed, pipeline.answer(BUDGET_QUESTION, permissions={"board:chair"}))

    # Source-side revoke to a fail-closed ACL: nobody is answered.
    _write_board(source, _front_matter("acl: [board]"))
    revoked = pipeline.recompile(source)
    assert revoked.equivalence is not None and revoked.equivalence.equivalent
    for permissions in (set(), holder, {"board:chair"}, {UNMAPPED_ACL}):
        _assert_refused(pipeline.answer(BUDGET_QUESTION, permissions=permissions))


#: Encoding/line-ending variants of a valid declaration: honoured, not dropped.
ENCODED_RESTRICTIONS = {
    "utf8-bom": "﻿" + RESTRICTED_SOURCE,
    "crlf": RESTRICTED_SOURCE.replace("\n", "\r\n"),
    "cr-only": RESTRICTED_SOURCE.replace("\n", "\r"),
    "quoted-value": _front_matter('required_permission: "board:minuted"'),
}


@pytest.mark.parametrize("board_text", ENCODED_RESTRICTIONS.values(), ids=ENCODED_RESTRICTIONS)
def test_encoded_restriction_is_still_enforced(
    tmp_path: Path, calls: Invocations, board_text: str
) -> None:
    _, pipeline, result = _compiled(tmp_path, board_text)

    assert {row["required_permission"] for row in _board_rows(result)} == {"board:minuted"}
    _assert_refused(pipeline.answer(BUDGET_QUESTION))
    _assert_board_answer(result, pipeline.answer(BUDGET_QUESTION, permissions={"board:minuted"}))


#: Every shape a line scanner cannot map with certainty. Each must fail closed.
UNMAPPABLE_ACLS = {
    "two-tokens": _front_matter("required_permission: board minuted"),
    "empty": _front_matter("required_permission:"),
    "yaml-list": _front_matter("required_permission:", "  - board:minuted"),
    "repeated": _front_matter("required_permission: board:a", "required_permission: board:b"),
    "trailing-comment": _front_matter("required_permission: board:minuted # board only"),
    "tagged-value": _front_matter("required_permission: !!str board:minuted"),
    "escaped-value": _front_matter('required_permission: "board\\x3aminuted"'),
    "marker-literal": _front_matter("required-permission: !acl-unmapped"),
    "acl-key": _front_matter("acl: board:minuted"),
    "visibility": _front_matter("visibility: private"),
    "allowed-groups": _front_matter("allowed_groups: [board]"),
    "camel-case": _front_matter("requiredPermission: board:minuted"),
    "title-case": _front_matter("Required_Permission: board:minuted"),
    "fullwidth": _front_matter("\uff52equired_\uff50ermission: board:minuted"),
    "double-quoted-key": _front_matter('"required_permission": board:minuted'),
    "single-quoted-key": _front_matter("'required_permission': board:minuted"),
    # The escape hides every ACL token, so only the key-syntax rule catches it.
    "escaped-key": _front_matter('"\\x72equired_\\x70ermission": board:minuted'),
    "flow-mapping": _front_matter("{required_permission: board:minuted}"),
    "anchor-merge": _front_matter("defaults: &d {required_permission: board:minuted}", "<<: *d"),
    "escaped-anchor-merge": _front_matter(
        'defaults: &d {"\\x72equired_\\x70ermission": board:minuted}', "<<: *d"
    ),
    "complex-key": _front_matter("? required_permission", ": board:minuted"),
    "indented-mapping": _front_matter("  required_permission: board:minuted"),
    "nested": _front_matter("meta:", "  required_permission: board:minuted"),
    "commented": _front_matter("# required_permission: board:minuted"),
    "toml": '+++\nrequired_permission = "board:minuted"\n+++\n' + BOARD_BODY,
    "json": '{"required_permission": "board:minuted"}\n' + BOARD_BODY,
    "leading-blank-line": "\n" + RESTRICTED_SOURCE,
    "bom-then-blank-line": "﻿\n" + RESTRICTED_SOURCE,
    # Unterminated front matter declaring an ACL: not trusted as data.
    "unterminated": "---\nrequired_permission: board:minuted\n" + BOARD_BODY,
    "dots-close": "---\nrequired_permission: board:minuted\n...\n" + BOARD_BODY,
    # A declaration outside the front matter is never silently ignored.
    "after-close": "---\ntitle: x\n---\nrequired_permission: board:minuted\n" + BOARD_BODY,
    "body-only": "Required permission: board:minuted\n\n" + BOARD_BODY,
    "body-after-valid": RESTRICTED_SOURCE + "\n- required-permissions = board:chair\n",
    # YAML 1.1 line breaks the scanner must split on, hiding an escaped key.
    "nel-break": _front_matter('title: x\x85"\\x72equired_\\x70ermission": board:minuted'),
    "ls-break": _front_matter('title: x\u2028"\\x72equired_\\x70ermission": board:minuted'),
    "ps-break": _front_matter('title: x\u2029"\\x72equired_\\x70ermission": board:minuted'),
    # An opener that is not exactly --- is a block, just not a standard one.
    "opener-comment": "--- # fm\nacl: board\n---\n" + BOARD_BODY,
    "opener-tag": "--- !meta\nacl: board\n---\n" + BOARD_BODY,
    # Unquoted YAML non-strings are not a permission token.
    "null-value": _front_matter("required_permission: null"),
    "tilde-value": _front_matter("required_permission: ~"),
    "bool-value": _front_matter("required_permission: yes"),
    "number-value": _front_matter("required_permission: 42"),
    # Zero-width characters splitting the key name.
    "zero-width": _front_matter("re\u200bquired_permi\u200bssion: board:minuted"),
}


@pytest.mark.parametrize("board_text", UNMAPPABLE_ACLS.values(), ids=UNMAPPABLE_ACLS)
def test_unmappable_source_acl_fails_closed(
    tmp_path: Path, calls: Invocations, board_text: str
) -> None:
    _, pipeline, result = _compiled(tmp_path, board_text)

    assert {row["required_permission"] for row in _board_rows(result)} == {UNMAPPED_ACL}
    for permissions in (set(), {"board:minuted"}, {UNMAPPED_ACL}, {"board:minuted", UNMAPPED_ACL}):
        _assert_refused(pipeline.answer(BUDGET_QUESTION, permissions=permissions))


#: Front matter with nothing ACL-ish in it stays public in every shape.
PUBLIC_FRONT_MATTER = {
    "yaml": _front_matter('title: "Board minutes"', "tags: [q3, board]", "- note"),
    "toml": '+++\ntitle = "Board minutes"\n+++\n' + BOARD_BODY,
    "leading-blank-line": "\n" + _front_matter("title: Board minutes"),
}


@pytest.mark.parametrize(
    "board_text",
    [_front_matter("permitted_users: [board]"), _front_matter("audience: board-only")],
    ids=["permitted-users", "audience"],
)
def test_acl_vocabulary_outside_the_contract_stays_public_known_limit(
    tmp_path: Path, calls: Invocations, board_text: str
) -> None:
    """Documented limit: ``required_permission`` is the only ACL contract.

    Vocabulary the token list does not name is not recognised as an ACL. This
    pins the limit so widening the contract is a visible, deliberate change.
    """
    _, pipeline, result = _compiled(tmp_path, board_text)

    assert all(row["required_permission"] is None for row in _board_rows(result))
    _assert_board_answer(result, pipeline.answer(BUDGET_QUESTION))


def test_quoted_null_is_a_literal_permission(tmp_path: Path, calls: Invocations) -> None:
    """Quoted, ``"null"`` is a string: a (more restrictive) literal permission."""
    _, pipeline, result = _compiled(tmp_path, _front_matter('required_permission: "null"'))

    assert {row["required_permission"] for row in _board_rows(result)} == {"null"}
    _assert_refused(pipeline.answer(BUDGET_QUESTION))
    _assert_board_answer(result, pipeline.answer(BUDGET_QUESTION, permissions={"null"}))


@pytest.mark.parametrize("board_text", PUBLIC_FRONT_MATTER.values(), ids=PUBLIC_FRONT_MATTER)
def test_front_matter_without_acl_stays_public(
    tmp_path: Path, calls: Invocations, board_text: str
) -> None:
    _, pipeline, result = _compiled(tmp_path, board_text)

    assert all(row["required_permission"] is None for row in _board_rows(result))
    _assert_board_answer(result, pipeline.answer(BUDGET_QUESTION))
