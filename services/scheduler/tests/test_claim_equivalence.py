"""GPU claim equivalence — the two categories that are not comparative.

The evidence for adapting `GpuInvocationWorker` to the claim broker is of three
kinds, and testing all of it the same way would be waste dressed as rigour.

* **COMPARATIVE** — eligibility, ordering, concurrency, lease expiry. Real
  BEFORE-vs-broker runs over one seeded population, in
  ``infra/postgres/shadow_validate_dual_plane.py`` where a live catalog exists.
  Not here.
* **INVARIANT / MADE IMPOSSIBLE** — the double lease stamp. Not "we checked and
  it did not happen": the shape of ``_claim_from_row`` means a second stamp is
  not expressible. §1 pins that shape so it cannot drift back.
* **SHARED-BODY + REACHABILITY** — attempt and state transitions, commit
  boundary, terminal states, rollback. One body with two callers proves both
  callers run the same code. It does **not** prove both *reach* it under the
  same conditions, and that half is not free — §2 pins the entry condition
  structurally, and the comparative set proves the population half.

These are structural assertions over the source. That is deliberate: an
invariant that holds because of how the code is shaped is checked by reading the
shape, and a runtime test would only observe one path through it.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
from akc_scheduler import gpu_jobs

SOURCE = pathlib.Path(inspect.getfile(gpu_jobs))
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def _method(name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.ClassDef) and node.name == "GpuInvocationWorker":
            for member in node.body:
                if isinstance(member, ast.AsyncFunctionDef) and member.name == name:
                    return member
    raise AssertionError(f"GpuInvocationWorker.{name} not found")


def _calls(node: ast.AST) -> list[str]:
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                out.append(func.attr)
            elif isinstance(func, ast.Name):
                out.append(func.id)
    return out


def _assigned_attributes(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Attribute):
                    out.add(target.attr)
        elif isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Attribute):
            out.add(child.target.attr)
    return out


# --- 1. INVARIANT: a second lease stamp is MADE IMPOSSIBLE -------------------
#
# Recorded as *made impossible*, not as *verified*. Nothing observed a double
# stamp and then concluded it cannot happen; the token is a parameter, so the
# body has nothing to mint a second one with. The tests below hold that shape.


def test_the_shared_body_cannot_mint_a_lease_token() -> None:
    """The structural invariant. If this fails, the guarantee is gone.

    Reintroducing ``uuid.uuid4()`` here would let AFTER stamp a token different
    from the one the broker already wrote to the row — and because the claim
    binding compares ``lease_token`` against ``app.lease_token``, the row would
    vanish from its own transaction mid-flight. That failure is silent, which is
    why the defence is shape rather than vigilance.
    """

    body = _method("_claim_from_row")

    assert "uuid4" not in _calls(body), (
        "_claim_from_row generated a uuid. The double-stamp guarantee is "
        "structural — the token must arrive as a parameter and never be minted "
        "here. See docs/audit/V5_CLAIM_SITE_BEHAVIOR_MATRIX.md section 5a."
    )


def test_the_token_and_lease_arrive_as_parameters() -> None:
    body = _method("_claim_from_row")
    keyword_only = {argument.arg for argument in body.args.kwonlyargs}

    assert {"token", "lease_expires_at"} <= keyword_only


def test_the_before_path_mints_exactly_one_token_and_hands_it_over() -> None:
    """BEFORE still owns lease generation; it just no longer applies it itself."""

    before = _method("_claim")

    assert _calls(before).count("uuid4") == 1
    handover = [
        node
        for node in ast.walk(before)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_claim_from_row"
    ]
    assert len(handover) == 1
    passed = {keyword.arg for keyword in handover[0].keywords}
    assert {"token", "lease_expires_at", "now"} <= passed


# --- 2. SHARED BODY + REACHABILITY ------------------------------------------


@pytest.mark.parametrize(
    "marker",
    [
        "_terminal_local",       # both terminal states live here
        "append_gpu_event",      # the event append inside the claim transaction
        "commit",                # the commit boundary
        "_fence_reason",         # the cancellation fence
    ],
)
def test_the_claim_choreography_has_exactly_one_implementation(marker: str) -> None:
    """Body equivalence: there is one copy, so there is nothing to diverge.

    Asserted per marker rather than in aggregate so a failure names which piece
    was duplicated back into a caller.
    """

    shared = _calls(_method("_claim_from_row"))
    before = _calls(_method("_claim"))

    assert marker in shared, f"{marker} left the shared body"
    assert marker not in before, (
        f"{marker} is implemented in _claim as well as _claim_from_row. Two "
        "copies of the claim choreography can drift, which is the whole thing "
        "the extraction exists to prevent."
    )


def test_every_state_transition_lives_in_the_shared_body() -> None:
    """Attempt counters and status writes belong to one body, not two."""

    shared = _assigned_attributes(_method("_claim_from_row"))
    before = _assigned_attributes(_method("_claim"))

    assert {
        "status",
        "attempt_count",
        "cancel_attempt_count",
        "lease_token",
        "lease_expires_at",
        "started_at",
        "last_error_code",
    } <= shared
    assert before == set(), (
        f"_claim writes {sorted(before)} of its own. Selection is all it may do; "
        "every transition belongs to the body both paths share."
    )


def test_entry_into_the_shared_body_is_gated_only_by_finding_a_row() -> None:
    """REACHABILITY — the half the shared body does not give for free.

    A shared implementation proves both callers run the same code. It says
    nothing about whether both *reach* it under the same conditions, and an
    extra condition on one side would be an equivalence break that no amount of
    body-sharing detects.

    So the entry condition is pinned: in BEFORE, the only thing standing between
    selecting a row and entering the body is "did the select return one". The
    broker path's entry condition must reduce to the same question — the broker
    grants a row or it does not — and that the two select the *same* row over
    the same population is the comparative half, proved against a live catalog
    by ``equivalence:*`` in the shadow validator.
    """

    before = _method("_claim")
    handover = next(
        node
        for node in ast.walk(before)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_claim_from_row"
    )

    guards = [node for node in ast.walk(before) if isinstance(node, ast.If)]
    assert len(guards) == 1, (
        f"_claim has {len(guards)} conditional(s) before the shared body. Each "
        "one is a condition the broker path would also have to reproduce, and "
        "an unreproduced one is a silent equivalence break."
    )
    guard = guards[0]
    assert isinstance(guard.test, ast.Compare)
    assert isinstance(guard.test.left, ast.Name)
    assert guard.test.left.id == "invocation"
    assert isinstance(guard.test.comparators[0], ast.Constant)
    assert guard.test.comparators[0].value is None
    assert any(isinstance(statement, ast.Return) for statement in guard.body)
    assert handover.lineno > guard.lineno


def test_the_shared_body_reaches_both_terminal_states() -> None:
    """Terminal-state reachability, by the codes rather than by call count."""

    source = ast.get_source_segment(
        SOURCE.read_text(encoding="utf-8"), _method("_claim_from_row")
    )
    assert source is not None
    assert "GPU_PROVIDER_CANCEL_UNCONFIRMED" in source
    assert "GPU_PROVIDER_ATTEMPTS_EXHAUSTED" in source


def test_the_commit_is_the_last_thing_the_shared_body_does() -> None:
    """Commit-boundary equivalence: one commit, after every transition.

    Rollback and visibility follow from this rather than needing their own
    exercise — every write above the commit is in one transaction, and the
    broker's ``UPDATE`` runs inside that same transaction because a
    ``SECURITY DEFINER`` function joins its caller's. An exception anywhere above
    takes the lease stamp with it.
    """

    body = _method("_claim_from_row")
    commits = [
        node
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]
    assert len(commits) == 1

    returns = [node for node in ast.walk(body) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert returns[0].lineno > commits[0].lineno


def test_the_broker_path_is_opt_in_and_off_by_default() -> None:
    """Canary A is a choice, not a deployment.

    This replaces `test_wiring_has_not_started`, which failed the moment the
    call was flipped — as its own comment instructed. What is worth holding now
    is not "the broker path is unreachable" but "reaching it takes a deliberate
    act": `run_one` can call either, and the default is the shipped ORM path.
    """

    from akc_scheduler.gpu_jobs import GpuWorkerPolicy

    assert GpuWorkerPolicy().use_claim_broker is False

    calls = _calls(_method("run_one"))
    assert "_claim_via_broker" in calls
    assert "_claim" in calls


def test_the_after_path_reuses_the_shared_body_rather_than_copying_it() -> None:
    """The whole point of the extraction, asserted against the written AFTER."""

    after = _calls(_method("_claim_via_broker"))

    assert "_claim_from_row" in after
    for marker in ("_terminal_local", "append_gpu_event", "commit", "_fence_reason"):
        assert marker not in after, (
            f"_claim_via_broker implements {marker} itself. Both paths must reach "
            "the one shared body; a second copy is how they drift apart."
        )


def test_the_after_path_cannot_mint_a_lease_either() -> None:
    """The invariant holds on the side that actually receives a broker token."""

    assert "uuid4" not in _calls(_method("_claim_via_broker"))


def test_an_unreadable_claimed_row_raises_rather_than_reading_as_idle() -> None:
    """Entry-condition equivalence, on the AFTER side.

    BEFORE enters the shared body iff its select found a row. AFTER must not
    acquire a second way of returning `None`: if the broker granted a claim and
    the scoped reread cannot see it, that is a binding fault, and reporting it
    as "no work" would be indistinguishable from an idle queue — the failure
    mode Gate 1 exists to make visible.
    """

    body = _method("_claim_via_broker")
    guards = [node for node in ast.walk(body) if isinstance(node, ast.If)]
    returning_none = [
        guard
        for guard in guards
        if any(
            isinstance(statement, ast.Return)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is None
            for statement in guard.body
        )
    ]
    assert len(returning_none) == 1, (
        "AFTER has more than one way to report an empty poll. Only 'the broker "
        "granted nothing' may do that."
    )
    assert any(isinstance(node, ast.Raise) for node in ast.walk(body))
