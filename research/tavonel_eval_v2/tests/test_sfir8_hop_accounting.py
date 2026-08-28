"""Controls for SFIR8's hop accounting and the SFIR7 reconciliation.

Two things have to hold. The instrument must keep the three counts apart --
logical requests, network hops, provider charge -- because conflating the first
and the last is what cost SFIR7 four runs. And the analysis must be able to
return the finding that clears the hypothesis: if redirects were not the cause,
a probe that can only say "renamed addresses cost more" would say it anyway.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir8_hop_accounting as hops  # noqa: E402
import sfir8_measure_hop_divergence as divergence  # noqa: E402
import sfir8_reconcile_sfir7_accounting as reconcile  # noqa: E402

# --- the three counts stay apart ---------------------------------------------


def _accounting(**kw) -> hops.RequestAccounting:
    base = {"url": "u", "final_url": "u", "status": 200}
    base.update(kw)
    return hops.RequestAccounting(**base)


def test_a_plain_request_is_one_hop_and_one_charge():
    row = _accounting(
        hops=[hops.Hop(url="u", status=200)], remaining_before=100, remaining_after=99
    )
    assert row.network_hops == 1
    assert row.provider_charged == 1
    assert row.redirected is False


def test_a_redirected_request_is_two_hops_and_two_charges():
    """One logical request, two responses, two deductions. SFIR7 counted one."""
    row = _accounting(
        hops=[
            hops.Hop(url="old", status=301, redirected_to="new"),
            hops.Hop(url="new", status=200),
        ],
        remaining_before=100,
        remaining_after=98,
    )
    assert row.network_hops == 2
    assert row.provider_charged == 2
    assert row.redirected is True


def test_the_charge_comes_from_the_provider_and_not_from_counting_hops():
    """The distinction the whole instrument rests on.

    If charge were derived from hops it could never disagree with them, and the
    three requests SFIR8 observed being charged more than their hops would have
    been invisible -- which is exactly how SFIR7's divergence stayed hidden.
    """
    row = _accounting(
        hops=[
            hops.Hop(url="old", status=301, redirected_to="new"),
            hops.Hop(url="new", status=200),
        ],
        remaining_before=100,
        remaining_after=96,
    )
    assert row.network_hops == 2
    assert row.provider_charged == 4


def test_a_request_without_rate_limit_headers_reports_no_charge():
    """None, not zero. A missing measurement is not a measurement of nothing."""
    row = _accounting(hops=[hops.Hop(url="u", status=200)], remaining_before=None)
    assert row.provider_charged is None


def test_totals_exclude_requests_with_no_provider_accounting():
    fetcher = hops.HopCountingFetcher()
    fetcher.requests = [
        _accounting(hops=[hops.Hop(url="a", status=200)], remaining_before=10, remaining_after=9),
        _accounting(hops=[hops.Hop(url="b", status=200)], remaining_before=None),
    ]
    totals = fetcher.totals()
    assert totals["logical_requests"] == 2
    assert totals["requests_with_provider_accounting"] == 1
    assert totals["provider_charged"] == 1


def test_the_body_is_kept_alongside_the_counts():
    """An earlier draft discarded it and justified the discard on tidiness, which
    forced the caller to pay for the same bytes twice.
    """
    assert hops._parse(b'{"default_branch": "main"}') == {"default_branch": "main"}
    assert hops._parse(b"not json") is None


# --- the probe can clear the hypothesis --------------------------------------


def _groups(renamed: float | None, unrenamed: float | None) -> dict:
    return {
        "renamed": {"charged_per_logical_request": renamed},
        "unrenamed": {"charged_per_logical_request": unrenamed},
    }


def test_equal_costs_report_that_redirects_are_not_the_cause():
    """The finding that would have sent the search elsewhere. A probe unable to
    return it would confirm the hypothesis whatever the data said.
    """
    verdict = divergence._verdict(_groups(1.0, 1.0))
    assert verdict["finding"] == "REDIRECTS_ARE_NOT_THE_CAUSE"


def test_a_higher_renamed_cost_supports_the_hypothesis():
    assert divergence._verdict(_groups(2.0, 1.0))["finding"] == "RENAMED_ADDRESSES_COST_MORE"


def test_missing_provider_accounting_concludes_nothing():
    assert divergence._verdict(_groups(None, 1.0))["finding"] == "NO_PROVIDER_ACCOUNTING"


def test_a_pattern_matching_neither_hypothesis_is_inconclusive():
    """Renamed cheaper than unrenamed fits no story and must not be forced into one."""
    assert divergence._verdict(_groups(1.0, 2.0))["finding"] == "INCONCLUSIVE"


def test_the_sample_splits_on_the_fact_under_test_and_nothing_else():
    census = {
        "identity_attestation": {"renames_observed": {"a/b": "c/b"}},
        "families": {
            "git_docs": {
                "root_dispositions": [
                    {"discovery_root_id": "git:a/b", "response_refs": ["u"]},
                    {"discovery_root_id": "git:d/e", "response_refs": ["u"]},
                    {"discovery_root_id": "git:f/g", "response_refs": []},
                ]
            }
        },
    }
    chosen = divergence.sample(census, per_group=5)
    assert chosen["renamed"] == ["a/b"]
    assert chosen["unrenamed"] == ["d/e"]


def test_a_census_with_no_renames_cannot_support_the_comparison():
    census = {
        "identity_attestation": {"renames_observed": {}},
        "families": {"git_docs": {"root_dispositions": [
            {"discovery_root_id": "git:d/e", "response_refs": ["u"]}
        ]}},
    }
    with pytest.raises(divergence.DivergenceRefused, match="comparison needs both"):
        divergence.sample(census, per_group=5)


# --- the reconciliation reports its residual ---------------------------------


def _probe(rows: list[tuple[str, int]]) -> dict:
    return {
        "finding": "RENAMED_ADDRESSES_COST_MORE",
        "requests": [{"group": g, "provider_charged": c} for g, c in rows],
    }


def _census(logical_on_renamed: int, logical_on_other: int) -> dict:
    return {
        "identity_attestation": {"renames_observed": {"a/b": "c/b"}},
        "families": {
            "git_docs": {
                "root_dispositions": [
                    {
                        "discovery_root_id": "git:a/b",
                        "response_refs": ["u"] * logical_on_renamed,
                    },
                    {
                        "discovery_root_id": "git:d/e",
                        "response_refs": ["u"] * logical_on_other,
                    },
                ]
            }
        },
    }


def test_the_modal_charge_is_used_rather_than_the_mean():
    """A mean absorbs outliers into the rule and dissolves the residual into a
    decimal. The mode is what the provider does; the rest is a separate
    observation someone has to explain.
    """
    probe = _probe([("renamed", 2)] * 33 + [("renamed", 3)] * 2 + [("renamed", 4)])
    assert reconcile._modal_charge(probe, "renamed") == 2


def test_a_shortfall_is_reported_as_a_residual_and_not_absorbed():
    """The finding this reconciliation actually produced: redirects explain part
    of SFIR7's divergence, not the whole of it.
    """
    probe = _probe([("renamed", 2)] * 10 + [("unrenamed", 1)] * 10)
    body = reconcile.reconcile(_census(100, 100), probe)
    assert body["predicted_provider_charge"] == 300
    assert body["residual_unexplained"] == reconcile.PROVIDER_LIMIT - 300
    assert body["finding"] == "PER_HOP_CHARGING_EXPLAINS_PART_OF_THE_DIVERGENCE"
    assert body["explains_the_divergence"] is False
    assert len(body["candidate_causes_of_the_residual"]) == 2


def test_a_full_explanation_is_reportable_too():
    """So the partial finding is not the only answer available."""
    probe = _probe([("renamed", 2)] * 10 + [("unrenamed", 1)] * 10)
    body = reconcile.reconcile(_census(3000, 2000), probe)
    assert body["predicted_provider_charge"] == 8000
    assert body["explains_the_divergence"] is True
    assert body["finding"] == "PER_HOP_CHARGING_EXPLAINS_THE_DIVERGENCE"


def test_the_reconciliation_makes_no_requests_and_reads_terminal_evidence():
    probe = _probe([("renamed", 2), ("unrenamed", 1)])
    body = reconcile.reconcile(_census(10, 10), probe)
    assert body["requests_made"] == 0
    assert body["reads_terminal_evidence_only"] is True
    assert body["produces_capacity_claim"] is False


def test_the_residual_is_explicitly_not_attributed():
    """Two candidates, neither established. Writing a receipt from a guess is
    the thing the founder ruling forbids by name.
    """
    probe = _probe([("renamed", 2), ("unrenamed", 1)])
    body = reconcile.reconcile(_census(10, 10), probe)
    assert "neither is established" in body["the_residual_is_not_attributed"].lower()
    for candidate in body["candidate_causes_of_the_residual"]:
        assert candidate["how_it_would_be_settled"]


# --- the receipts on disk say what the tools computed ------------------------


def test_the_live_probe_receipt_recorded_a_clean_per_group_split():
    body = json.loads((NS / "receipts/sfir8-hop-divergence.json").read_text(encoding="utf-8"))
    assert body["groups"]["unrenamed"]["charged_per_logical_request"] == 1.0
    assert body["groups"]["unrenamed"]["requests_that_redirected"] == 0
    assert body["groups"]["renamed"]["requests_that_redirected"] == (
        body["groups"]["renamed"]["logical_requests"]
    )
    assert body["produces_capacity_claim"] is False


def test_the_reconciliation_receipt_reports_an_unexplained_residual():
    body = json.loads(
        (NS / "receipts/sfir8-sfir7-accounting-reconciliation.json").read_text(encoding="utf-8")
    )
    assert body["finding"] == "PER_HOP_CHARGING_EXPLAINS_PART_OF_THE_DIVERGENCE"
    assert body["residual_unexplained"] > 0
    assert body["sfir7_observed"]["our_counter_stayed_below_the_bound"] is True


def test_fetch_records_the_redirects_it_followed_as_hops(monkeypatch):
    """Driven through `fetch`, not assembled by hand.

    Constructing a `RequestAccounting` with hops already in it proves the
    properties compute correctly; it does not prove `fetch` puts the redirects
    there. Deleting the handler's recorded hops from the assembly survived a
    suite that only did the former -- INC-V2-113's shape once more.
    """
    import io

    class _Response(io.BytesIO):
        headers: ClassVar[dict] = {"x-ratelimit-remaining": "98", "x-ratelimit-used": "2"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def geturl(self):
            return "https://api.github.com/repos/new/name"

        status = 200

    fetcher = hops.HopCountingFetcher()

    def _build_opener(handler):
        handler.recorded.append(
            hops.Hop(
                url="https://api.github.com/repos/old/name",
                status=301,
                redirected_to="https://api.github.com/repos/new/name",
            )
        )

        class _Opener:
            handlers = ()

            def open(self, request, timeout=None):
                return _Response(b'{"full_name": "new/name"}')

        return _Opener()

    monkeypatch.setattr(hops.urllib.request, "build_opener", _build_opener)
    row = fetcher.fetch("https://api.github.com/repos/old/name")
    assert row.network_hops == 2
    assert row.redirected is True
    assert row.hops[0].redirected_to.endswith("/repos/new/name")
    assert row.hops[-1].status == 200


def test_fetch_records_a_plain_request_as_a_single_hop(monkeypatch):
    """So the control above is measuring the redirect and not the assembly."""
    import io

    class _Response(io.BytesIO):
        headers: ClassVar[dict] = {"x-ratelimit-remaining": "99"}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def geturl(self):
            return "https://api.github.com/repos/a/b"

    class _Opener:
        def open(self, request, timeout=None):
            return _Response(b"{}")

    monkeypatch.setattr(hops.urllib.request, "build_opener", lambda handler: _Opener())
    row = hops.HopCountingFetcher().fetch("https://api.github.com/repos/a/b")
    assert row.network_hops == 1
    assert row.redirected is False


def test_the_mode_and_the_mean_are_distinguishable():
    """The previous control used a distribution where int(mean) happened to equal
    the mode, so swapping one for the other changed nothing and the mutation
    survived. Here they differ.
    """
    probe = _probe([("renamed", 2)] * 6 + [("renamed", 5)] * 4)
    assert reconcile._modal_charge(probe, "renamed") == 2
    mean = sum(r["provider_charged"] for r in probe["requests"]) / len(probe["requests"])
    assert int(mean) == 3, "fixture no longer separates mode from mean"
