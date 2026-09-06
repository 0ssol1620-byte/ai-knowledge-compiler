"""What SFIR5 does when the endpoint pushes back, and when it runs out of budget.

SFIR4 died in this code path. The retry loop is the part of the instrument that
decides whether a census ends with a result, a refusal, or a receipt describing a
run that did not happen, so each of its three exits gets a control:

- the server asks us to wait, and we wait the server's number;
- the server keeps asking, and the frozen budget ends the run rather than being
  quietly enlarged;
- the run ends without a result, and nothing is written.

The last is the one that keeps the study result-blind. A census that aborts must
leave no capacity quantity anywhere -- not a partial receipt, not a printed
number -- because the moment a quantity exists, the decision to re-run becomes a
decision made after seeing it.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import probe_sfir4_capacity as probe4  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
import sfir4_spent_authority as spent_builder  # noqa: E402
import sfir5_transport as t5  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

STAMP = "2026-08-27T00:00:00Z"


def _isolated(tmp_path: Path) -> tuple[Path, dict[str, str], dict[str, str]]:
    """A charter and spent authority in a throwaway tree.

    `probe_capacity` refuses to start unless the probe's own bytes match the
    charter's pin, so a control cannot skip the charter and still be exercising
    the real entry point.
    """
    for relative in (
        "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4_DESIGN_CHARTER.yaml",
        "acquisition/sources_sfir4.py",
        "acquisition/sources_sfir3.py",
        "tools/probe_sfir4_capacity.py",
        "tools/probe_sfir3_capacity.py",
        "tools/sfir4_spent_authority.py",
        "tools/sfir4_protocol.py",
        "receipts/sfir3-spent-identity-authority.json",
        "receipts/sfir3-design-charter-freeze.json",
        "receipts/sfir3-capacity-failure-authority.json",
    ):
        target = tmp_path / "research/tavonel_eval_v2" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(NS / relative, target)
    base = tmp_path / "research/tavonel_eval_v2"
    charter = base / "receipts/charter.json"
    protocol.freeze_design_charter(
        tmp_path,
        base / "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4_DESIGN_CHARTER.yaml",
        base / "tools/sfir4_protocol.py",
        base / "acquisition/sources_sfir4.py",
        base / "tools/probe_sfir4_capacity.py",
        base / "tools/sfir4_spent_authority.py",
        base / "acquisition/sources_sfir3.py",
        base / "tools/probe_sfir3_capacity.py",
        charter,
        STAMP,
    )
    spent = base / "receipts/sfir4-spent.json"
    spent_builder.compose_spent_authority(
        tmp_path,
        protocol.exact_ref(tmp_path, base / "receipts/sfir3-spent-identity-authority.json"),
        protocol.exact_ref(tmp_path, base / "receipts/sfir3-design-charter-freeze.json"),
        protocol.exact_ref(tmp_path, base / "receipts/sfir3-capacity-failure-authority.json"),
        spent,
        STAMP,
    )
    return tmp_path, protocol.exact_ref(tmp_path, charter), protocol.exact_ref(tmp_path, spent)


class ThrottlingTransport:
    """Answers `throttles` times with a 429 and `interruptions` times with a
    dropped connection, then completes the root with zero candidates.

    The two kinds are separate on purpose. `rate_limit_retries` is derived as
    `retries - transport_retries`, so a stub that only ever throttles makes that
    subtraction compare a number to itself: the arithmetic control passes, and
    would go on passing if the two counts were merged. Producing both is what
    gives the check two independent sides. Zero candidates throughout, because
    these controls are about the retry loop and a candidate count would make
    them depend on data they are not testing.
    """

    def __init__(self, *, throttles: int, retry_after: int = 3, interruptions: int = 0):
        self.throttles = throttles
        self.interruptions = interruptions
        self.retry_after = retry_after
        self.seen: list[str] = []
        self.remaining = dict.fromkeys(sources.FAMILIES, throttles)
        self.remaining_interruptions = dict.fromkeys(sources.FAMILIES, interruptions)

    def __call__(self, family: str, request: dict[str, Any]) -> dict[str, Any]:
        self.seen.append(family)
        root = str(request["expected_discovery_root_id"])
        if self.remaining_interruptions[family] > 0:
            self.remaining_interruptions[family] -= 1
            return {
                "items": [],
                "rate_limited": False,
                "transport_interrupted": True,
                "retry_after_seconds": sources.RETRYABLE_HTTP_BACKOFF_SECONDS,
                "snapshot_id": "interrupted",
                "response_refs": ["https://example.invalid/interrupted"],
            }
        if self.remaining[family] > 0:
            self.remaining[family] -= 1
            return {
                "items": [],
                "rate_limited": True,
                "retry_after_seconds": self.retry_after,
                "snapshot_id": "throttled",
                "response_refs": ["https://example.invalid/throttled"],
            }
        return {
            "items": [],
            "next_cursor": None,
            "snapshot_id": f"stub:{root}",
            "response_refs": [f"https://example.invalid/{root}"],
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": root,
                "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
                "reason": "STUB",
            },
        }


@pytest.fixture
def slept(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(probe4.time, "sleep", waits.append)
    return waits


# --- the server's number, not ours ------------------------------------------


def test_the_wait_is_the_servers_retry_after_not_our_pacing_interval(tmp_path, slept):
    """`Retry-After` outranks local pacing, per the ruling. A transport that
    substituted its own interval would be overriding the endpoint's own
    statement about when it is willing to be asked again."""
    root, charter, spent = _isolated(tmp_path)
    probe4.probe_capacity(
        root,
        charter,
        spent,
        tmp_path / "census.json",
        ThrottlingTransport(throttles=1, retry_after=9),
    )
    assert slept and set(slept) == {9}
    assert 9 not in set(t5.HOST_MIN_INTERVAL_SECONDS.values())


def test_a_retry_after_above_the_frozen_ceiling_refuses_rather_than_sleeping(tmp_path, slept):
    """A server can name any number. The fail-safe is that we do not honour an
    arbitrary one -- an endpoint asking for an hour ends the census instead."""
    root, charter, spent = _isolated(tmp_path)
    with pytest.raises(protocol.SFIR4Refused, match="frozen fail-safe"):
        probe4.probe_capacity(
            root,
            charter,
            spent,
            tmp_path / "census.json",
            ThrottlingTransport(throttles=1, retry_after=sources.MAX_RATE_LIMIT_WAIT_SECONDS + 1),
        )
    assert slept == []


# --- the arithmetic of the budget -------------------------------------------


def test_retries_within_budget_complete_and_the_arithmetic_reconciles(tmp_path, slept):
    """Both retry kinds in one run, and each reported as its own figure.

    A census that silently retried a hundred dropped connections is a different
    observation from one that was throttled a hundred times, and a single total
    cannot tell a reader which happened. So the assertion is not only that the
    parts sum to the total -- it is that neither part equals the total, which is
    what would be true if the two were being conflated."""
    root, charter, spent = _isolated(tmp_path)
    written = probe4.probe_capacity(
        root,
        charter,
        spent,
        tmp_path / "census.json",
        ThrottlingTransport(throttles=3, interruptions=2),
    )
    body = json.loads(written.read_text(encoding="utf-8"))
    for family in sources.FAMILIES:
        pagination = body["families"][family]["pagination"]
        assert pagination["rate_limit_retries"] == 3
        assert pagination["transport_retries"] == 2
        assert pagination["retries_total"] == 5
        assert (
            pagination["retries_total"]
            == pagination["rate_limit_retries"] + pagination["transport_retries"]
        )
        assert pagination["rate_limit_wait_seconds"] == (
            3 * 3 + 2 * sources.RETRYABLE_HTTP_BACKOFF_SECONDS
        )


def test_a_dropped_connection_and_a_throttle_exhaust_one_shared_budget(tmp_path, slept):
    """They are counted separately and bounded together. Three throttles plus
    three drops is six retries against a budget of five, and a census that let
    each kind have its own five would run twice as long as the frozen bound."""
    root, charter, spent = _isolated(tmp_path)
    with pytest.raises(protocol.SFIR4Refused, match="retry budget exhausted"):
        probe4.probe_capacity(
            root,
            charter,
            spent,
            tmp_path / "census.json",
            ThrottlingTransport(throttles=3, interruptions=3),
        )


def test_one_retry_past_the_budget_ends_the_census(tmp_path, slept):
    """The exact boundary, because an off-by-one here is the difference between
    a bound that stops a runaway and a bound that stops a working census."""
    root, charter, spent = _isolated(tmp_path)
    over = sources.PAGINATION_CONTRACT["maximum_retries_per_request"] + 1
    with pytest.raises(protocol.SFIR4Refused, match="retry budget exhausted"):
        probe4.probe_capacity(
            root, charter, spent, tmp_path / "census.json", ThrottlingTransport(throttles=over)
        )


def test_the_total_wait_ceiling_ends_the_census_even_within_the_retry_count(tmp_path, slept):
    """Two independent bounds, and this is the one SFIR4 actually hit: five
    retries is permitted, five waits of 55 seconds is not."""
    root, charter, spent = _isolated(tmp_path)
    with pytest.raises(protocol.SFIR4Refused, match="frozen fail-safe"):
        probe4.probe_capacity(
            root,
            charter,
            spent,
            tmp_path / "census.json",
            ThrottlingTransport(throttles=5, retry_after=55),
        )


# --- nothing is written when nothing was measured ---------------------------


@pytest.mark.parametrize(
    ("throttles", "retry_after"),
    [
        (sources.PAGINATION_CONTRACT["maximum_retries_per_request"] + 1, 3),
        (1, sources.MAX_RATE_LIMIT_WAIT_SECONDS + 1),
        (5, 55),
    ],
    ids=["retry-count-exhausted", "retry-after-too-large", "total-wait-ceiling"],
)
def test_a_census_that_ends_early_writes_no_receipt(tmp_path, slept, throttles, retry_after):
    """Result-blindness at every exit, not just the one that was tested. Each of
    these is a way SFIR4 could have ended, and a partial capacity receipt from
    any of them would turn the decision to re-run into a decision made after
    seeing a number."""
    root, charter, spent = _isolated(tmp_path)
    destination = tmp_path / "census.json"
    with pytest.raises(protocol.SFIR4Refused):
        probe4.probe_capacity(
            root,
            charter,
            spent,
            destination,
            ThrottlingTransport(throttles=throttles, retry_after=retry_after),
        )
    assert not destination.exists()


def test_the_transport_budget_ends_a_census_without_writing_one(tmp_path, monkeypatch):
    """SFIR5's own wall-clock ceiling, exercised through the real entry point.
    It is a different exit from SFIR4's retry bounds and must be just as silent:
    a timeout produces a terminal outcome, never a partial result."""
    root, charter, spent = _isolated(tmp_path)
    destination = tmp_path / "census.json"

    def exhausted(family: str, request: dict[str, Any]) -> dict[str, Any]:
        raise t5.TransportBudgetExceeded("census exceeded the frozen wall-clock budget")

    with pytest.raises(t5.TransportBudgetExceeded):
        probe4.probe_capacity(root, charter, spent, destination, exhausted)
    assert not destination.exists()


def test_a_completed_census_carries_a_response_evidence_block(tmp_path, slept):
    """The paired positive for the three refusals above: when the loop does
    finish, a receipt exists and carries the chain. Without this, a probe that
    always refused would satisfy every control in this section."""
    root, charter, spent = _isolated(tmp_path)
    written = probe4.probe_capacity(
        root, charter, spent, tmp_path / "census.json", ThrottlingTransport(throttles=0)
    )
    body = json.loads(written.read_text(encoding="utf-8"))
    assert body["protocol_id"] == protocol.PROTOCOL_ID
    assert "response_evidence" in body
    assert set(body["families"]) == set(sources.FAMILIES)
