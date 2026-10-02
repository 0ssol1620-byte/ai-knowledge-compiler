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
claim: today a recompile re-parses every file and its built-in §44 oracle
re-resolves every document, so it does *more* resolver work than a full
compile. That gap is pinned below as strict xfails, not hidden.

The ACL test pins a second open gap: an access restriction declared in a
source never reaches a compiled row (``required_permission`` is always None).
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from akc_cir.answer_compiler import AnswerOutcome
from akc_compiler_runtime import DEMO_FILES, Pipeline, WorldResult, write_demo_workspace
from akc_compiler_runtime import extraction as runtime_extraction
from akc_compiler_runtime.demo import LAUNCH_PLAN

LAUNCH_QUESTION = "What is the current launch date?"
ALL_DOCUMENTS = sorted(DEMO_FILES)
UNTOUCHED = sorted(set(ALL_DOCUMENTS) - {LAUNCH_PLAN})


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


def _run(tmp_path: Path, calls: Invocations) -> Run:
    source = tmp_path / "source"
    write_demo_workspace(source)
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


def test_recompile_with_no_change_is_a_no_op(tmp_path: Path, calls: Invocations) -> None:
    source = tmp_path / "source"
    write_demo_workspace(source)
    pipeline = Pipeline(tmp_path / "store")
    pipeline.compile_workspace(source)
    calls.reset()

    again = pipeline.recompile(source)

    assert again.no_op and not again.published
    assert again.world_state_id == "WS-1"
    assert calls.resolved == []
    # Even a no-op re-parses the whole tree to hash it against the cursor.
    assert calls.parsed == Counter(dict.fromkeys(ALL_DOCUMENTS, 1))


# ---------------------------------------------------------------------------
# What the runtime actually invokes (a record, not a cost claim)
# ---------------------------------------------------------------------------


def test_recompile_invocation_counts_are_what_the_runtime_does(
    tmp_path: Path, calls: Invocations
) -> None:
    source = tmp_path / "source"
    write_demo_workspace(source)
    pipeline = Pipeline(tmp_path / "store")
    pipeline.compile_workspace(source)
    full_compile_resolves = Counter(path for _, path in calls.resolved)
    assert full_compile_resolves == Counter(dict.fromkeys(ALL_DOCUMENTS, 1))

    _edit_launch_plan(source)
    calls.reset()
    pipeline.recompile(source)

    # The selective build itself touches only the edited document ...
    assert calls.resolved_in("build") == Counter({LAUNCH_PLAN: 1})
    # ... but the §44 oracle then re-resolves every document, and every file
    # is re-parsed up front. Total resolver work exceeds a full compile.
    assert calls.resolved_in("oracle") == Counter(dict.fromkeys(ALL_DOCUMENTS, 1))
    assert calls.parsed == Counter(dict.fromkeys(ALL_DOCUMENTS, 1))
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "known gap: Pipeline._parse runs parse_file (claim extraction) on every "
        "file before the cursor diff, so untouched documents are re-parsed"
    ),
)
def test_recompile_does_not_reparse_untouched_documents(tmp_path: Path, calls: Invocations) -> None:
    _run(tmp_path, calls)
    assert all(calls.parsed[path] == 0 for path in UNTOUCHED)


# ---------------------------------------------------------------------------
# ACL: a source-declared restriction never reaches a compiled row
# ---------------------------------------------------------------------------

RESTRICTED_DOC = "policies/board-minutes.md"
RESTRICTED_SOURCE = """\
---
required_permission: board:minuted
---
# Board minutes

## Decision

The current acquisition budget approved by the board is four million dollars.
"""


def test_runtime_rows_drop_source_acl_known_gap(tmp_path: Path, calls: Invocations) -> None:
    """Pins today's behaviour; flip it when ACL input reaches compiled rows.

    The front matter is stripped before extraction and ``_row_from_draft``
    hard-codes ``required_permission: None``, so the restricted claim is
    served CURRENT to a context that holds no permission at all.
    """
    source = tmp_path / "source"
    write_demo_workspace(source)
    (source / RESTRICTED_DOC).write_text(RESTRICTED_SOURCE, encoding="utf-8", newline="\n")
    pipeline = Pipeline(tmp_path / "store")

    result = pipeline.compile_workspace(source)

    restricted = [row for row in result.claims.values() if row["rel_path"] == RESTRICTED_DOC]
    assert restricted, "the restricted document compiled no claim"
    assert all(row["required_permission"] is None for row in result.claims.values())

    answer = pipeline.answer("What is the current acquisition budget?")
    assert answer.outcome is AnswerOutcome.CURRENT
    assert answer.outcome is not AnswerOutcome.NOT_AUTHORIZED
    assert result.claims[answer.claim_ids[0]]["rel_path"] == RESTRICTED_DOC
