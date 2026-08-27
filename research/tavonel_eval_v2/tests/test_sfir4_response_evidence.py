"""Controls for SFIR4's observed-response evidence ledger."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for extra in (NS, NS / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import sfir4_response_evidence as ev  # noqa: E402

URL = "https://api.github.com/repos/octo/docs/git/trees/" + "a" * 40


def observed(ledger: ev.ResponseLedger, raw: bytes, *, root: str = "git:octo/docs", url: str = URL):
    return ledger.record(
        family="git_docs",
        root_id=root,
        purpose="tree",
        url=url,
        status=200,
        content_digest=ev.digest_bytes(raw),
        observed_length=len(raw),
        declared_length=len(raw),
        observed_bytes=True,
    )


# ---------------------------------------------------------------------------
# The digest is over bytes, not over a re-serialised parse
# ---------------------------------------------------------------------------


def test_the_digest_is_over_the_bytes_that_arrived() -> None:
    raw = b'{"sha":"abc","tree":[]}'
    ledger = ev.ResponseLedger()
    row = observed(ledger, raw)
    assert row.content_digest == ev.digest_bytes(raw)
    assert row.observed_length == len(raw)


def test_two_encodings_of_one_object_have_different_digests() -> None:
    """Why re-serialising the parse was never a measurement of the response."""
    a = b'{"sha":"abc","tree":[]}'
    b = b'{ "tree": [], "sha": "abc" }'
    assert ev.digest_bytes(a) != ev.digest_bytes(b)
    assert len(a) != len(b)


def test_a_declared_length_that_disagrees_with_the_observed_one_refuses() -> None:
    ledger = ev.ResponseLedger()
    with pytest.raises(ev.ResponseEvidenceRefused, match="lengths disagree"):
        ledger.record(
            family="git_docs",
            root_id="r",
            purpose="tree",
            url=URL,
            status=200,
            content_digest=ev.digest_bytes(b"xy"),
            observed_length=2,
            declared_length=99,
            observed_bytes=True,
        )


def test_a_negative_observed_length_refuses() -> None:
    ledger = ev.ResponseLedger()
    with pytest.raises(ev.ResponseEvidenceRefused, match="negative"):
        ledger.record(
            family="git_docs",
            root_id="r",
            purpose="tree",
            url=URL,
            status=200,
            content_digest=ev.digest_bytes(b""),
            observed_length=-1,
            declared_length=None,
            observed_bytes=True,
        )


# ---------------------------------------------------------------------------
# Synthesised observations cannot pose as observed ones
# ---------------------------------------------------------------------------


def test_a_synthesised_observation_is_marked_and_refuses_the_live_gate() -> None:
    ledger = ev.ResponseLedger()
    ledger.record(
        family="git_docs",
        root_id="r",
        purpose="tree",
        url=URL,
        status=200,
        content_digest=ev.digest_parsed({"tree": []}),
        observed_length=0,
        declared_length=None,
        observed_bytes=False,
    )
    with pytest.raises(ev.ResponseEvidenceRefused, match="synthesised, not observed"):
        ledger.require_all_observed()


def test_a_synthesised_digest_cannot_be_filed_as_observed() -> None:
    ledger = ev.ResponseLedger()
    with pytest.raises(ev.ResponseEvidenceRefused, match="synthesised digest"):
        ledger.record(
            family="git_docs",
            root_id="r",
            purpose="tree",
            url=URL,
            status=200,
            content_digest=ev.digest_parsed({"tree": []}),
            observed_length=0,
            declared_length=None,
            observed_bytes=True,
        )


def test_an_observed_digest_cannot_be_filed_as_synthesised() -> None:
    ledger = ev.ResponseLedger()
    with pytest.raises(ev.ResponseEvidenceRefused, match="claims an observed digest"):
        ledger.record(
            family="git_docs",
            root_id="r",
            purpose="tree",
            url=URL,
            status=200,
            content_digest=ev.digest_bytes(b"x"),
            observed_length=1,
            declared_length=None,
            observed_bytes=False,
        )


def test_an_all_observed_ledger_passes_the_live_gate() -> None:
    ledger = ev.ResponseLedger()
    observed(ledger, b"one")
    observed(ledger, b"two")
    ledger.require_all_observed()


# ---------------------------------------------------------------------------
# Credentials never reach an artifact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pw@api.github.com/repos/o/d",
        "https://api.github.com/repos/o/d?access_token=abc",
        "https://api.github.com/repos/o/d?token=abc",
        "https://api.github.com/repos/o/d?KEY=abc",
        "https://api.github.com/repos/o/d?x=ghp_aaaaaaaaaaaaaaaaaaaa",
    ],
)
def test_a_url_that_could_carry_a_secret_refuses(url: str) -> None:
    with pytest.raises(ev.ResponseEvidenceRefused):
        ev.assert_credential_free(url)


def test_the_ordinary_api_url_is_accepted() -> None:
    ev.assert_credential_free(URL)


def test_no_recorded_field_is_a_header() -> None:
    ledger = ev.ResponseLedger()
    observed(ledger, b"x")
    fields = set(ledger.proof()["observations"][0])
    assert "headers" not in fields
    assert not any("author" in name.casefold() for name in fields)


# ---------------------------------------------------------------------------
# The chain binds order
# ---------------------------------------------------------------------------


def test_the_head_moves_on_every_append() -> None:
    ledger = ev.ResponseLedger()
    seen = {ledger.head}
    for payload in (b"a", b"b", b"c"):
        observed(ledger, payload)
        seen.add(ledger.head)
    assert len(seen) == 4


def test_the_chain_verifies_over_its_own_proof() -> None:
    ledger = ev.ResponseLedger()
    for payload in (b"a", b"b", b"c"):
        observed(ledger, payload)
    assert ev.verify_chain(ledger.proof())


def test_reordering_two_observations_breaks_the_chain() -> None:
    ledger = ev.ResponseLedger()
    for payload in (b"a", b"b", b"c"):
        observed(ledger, payload)
    proof = copy.deepcopy(ledger.proof())
    proof["observations"][0], proof["observations"][1] = (
        proof["observations"][1],
        proof["observations"][0],
    )
    assert not ev.verify_chain(proof)


def test_dropping_an_observation_breaks_the_chain() -> None:
    ledger = ev.ResponseLedger()
    for payload in (b"a", b"b", b"c"):
        observed(ledger, payload)
    proof = copy.deepcopy(ledger.proof())
    del proof["observations"][1]
    assert not ev.verify_chain(proof)


def test_editing_a_digest_breaks_the_chain() -> None:
    ledger = ev.ResponseLedger()
    observed(ledger, b"a")
    proof = copy.deepcopy(ledger.proof())
    proof["observations"][0]["content_digest"] = ev.digest_bytes(b"tampered")
    assert not ev.verify_chain(proof)


def test_appending_a_forged_observation_breaks_the_chain() -> None:
    ledger = ev.ResponseLedger()
    observed(ledger, b"a")
    proof = copy.deepcopy(ledger.proof())
    forged = dict(proof["observations"][0])
    forged["sequence"] = 1
    proof["observations"].append(forged)
    assert not ev.verify_chain(proof)


# ---------------------------------------------------------------------------
# Arithmetic reconciles
# ---------------------------------------------------------------------------


def test_per_root_request_counts_sum_to_the_global_count() -> None:
    ledger = ev.ResponseLedger()
    observed(ledger, b"a", root="git:one")
    observed(ledger, b"b", root="git:one")
    observed(ledger, b"c", root="git:two")
    proof = ledger.proof()
    assert proof["global"]["requests"] == 3
    assert proof["per_root_requests_sum"] == 3
    assert proof["per_root"]["git:one"]["requests"] == 2
    assert proof["per_root"]["git:two"]["requests"] == 1


def test_each_root_records_its_own_sequence_window() -> None:
    ledger = ev.ResponseLedger()
    observed(ledger, b"a", root="git:one")
    observed(ledger, b"b", root="git:two")
    observed(ledger, b"c", root="git:one")
    proof = ledger.proof()
    assert proof["per_root"]["git:one"]["first_sequence"] == 0
    assert proof["per_root"]["git:one"]["last_sequence"] == 2
    assert proof["per_root"]["git:two"]["first_sequence"] == 1


def test_repeated_identical_responses_are_visible_as_repeated() -> None:
    """A root that returned the same bytes twice is a fact worth seeing."""
    ledger = ev.ResponseLedger()
    observed(ledger, b"same")
    observed(ledger, b"same")
    row = ledger.proof()["per_root"]["git:octo/docs"]
    assert row["requests"] == 2
    assert row["distinct_response_digests"] == 1


def test_the_sequence_is_dense() -> None:
    ledger = ev.ResponseLedger()
    for payload in (b"a", b"b"):
        observed(ledger, payload)
    assert ledger.proof()["global"]["sequence_is_dense"] is True


def test_an_empty_ledger_states_an_empty_proof() -> None:
    proof = ev.ResponseLedger().proof()
    assert proof["global"]["requests"] == 0
    assert proof["per_root"] == {}
    assert ev.verify_chain(proof)


# ---------------------------------------------------------------------------
# The pre-freeze audit finding: verify_chain covers only `observations`
# ---------------------------------------------------------------------------


def _observed_ledger(count: int = 2) -> ev.ResponseLedger:
    ledger = ev.ResponseLedger()
    for index in range(count):
        payload = f"body-{index}".encode()
        ledger.record(
            family="git_docs",
            root_id=f"root-{index % 2}",
            purpose="tree",
            url=f"https://api.github.com/repos/x/y/git/trees/{index}",
            status=200,
            content_digest=ev.digest_bytes(payload),
            observed_length=len(payload),
            declared_length=len(payload),
            observed_bytes=True,
        )
    return ledger


def test_an_honestly_produced_proof_is_accepted() -> None:
    """Without this, every refusal below could be satisfied by refusing always."""
    recomputed = ev.require_observed_census(_observed_ledger().proof())
    assert recomputed["global"]["requests"] == 2
    assert recomputed["global"]["all_observed"] is True


def test_a_zero_observation_census_with_fabricated_aggregates_is_refused() -> None:
    """The exact block a pre-freeze audit used to certify a census of nothing.

    The head of an empty chain is ``sha256(CHAIN_SEED)`` -- a public, unkeyed
    constant anyone can compute -- so ``verify_chain`` returns True on it. The
    aggregates beside it were then believed. This asserts both halves: that the
    chain really does verify, so the test is about the gap and not about a
    malformed document, and that the census is refused anyway.
    """
    forged = {
        "schema": ev.SCHEMA,
        "chain_seed": ev.CHAIN_SEED.decode("ascii"),
        "chain_head": "sha256:" + hashlib.sha256(ev.CHAIN_SEED).hexdigest(),
        "global": {
            "requests": 1000,
            "roots": 20,
            "observed_bytes_total": 999999,
            "responses": 1000,
            "failures": 0,
            "all_observed": True,
            "sequence_is_dense": True,
        },
        "per_root": {},
        "per_root_requests_sum": 1000,
        "observations": [],
    }
    assert ev.verify_chain(dict(forged)) is True
    with pytest.raises(ev.ResponseEvidenceRefused, match="records no observations"):
        ev.require_observed_census(forged)


def test_an_edited_aggregate_is_refused_even_though_the_chain_still_verifies() -> None:
    proof = _observed_ledger().proof()
    proof["global"]["requests"] = 500
    assert ev.verify_chain(dict(proof)) is True
    with pytest.raises(ev.ResponseEvidenceRefused, match="does not match the observations"):
        ev.require_observed_census(proof)


def test_an_edited_per_root_block_is_refused() -> None:
    proof = _observed_ledger().proof()
    first = next(iter(proof["per_root"]))
    proof["per_root"][first]["observed_bytes_total"] += 1
    with pytest.raises(ev.ResponseEvidenceRefused, match="does not match the observations"):
        ev.require_observed_census(proof)


def test_a_synthesised_census_is_refused_on_its_own_arithmetic() -> None:
    """Self-consistent, nothing edited -- and still not a live census."""
    ledger = ev.ResponseLedger()
    ledger.record(
        family="git_docs",
        root_id="root-0",
        purpose="tree",
        url="https://api.github.com/repos/x/y/git/trees/0",
        status=200,
        content_digest=ev.digest_parsed({"injected": True}),
        observed_length=0,
        declared_length=None,
        observed_bytes=False,
    )
    with pytest.raises(ev.ResponseEvidenceRefused, match="synthesised"):
        ev.require_observed_census(ledger.proof())


def test_flipping_the_observed_flag_leaves_the_digest_prefix_behind() -> None:
    """The two signals are checked independently, on purpose.

    A forger who rewrites ``observed_bytes`` AND every aggregate to match, and
    rebuilds the chain over the edited rows, still leaves ``synthesized-sha256:``
    in the digest. One signal alone would make this forgery succeed.
    """
    ledger = ev.ResponseLedger()
    ledger.record(
        family="git_docs",
        root_id="root-0",
        purpose="tree",
        url="https://api.github.com/repos/x/y/git/trees/0",
        status=200,
        content_digest=ev.digest_parsed({"injected": True}),
        observed_length=0,
        declared_length=None,
        observed_bytes=False,
    )
    proof = ledger.proof()
    for row in proof["observations"]:
        row["observed_bytes"] = True
    proof.update(ev.recompute_proof_arithmetic(proof))
    head = "sha256:" + hashlib.sha256(ev.CHAIN_SEED).hexdigest()
    for row in proof["observations"]:
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
        head = (
            "sha256:"
            + hashlib.sha256(head.encode("ascii") + b"\0" + canonical.encode("utf-8")).hexdigest()
        )
    proof["chain_head"] = head

    assert ev.verify_chain(dict(proof)) is True, "the forgery must be chain-valid"
    with pytest.raises(ev.ResponseEvidenceRefused, match="synthesised"):
        ev.require_observed_census(proof)


def test_a_reordered_chain_is_still_refused() -> None:
    proof = _observed_ledger(3).proof()
    proof["observations"][0], proof["observations"][1] = (
        proof["observations"][1],
        proof["observations"][0],
    )
    with pytest.raises(ev.ResponseEvidenceRefused, match="chain does not recompute"):
        ev.require_observed_census(proof)
