from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import sfir10r4_transport as t  # noqa: E402


class Response:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout=60):
        self.calls.append(request.full_url)
        if not self.responses:
            raise AssertionError("unexpected network call")
        return self.responses.pop(0)


class RateOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, timeout=30):
        self.calls.append(request.full_url)
        if not self.responses:
            raise AssertionError("unexpected rate-window call")
        return self.responses.pop(0)


def headers(remaining, reset=1000, retry_after=None, location=None, request_id="fixture"):
    result = {
        "x-ratelimit-remaining": str(remaining),
        "x-ratelimit-reset": str(reset),
    }
    if request_id is not None:
        result["x-github-request-id"] = request_id
    if retry_after is not None:
        result["retry-after"] = str(retry_after)
    if location is not None:
        result["Location"] = location
    return result


def window(remaining=5000, used=0, reset=1000):
    return t.RateWindow(limit=5000, remaining=remaining, used=used, reset_epoch=reset)


def rate_response(*, remaining, used, reset=1000):
    return Response(
        200,
        {
            "resources": {
                "core": {"limit": 5000, "remaining": remaining, "used": used, "reset": reset}
            }
        },
        {},
    )


def preflight_responses(*, start_remaining=5000, reset=1000):
    return [
        Response(
            200,
            {"id": 583231},
            headers(start_remaining - index, reset=reset, request_id=f"req-{index}"),
        )
        for index in range(1, 11)
    ]


def test_accounting_preflight_proves_headers_without_claiming_exclusivity():
    rate = RateOpener(
        [rate_response(remaining=5000, used=0), rate_response(remaining=4990, used=10)]
    )
    requests = Opener(preflight_responses())
    proof = t.accounting_sanity_preflight(rate_opener=rate, request_opener=requests.open)
    assert proof.requests == 10
    assert proof.per_response_observed_delta_sum == 10
    assert proof.global_observed_delta == 10
    assert proof.unattributed_extra == 0
    assert proof.as_dict()["claims_credential_exclusivity"] is False
    assert requests.calls == [t.protocol.ACCOUNTING_PREFLIGHT_ENDPOINT] * 10


def test_accounting_preflight_allows_positive_external_interference():
    responses = preflight_responses()
    responses[3] = Response(200, {"id": 583231}, headers(4995, request_id="req-4"))
    # Continue monotonically from 4995, so the final response is 4989: observed sum 11.
    for index in range(4, 10):
        remaining = 4995 - (index - 3)
        responses[index] = Response(
            200,
            {"id": 583231},
            headers(remaining, request_id=f"req-{index + 1}"),
        )
    rate = RateOpener(
        [rate_response(remaining=5000, used=0), rate_response(remaining=4989, used=11)]
    )
    proof = t.accounting_sanity_preflight(rate_opener=rate, request_opener=Opener(responses).open)
    assert proof.per_response_observed_delta_sum == 11
    assert proof.global_observed_delta == 11
    assert proof.unattributed_extra == 1


def test_accounting_preflight_refuses_nonpositive_delta():
    responses = preflight_responses()
    responses[2] = Response(200, {"id": 583231}, headers(4998, request_id="req-3"))
    rate = RateOpener([rate_response(remaining=5000, used=0)])
    with pytest.raises(t.SegmentNotReady, match="too-small delta 0"):
        t.accounting_sanity_preflight(rate_opener=rate, request_opener=Opener(responses).open)


def test_accounting_preflight_requires_unique_request_ids():
    responses = preflight_responses()
    responses[-1] = Response(200, {"id": 583231}, headers(4990, request_id="req-9"))
    rate = RateOpener([rate_response(remaining=5000, used=0)])
    with pytest.raises(t.SegmentNotReady, match="not unique"):
        t.accounting_sanity_preflight(rate_opener=rate, request_opener=Opener(responses).open)


def test_accounting_preflight_requires_request_id():
    responses = preflight_responses()
    responses[0] = Response(200, {"id": 583231}, headers(4999, request_id=None))
    rate = RateOpener([rate_response(remaining=5000, used=0)])
    with pytest.raises(t.SegmentNotReady, match="lacks request id"):
        t.accounting_sanity_preflight(rate_opener=rate, request_opener=Opener(responses).open)


def test_accounting_preflight_global_witness_must_dominate_response_chain():
    responses = preflight_responses()
    responses[3] = Response(200, {"id": 583231}, headers(4995, request_id="req-4"))
    for index in range(4, 10):
        remaining = 4995 - (index - 3)
        responses[index] = Response(
            200,
            {"id": 583231},
            headers(remaining, request_id=f"req-{index + 1}"),
        )
    rate = RateOpener(
        [rate_response(remaining=5000, used=0), rate_response(remaining=4990, used=10)]
    )
    with pytest.raises(t.SegmentNotReady, match="does not dominate"):
        t.accounting_sanity_preflight(rate_opener=rate, request_opener=Opener(responses).open)


def test_accounting_preflight_requires_room_for_following_segment():
    rate = RateOpener([rate_response(remaining=4509, used=491)])
    with pytest.raises(t.SegmentNotReady, match="preflight\\+segment floor"):
        t.accounting_sanity_preflight(rate_opener=rate, request_opener=Opener([]).open)


def test_metadata_identity_and_default_branch_are_one_response():
    opener = Opener(
        [
            Response(
                200, {"id": 7, "full_name": "new/name", "default_branch": "trunk"}, headers(4999)
            )
        ]
    )
    client = t.Transport(window=window(), opener=opener)
    client.begin_root("7", 0)
    resolved = client.resolve_canonical_address("old/name", "7")
    assert resolved["observed_repository_id"] == "7"
    assert resolved["canonical_address"] == "new/name"
    assert resolved["default_branch"] == "trunk"
    assert resolved["minimum_attributable_charged_resolving"] == 1


def test_missing_default_branch_stays_missing():
    opener = Opener([Response(200, {"id": 7, "full_name": "new/name"}, headers(4999))])
    client = t.Transport(window=window(), opener=opener)
    client.begin_root("7", 0)
    assert client.resolve_canonical_address("old/name", "7")["default_branch"] is None


def test_identity_mismatch_refuses_instead_of_adopting_target():
    opener = Opener(
        [Response(200, {"id": 8, "full_name": "new/name", "default_branch": "main"}, headers(4999))]
    )
    client = t.Transport(window=window(), opener=opener)
    client.begin_root("7", 0)
    with pytest.raises(t.IdentityRefused):
        client.resolve_canonical_address("old/name", "7")


def test_metadata_transport_failure_is_stopped_not_identity_refused():
    client = t.Transport(window=window(), opener=Opener([Response(500, {}, headers(4999))]))
    client.begin_root("7", 0)
    with pytest.raises(t.TransportStop):
        client.resolve_canonical_address("old/name", "7")


def test_missing_rate_or_request_id_evidence_is_measurement_unproven():
    client = t.Transport(
        window=window(),
        opener=Opener([Response(200, {"x": 1}, {"x-ratelimit-remaining": "4999"})]),
    )
    with pytest.raises(t.MeasurementUnproven):
        client.get("https://api.github.com/repos/a/b")
    client = t.Transport(
        window=window(),
        opener=Opener([Response(200, {"x": 1}, headers(4999, request_id=None))]),
    )
    with pytest.raises(t.MeasurementUnproven, match="request-id"):
        client.get("https://api.github.com/repos/a/b")


def test_403_with_quota_remaining_is_operational_stop():
    client = t.Transport(window=window(), opener=Opener([Response(403, {}, headers(4999))]))
    with pytest.raises(t.TransportStop):
        client.get("https://api.github.com/repos/a/b")


def test_rate_stop_closes_segment():
    client = t.Transport(window=window(), opener=Opener([Response(403, {}, headers(0))]))
    client.previous_remaining = 1
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b")
    client = t.Transport(
        window=window(), opener=Opener([Response(429, {}, headers(4999, retry_after=30))])
    )
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b")


def test_success_with_remaining_zero_is_consumed_then_next_request_closes():
    opener = Opener([Response(200, {"ok": True}, headers(0))])
    client = t.Transport(window=window(), opener=opener)
    client.previous_remaining = 1
    assert client.get("https://api.github.com/repos/a/b").body == {"ok": True}
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b/commits/main")
    assert len(opener.calls) == 1


def test_segment_and_root_budgets_reserve_worst_case_hops_before_network():
    client = t.Transport(window=window(), opener=Opener([]))
    client.provider_charged = 4497
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b")
    client = t.Transport(window=window(), opener=Opener([]))
    client.begin_root("7", 537)
    with pytest.raises(t.TransportStop):
        client._reserve()


def test_redirects_account_each_network_hop_and_stay_on_host():
    opener = Opener(
        [
            Response(
                301,
                {},
                headers(4999, location="https://api.github.com/repos/new/name", request_id="r1"),
            ),
            Response(200, {"id": 7}, headers(4998, request_id="r2")),
        ]
    )
    client = t.Transport(window=window(), opener=opener)
    response = client.get("https://api.github.com/repos/old/name")
    assert response.network_hops == 2
    assert response.minimum_attributable_charged == 2
    assert response.observed_provider_decrement == 2
    assert client.totals()["minimum_attributable_charged"] == 2
    assert client.totals()["per_response_unattributed_extra"] == 0


def test_cross_host_redirect_is_refused():
    client = t.Transport(
        window=window(),
        opener=Opener([Response(301, {}, headers(4999, location="https://example.com/repo"))]),
    )
    with pytest.raises(t.TransportStop):
        client.get("https://api.github.com/repos/a/b")


def test_window_reset_mid_segment_closes_and_discards_boundary_response():
    client = t.Transport(
        window=window(reset=1000),
        opener=Opener(
            [
                Response(
                    200,
                    {"evil_boundary_body": ["must", "never", "be", "consumed"]},
                    headers(4999, reset=2000, request_id="rollover-1"),
                )
            ]
        ),
    )
    with pytest.raises(t.WindowRollover) as excinfo:
        client.get("https://api.github.com/repos/a/b")
    boundary = excinfo.value.boundary
    assert boundary["old_reset_epoch"] == 1000
    assert boundary["new_reset_epoch"] == 2000
    assert boundary["scientific_body_consumed"] is False
    assert boundary["minimum_attributable_charge_credited"] == 0
    assert boundary["provider_request_id"] == "rollover-1"
    assert "evil_boundary_body" not in json.dumps(client.receipt(), sort_keys=True)
    assert client.totals()["minimum_attributable_charged"] == 0
    assert client.totals()["network_hops"] == 0


def test_delta_two_is_recorded_as_interference_not_scientific_failure():
    client = t.Transport(
        window=window(),
        opener=Opener([Response(200, {"ok": True}, headers(4998, request_id="r1"))]),
    )
    response = client.get("https://api.github.com/repos/a/b")
    assert response.minimum_attributable_charged == 1
    assert response.observed_provider_decrement == 2
    totals = client.totals()
    assert totals["minimum_attributable_charged"] == 1
    assert totals["per_response_observed_provider_decrement"] == 2
    assert totals["per_response_unattributed_extra"] == 1


def test_nonpositive_hop_delta_is_unproven():
    client = t.Transport(
        window=window(),
        opener=Opener([Response(200, {"ok": True}, headers(5000, request_id="r1"))]),
    )
    with pytest.raises(t.MeasurementUnproven, match="positive hop charge"):
        client.get("https://api.github.com/repos/a/b")


def test_reconciliation_exact_cost_when_no_interference():
    client = t.Transport(
        window=window(remaining=5000, used=0),
        opener=Opener([Response(200, {"ok": True}, headers(4999, request_id="r1"))]),
    )
    client.get("https://api.github.com/repos/a/b")
    result = client.reconcile(t.RateWindow(limit=5000, remaining=4999, used=1, reset_epoch=1000))
    assert result["accounting_is_conservative"] is True
    assert result["total_unattributed_extra"] == 0
    assert result["exact_provider_cost_attribution"] is True
    assert result["provider_cost_claim_publishable"] is True
    assert result["capacity_evidence_publishable"] is True


def test_reconciliation_withholds_cost_but_keeps_capacity_under_interference():
    client = t.Transport(
        window=window(remaining=5000, used=0),
        opener=Opener([Response(200, {"ok": True}, headers(4998, request_id="r1"))]),
    )
    client.get("https://api.github.com/repos/a/b")
    result = client.reconcile(t.RateWindow(limit=5000, remaining=4998, used=2, reset_epoch=1000))
    assert result["minimum_attributable_charges"] == 1
    assert result["total_unattributed_extra"] == 1
    assert result["exact_provider_cost_attribution"] is False
    assert result["provider_cost_claim_publishable"] is False
    assert result["capacity_evidence_publishable"] is True


def test_reconciliation_records_tail_interference_after_last_response():
    client = t.Transport(
        window=window(remaining=5000, used=0),
        opener=Opener([Response(200, {"ok": True}, headers(4999, request_id="r1"))]),
    )
    client.get("https://api.github.com/repos/a/b")
    result = client.reconcile(t.RateWindow(limit=5000, remaining=4998, used=2, reset_epoch=1000))
    assert result["per_response_unattributed_extra"] == 0
    assert result["tail_unattributed_extra"] == 1
    assert result["total_unattributed_extra"] == 1


def test_rollover_reconciliation_keeps_capacity_but_withholds_exact_provider_cost():
    opener = Opener(
        [
            Response(200, {"old_window": True}, headers(4999, request_id="old-1")),
            Response(
                200,
                {"evil_boundary_body": True},
                headers(4998, reset=2000, request_id="new-1"),
            ),
        ]
    )
    client = t.Transport(window=window(remaining=5000, used=0, reset=1000), opener=opener)
    assert client.get("https://api.github.com/repos/a/b").body == {"old_window": True}
    with pytest.raises(t.WindowRollover):
        client.get("https://api.github.com/repos/a/b/commits/main")
    result = client.reconcile(
        t.RateWindow(limit=5000, remaining=4998, used=2, reset_epoch=2000)
    )
    assert result["minimum_attributable_charges"] == 1
    assert result["boundary_response_scientific_consumption"] is False
    assert result["boundary_response_charge_credited_to_old_window"] is False
    assert result["exact_provider_cost_attribution"] is False
    assert result["provider_cost_claim_publishable"] is False
    assert result["capacity_evidence_publishable"] is True
    assert result["replay_required_under_fresh_segment"] is True
    assert result["rollover_boundary"]["new_reset_epoch"] == 2000


def test_reconciliation_refuses_inconsistent_global_witness():
    client = t.Transport(
        window=window(remaining=5000, used=0),
        opener=Opener([Response(200, {"ok": True}, headers(4998, request_id="r1"))]),
    )
    client.get("https://api.github.com/repos/a/b")
    with pytest.raises(t.MeasurementUnproven, match="smaller than the chained"):
        client.reconcile(t.RateWindow(limit=5000, remaining=4999, used=1, reset_epoch=1000))
    with pytest.raises(t.MeasurementUnproven, match="do not reconcile"):
        client.reconcile(t.RateWindow(limit=5000, remaining=4998, used=1, reset_epoch=1000))


def test_transport_receipt_never_serializes_response_bodies_or_secret_values(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-must-never-appear")
    client = t.Transport(
        window=window(),
        opener=Opener([Response(200, {"private": "body-value"}, headers(4999, request_id="r1"))]),
    )
    client.get("https://api.github.com/repos/a/b")
    encoded = json.dumps(client.receipt())
    assert "secret-must-never-appear" not in encoded
    assert "body-value" not in encoded
    assert "Authorization" not in encoded
