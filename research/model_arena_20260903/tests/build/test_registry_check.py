"""registry_check.py: pure parsing/classification logic, no network and no
subprocess. The live gh/GHCR calls are exercised manually (see BUILD_PLAN.md),
never by pytest -- CI must not depend on gh being installed or authenticated."""

from __future__ import annotations

import pytest
import registry_check
from registry_check import (
    REQUIRED_SCOPES,
    ManifestCheck,
    check_target_manifest,
    classify_scopes,
    parse_http_status,
    parse_oauth_scopes,
)
from registry_resolve import RegistryLookup

_SAMPLE_GH_OUTPUT = """HTTP/2.0 200 OK
Access-Control-Expose-Headers: ETag, Link
X-Accepted-Oauth-Scopes:
X-Oauth-Scopes: repo, user, write:packages, workflow

{"login": "0ssol1620-byte"}
"""


def test_parse_http_status_from_gh_dash_i_output() -> None:
    assert parse_http_status(_SAMPLE_GH_OUTPUT) == 200


def test_parse_http_status_missing_returns_none() -> None:
    assert parse_http_status("no status line here") is None


def test_parse_oauth_scopes_extracts_comma_separated_list() -> None:
    scopes = parse_oauth_scopes(_SAMPLE_GH_OUTPUT)
    assert scopes == ("repo", "user", "write:packages", "workflow")


def test_parse_oauth_scopes_missing_header_returns_none() -> None:
    assert parse_oauth_scopes("HTTP/2.0 200 OK\n\n{}\n") is None


def test_parse_oauth_scopes_empty_header_returns_empty_tuple() -> None:
    text = "HTTP/2.0 200 OK\nX-Oauth-Scopes: \n\n{}\n"
    assert parse_oauth_scopes(text) == ()


def test_classify_scopes_ok_when_write_packages_present() -> None:
    report = classify_scopes(_SAMPLE_GH_OUTPUT)
    assert report.ok is True
    assert report.missing_required == ()
    assert "write:packages" in (report.scopes or ())


def test_classify_scopes_reports_missing_required() -> None:
    text = "HTTP/2.0 200 OK\nX-Oauth-Scopes: repo, user\n\n{}\n"
    report = classify_scopes(text)
    assert report.ok is False
    assert report.missing_required == REQUIRED_SCOPES


def test_classify_scopes_non_200_is_not_ok() -> None:
    text = "HTTP/2.0 401 Unauthorized\nX-Oauth-Scopes: repo\n\n{}\n"
    report = classify_scopes(text)
    assert report.ok is False
    assert report.error is not None


def test_classify_scopes_no_scopes_header_is_unknown_not_ok() -> None:
    text = "HTTP/2.0 200 OK\n\n{}\n"
    report = classify_scopes(text)
    assert report.ok is False
    assert report.scopes is None
    assert report.error is not None


def test_classify_scopes_propagates_explicit_error() -> None:
    report = classify_scopes("", error="gh CLI is not installed")
    assert report.ok is False
    assert report.error == "gh CLI is not installed"
    assert report.missing_required == REQUIRED_SCOPES


def test_check_target_manifest_404_means_not_yet_pushed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_resolve(ref: str, **kwargs: object) -> RegistryLookup:
        return RegistryLookup(
            ref=ref, digest=None, resolved=False, method="anonymous_manifest_get",
            detail="404", resolve_command="docker buildx imagetools inspect x", http_status=404,
        )

    monkeypatch.setattr(registry_check, "resolve_digest", _fake_resolve)
    result = check_target_manifest("ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6")
    assert isinstance(result, ManifestCheck)
    assert result.already_pushed is False
    assert result.model_key == "paddleocr_vl_1_6"


def test_check_target_manifest_resolved_means_already_pushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "sha256:" + "a" * 64

    def _fake_resolve(ref: str, **kwargs: object) -> RegistryLookup:
        return RegistryLookup(
            ref=ref, digest=digest, resolved=True, method="anonymous_manifest_get",
            detail="200", resolve_command="docker buildx imagetools inspect x", http_status=200,
        )

    monkeypatch.setattr(registry_check, "resolve_digest", _fake_resolve)
    result = check_target_manifest("ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6")
    assert result.already_pushed is True
    assert digest in result.detail


def test_check_target_manifest_denied_token_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real, observed GHCR behaviour for a namespace that has never been
    pushed to: the anonymous token endpoint itself denies (403), not a 404 on
    the manifest. Must be reported as inconclusive, never as "not pushed"."""

    def _fake_resolve(ref: str, **kwargs: object) -> RegistryLookup:
        return RegistryLookup(
            ref=ref, digest=None, resolved=False, method="anonymous_token_exchange",
            detail="token endpoint returned 403", resolve_command="x", http_status=403,
        )

    monkeypatch.setattr(registry_check, "resolve_digest", _fake_resolve)
    result = check_target_manifest("ghcr.io/0ssol1620-byte/tavonel-arena/hpd_parsing")
    assert result.already_pushed is None
    assert "inconclusive" in result.detail
