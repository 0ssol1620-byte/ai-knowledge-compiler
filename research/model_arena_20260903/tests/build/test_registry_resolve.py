"""registry_resolve.py: pure parsing (no network) plus a mocked-transport
digest resolution (no network -- httpx.MockTransport intercepts every
request deterministically)."""

from __future__ import annotations

import httpx
import pytest
from registry_resolve import (
    RegistryResolveError,
    parse_image_ref,
    resolve_digest,
)


def test_parse_plain_docker_hub_ref() -> None:
    ref = parse_image_ref("vllm/vllm-openai:v0.21.0")
    assert ref.registry_host == "registry-1.docker.io"
    assert ref.repository == "vllm/vllm-openai"
    assert ref.tag == "v0.21.0"
    assert ref.embedded_digest is None


def test_parse_library_image_gets_library_prefix() -> None:
    ref = parse_image_ref("python:3.12-slim")
    assert ref.repository == "library/python"


def test_parse_ref_with_explicit_registry_host() -> None:
    ref = parse_image_ref("ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6:latest")
    assert ref.registry_host == "ghcr.io"
    assert ref.repository == "0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6"
    assert ref.tag == "latest"


def test_parse_ref_with_embedded_digest() -> None:
    digest = "sha256:" + "a" * 64
    ref = parse_image_ref(f"vllm/vllm-openai:v0.21.0@{digest}")
    assert ref.embedded_digest == digest
    assert ref.tag == "v0.21.0"


def test_parse_ref_with_only_digest_no_tag() -> None:
    digest = "sha256:" + "b" * 64
    ref = parse_image_ref(f"docker.io/vllm/vllm-openai@{digest}")
    assert ref.embedded_digest == digest
    assert ref.tag is None


def test_parse_ref_with_registry_host_that_has_a_port() -> None:
    ref = parse_image_ref("localhost:5000/my/image:tag")
    assert ref.registry_host == "localhost:5000"
    assert ref.repository == "my/image"
    assert ref.tag == "tag"


@pytest.mark.parametrize("bad_ref", ["", "   ", "no-tag-no-digest-repo"])
def test_parse_rejects_malformed_refs(bad_ref: str) -> None:
    with pytest.raises(RegistryResolveError):
        parse_image_ref(bad_ref)


def test_resolve_digest_with_embedded_digest_never_makes_a_request() -> None:
    digest = "sha256:" + "c" * 64

    def _unreachable(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call should happen for an embedded digest")

    with httpx.Client(transport=httpx.MockTransport(_unreachable)) as client:
        result = resolve_digest(f"vllm/vllm-openai:v0.21.0@{digest}", client=client)
    assert result.digest == digest
    assert result.resolved is True
    assert result.method == "embedded_in_reference"


def test_resolve_digest_direct_200(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = "sha256:" + "d" * 64

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"docker-content-digest": digest})

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = resolve_digest("some/repo:tag", client=client)
    assert result.digest == digest
    assert result.resolved is True
    assert result.http_status == 200


def test_resolve_digest_401_then_token_then_200(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = "sha256:" + "e" * 64
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url).startswith("https://auth.example.com/token"):
            return httpx.Response(200, json={"token": "anon-token"})
        if "Authorization" not in request.headers:
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": 'Bearer realm="https://auth.example.com/token",service="example"'
                },
            )
        assert request.headers["Authorization"] == "Bearer anon-token"
        return httpx.Response(200, headers={"docker-content-digest": digest})

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = resolve_digest("myregistry.example.com/some/repo:tag", client=client)
    assert result.digest == digest
    assert result.resolved is True
    assert result.method == "anonymous_manifest_get"
    assert len(calls) == 3  # initial 401, token, authenticated retry


def test_resolve_digest_404_is_not_resolved_but_is_not_an_exception() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = resolve_digest("some/repo:missing-tag", client=client)
    assert result.digest is None
    assert result.resolved is False
    assert result.http_status == 404


def test_resolve_digest_denied_anonymous_token_is_not_resolved() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if "/token" in str(request.url):
            return httpx.Response(403)
        return httpx.Response(
            401,
            headers={"www-authenticate": 'Bearer realm="https://auth.example.com/token",service="x"'},
        )

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = resolve_digest("private.example.com/some/repo:tag", client=client)
    assert result.digest is None
    assert result.resolved is False
    assert "403" in result.detail


def test_resolve_digest_transport_failure_is_reported_not_raised() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = resolve_digest("unreachable.example.com/some/repo:tag", client=client)
    assert result.digest is None
    assert result.resolved is False
    assert "ConnectTimeout" in result.detail


def test_resolve_command_is_always_present_even_on_failure() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = resolve_digest("some/repo:missing-tag", client=client)
    assert "docker buildx imagetools inspect some/repo:missing-tag" in result.resolve_command
