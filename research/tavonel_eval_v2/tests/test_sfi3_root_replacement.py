"""Tests for `tools/replace_sfi3_roots.py` — the frozen-criterion recovery of
SFI3's unavailable declared roots.

No live network call in this file, for the same reason
`tests/test_sfi3_root_preflight.py` states for itself: the property under
test — that the replacement criterion is frozen and every candidate is
evaluated only by it — must be checkable without depending on GitHub, eCFR or
Wikipedia being up. Every test below either exercises pure logic
(`build_policy`, `candidate_order_key`, disjointness of the literal pools) or
replaces the network-touching pieces (`_CHECK_FN`, `_declared_root_lookup`,
`_ALREADY_DECLARED`, `write_immutable`) with fakes.

What this file guards, matching the task's definition of done:

1. `build_policy()` is pure — no network call anywhere in it, deterministic,
   and splits the pinned source receipt's invalid roots correctly into
   retry-eligible (the one transient state) vs. needs-a-candidate (everything
   else)
2. the pinned source receipt is hash-verified before use; a mismatched or
   missing receipt raises rather than being silently trusted
3. `freeze_policy()` writes its receipt before anything in `run_replacement`
   ever runs — asserted both by "no network call happens inside it" and by
   call-order under a fake `write_immutable`
4. `candidate_order_key` is deterministic and salted distinctly from every
   SFI-family lineage order key
5. the three literal candidate pools are disjoint from every predecessor
   study's declared roots, from SFI3's own current declaration, and internally
   duplicate-free
6. `_check_with_retry` retries only a transient (`UNREACHABLE`) result, stops
   at the declared bound, and never retries a non-transient state
7. `run_replacement` retries before falling back to a candidate, accepts the
   first N candidates in the frozen order, rejects a non-disjoint candidate
   before any network call, and reports an honest shortfall rather than
   fabricating an acceptance when the pool runs out
8. `candidates_considered` rows carry only the declared, whitelisted fields
9. the CLI's `--no-receipt` path never calls `write_immutable`
"""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("acquisition", "tools"):
    if str(NS / _sub) not in sys.path:
        sys.path.insert(0, str(NS / _sub))

import preflight_sfi3_roots as pre  # noqa: E402
import replace_sfi3_roots as repl  # noqa: E402
import sources_p4i as p4i  # noqa: E402
import sources_sfi1 as sfi1  # noqa: E402
import sources_sfi2 as sfi2  # noqa: E402
import sources_sfi3 as sfi3  # noqa: E402
import sources_vbc2 as vbc2  # noqa: E402

# ---------------------------------------------------------------------------
# 1 — build_policy is pure, deterministic, and splits correctly
# ---------------------------------------------------------------------------


def test_build_policy_is_pure_and_deterministic() -> None:
    first = repl.build_policy()
    second = repl.build_policy()
    assert first == second
    assert first["policy_digest"] == second["policy_digest"]
    assert first["policy_digest"].startswith("sha256:")


def test_build_policy_never_touches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _should_not_be_called(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("build_policy must never reach the network")

    monkeypatch.setattr(pre.urllib.request, "urlopen", _should_not_be_called)
    policy = repl.build_policy()
    assert policy["frozen_before_any_network_call"] is True


def test_build_policy_splits_the_pinned_receipts_invalid_roots_by_state() -> None:
    """Against the real pinned receipt: trino's TLS timeout is the one
    retry-eligible git root; the other 11 git roots, the one eCFR part and the
    one Wikipedia category are all NOT_FOUND and go straight to
    needs-a-replacement-candidate."""
    policy = repl.build_policy()
    retry = policy["roots_eligible_for_retry"]
    needs = policy["roots_needing_a_replacement_candidate"]

    assert retry[repl.FAMILY_GIT] == ["trinodb/trino"]
    assert retry[repl.FAMILY_ECFR] == []
    assert retry[repl.FAMILY_WIKIPEDIA] == []

    assert len(needs[repl.FAMILY_GIT]) == 11
    assert "trinodb/trino" not in needs[repl.FAMILY_GIT]
    assert needs[repl.FAMILY_ECFR] == ["title-41-part-301"]
    assert needs[repl.FAMILY_WIKIPEDIA] == ["Category:Cities and towns in Hyogo Prefecture"]

    #: every root named is coded either retry or replace, never both, never
    #: neither, for every one of the 14 the pinned receipt found invalid
    all_named = sum((len(v) for v in retry.values()), 0) + sum(
        (len(v) for v in needs.values()), 0
    )
    assert all_named == 14


def test_build_policy_pins_the_exact_source_receipt_it_used() -> None:
    policy = repl.build_policy()
    assert policy["source_preflight_receipt"] == repl.rel(repl.SOURCE_PREFLIGHT_RECEIPT)
    assert policy["source_preflight_receipt_sha256"] == repl.SOURCE_PREFLIGHT_RECEIPT_SHA256


def test_build_policy_declares_permitted_and_forbidden_properties() -> None:
    policy = repl.build_policy()
    joined_permitted = " ".join(policy["permitted_properties"])
    assert "repository exists" in joined_permitted
    assert "disjoint" in joined_permitted
    joined_forbidden = " ".join(policy["forbidden_properties"])
    assert "revision content" in joined_forbidden
    assert "yield" in joined_forbidden


# ---------------------------------------------------------------------------
# 2 — the pinned receipt is hash-verified
# ---------------------------------------------------------------------------


def test_load_source_preflight_raises_if_the_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(repl, "SOURCE_PREFLIGHT_RECEIPT", tmp_path / "does-not-exist.json")
    with pytest.raises(FileNotFoundError):
        repl._load_source_preflight()


def test_load_source_preflight_raises_if_the_file_was_tampered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A copy whose body was edited after being written no longer recomputes
    to its own recorded `receipt_sha256`; this must raise, not silently pass
    the tampered content through as the frozen basis."""
    real = json.loads(repl.SOURCE_PREFLIGHT_RECEIPT.read_text(encoding="utf-8"))
    real["declared_totals"]["git_docs"] = 999  # tamper, receipt_sha256 left stale
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(real), encoding="utf-8")

    monkeypatch.setattr(repl, "SOURCE_PREFLIGHT_RECEIPT", tampered)
    with pytest.raises(ValueError, match="does not match its own recorded hash"):
        repl._load_source_preflight()


def test_load_source_preflight_raises_if_the_pin_no_longer_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real, internally-consistent receipt (self-hash matches its own body)
    that is simply not the one this module is pinned to must still raise."""
    monkeypatch.setattr(repl, "SOURCE_PREFLIGHT_RECEIPT_SHA256", "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match=r"not the.*pinned in this module"):
        repl._load_source_preflight()


# ---------------------------------------------------------------------------
# 3 — freeze happens before any candidate check
# ---------------------------------------------------------------------------


def test_freeze_policy_writes_before_run_replacement_is_ever_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_log: list[str] = []

    def _fake_write_immutable(stem: str, _body: dict[str, Any], **_kw: Any) -> dict[str, str]:
        call_log.append(f"write:{stem}")
        return {"run_id": "fixture", "receipt": f"fixture/{stem}.json"}

    monkeypatch.setattr(repl, "write_immutable", _fake_write_immutable)

    policy, written = repl.freeze_policy()
    assert written is not None
    assert call_log == ["write:sfi3-root-replacement-policy"]

    #: nothing in run_replacement has been reached yet — no _CHECK_FN call
    #: could have happened because run_replacement was never invoked
    assert policy["frozen_before_any_network_call"] is True


def test_freeze_policy_no_receipt_mode_skips_the_write(monkeypatch: pytest.MonkeyPatch) -> None:
    def _should_not_be_called(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("write_immutable must not be called under no_receipt=True")

    monkeypatch.setattr(repl, "write_immutable", _should_not_be_called)
    policy, written = repl.freeze_policy(no_receipt=True)
    assert written is None
    assert policy["policy_digest"]


# ---------------------------------------------------------------------------
# 4 — candidate_order_key
# ---------------------------------------------------------------------------


def test_candidate_order_key_is_deterministic() -> None:
    candidate_id = "acme/docs"
    digest = repl.candidate_order_key(candidate_id)
    assert isinstance(digest, str)
    assert digest == repl.candidate_order_key(candidate_id)


def test_candidate_order_key_salt_is_distinct_from_every_lineage_order_key() -> None:
    assert repl.REPLACEMENT_ORDER_SALT != sfi3.ORDER_SALT
    assert repl.REPLACEMENT_ORDER_SALT != sfi1.ORDER_SALT
    assert repl.REPLACEMENT_ORDER_SALT != sfi2.ORDER_SALT
    candidate_id = "acme/docs"
    assert repl.candidate_order_key(candidate_id) != sfi3.order_key(candidate_id)


# ---------------------------------------------------------------------------
# 5 — the literal candidate pools are disjoint and duplicate-free
# ---------------------------------------------------------------------------


def _accepted_ids() -> set[str]:
    """The replacements the frozen policy actually accepted, from its own receipt."""
    import glob
    import json

    found = sorted(glob.glob(str(NS / "receipts" / "sfi3-root-replacement--*.json")))
    assert found, "no replacement receipt; the pool has not been drawn from"
    body = json.loads(pathlib.Path(found[-1]).read_text(encoding="utf-8"))
    #: keyed by family, each holding a list of accepted candidate ids.
    return {
        str(candidate)
        for accepted in body["accepted_replacements"].values()
        for candidate in accepted
    }


def test_git_candidate_pool_is_disjoint_from_every_SPENT_corpus() -> None:
    """The held-out guarantee. Overlap here would spend the corpus before it is read.

    Note what is NOT asserted: disjointness from `sfi3.GIT_ROOTS`. Accepted
    candidates are PROMOTED INTO those roots, so after a replacement run the pool
    necessarily intersects them — by construction, not by defect. An earlier
    version of this test asserted that disjointness too, and it was correct only
    until the moment the tool it tests did its job.
    """
    pool_keys = {(root["owner"], root["repo"]) for root in repl.GIT_CANDIDATE_ROOTS}
    assert pool_keys
    assert pool_keys.isdisjoint({(r["owner"], r["repo"]) for r in sfi1.GIT_ROOTS})
    assert pool_keys.isdisjoint({(r["owner"], r["repo"]) for r in sfi2.GIT_ROOTS})
    assert pool_keys.isdisjoint({(r["owner"], r["repo"]) for r in vbc2.GIT_ROOTS})
    assert pool_keys.isdisjoint({(r["owner"], r["repo"]) for r in p4i.GIT_REPOSITORIES_ALL})


def test_ecfr_candidate_pool_is_disjoint_from_every_SPENT_corpus() -> None:
    pool_keys = {(title, part) for title, part, _ in repl.ECFR_CANDIDATE_ROOTS}
    assert pool_keys
    assert pool_keys.isdisjoint({(t, p) for t, p, _ in sfi1.ECFR_ROOTS})
    assert pool_keys.isdisjoint({(t, p) for t, p, _ in sfi2.ECFR_ROOTS})
    assert pool_keys.isdisjoint({(t, p) for t, p, _ in vbc2.ECFR_ROOTS})
    assert pool_keys.isdisjoint({(t, p) for t, p, _ in p4i.ECFR_PARTS_ALL})


def test_wikipedia_candidate_pool_is_disjoint_from_every_SPENT_corpus() -> None:
    pool = set(repl.WIKIPEDIA_CANDIDATE_ROOTS)
    assert pool
    assert pool.isdisjoint(set(sfi1.WIKIPEDIA_CATEGORY_ROOTS))
    assert pool.isdisjoint(set(sfi2.WIKIPEDIA_CATEGORY_ROOTS))
    assert pool.isdisjoint(set(vbc2.WIKIPEDIA_CATEGORY_ROOTS))


def test_the_only_pool_entries_now_in_the_sfi3_frame_are_the_accepted_replacements() -> None:
    """The stronger form of what the old disjointness assertion was reaching for.

    A pool entry may appear in the SFI3 frame only if the frozen policy accepted
    it and said so in the receipt. Anything else in the intersection would be a
    root that entered the frame without passing the criterion — which is the
    actual risk the old test was gesturing at, and it could not have caught it.
    """
    accepted = _accepted_ids()
    pool_ids = {f"{r['owner']}/{r['repo']}" for r in repl.GIT_CANDIDATE_ROOTS}
    in_frame = pool_ids & {f"{r['owner']}/{r['repo']}" for r in sfi3.GIT_ROOTS}
    assert in_frame <= accepted, sorted(in_frame - accepted)


def test_no_candidate_pool_has_an_internal_duplicate() -> None:
    git_keys = [(r["owner"], r["repo"]) for r in repl.GIT_CANDIDATE_ROOTS]
    ecfr_keys = [(t, p) for t, p, _ in repl.ECFR_CANDIDATE_ROOTS]
    assert len(git_keys) == len(set(git_keys))
    assert len(ecfr_keys) == len(set(ecfr_keys))
    assert len(repl.WIKIPEDIA_CANDIDATE_ROOTS) == len(set(repl.WIKIPEDIA_CANDIDATE_ROOTS))


def test_candidate_pools_are_generous_relative_to_the_known_shortfall() -> None:
    """Sized before any candidate is checked: at least the shortfall, with
    headroom, so an honest shortfall report is possible instead of a pool
    that can only ever exactly succeed or come up short by construction."""
    policy = repl.build_policy()
    for family, pool in (
        (repl.FAMILY_GIT, repl.GIT_CANDIDATE_ROOTS),
        (repl.FAMILY_ECFR, repl.ECFR_CANDIDATE_ROOTS),
        (repl.FAMILY_WIKIPEDIA, repl.WIKIPEDIA_CANDIDATE_ROOTS),
    ):
        needed = len(policy["roots_needing_a_replacement_candidate"][family])
        assert len(pool) >= needed


# ---------------------------------------------------------------------------
# 6 — the bounded transient retry wrapper
# ---------------------------------------------------------------------------


def _record(state: str, reason: str = "x") -> dict[str, Any]:
    return {"state": state, "reason": reason}


def test_check_with_retry_stops_at_the_first_non_transient_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = [
        _record(pre.STATE_UNREACHABLE),
        _record(pre.STATE_UNREACHABLE),
        _record(pre.STATE_VALID),
    ]
    calls = {"count": 0}

    def _fake_check(_candidate: Any) -> dict[str, Any]:
        record = outcomes[calls["count"]]
        calls["count"] += 1
        return record

    sleeps: list[float] = []
    monkeypatch.setattr(repl.time, "sleep", lambda seconds: sleeps.append(seconds))

    record, attempts = repl._check_with_retry(_fake_check, "candidate")
    assert record["state"] == pre.STATE_VALID
    assert len(attempts) == 3
    assert [a["state"] for a in attempts] == [
        pre.STATE_UNREACHABLE,
        pre.STATE_UNREACHABLE,
        pre.STATE_VALID,
    ]
    assert sleeps == [
        repl.RETRY_POLICY["backoff_seconds"][0],
        repl.RETRY_POLICY["backoff_seconds"][1],
    ]


def test_check_with_retry_gives_up_after_the_declared_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def _always_unreachable(_candidate: Any) -> dict[str, Any]:
        calls["count"] += 1
        return _record(pre.STATE_UNREACHABLE)

    monkeypatch.setattr(repl.time, "sleep", lambda *_a, **_k: None)
    record, attempts = repl._check_with_retry(_always_unreachable, "candidate")
    assert record["state"] == pre.STATE_UNREACHABLE
    assert calls["count"] == repl.RETRY_POLICY["max_attempts"]
    assert len(attempts) == repl.RETRY_POLICY["max_attempts"]


def test_check_with_retry_never_retries_a_non_transient_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def _not_found(_candidate: Any) -> dict[str, Any]:
        calls["count"] += 1
        return _record(pre.STATE_NOT_FOUND)

    def _should_not_sleep(*_a: Any, **_k: Any) -> None:
        raise AssertionError("no backoff for a non-transient state")

    monkeypatch.setattr(repl.time, "sleep", _should_not_sleep)
    record, attempts = repl._check_with_retry(_not_found, "candidate")
    assert record["state"] == pre.STATE_NOT_FOUND
    assert calls["count"] == 1
    assert len(attempts) == 1


# ---------------------------------------------------------------------------
# 7 — run_replacement, fully mocked (no real network anywhere in this file)
# ---------------------------------------------------------------------------


def _synthetic_policy(**overrides: Any) -> dict[str, Any]:
    base = {
        "policy_digest": "sha256:fixture",
        "declared_totals": {repl.FAMILY_GIT: 3, repl.FAMILY_ECFR: 1, repl.FAMILY_WIKIPEDIA: 1},
        "roots_eligible_for_retry": {
            repl.FAMILY_GIT: [],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
        "roots_needing_a_replacement_candidate": {
            repl.FAMILY_GIT: [],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
    }
    base.update(overrides)
    return base


def test_run_replacement_retries_before_falling_back_to_a_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _synthetic_policy(
        roots_eligible_for_retry={
            repl.FAMILY_GIT: ["fixture/retriable"],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
    )
    monkeypatch.setattr(
        repl, "_declared_root_lookup",
        lambda: {"fixture/retriable": (repl.FAMILY_GIT, {"owner": "fixture", "repo": "retriable"})},
    )

    def _recovers(_root: Any) -> dict[str, Any]:
        return _record(pre.STATE_VALID)

    def _should_not_be_called(_candidate: Any) -> dict[str, Any]:
        raise AssertionError("no candidate pool should be consulted; the retry already covered it")

    monkeypatch.setattr(repl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setitem(repl._CHECK_FN, repl.FAMILY_GIT, _recovers)
    monkeypatch.setitem(repl._CANDIDATE_POOL, repl.FAMILY_GIT, ())

    result = repl.run_replacement(policy)
    assert result["recovered_via_retry"][repl.FAMILY_GIT] == ["fixture/retriable"]
    assert result["shortfall_before_replacement"][repl.FAMILY_GIT] == 0
    assert result["accepted_replacements"][repl.FAMILY_GIT] == []
    assert result["fully_recovered"] is True


def test_run_replacement_accepts_the_first_n_candidates_in_frozen_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = (
        {"owner": "fixture", "repo": "a", "prefix": "docs/", "license": "MIT"},
        {"owner": "fixture", "repo": "b", "prefix": "docs/", "license": "MIT"},
        {"owner": "fixture", "repo": "c", "prefix": "docs/", "license": "MIT"},
    )
    #: the frozen order for these three ids, computed the same way
    #: run_replacement computes it — not asserted against a hardcoded guess
    def _cid(root: dict[str, str]) -> str:
        return f"{root['owner']}/{root['repo']}"

    expected_order = sorted(pool, key=lambda r: repl.candidate_order_key(_cid(r)))
    expected_ids = [_cid(r) for r in expected_order]

    policy = _synthetic_policy(
        roots_needing_a_replacement_candidate={
            repl.FAMILY_GIT: ["fixture/old-1", "fixture/old-2"],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
    )
    monkeypatch.setattr(repl, "_declared_root_lookup", lambda: {})
    monkeypatch.setattr(repl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setitem(repl._CHECK_FN, repl.FAMILY_GIT, lambda _r: _record(pre.STATE_VALID))
    monkeypatch.setitem(repl._CANDIDATE_POOL, repl.FAMILY_GIT, pool)
    monkeypatch.setitem(repl._ALREADY_DECLARED, repl.FAMILY_GIT, lambda: set())

    result = repl.run_replacement(policy)
    assert result["accepted_replacements"][repl.FAMILY_GIT] == expected_ids[:2]
    assert result["shortfall_after_replacement"][repl.FAMILY_GIT] == 0
    #: the third candidate was never needed, so it was never considered
    considered_ids = {
        row["candidate_id"]
        for row in result["candidates_considered"]
        if row["family"] == repl.FAMILY_GIT
    }
    assert considered_ids == set(expected_ids[:2])


def test_run_replacement_rejects_a_non_disjoint_candidate_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ({"owner": "fixture", "repo": "already-used", "prefix": "docs/", "license": "MIT"},)
    policy = _synthetic_policy(
        roots_needing_a_replacement_candidate={
            repl.FAMILY_GIT: ["fixture/old-1"],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
    )
    monkeypatch.setattr(repl, "_declared_root_lookup", lambda: {})

    def _should_not_be_called(_r: Any) -> dict[str, Any]:
        raise AssertionError("a non-disjoint candidate must be rejected before any network call")

    monkeypatch.setitem(repl._CHECK_FN, repl.FAMILY_GIT, _should_not_be_called)
    monkeypatch.setitem(repl._CANDIDATE_POOL, repl.FAMILY_GIT, pool)
    monkeypatch.setitem(
        repl._ALREADY_DECLARED, repl.FAMILY_GIT, lambda: {("fixture", "already-used")}
    )

    result = repl.run_replacement(policy)
    rows = [row for row in result["candidates_considered"] if row["family"] == repl.FAMILY_GIT]
    assert len(rows) == 1
    assert rows[0]["state"] == "REJECTED_NOT_DISJOINT"
    assert rows[0]["accepted"] is False
    assert rows[0]["attempts"] == []
    assert result["shortfall_after_replacement"][repl.FAMILY_GIT] == 1
    assert result["fully_recovered"] is False


def test_run_replacement_reports_an_honest_shortfall_when_the_pool_runs_dry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ({"owner": "fixture", "repo": "only-one", "prefix": "docs/", "license": "MIT"},)
    policy = _synthetic_policy(
        roots_needing_a_replacement_candidate={
            repl.FAMILY_GIT: ["fixture/old-1", "fixture/old-2"],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
    )
    monkeypatch.setattr(repl, "_declared_root_lookup", lambda: {})
    monkeypatch.setattr(repl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setitem(repl._CHECK_FN, repl.FAMILY_GIT, lambda _r: _record(pre.STATE_VALID))
    monkeypatch.setitem(repl._CANDIDATE_POOL, repl.FAMILY_GIT, pool)
    monkeypatch.setitem(repl._ALREADY_DECLARED, repl.FAMILY_GIT, lambda: set())

    result = repl.run_replacement(policy)
    assert len(result["accepted_replacements"][repl.FAMILY_GIT]) == 1
    assert result["shortfall_after_replacement"][repl.FAMILY_GIT] == 1
    assert result["fully_recovered"] is False
    assert (
        result["valid_root_count_per_family"][repl.FAMILY_GIT]
        == policy["declared_totals"][repl.FAMILY_GIT] - 1
    )


def test_run_replacement_never_fabricates_an_acceptance_for_a_failing_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ({"owner": "fixture", "repo": "fails", "prefix": "docs/", "license": "MIT"},)
    policy = _synthetic_policy(
        roots_needing_a_replacement_candidate={
            repl.FAMILY_GIT: ["fixture/old-1"],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
    )
    monkeypatch.setattr(repl, "_declared_root_lookup", lambda: {})
    monkeypatch.setattr(repl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setitem(
        repl._CHECK_FN, repl.FAMILY_GIT, lambda _r: _record(pre.STATE_NOT_FOUND, "still gone")
    )
    monkeypatch.setitem(repl._CANDIDATE_POOL, repl.FAMILY_GIT, pool)
    monkeypatch.setitem(repl._ALREADY_DECLARED, repl.FAMILY_GIT, lambda: set())

    result = repl.run_replacement(policy)
    assert result["accepted_replacements"][repl.FAMILY_GIT] == []
    row = next(r for r in result["candidates_considered"] if r["family"] == repl.FAMILY_GIT)
    assert row["accepted"] is False
    assert row["state"] == pre.STATE_NOT_FOUND


# ---------------------------------------------------------------------------
# 8 — candidates_considered rows carry only whitelisted fields
# ---------------------------------------------------------------------------


def test_candidates_considered_rows_carry_only_declared_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ({"owner": "fixture", "repo": "x", "prefix": "docs/", "license": "MIT"},)
    policy = _synthetic_policy(
        roots_needing_a_replacement_candidate={
            repl.FAMILY_GIT: ["fixture/old-1"],
            repl.FAMILY_ECFR: [],
            repl.FAMILY_WIKIPEDIA: [],
        },
    )
    monkeypatch.setattr(repl, "_declared_root_lookup", lambda: {})
    monkeypatch.setattr(repl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setitem(repl._CHECK_FN, repl.FAMILY_GIT, lambda _r: _record(pre.STATE_VALID))
    monkeypatch.setitem(repl._CANDIDATE_POOL, repl.FAMILY_GIT, pool)
    monkeypatch.setitem(repl._ALREADY_DECLARED, repl.FAMILY_GIT, lambda: set())

    result = repl.run_replacement(policy)
    row = result["candidates_considered"][0]
    assert set(row) == {"family", "candidate_id", "state", "reason", "accepted", "attempts"}


# ---------------------------------------------------------------------------
# 9 — CLI
# ---------------------------------------------------------------------------


def test_cli_no_receipt_never_calls_write_immutable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _should_not_be_called(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("write_immutable must not run under --no-receipt")

    monkeypatch.setattr(repl, "write_immutable", _should_not_be_called)
    for family in repl.FAMILY_QUOTA_FAMILIES:
        monkeypatch.setitem(repl._CANDIDATE_POOL, family, ())

    exit_code = repl.main(["--no-receipt"])
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert "policy" in printed and "result" in printed


def test_main_writes_the_policy_receipt_strictly_before_the_result_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    call_order: list[str] = []

    def _fake_write_immutable(stem: str, _body: dict[str, Any], **_kw: Any) -> dict[str, str]:
        call_order.append(stem)
        return {"run_id": "fixture", "receipt": f"fixture/{stem}.json"}

    monkeypatch.setattr(repl, "write_immutable", _fake_write_immutable)
    for family in repl.FAMILY_QUOTA_FAMILIES:
        monkeypatch.setitem(repl._CANDIDATE_POOL, family, ())

    exit_code = repl.main([])
    assert exit_code == 0
    assert call_order == ["sfi3-root-replacement-policy", "sfi3-root-replacement"]
    printed = json.loads(capsys.readouterr().out)
    assert printed["policy_receipt"]["receipt"] == "fixture/sfi3-root-replacement-policy.json"
