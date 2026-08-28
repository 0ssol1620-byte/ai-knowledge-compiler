"""Controls for the manual-redirect transport and the provider reconciliation.

Two things are being defended here, and both were paid for.

A redirect must be *followed by the instrument*, one evidence atom per hop, and
never adopted without checking the numeric repository id -- a matching path is
not a matching repository. And a difference between our per-response charge sum
and the provider's own counter must be reported as a difference, not classified
into a cause we cannot see from here.

Every test that concerns assembly drives `get()` or `reconcile()` through a stub
rather than building the dataclass by hand. INC-V2-113 has recurred five times
in this study: a unit test of a guard is not a test that the guard is wired in.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir8_provider_accounting as accounting  # noqa: E402
import sfir8_transport as transport  # noqa: E402

# ---------------------------------------------------------------- stub server


class _Headers(dict):
    """Case-insensitive enough for what the transport reads."""

    def get(self, name, default=None):
        for key, value in self.items():
            if key.casefold() == name.casefold():
                return value
        return default


class _Response(io.BytesIO):
    def __init__(self, status, headers, body):
        super().__init__(body)
        self.status = status
        self.headers = _Headers(headers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _Server:
    """A scripted opener. Records every URL it is asked for, in order."""

    def __init__(self, routes):
        self.routes = routes
        self.seen: list[str] = []
        self.headers_seen: list[dict] = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.seen.append(url)
        self.headers_seen.append(dict(request.headers))
        if url not in self.routes:
            raise AssertionError(f"unscripted request to {url}")
        status, headers, body = self.routes[url]
        return _Response(status, headers, body)


def _install(monkeypatch, server):
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *a: server)
    return server


def _json(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _rate(remaining: int, request_id: str = "req-1") -> dict:
    return {"x-ratelimit-remaining": str(remaining), "x-github-request-id": request_id}


REPO = "https://api.github.com/repos/facebook/react"
MOVED = "https://api.github.com/repos/react/react"


# ------------------------------------------------- the redirect is ours to follow


def test_a_redirect_is_followed_by_the_instrument_and_recorded_as_two_atoms(monkeypatch):
    server = _install(
        monkeypatch,
        _Server(
            {
                REPO: (301, {**_rate(4999), "Location": MOVED}, b""),
                MOVED: (200, _rate(4998, "req-2"), _json({"id": 10270250})),
            }
        ),
    )
    client = transport.ManualRedirectTransport()
    result = client.get(REPO)

    assert server.seen == [REPO, MOVED], "the instrument issued both hops itself"
    assert result.network_hops == 2
    assert [a.hop_index for a in result.atoms] == [0, 1]
    assert [a.requested_url for a in result.atoms] == [REPO, MOVED]
    assert result.status == 200
    assert result.final_url == MOVED
    assert result.redirected is True


def test_the_no_redirect_handler_hands_the_response_back(monkeypatch):
    """The unit: returning None is what makes urllib stop and give us the 301."""
    handler = transport._NoRedirect()
    assert handler.redirect_request(None, None, 301, "Moved", {}, MOVED) is None


def test_the_no_redirect_handler_is_installed_on_the_opener_that_fetches(monkeypatch):
    """The wiring. A handler that exists but is never installed follows nothing.

    Mutation T1 removed the handler from `build_opener` and every other control
    stayed green, because the stub server replaces `build_opener` wholesale and
    never looks at its arguments. This one looks.
    """
    installed = []

    def _build_opener(*handlers):
        installed.append(handlers)
        return _Server({REPO: (200, _rate(4999), _json({"id": 1}))})

    monkeypatch.setattr(transport.urllib.request, "build_opener", _build_opener)
    transport.ManualRedirectTransport().get(REPO)

    assert installed, "no opener was built"
    assert any(
        isinstance(handler, transport._NoRedirect) for handler in installed[0]
    ), "the fetch path built an opener that would follow redirects on its own"


def test_the_reported_redirect_policy_is_derived_from_the_installed_handler(monkeypatch):
    """`automatic_redirect_following: False` must be a reading, not a claim."""
    client = transport.ManualRedirectTransport()
    assert client.totals()["automatic_redirect_following"] is False

    class _Following(transport.urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return object()

    monkeypatch.setattr(client, "REDIRECT_HANDLER", _Following)
    assert client.totals()["automatic_redirect_following"] is True, (
        "the receipt would have gone on claiming manual following after the "
        "transport stopped doing it"
    )


def test_the_redirect_target_is_stored_as_a_digest_not_as_an_address(monkeypatch):
    _install(
        monkeypatch,
        _Server(
            {
                REPO: (301, {**_rate(4999), "Location": MOVED}, b""),
                MOVED: (200, _rate(4998), _json({"id": 1})),
            }
        ),
    )
    result = transport.ManualRedirectTransport().get(REPO)
    expected = "sha256:" + hashlib.sha256(MOVED.encode()).hexdigest()
    assert result.atoms[0].redirect_target_digest == expected
    assert result.atoms[1].redirect_target_digest is None


def test_a_relative_location_resolves_against_the_url_that_issued_it(monkeypatch):
    server = _install(
        monkeypatch,
        _Server(
            {
                REPO: (301, {**_rate(4999), "Location": "/repos/react/react"}, b""),
                MOVED: (200, _rate(4998), _json({"id": 1})),
            }
        ),
    )
    transport.ManualRedirectTransport().get(REPO)
    assert server.seen[1] == MOVED


def test_a_redirect_without_a_location_is_refused_rather_than_guessed(monkeypatch):
    _install(monkeypatch, _Server({REPO: (301, _rate(4999), b"")}))
    with pytest.raises(transport.RedirectRefused, match="no Location"):
        transport.ManualRedirectTransport().get(REPO)


def test_a_chain_longer_than_the_hop_bound_is_refused(monkeypatch):
    hops = {
        f"https://api.github.com/r/{i}": (
            301,
            {**_rate(4999 - i), "Location": f"https://api.github.com/r/{i + 1}"},
            b"",
        )
        for i in range(12)
    }
    _install(monkeypatch, _Server(hops))
    client = transport.ManualRedirectTransport(max_hops=3)
    with pytest.raises(transport.RedirectRefused, match="exceeded 3 hops"):
        client.get("https://api.github.com/r/0")


def test_a_refused_chain_does_not_count_as_a_completed_logical_request(monkeypatch):
    """A request that never resolved must not inflate the logical count."""
    _install(monkeypatch, _Server({REPO: (301, _rate(4999), b"")}))
    client = transport.ManualRedirectTransport()
    with pytest.raises(transport.RedirectRefused):
        client.get(REPO)
    assert client.totals()["logical_requests"] == 0


def test_a_chain_refused_at_the_hop_bound_also_counts_no_logical_request(monkeypatch):
    """The other refusal path. Mutation T10 survived because only one was covered."""
    hops = {
        f"https://api.github.com/r/{i}": (
            301,
            {**_rate(4999 - i), "Location": f"https://api.github.com/r/{i + 1}"},
            b"",
        )
        for i in range(12)
    }
    _install(monkeypatch, _Server(hops))
    client = transport.ManualRedirectTransport(max_hops=3)
    with pytest.raises(transport.RedirectRefused, match="exceeded"):
        client.get("https://api.github.com/r/0")
    assert client.totals()["logical_requests"] == 0
    assert client.totals()["network_hops"] == 0, (
        "hops belonging to an unresolved request must not be attributed to a "
        "request that never completed"
    )


def test_an_http_error_is_a_response_not_an_exception(monkeypatch):
    class _Failing:
        def open(self, request, timeout=None):
            raise transport.urllib.error.HTTPError(
                REPO, 404, "Not Found", _Headers(_rate(4999)), io.BytesIO(b"{}")
            )

    _install(monkeypatch, _Failing())
    result = transport.ManualRedirectTransport().get(REPO)
    assert result.status == 404
    assert result.provider_charged is None or result.network_hops == 1


# ------------------------------------------------------- three layers, kept apart


def test_the_three_layers_are_counted_separately(monkeypatch):
    _install(
        monkeypatch,
        _Server(
            {
                REPO: (301, {**_rate(4999), "Location": MOVED}, b""),
                MOVED: (200, _rate(4997), _json({"id": 1})),
            }
        ),
    )
    client = transport.ManualRedirectTransport()
    client._remaining = 5000
    result = client.get(REPO)
    totals = client.totals()

    assert totals["logical_requests"] == 1
    assert totals["network_hops"] == 2
    assert totals["provider_charged"] == 3, "1 on the redirect, 2 on the target"
    assert result.provider_charged == 3


def test_a_response_without_rate_headers_yields_no_charge_rather_than_zero(monkeypatch):
    """Absent accounting is unknown, not free. Zero would be a fabricated number."""
    _install(monkeypatch, _Server({REPO: (200, {}, _json({"id": 1}))}))
    client = transport.ManualRedirectTransport()
    result = client.get(REPO)
    assert result.provider_charged is None
    assert result.atoms[0].provider_charge_delta is None
    assert client.totals()["requests_with_provider_accounting"] == 0


def test_the_body_digest_is_of_the_bytes_received(monkeypatch):
    body = _json({"id": 1})
    _install(monkeypatch, _Server({REPO: (200, _rate(4999), body)}))
    result = transport.ManualRedirectTransport().get(REPO)
    assert result.atoms[0].response_body_sha256 == "sha256:" + hashlib.sha256(body).hexdigest()


# --------------------------------------------------------------- no credentials


def test_no_secret_header_can_reach_an_atom(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_ThisMustNeverAppearAnywhere")
    _install(
        monkeypatch,
        _Server(
            {
                REPO: (
                    200,
                    {
                        **_rate(4999),
                        "Authorization": "Bearer ghp_ThisMustNeverAppearAnywhere",
                        "Cookie": "session=ghp_ThisMustNeverAppearAnywhere",
                    },
                    _json({"id": 1}),
                )
            }
        ),
    )
    client = transport.ManualRedirectTransport()
    client.get(REPO)
    serialized = json.dumps(client.atoms())
    assert "ghp_ThisMustNeverAppearAnywhere" not in serialized
    assert "Bearer" not in serialized


def test_the_secret_header_reader_refuses_by_name_not_by_value(monkeypatch):
    headers = _Headers({"Authorization": "Bearer x", "X-GitHub-Request-Id": "abc"})
    assert transport._header_str(headers, "authorization") is None
    assert transport._header_str(headers, "Cookie") is None
    assert transport._header_str(headers, "x-github-request-id") == "abc"


def test_the_token_is_actually_sent_even_though_it_is_never_recorded(monkeypatch):
    """The guard must not be satisfied by simply not authenticating."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_live")
    server = _install(monkeypatch, _Server({REPO: (200, _rate(4999), _json({"id": 1}))}))
    transport.ManualRedirectTransport().get(REPO)
    sent = {k.casefold(): v for k, v in server.headers_seen[0].items()}
    assert sent.get("authorization") == "Bearer ghp_live"


# ------------------------------------------------------------ identity is checked


def _rename_routes(observed_id):
    return {
        REPO: (301, {**_rate(4999), "Location": MOVED}, b""),
        MOVED: (
            200,
            _rate(4998),
            _json({"id": observed_id, "full_name": "react/react", "default_branch": "main"}),
        ),
    }


def test_a_matching_numeric_id_adopts_the_canonical_address(monkeypatch):
    _install(monkeypatch, _Server(_rename_routes(10270250)))
    client = transport.ManualRedirectTransport()
    resolution = client.resolve_canonical_address("facebook/react", "10270250")

    assert resolution["identity_verified"] is True
    assert resolution["renamed"] is True
    assert resolution["canonical_address"] == "react/react"
    assert client.address_for("facebook/react") == "react/react"


def test_a_mismatched_numeric_id_refuses_instead_of_adopting_the_redirect(monkeypatch):
    """HTTP 200, real repository, wrong one. The fourth gate."""
    _install(monkeypatch, _Server(_rename_routes(999999)))
    client = transport.ManualRedirectTransport()
    with pytest.raises(transport.IdentityRefused, match="NOT adopted"):
        client.resolve_canonical_address("facebook/react", "10270250")
    assert "facebook/react" not in client.canonical
    assert client.address_for("facebook/react") == "facebook/react"


def test_a_non_200_metadata_response_refuses_the_root(monkeypatch):
    _install(monkeypatch, _Server({REPO: (404, _rate(4999), _json({}))}))
    with pytest.raises(transport.IdentityRefused, match="identity"):
        transport.ManualRedirectTransport().resolve_canonical_address(
            "facebook/react", "10270250"
        )


def test_a_missing_repository_id_refuses(monkeypatch):
    _install(
        monkeypatch,
        _Server({REPO: (200, _rate(4999), _json({"full_name": "facebook/react"}))}),
    )
    with pytest.raises(transport.IdentityRefused, match="no repository id"):
        transport.ManualRedirectTransport().resolve_canonical_address(
            "facebook/react", "10270250"
        )


def test_a_missing_canonical_name_refuses_rather_than_falling_back(monkeypatch):
    _install(monkeypatch, _Server({REPO: (200, _rate(4999), _json({"id": 10270250}))}))
    with pytest.raises(transport.IdentityRefused, match="canonical name"):
        transport.ManualRedirectTransport().resolve_canonical_address(
            "facebook/react", "10270250"
        )


def test_an_unmoved_repository_resolves_to_itself_and_is_not_marked_renamed(monkeypatch):
    _install(
        monkeypatch,
        _Server(
            {
                REPO: (
                    200,
                    _rate(4999),
                    _json({"id": 10270250, "full_name": "facebook/react"}),
                )
            }
        ),
    )
    client = transport.ManualRedirectTransport()
    resolution = client.resolve_canonical_address("facebook/react", "10270250")
    assert resolution["renamed"] is False
    assert resolution["hops_spent_resolving"] == 1


def test_the_toll_is_paid_once_and_not_on_every_later_request(monkeypatch):
    """The whole point of resolving: SFIR7 spent 790 charges re-paying it."""
    routes = _rename_routes(10270250)
    routes["https://api.github.com/repos/react/react/git/trees/abc"] = (
        200,
        _rate(4997),
        _json({"tree": []}),
    )
    _install(monkeypatch, _Server(routes))
    client = transport.ManualRedirectTransport()
    client.resolve_canonical_address("facebook/react", "10270250")
    address = client.address_for("facebook/react")
    later = client.get(f"https://api.github.com/repos/{address}/git/trees/abc")
    assert later.network_hops == 1, "the canonical address does not redirect"
    assert later.redirected is False


# ------------------------------------------------- provider reconciliation


def _reading(used, remaining=5000, reset=1000):
    return accounting.GlobalReading(
        limit=5000, remaining=remaining, used=used, reset_epoch=reset
    )


def test_a_complete_accounting_reports_zero_and_says_so():
    result = accounting.reconcile(
        before=_reading(0),
        after=_reading(76),
        logical_request_count=36,
        network_hop_count=72,
        per_request_charge_sum=76,
        credential_exclusivity_established=True,
    )
    assert result["UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA"] == 0
    assert result["accounting_is_complete"] is True


def test_a_gap_is_reported_as_a_difference_and_not_classified():
    result = accounting.reconcile(
        before=_reading(0),
        after=_reading(100),
        logical_request_count=36,
        network_hop_count=72,
        per_request_charge_sum=76,
    )
    assert result["UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA"] == 24
    assert result["accounting_is_complete"] is False
    disclaimer = result["what_a_nonzero_delta_does_not_establish"].casefold()
    for cause in ("secondary", "another process", "provider-side"):
        assert cause in disclaimer
    assert "because" not in disclaimer, "no cause is being asserted"


def test_a_window_reset_refuses_to_compute_rather_than_reporting_zero():
    """`used` resets with the window. Subtracting across it invents a number."""
    result = accounting.reconcile(
        before=_reading(4000, reset=1000),
        after=_reading(12, reset=4600),
        logical_request_count=12,
        network_hop_count=12,
        per_request_charge_sum=12,
    )
    assert result["rate_window_reset_mid_measurement"] is True
    assert result["counts"]["provider_used_delta"] is None
    assert result["UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA"] is None
    assert result["accounting_is_complete"] is False
    assert any("reset" in limit for limit in result["limitations"])


def test_unestablished_credential_exclusivity_is_a_recorded_limitation():
    result = accounting.reconcile(
        before=_reading(0),
        after=_reading(10),
        logical_request_count=10,
        network_hop_count=10,
        per_request_charge_sum=10,
        credential_exclusivity_established=False,
    )
    assert any("exclusive" in limit for limit in result["limitations"])


def test_the_three_internal_sums_are_reported_independently():
    result = accounting.reconcile(
        before=_reading(0),
        after=_reading(76),
        logical_request_count=36,
        network_hop_count=72,
        per_request_charge_sum=76,
    )
    counts = result["counts"]
    assert counts["logical_request_count"] == 36
    assert counts["network_hop_count"] == 72
    assert counts["per_request_charge_sum"] == 76
    assert result["hops_equal_charges"] is False
    assert result["logical_equals_charges"] is False


def test_read_global_parses_the_core_resource(monkeypatch):
    payload = _json(
        {"resources": {"core": {"limit": 5000, "remaining": 4900, "used": 100, "reset": 77}}}
    )

    def _opener(request, timeout=None):
        assert request.full_url == "https://api.github.com/rate_limit"
        return _Response(200, {}, payload)

    reading = accounting.read_global(opener=_opener)
    assert (reading.limit, reading.remaining, reading.used, reading.reset_epoch) == (
        5000,
        4900,
        100,
        77,
    )
