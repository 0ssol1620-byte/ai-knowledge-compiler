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

The ACL tests drive a source's front-matter ``required_permission`` through
the same spine: it reaches compiled rows, gates the next ask, an ACL-only
edit recompiles selectively, and an ACL the runtime cannot map fails closed.
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
from akc_compiler_runtime.extraction import UNMAPPED_ACL

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
