"""image_config_inspect.py: mocked-transport manifest + config-blob reads
(no network -- httpx.MockTransport intercepts every request deterministically,
matching test_registry_resolve.py's convention)."""

from __future__ import annotations

import httpx
from image_config_inspect import inspect_base_image_config


def test_offline_never_makes_a_request() -> None:
    def _unreachable(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call should happen when offline=True")

    with httpx.Client(transport=httpx.MockTransport(_unreachable)) as client:
        result = inspect_base_image_config("some/repo:tag", offline=True, client=client)
    assert result.resolved is False
    assert "offline" in result.detail
    assert result.entrypoint is None
    assert result.cmd is None
    assert result.source is None


def test_malformed_ref_is_reported_not_raised() -> None:
    result = inspect_base_image_config("no-tag-no-digest-repo", offline=False)
    assert result.resolved is False
    assert "malformed" in result.detail


_CONFIG_DIGEST = "sha256:" + "f" * 64
_MANIFEST_DIGEST = "sha256:" + "a" * 64


def _single_arch_manifest_handler(config_body: dict[str, object]):
    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith(f"/manifests/{_MANIFEST_DIGEST}") or "/manifests/" in url:
            return httpx.Response(
                200,
                json={
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {"digest": _CONFIG_DIGEST},
                },
                headers={"docker-content-digest": _MANIFEST_DIGEST},
            )
        if f"/blobs/{_CONFIG_DIGEST}" in url:
            return httpx.Response(200, json=config_body)
        raise AssertionError(f"unexpected URL: {url}")

    return _handler


def test_single_arch_manifest_extracts_entrypoint_and_cmd() -> None:
    config_body = {
        "config": {
            "Entrypoint": ["/opt/nvidia/nvidia_entrypoint.sh"],
            "Cmd": None,
            "Env": ["PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin"],
        }
    }
    with httpx.Client(
        transport=httpx.MockTransport(_single_arch_manifest_handler(config_body))
    ) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is True
    assert result.entrypoint == ["/opt/nvidia/nvidia_entrypoint.sh"]
    assert result.cmd is None
    assert result.source == _MANIFEST_DIGEST
    assert result.inspected_at is not None
    assert "/usr/local/bin" in (result.python_on_path or "")


def test_python_version_env_wins_over_path_heuristic() -> None:
    config_body = {
        "config": {
            "Entrypoint": None,
            "Cmd": ["paddlex", "--serve"],
            "Env": ["PYTHON_VERSION=3.10.16", "PATH=/usr/local/bin:/usr/bin"],
        }
    }
    with httpx.Client(
        transport=httpx.MockTransport(_single_arch_manifest_handler(config_body))
    ) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is True
    assert result.cmd == ["paddlex", "--serve"]
    assert result.python_on_path == (
        "PYTHON_VERSION env=3.10.16 (declared in image config, not executed)"
    )


def test_no_env_yields_null_python_on_path() -> None:
    config_body = {"config": {"Entrypoint": ["vllm", "serve"], "Cmd": None}}
    with httpx.Client(
        transport=httpx.MockTransport(_single_arch_manifest_handler(config_body))
    ) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is True
    assert result.python_on_path is None


def test_multi_arch_index_selects_linux_amd64() -> None:
    amd64_digest = "sha256:" + "b" * 64
    arm64_digest = "sha256:" + "c" * 64
    config_body = {"config": {"Entrypoint": ["vllm", "serve"], "Cmd": None}}

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith(f"/manifests/{_MANIFEST_DIGEST}"):
            return httpx.Response(
                200,
                json={
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                    "manifests": [
                        {
                            "digest": arm64_digest,
                            "platform": {"os": "linux", "architecture": "arm64"},
                        },
                        {
                            "digest": amd64_digest,
                            "platform": {"os": "linux", "architecture": "amd64"},
                        },
                    ],
                },
            )
        if url.endswith(f"/manifests/{amd64_digest}"):
            return httpx.Response(
                200,
                json={
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {"digest": _CONFIG_DIGEST},
                },
            )
        if url.endswith(f"/manifests/{arm64_digest}"):  # pragma: no cover
            raise AssertionError("must not fetch the arm64 sub-manifest")
        if f"/blobs/{_CONFIG_DIGEST}" in url:
            return httpx.Response(200, json=config_body)
        raise AssertionError(f"unexpected URL: {url}")

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is True
    assert result.source == amd64_digest
    assert result.entrypoint == ["vllm", "serve"]


def test_index_without_amd64_linux_is_reported_not_guessed() -> None:
    arm64_digest = "sha256:" + "c" * 64

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"digest": arm64_digest, "platform": {"os": "linux", "architecture": "arm64"}},
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is False
    assert "linux/amd64" in result.detail
    assert result.entrypoint is None


def test_manifest_401_then_anonymous_token_then_200() -> None:
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        url = str(request.url)
        if url.startswith("https://auth.example.com/token"):
            return httpx.Response(200, json={"token": "anon-token"})
        if "Authorization" not in request.headers:
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": (
                        'Bearer realm="https://auth.example.com/token",service="example"'
                    )
                },
            )
        if "/manifests/" in url:
            return httpx.Response(
                200,
                json={
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {"digest": _CONFIG_DIGEST},
                },
            )
        if "/blobs/" in url:
            return httpx.Response(
                200, json={"config": {"Entrypoint": ["vllm", "serve"], "Cmd": None}}
            )
        raise AssertionError(f"unexpected URL: {url}")

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = inspect_base_image_config(
            "myregistry.example.com/some/repo:tag", offline=False, client=client
        )
    assert result.resolved is True
    assert result.entrypoint == ["vllm", "serve"]
    # 401 + token exchange for the manifest, then a repeat for the blob.
    assert len(calls) >= 4


def test_registry_refuses_anonymous_config_read_is_recorded_verbatim() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/manifests/" in url:
            return httpx.Response(
                200,
                json={
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {"digest": _CONFIG_DIGEST},
                },
            )
        if "/blobs/" in url:
            return httpx.Response(403)
        raise AssertionError(f"unexpected URL: {url}")

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is False
    assert "403" in result.detail
    assert result.entrypoint is None
    assert result.cmd is None


def test_manifest_404_is_recorded_not_raised() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is False
    assert "404" in result.detail


def test_transport_failure_is_reported_not_raised() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        result = inspect_base_image_config(
            f"some/repo@{_MANIFEST_DIGEST}", offline=False, client=client
        )
    assert result.resolved is False
    assert "ConnectTimeout" in result.detail
