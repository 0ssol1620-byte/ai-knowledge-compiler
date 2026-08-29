from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import sfir10r2_transport as t  # noqa: E402


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


class RateOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, timeout=30):
        self.calls.append(request.full_url)
        if not self.responses:
            raise AssertionError("unexpected rate-window call")
        return self.responses.pop(0)


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


def test_exclusive_preflight_proves_ten_unit_charges_before_cohort_contact():
    rate = RateOpener(
        [
            rate_response(remaining=5000, used=0),
            rate_response(remaining=4990, used=10),
        ]
    )
    requests = Opener(preflight_responses())
    proof = t.exclusive_segment_preflight(rate_opener=rate, request_opener=requests.open)
    assert proof.before.remaining == 5000
    assert proof.after.remaining == 4990
    assert proof.requests == 10
    assert proof.request_ids_digest.startswith("sha256:")
    assert proof.as_dict()["cohort_contact"] is False
    assert requests.calls == [t.protocol.EXCLUSIVITY_PREFLIGHT_ENDPOINT] * 10
    assert rate.calls == [t.protocol.RATE_LIMIT_ENDPOINT] * 2


def test_exclusive_preflight_refuses_before_requests_if_4510_is_unavailable():
    rate = RateOpener([rate_response(remaining=4509, used=491)])
    requests = Opener([])
    with pytest.raises(t.SegmentNotReady, match="preflight\\+segment floor"):
        t.exclusive_segment_preflight(rate_opener=rate, request_opener=requests.open)
    assert requests.calls == []


def test_exclusive_preflight_delta_two_is_retryable_not_measurement_unproven():
    rate = RateOpener([rate_response(remaining=5000, used=0)])
    responses = preflight_responses()
    responses[3] = Response(200, {"id": 583231}, headers(4995, request_id="req-4"))
    with pytest.raises(t.SegmentNotReady, match="delta 2"):
        t.exclusive_segment_preflight(rate_opener=rate, request_opener=Opener(responses).open)


def test_exclusive_preflight_requires_unique_request_ids():
    rate = RateOpener([rate_response(remaining=5000, used=0)])
    responses = preflight_responses()
    responses[-2] = Response(200, {"id": 583231}, headers(4991, request_id="req-9"))
    responses[-1] = Response(200, {"id": 583231}, headers(4990, request_id="req-9"))
    with pytest.raises(t.SegmentNotReady, match="not unique"):
        t.exclusive_segment_preflight(rate_opener=rate, request_opener=Opener(responses).open)


def test_exclusive_preflight_requires_request_id():
    rate = RateOpener([rate_response(remaining=5000, used=0)])
    responses = preflight_responses()
    responses[0] = Response(200, {"id": 583231}, headers(4999, request_id=None))
    with pytest.raises(t.SegmentNotReady, match="lacks request id"):
        t.exclusive_segment_preflight(rate_opener=rate, request_opener=Opener(responses).open)


def test_exclusive_preflight_reconciliation_must_equal_exactly_ten_charges():
    rate = RateOpener(
        [
            rate_response(remaining=5000, used=0),
            rate_response(remaining=4989, used=11),
        ]
    )
    with pytest.raises(t.SegmentNotReady, match="not exclusive"):
        t.exclusive_segment_preflight(
            rate_opener=rate,
            request_opener=Opener(preflight_responses()).open,
        )


def test_exclusive_preflight_allows_exactly_4500_after_ten_charges():
    rate = RateOpener(
        [
            rate_response(remaining=4510, used=490),
            rate_response(remaining=4500, used=500),
        ]
    )
    proof = t.exclusive_segment_preflight(
        rate_opener=rate,
        request_opener=Opener(preflight_responses(start_remaining=4510)).open,
    )
    assert proof.after.remaining == 4500


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
    assert len(opener.calls) == 1


def test_missing_default_branch_stays_missing():
    opener = Opener([Response(200, {"id": 7, "full_name": "new/name"}, headers(4999))])
    client = t.Transport(window=window(), opener=opener)
    client.begin_root("7", 0)
    resolved = client.resolve_canonical_address("old/name", "7")
    assert resolved["default_branch"] is None


def test_identity_mismatch_refuses_instead_of_adopting_redirect_target():
    opener = Opener(
        [Response(200, {"id": 8, "full_name": "new/name", "default_branch": "main"}, headers(4999))]
    )
    client = t.Transport(window=window(), opener=opener)
    client.begin_root("7", 0)
    with pytest.raises(t.IdentityRefused):
        client.resolve_canonical_address("old/name", "7")


def test_metadata_transport_failure_is_stopped_not_identity_refused():
    opener = Opener([Response(500, {"message": "server"}, headers(4999))])
    client = t.Transport(window=window(), opener=opener)
    client.begin_root("7", 0)
    with pytest.raises(t.TransportStop):
        client.resolve_canonical_address("old/name", "7")


def test_missing_reset_header_is_measurement_unproven():
    opener = Opener([Response(200, {"x": 1}, {"x-ratelimit-remaining": "4999"})])
    client = t.Transport(window=window(), opener=opener)
    with pytest.raises(t.MeasurementUnproven):
        client.get("https://api.github.com/repos/a/b")


def test_non_rate_403_is_never_returned_as_empty_tree():
    opener = Opener([Response(403, {"message": "forbidden"}, headers(4999))])
    client = t.Transport(window=window(), opener=opener)
    with pytest.raises(t.TransportStop):
        client.get("https://api.github.com/repos/a/b")


def test_rate_limit_403_closes_segment_before_body_reaches_traversal():
    opener = Opener([Response(403, {"message": "rate"}, headers(0))])
    client = t.Transport(window=window(), opener=opener)
    client.previous_remaining = 1
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b")


def test_429_always_closes_segment():
    opener = Opener([Response(429, {"message": "secondary"}, headers(4999, retry_after=30))])
    client = t.Transport(window=window(), opener=opener)
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b")


def test_success_with_remaining_zero_is_consumed_then_next_request_closes_without_network():
    opener = Opener([Response(200, {"ok": True}, headers(0))])
    client = t.Transport(window=window(), opener=opener)
    client.previous_remaining = 1
    response = client.get("https://api.github.com/repos/a/b")
    assert response.body == {"ok": True}
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b/commits/main")
    assert len(opener.calls) == 1


def test_segment_budget_reserves_worst_case_redirect_before_network():
    opener = Opener([])
    client = t.Transport(window=window(), opener=opener)
    client.provider_charged = 4497
    with pytest.raises(t.SegmentClose):
        client.get("https://api.github.com/repos/a/b")
    assert opener.calls == []


def test_root_budget_reserves_worst_case_redirect_before_network():
    opener = Opener([])
    client = t.Transport(window=window(), opener=opener)
    client.begin_root("7", 537)
    with pytest.raises(t.TransportStop):
        client.get("https://api.github.com/repos/a/b")
    assert opener.calls == []


def test_redirects_stay_on_single_host_and_account_each_hop():
    opener = Opener(
        [
            Response(301, {}, headers(4999, location="https://api.github.com/repos/new/name")),
            Response(200, {"id": 7}, headers(4998)),
        ]
    )
    client = t.Transport(window=window(), opener=opener)
    response = client.get("https://api.github.com/repos/old/name")
    assert response.network_hops == 2
    assert response.provider_charged == 2
    assert client.totals() == {"logical_requests": 1, "network_hops": 2, "provider_charged": 2}


def test_cross_host_redirect_is_refused():
    opener = Opener(
        [
            Response(301, {}, headers(4999, location="https://example.com/repo")),
        ]
    )
    client = t.Transport(window=window(), opener=opener)
    with pytest.raises(t.TransportStop):
        client.get("https://api.github.com/repos/a/b")


def test_window_reset_mid_segment_is_unproven():
    opener = Opener([Response(200, {"ok": True}, headers(4999, reset=2000))])
    client = t.Transport(window=window(reset=1000), opener=opener)
    with pytest.raises(t.MeasurementUnproven):
        client.get("https://api.github.com/repos/a/b")


def test_provider_reconciliation_requires_exact_zero_delta():
    client = t.Transport(window=window(remaining=5000, used=10), opener=Opener([]))
    client.provider_charged = 4
    clean = client.reconcile(t.RateWindow(limit=5000, remaining=4996, used=14, reset_epoch=1000))
    assert clean["accounting_is_complete"] is True
    with pytest.raises(t.MeasurementUnproven):
        client.reconcile(t.RateWindow(limit=5000, remaining=4995, used=15, reset_epoch=1000))


def test_per_hop_provider_delta_above_one_is_unproven():
    opener = Opener([Response(200, {"ok": True}, headers(4998))])
    client = t.Transport(window=window(), opener=opener)
    with pytest.raises(t.MeasurementUnproven, match="per-response provider delta"):
        client.get("https://api.github.com/repos/a/b")


def test_transport_receipt_never_serializes_response_bodies_or_secret_values(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-must-never-appear")
    opener = Opener([Response(200, {"private": "body-value"}, headers(4999))])
    client = t.Transport(window=window(), opener=opener)
    client.get("https://api.github.com/repos/a/b")
    encoded = json.dumps(client.receipt())
    assert "secret-must-never-appear" not in encoded
    assert "body-value" not in encoded
    assert "Authorization" not in encoded
