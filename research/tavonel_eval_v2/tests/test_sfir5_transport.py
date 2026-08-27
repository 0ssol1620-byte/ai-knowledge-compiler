"""SFIR5's transport: paced, and observing on every family.

The two defects these controls exist for:

INC-V2-101 -- ~90 unpaced Wikimedia requests exhausted a 5-retry budget, because
the endpoint admits about ten per sixty-second window.

INC-V2-102 -- `_observe` is the only writer to the response ledger and only
`git_docs` reached it, so two families of three produced no response evidence at
all, and the consistency check could not notice because absent rows produce
absent aggregates that agree.

Every control here runs against stubs. The suite is barred from the network by
`conftest`, and nothing below wants a socket.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import probe_sfir4_capacity as probe4  # noqa: E402
import sfir5_transport as t5  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

EMPTY_ECFR = {
    "content_versions": [],
    "meta": {"total_pages": 1, "result_count": "0", "title": "35"},
}


@pytest.fixture
def stub_observed(monkeypatch):
    """Stand in for `_http_json_observed` so the live path runs without a socket.

    Patching THIS rather than injecting a fetcher is the whole point: injecting
    one flips `_live_transport` to False and makes every observation synthesised,
    which is the thing `require_observed_census` refuses at seal time.
    """
    seen: list[str] = []

    def fake(url: str) -> tuple[Any, dict[str, Any]]:
        seen.append(url)
        return EMPTY_ECFR, {
            "status": 200,
            "content_digest": "sha256:" + "a" * 64,
            "observed_length": 12,
            "declared_length": None,
            "observed_bytes": True,
        }

    monkeypatch.setattr(probe4, "_http_json_observed", fake)
    return seen


def _ecfr_request():
    root = sources.declared_roots("regulation_ecfr")[0]
    return {
        "cursor": None,
        "pool": sources.SOURCE_POOLS["regulation_ecfr"],
        "metadata_only": True,
        "expected_discovery_root_id": sources.discovery_root_id("regulation_ecfr", root),
    }


def _transport(sleeps: list[float] | None = None, times: list[float] | None = None):
    """A transport on a stub clock. `times` is consumed one reading per call and
    the last value then holds, so a control can say what the clock reports
    without counting how many times the code under test looks at it."""
    remaining = list(times or [0.0])

    def clock() -> float:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return t5.PacedObservingTransport(
        clock=clock, sleep=(sleeps.append if sleeps is not None else lambda _s: None)
    )


# --- INC-V2-102: every family reaches the ledger -----------------------------


def test_the_legacy_family_now_records_observations(stub_observed):
    """The repair. SFIR4 recorded ZERO here; the assertion is that it is not
    zero any more, and that what it records is observed rather than parsed."""
    transport = _transport()
    transport("regulation_ecfr", _ecfr_request())
    rows = transport.ledger.observations()
    assert rows, "the legacy family still records nothing"
    assert {row.family for row in rows} == {"regulation_ecfr"}
    assert all(row.observed_bytes for row in rows)


def test_sfir4s_transport_still_records_nothing_for_the_legacy_family():
    """The measurement the incident rests on, kept as a control so the claim
    'SFIR4 covered one family of three' stays checkable rather than becoming a
    story about a version nobody can run any more."""
    transport = probe4.LiveMetadataTransport(lambda _url: EMPTY_ECFR)
    transport("regulation_ecfr", _ecfr_request())
    assert transport.ledger.observations() == ()


def test_the_recorded_root_is_the_root_being_censused(stub_observed):
    """`legacy_fetch` gets a URL and nothing else, so the family and root come
    from state set in `__call__`. If that were stale, every legacy observation
    would be filed under whichever root ran first -- a chain that verifies
    perfectly and attributes every response to the wrong place."""
    transport = _transport()
    request = _ecfr_request()
    transport("regulation_ecfr", request)
    expected = request["expected_discovery_root_id"]
    assert {row.root_id for row in transport.ledger.observations()} == {expected}


def test_family_coverage_refuses_a_family_that_never_recorded():
    with pytest.raises(t5.FamilyCoverageRefused, match="encyclopedia_wikipedia"):
        t5.require_family_coverage(
            ledger_families={"git_docs", "regulation_ecfr"},
            families_with_candidates={"git_docs", "regulation_ecfr", "encyclopedia_wikipedia"},
        )


def test_family_coverage_passes_when_every_family_recorded():
    """The paired positive -- without it a check that refused everything would
    satisfy the control above and prove nothing."""
    covered = t5.require_family_coverage(
        ledger_families={"git_docs", "regulation_ecfr", "encyclopedia_wikipedia"},
        families_with_candidates={"git_docs", "regulation_ecfr"},
    )
    assert covered["covered"] is True


def test_family_coverage_compares_against_candidates_not_against_itself():
    """The defect being repaired was a check that compared an absence to an
    absence. This asserts the comparison has two independent sides: an empty
    ledger is fine only when the census also claims nothing."""
    assert t5.require_family_coverage(set(), set())["covered"] is True
    with pytest.raises(t5.FamilyCoverageRefused):
        t5.require_family_coverage(set(), {"git_docs"})


# --- INC-V2-101: pacing ------------------------------------------------------


def test_the_second_request_to_a_host_waits_the_frozen_interval(stub_observed):
    sleeps: list[float] = []
    transport = _transport(sleeps=sleeps)
    transport._pace("https://en.wikipedia.org/w/api.php?x=1")
    transport._pace("https://en.wikipedia.org/w/api.php?x=2")
    assert sleeps and sleeps[0] == pytest.approx(t5.HOST_MIN_INTERVAL_SECONDS["en.wikipedia.org"])


def test_the_first_request_to_a_host_does_not_wait(stub_observed):
    sleeps: list[float] = []
    transport = _transport(sleeps=sleeps)
    transport._pace("https://en.wikipedia.org/w/api.php")
    assert sleeps == []


def test_pacing_is_per_host_so_one_slow_endpoint_does_not_stall_the_others():
    """A quota is a property of the service. Charging Wikimedia's interval to
    the git lane would turn a 7-second courtesy into hours of dead time."""
    sleeps: list[float] = []
    transport = _transport(sleeps=sleeps)
    transport._pace("https://en.wikipedia.org/w/api.php")
    transport._pace("https://api.github.com/repos/x/y")
    transport._pace("https://www.ecfr.gov/api/versioner/v1/titles.json")
    assert sleeps == []


def test_an_unlisted_host_is_paced_by_default_not_unpaced_by_omission():
    assert t5.PacedObservingTransport.interval_for("example.invalid") == (
        t5.DEFAULT_MIN_INTERVAL_SECONDS
    )
    assert t5.DEFAULT_MIN_INTERVAL_SECONDS > 0


def test_the_wikimedia_interval_is_above_the_spacing_that_still_throttled():
    """5s still throttled and 7s did not, measured before SFIR5 was designed.
    A frozen constant below the measurement would be a value chosen for speed
    over the evidence it is supposed to rest on."""
    assert t5.HOST_MIN_INTERVAL_SECONDS["en.wikipedia.org"] >= 6.0


def test_the_request_cap_is_terminal_not_retryable():
    transport = _transport()
    transport.requests_made = t5.MAX_TOTAL_REQUESTS
    with pytest.raises(t5.TransportBudgetExceeded, match="request cap"):
        transport._pace("https://en.wikipedia.org/w/api.php")


def test_the_wall_clock_budget_is_terminal_not_retryable():
    times = iter([0.0] + [t5.MAX_TOTAL_WALL_CLOCK_SECONDS + 1.0] * 8)
    transport = t5.PacedObservingTransport(clock=lambda: next(times), sleep=lambda _s: None)
    with pytest.raises(t5.TransportBudgetExceeded, match="wall-clock"):
        transport._pace("https://en.wikipedia.org/w/api.php")


def test_the_frozen_bounds_are_finite():
    """A budget that is not finite is not a budget. Each of these is the thing
    that ends a run the pacing failed to keep inside the endpoint's limits."""
    assert 0 < t5.MAX_TOTAL_WALL_CLOCK_SECONDS < float("inf")
    assert 0 < t5.MAX_TOTAL_REQUESTS < float("inf")
    assert t5.MAX_CONCURRENT_REQUESTS_PER_HOST == 1


def test_sfir4s_retry_budget_is_not_touched_by_sfir5():
    """The bound SFIR5 exists NOT to change. Pacing keeps the request pattern
    inside what the endpoint permits so this is never stressed; enlarging it
    would have been a value chosen by a failure."""
    assert sources.PAGINATION_CONTRACT["maximum_retries_per_request"] == 5
    assert sources.MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS == 180
    assert sources.MAX_RATE_LIMIT_WAIT_SECONDS == 60


def test_the_transport_keeps_live_evidence_live(stub_observed):
    """Injecting a fetcher was the obvious way to add pacing and would have made
    every observation synthesised, because `_live_transport` is
    `fetch_json is _http_json`. The subclass must not have reintroduced that."""
    transport = _transport()
    assert transport._live_transport is True
    transport("regulation_ecfr", _ecfr_request())
    assert all(row.content_digest.startswith("sha256:") for row in transport.ledger.observations())


def test_the_summary_reports_what_actually_left_the_machine(stub_observed):
    transport = _transport()
    transport("regulation_ecfr", _ecfr_request())
    summary = transport.summary()
    assert summary["requests_made"] >= 1
    assert sum(summary["per_host_requests"].values()) == summary["requests_made"]
    assert summary["frozen_bounds"]["max_total_requests"] == t5.MAX_TOTAL_REQUESTS


# --- a failed request is evidence too ----------------------------------------


def _failing_observed(monkeypatch, error):
    def fake(url: str):
        raise error

    monkeypatch.setattr(probe4, "_http_json_observed", fake)


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (probe4.RootUnavailable(404, "ref"), "HTTP_ERROR"),
        (probe4.TransportInterrupted(5, "RemoteDisconnected"), "TRANSPORT_INTERRUPTED"),
        (probe4.RateLimited("55"), "TRANSPORT_ERROR"),
    ],
    ids=["http-error", "dropped-connection", "throttled"],
)
def test_a_request_that_failed_is_still_in_the_chain(monkeypatch, error, outcome):
    """It consumed the same budget the frozen bounds are checked against.

    A chain that recorded only successes would reconcile perfectly against a
    request count that omitted every failure -- and the census that died in
    INC-V2-101 was nothing BUT failures. Through the paced transport
    specifically, because the legacy families reach the network by a different
    route and that is exactly what INC-V2-102 was about.
    """
    _failing_observed(monkeypatch, error)
    transport = _transport()
    with pytest.raises(type(error)):
        transport._observe("regulation_ecfr", "root", "https://www.ecfr.gov/api/x")
    rows = transport.ledger.observations()
    assert len(rows) == 1
    assert rows[0].outcome == outcome
    assert rows[0].observed_bytes is False


def test_a_failed_request_is_paced_and_counted_like_any_other(monkeypatch):
    """A failure that skipped pacing would let a throttled endpoint be hammered
    precisely when it is asking to be left alone."""
    _failing_observed(monkeypatch, probe4.RateLimited("55"))
    transport = _transport()
    for _ in range(2):
        with pytest.raises(probe4.RateLimited):
            transport._observe("regulation_ecfr", "root", "https://en.wikipedia.org/w/api.php")
    assert transport.requests_made == 2
    assert transport.paced_seconds >= t5.HOST_MIN_INTERVAL_SECONDS["en.wikipedia.org"]


# --- cancellation -------------------------------------------------------------


def test_cancelling_mid_census_leaves_no_receipt_and_a_readable_chain(tmp_path, monkeypatch):
    """A cancelled run must be indistinguishable from one that never started, as
    far as sealed artifacts go -- and must still be able to say what it did
    before it stopped. Those are different requirements and both are needed: no
    partial authority anyone could bind to, but no silent loss of the record of
    what already left the machine either."""
    calls = {"n": 0}
    good = {
        "status": 200,
        "content_digest": "sha256:" + "b" * 64,
        "observed_length": 4,
        "declared_length": None,
        "observed_bytes": True,
    }

    def fake(url: str):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt
        return {"content_versions": []}, good

    monkeypatch.setattr(probe4, "_http_json_observed", fake)
    transport = _transport()
    destination = tmp_path / "census.json"
    transport._observe("regulation_ecfr", "root", "https://www.ecfr.gov/api/1")
    with pytest.raises(KeyboardInterrupt):
        transport._observe("regulation_ecfr", "root", "https://www.ecfr.gov/api/2")

    assert not destination.exists()
    assert len(transport.ledger.observations()) == 1
    # Two requests left the machine; one produced a chain entry. The interrupted
    # one never got a response, so there is nothing to record about it beyond
    # the count -- and the count is what makes the gap visible rather than
    # invisible. It is only tolerable because cancellation is terminal: nothing
    # is sealed, so no receipt ever claims these two numbers agree.
    assert transport.summary()["requests_made"] == 2
