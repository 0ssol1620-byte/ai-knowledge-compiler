"""Contract tests for cap_v1 capability tokens (pure stdlib module).

The verifier is the security boundary, so these tests pin its fail-closed
behaviour case by case: the five negative classes -- expiry, audience
mismatch, tampering, jti revocation, insufficient scope -- plus the malformed
inputs an attacker would try before any of those.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from akc_cir import (
    CAPABILITY_SCOPES,
    MAX_TTL_SECONDS,
    Claims,
    InMemoryRevocationStore,
    TokenError,
    mint,
    require_scope,
    verify,
)

SECRET = "unit-test-capability-signing-secret"
NOW = 1_800_000_000  # fixed epoch so every token in this module is reproducible


def _mint_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "sub": "user:0f1e2d3c",
        "scopes": ["worlds:read"],
        "aud": "ai-knowledge-compiler",
        "secret": SECRET,
        "now": NOW,
        "ttl_seconds": 600,
        "jti": "jti-fixed-1",
    }
    kwargs.update(overrides)
    return kwargs


def _payload_of(token: str) -> dict[str, object]:
    part = token.split(".")[1]
    raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    payload: dict[str, object] = json.loads(raw)
    return payload


def _header_of(token: str) -> dict[str, object]:
    part = token.split(".")[0]
    raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    header: dict[str, object] = json.loads(raw)
    return header


def _b64_payload(obj: dict[str, object]) -> str:
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _encoded_cap_v1_header() -> str:
    return _b64_payload({"alg": "HS256", "typ": "cap_v1"})


def _sign(encoded_header_dot_payload: str) -> str:
    digest = hmac.new(SECRET.encode(), encoded_header_dot_payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Round trip and determinism
# ---------------------------------------------------------------------------


def test_mint_then_verify_roundtrips_every_claim() -> None:
    token = mint(**_mint_kwargs())  # type: ignore[arg-type]

    claims = verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW + 30)

    assert isinstance(claims, Claims)
    assert claims.sub == "user:0f1e2d3c"
    assert claims.scopes == ("worlds:read",)
    assert claims.aud == "ai-knowledge-compiler"
    assert claims.iat == NOW
    assert claims.exp == NOW + 600
    assert claims.jti == "jti-fixed-1"


def test_mint_is_deterministic_for_fixed_inputs() -> None:
    # Same sub/scopes/aud/now/jti must yield byte-identical tokens: canonical
    # JSON with sorted keys, no whitespace, one encoding rule.
    first = mint(**_mint_kwargs())  # type: ignore[arg-type]
    second = mint(**_mint_kwargs())  # type: ignore[arg-type]

    assert first == second


def test_header_declares_hs256_and_cap_v1() -> None:
    header = _header_of(mint(**_mint_kwargs()))  # type: ignore[arg-type]

    assert header == {"alg": "HS256", "typ": "cap_v1"}


def test_token_is_three_base64url_parts_without_padding() -> None:
    token = mint(**_mint_kwargs())  # type: ignore[arg-type]

    parts = token.split(".")
    assert len(parts) == 3
    assert all("=" not in part and "+" not in part and "/" not in part for part in parts)


def test_scopes_are_deduplicated_preserving_first_seen_order() -> None:
    token = mint(
        **_mint_kwargs(scopes=["export:run", "worlds:read", "export:run"])  # type: ignore[arg-type]
    )

    claims = verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert claims.scopes == ("export:run", "worlds:read")


# ---------------------------------------------------------------------------
# Negative class 1: expiry
# ---------------------------------------------------------------------------


def test_expired_token_is_rejected() -> None:
    token = mint(**_mint_kwargs(ttl_seconds=600))  # type: ignore[arg-type]

    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW + 601)
    assert excinfo.value.code == "TOKEN_EXPIRED"


def test_expiry_boundary_is_fail_closed() -> None:
    # now == exp means zero seconds of life remain; that is expired.
    token = mint(**_mint_kwargs(ttl_seconds=600))  # type: ignore[arg-type]

    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW + 600)
    assert excinfo.value.code == "TOKEN_EXPIRED"


def test_future_issued_token_beyond_leeway_is_rejected() -> None:
    token = mint(**_mint_kwargs(now=NOW))  # type: ignore[arg-type]

    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW - 3600)
    assert excinfo.value.code == "TOKEN_MALFORMED"


# ---------------------------------------------------------------------------
# Negative class 2: audience mismatch
# ---------------------------------------------------------------------------


def test_audience_mismatch_is_rejected() -> None:
    token = mint(**_mint_kwargs(aud="ai-knowledge-compiler"))  # type: ignore[arg-type]

    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="other-service", secret=SECRET, now=NOW + 30)
    assert excinfo.value.code == "AUDIENCE_MISMATCH"


# ---------------------------------------------------------------------------
# Negative class 3: tampering / wrong key
# ---------------------------------------------------------------------------


def test_tampered_payload_is_rejected() -> None:
    token = mint(**_mint_kwargs())  # type: ignore[arg-type]
    header, _, signature = token.split(".")
    forged_payload = _b64_payload({**_payload_of(token), "scopes": ["export:run"]})

    forged = f"{header}.{forged_payload}.{signature}"
    with pytest.raises(TokenError) as excinfo:
        verify(forged, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "BAD_SIGNATURE"


def test_tampered_signature_is_rejected() -> None:
    token = mint(**_mint_kwargs())  # type: ignore[arg-type]
    header, payload, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

    with pytest.raises(TokenError) as excinfo:
        verify(f"{header}.{payload}.{flipped}", aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "BAD_SIGNATURE"


def test_token_signed_with_different_secret_is_rejected() -> None:
    token = mint(**_mint_kwargs(secret="attacker-known-secret"))  # type: ignore[arg-type]

    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "BAD_SIGNATURE"


def test_session_style_jwt_payload_swapped_into_cap_v1_envelope_is_rejected() -> None:
    # Cross-protocol confusion: a payload copied from another token format
    # still fails because it does not carry cap_v1's exact claim shape.
    envelope = mint(**_mint_kwargs())  # type: ignore[arg-type]
    header, _, signature = envelope.split(".")
    session_like = _b64_payload(
        {"sub": "x", "typ": "session", "tid": "t", "exp": NOW + 99}
    )

    swapped = f"{header}.{session_like}.{signature}"
    with pytest.raises(TokenError):
        verify(swapped, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)


# ---------------------------------------------------------------------------
# Negative class 4: jti revocation
# ---------------------------------------------------------------------------


def test_revoked_jti_is_rejected() -> None:
    store = InMemoryRevocationStore()
    token = mint(**_mint_kwargs())  # type: ignore[arg-type]

    ok = verify(
        token,
        aud="ai-knowledge-compiler",
        secret=SECRET,
        now=NOW,
        revocation_store=store,
    )
    assert ok.jti == "jti-fixed-1"

    store.revoke("jti-fixed-1")

    with pytest.raises(TokenError) as excinfo:
        verify(
            token,
            aud="ai-knowledge-compiler",
            secret=SECRET,
            now=NOW,
            revocation_store=store,
        )
    assert excinfo.value.code == "JTI_REVOKED"


def test_verification_without_a_store_skips_revocation_but_still_verifies() -> None:
    # Revocation checking is opt-in at the call site so offline tooling can
    # still validate structure/signature; deployments that care pass a store.
    token = mint(**_mint_kwargs())  # type: ignore[arg-type]

    claims = verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert claims.jti == "jti-fixed-1"


def test_in_memory_store_reports_and_requires_jti() -> None:
    store = InMemoryRevocationStore()

    assert store.is_revoked("missing") is False
    store.revoke("gone")
    assert store.is_revoked("gone") is True

    with pytest.raises(ValueError):
        store.revoke("")


# ---------------------------------------------------------------------------
# Negative class 5: scope enforcement
# ---------------------------------------------------------------------------


def test_require_scope_passes_matching_claims_through() -> None:
    claims = Claims(
        sub="user:x",
        scopes=("worlds:read", "search:run"),
        aud="ai-knowledge-compiler",
        iat=NOW,
        exp=NOW + 1,
        jti="j",
    )

    assert require_scope(claims, "search:run") is claims


def test_require_scope_refuses_missing_scope() -> None:
    claims = Claims(
        sub="user:x",
        scopes=("worlds:read",),
        aud="ai-knowledge-compiler",
        iat=NOW,
        exp=NOW + 1,
        jti="j",
    )

    with pytest.raises(TokenError) as excinfo:
        require_scope(claims, "export:run")
    assert excinfo.value.code == "SCOPE_INSUFFICIENT"


# ---------------------------------------------------------------------------
# Malformed inputs and issuance validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-token",
        "only.two",
        "one.too.many.parts",
        "..",
        # Valid base64url but not JSON in the header slot.
        "bm90LWpzb24.e30.c2ln",
    ],
)
def test_structurally_broken_tokens_are_rejected(token: str) -> None:
    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "TOKEN_MALFORMED"


def test_garbage_payload_with_valid_header_fails_signature_first() -> None:
    # Order matters: authenticity is established before the claims are read,
    # so junk inside an envelope never gets parsed as claims.
    junk = "not-base64!!"
    token = (
        f"{_encoded_cap_v1_header()}.{junk}"
        f".{_sign(_encoded_cap_v1_header() + '.' + junk)}"
    )

    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "BAD_SIGNATURE"


@pytest.mark.parametrize(
    "header_obj",
    [
        {"alg": "none", "typ": "cap_v1"},
        {"alg": "HS256", "typ": "JWT"},
        {"typ": "cap_v1"},
        {"alg": "HS512", "typ": "cap_v1"},
    ],
)
def test_non_cap_v1_headers_are_rejected_before_signature(header_obj: dict[str, str]) -> None:
    # Algorithm negotiation does not exist in cap_v1: a header proposing
    # anything else is not a downgrade to weigh, it is simply not this format.
    encoded_header = _b64_payload(header_obj)  # type: ignore[arg-type]
    encoded_payload = _b64_payload(_payload_of(mint(**_mint_kwargs())))  # type: ignore[arg-type]

    token = f"{encoded_header}.{encoded_payload}.c2ln"
    with pytest.raises(TokenError) as excinfo:
        verify(token, aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "TOKEN_MALFORMED"


def _resigned(payload: dict[str, object]) -> str:
    encoded = _b64_payload(payload)
    return f"{_encoded_cap_v1_header()}.{encoded}.{_sign(f'{_encoded_cap_v1_header()}.{encoded}')}"


@pytest.mark.parametrize(
    "field",
    ["sub", "aud", "iat", "exp", "jti", "scopes"],
)
def test_missing_claims_are_rejected(field: str) -> None:
    payload = _payload_of(mint(**_mint_kwargs()))  # type: ignore[arg-type]
    del payload[field]

    with pytest.raises(TokenError) as excinfo:
        verify(_resigned(payload), aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "TOKEN_MALFORMED"


def test_inverted_exp_is_rejected_as_malformed() -> None:
    payload = {**_payload_of(mint(**_mint_kwargs())), "exp": NOW - 1}  # type: ignore[arg-type]

    with pytest.raises(TokenError) as excinfo:
        verify(_resigned(payload), aud="ai-knowledge-compiler", secret=SECRET, now=NOW)
    assert excinfo.value.code == "TOKEN_MALFORMED"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sub": ""},
        {"sub": "   "},
        {"sub": "x" * 256},
        {"aud": ""},
        {"aud": "x" * 256},
        {"scopes": []},
        {"scopes": ["worlds:read", "admin:everything"]},
        {"ttl_seconds": 0},
        {"ttl_seconds": -5},
        {"ttl_seconds": MAX_TTL_SECONDS + 1},
        {"jti": ""},
        {"jti": "x" * 129},
    ],
)
def test_mint_refuses_inputs_that_would_weaken_a_token(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        mint(**_mint_kwargs(**kwargs))  # type: ignore[arg-type]


def test_capability_scope_vocabulary_matches_contract() -> None:
    assert frozenset(
        {"worlds:read", "search:run", "evidence:read", "export:run"}
    ) == CAPABILITY_SCOPES
