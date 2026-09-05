"""Read-only, anonymous OCI image-config inspection (D2 support).

Given a base image reference that already carries a resolved digest (from
``registry_resolve.resolve_digest`` or embedded directly in ``runtime.json``
per D5), fetches the manifest at that digest and the image config blob it
points at -- both plain anonymous ``GET`` requests, same token flow as
``registry_resolve.py`` -- and extracts the fields ``generate_build_plan.py``
needs to answer "does the *official* upstream image already set its own
ENTRYPOINT/CMD" (relevant to D2: bootstrap mode overrides an image
ENTRYPOINT via RunPod REST v1 ``dockerEntrypoint``/``dockerStartCmd``, so a
baked image with its own ENTRYPOINT is not a concern there, but a bootstrap
canary running the *official* image directly needs to know what it is
replacing).

Handles multi-arch manifest lists/indexes by selecting ``linux/amd64`` (the
only platform this campaign runs on). Never invents a value: any failure --
a non-200 status, a registry that refuses anonymous config reads, no
``linux/amd64`` entry in an index, a malformed body -- is recorded verbatim
in ``detail`` with ``resolved=False`` and every field left ``None``, never
guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx
from registry_resolve import _BEARER_RE, ImageRef, RegistryResolveError, parse_image_ref

_INDEX_MEDIA_TYPES: Final = frozenset(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
)
_MANIFEST_ACCEPT: Final = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
_CONFIG_ACCEPT: Final = ", ".join(
    (
        "application/vnd.oci.image.config.v1+json",
        "application/vnd.docker.container.image.v1+json",
        "application/octet-stream",
        "*/*",
    )
)
_DEFAULT_TIMEOUT_SECONDS: Final = 15.0
_PREFERRED_OS: Final = "linux"
_PREFERRED_ARCH: Final = "amd64"


@dataclass(frozen=True, slots=True)
class BaseImageConfigResult:
    """Outcome of an anonymous image-config inspection attempt.

    Every field is ``None`` unless the inspection actually succeeded --
    ``resolved`` is the only field a caller needs to check before trusting
    the rest.
    """

    entrypoint: list[str] | None
    cmd: list[str] | None
    python_on_path: str | None
    inspected_at: str | None
    source: str | None  # the manifest digest the config was read from
    resolved: bool
    detail: str


def _failure(detail: str) -> BaseImageConfigResult:
    return BaseImageConfigResult(
        entrypoint=None, cmd=None, python_on_path=None, inspected_at=None,
        source=None, resolved=False, detail=detail,
    )


def _manifest_url(image_ref: ImageRef, reference: str) -> str:
    return f"https://{image_ref.registry_host}/v2/{image_ref.repository}/manifests/{reference}"


def _blob_url(image_ref: ImageRef, digest: str) -> str:
    return f"https://{image_ref.registry_host}/v2/{image_ref.repository}/blobs/{digest}"


def _get_anonymous_token(
    http_client: httpx.Client, image_ref: ImageRef, challenge: str
) -> tuple[str | None, str]:
    """Exchange a 401 ``WWW-Authenticate`` challenge for an anonymous pull
    token. Returns ``(token, detail)``; ``token`` is ``None`` on any failure,
    with ``detail`` explaining why -- never raises for a registry outcome."""
    match = _BEARER_RE.search(challenge)
    if not match:
        return None, "401 without a parseable Bearer WWW-Authenticate challenge"
    realm = match.group("realm")
    service = match.group("service") or ""
    try:
        token_response = http_client.get(
            realm,
            params={"service": service, "scope": f"repository:{image_ref.repository}:pull"},
        )
    except httpx.HTTPError as exc:
        return None, f"token endpoint transport failure: {exc.__class__.__name__}"
    if token_response.status_code != 200:
        return None, f"token endpoint returned {token_response.status_code}"
    try:
        token = str(token_response.json().get("token", ""))
    except ValueError:
        return None, "token endpoint returned malformed JSON"
    if not token:
        return None, "token endpoint granted no anonymous pull token (likely private/denied)"
    return token, "anonymous token granted"


def _get_with_auth(
    http_client: httpx.Client, image_ref: ImageRef, url: str, accept: str
) -> tuple[httpx.Response | None, str]:
    """GET ``url`` anonymously, retrying once with a bearer token on a 401.
    Returns ``(response_or_none, detail)``."""
    headers = {"Accept": accept}
    try:
        response = http_client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return None, f"transport failure: {exc.__class__.__name__}"
    if response.status_code == 401:
        token, token_detail = _get_anonymous_token(
            http_client, image_ref, response.headers.get("www-authenticate", "")
        )
        if token is None:
            return None, token_detail
        try:
            response = http_client.get(
                url, headers={**headers, "Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            return None, f"authenticated retry transport failure: {exc.__class__.__name__}"
    if response.status_code != 200:
        return None, f"unexpected status {response.status_code} fetching {url}"
    return response, "200"


def _select_amd64_linux(index_body: dict[str, Any]) -> tuple[str | None, str]:
    manifests = index_body.get("manifests")
    if not isinstance(manifests, list):
        return None, "manifest index carried no 'manifests' array"
    for entry in manifests:
        if not isinstance(entry, dict):
            continue
        platform = entry.get("platform")
        if not isinstance(platform, dict):
            continue
        if (
            platform.get("os") == _PREFERRED_OS
            and platform.get("architecture") == _PREFERRED_ARCH
        ):
            digest = entry.get("digest")
            if isinstance(digest, str):
                return digest, f"selected {_PREFERRED_OS}/{_PREFERRED_ARCH} sub-manifest"
    return None, f"no {_PREFERRED_OS}/{_PREFERRED_ARCH} entry in manifest index"


def _best_effort_python_on_path(config: dict[str, Any]) -> str | None:
    """Best-effort, non-fabricated read of where Python might live, derived
    only from what the image config actually declares (``Env``). Never
    executes the image, so this is a candidate signal, not a verified path --
    callers must treat a non-``None`` value as "observed in config", not
    "confirmed on disk"."""
    env = config.get("Env")
    if not isinstance(env, list):
        return None
    python_version: str | None = None
    path_value: str | None = None
    for var in env:
        if not isinstance(var, str) or "=" not in var:
            continue
        key, _, value = var.partition("=")
        if key == "PYTHON_VERSION" and value:
            python_version = value
        elif key == "PATH" and value:
            path_value = value
    if python_version:
        return f"PYTHON_VERSION env={python_version} (declared in image config, not executed)"
    if path_value:
        for candidate in ("/opt/conda/bin", "/usr/local/bin", "/opt/venv/bin", "/venv/bin"):
            if candidate in path_value:
                return (
                    f"candidate on PATH (unverified, not executed): {candidate} "
                    f"(full PATH={path_value})"
                )
    return None


def inspect_base_image_config(
    ref: str,
    *,
    offline: bool,
    client: httpx.Client | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> BaseImageConfigResult:
    """Anonymously fetch the manifest + image config for ``ref`` (a
    ``name@sha256:...`` or ``name:tag`` reference; a resolved digest is
    strongly preferred so the inspection is pinned to the exact image
    ``build_plan.json`` already recorded). Never raises for a network or
    registry outcome -- only for a malformed ``ref``."""
    if offline:
        return _failure("--offline was passed; no network call attempted")

    try:
        image_ref = parse_image_ref(ref)
    except RegistryResolveError as exc:
        return _failure(f"malformed base image reference: {exc}")

    reference = image_ref.embedded_digest or image_ref.tag
    if reference is None:  # pragma: no cover - parse_image_ref guarantees one
        return _failure("reference has neither digest nor tag")

    owns_client = client is None
    # Registry blob storage (config/layer blobs, as opposed to manifest
    # lookups) commonly answers with a 302/307 redirect to a CDN -- unlike
    # registry_resolve.py's manifest-only GETs, a blob fetch here needs to
    # follow that redirect to actually read the config JSON.
    http_client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        manifest_response, detail = _get_with_auth(
            http_client, image_ref, _manifest_url(image_ref, reference), _MANIFEST_ACCEPT
        )
        if manifest_response is None:
            return _failure(f"manifest fetch failed: {detail}")

        try:
            manifest_body = manifest_response.json()
        except ValueError:
            return _failure("manifest response was not valid JSON")
        if not isinstance(manifest_body, dict):
            return _failure("manifest response was not a JSON object")

        manifest_digest = manifest_response.headers.get("docker-content-digest") or reference
        media_type = manifest_body.get("mediaType")
        if media_type in _INDEX_MEDIA_TYPES:
            sub_digest, select_detail = _select_amd64_linux(manifest_body)
            if sub_digest is None:
                return _failure(f"multi-arch index present but {select_detail}")
            manifest_response, detail = _get_with_auth(
                http_client, image_ref, _manifest_url(image_ref, sub_digest), _MANIFEST_ACCEPT
            )
            if manifest_response is None:
                return _failure(f"{select_detail}, but sub-manifest fetch failed: {detail}")
            try:
                manifest_body = manifest_response.json()
            except ValueError:
                return _failure(f"{select_detail}, but sub-manifest was not valid JSON")
            if not isinstance(manifest_body, dict):
                return _failure(f"{select_detail}, but sub-manifest was not a JSON object")
            manifest_digest = sub_digest

        config_ref = manifest_body.get("config")
        if not isinstance(config_ref, dict) or not isinstance(config_ref.get("digest"), str):
            return _failure("manifest carried no usable 'config.digest'")
        config_digest = config_ref["digest"]

        blob_response, detail = _get_with_auth(
            http_client, image_ref, _blob_url(image_ref, config_digest), _CONFIG_ACCEPT
        )
        if blob_response is None:
            return _failure(f"config blob fetch failed (registry refused anonymous read): {detail}")
        try:
            config_blob = blob_response.json()
        except ValueError:
            return _failure("config blob response was not valid JSON")
        if not isinstance(config_blob, dict):
            return _failure("config blob response was not a JSON object")

        config = config_blob.get("config")
        if not isinstance(config, dict):
            return _failure("config blob carried no 'config' object")

        entrypoint = config.get("Entrypoint")
        cmd = config.get("Cmd")
        return BaseImageConfigResult(
            entrypoint=list(entrypoint) if isinstance(entrypoint, list) else None,
            cmd=list(cmd) if isinstance(cmd, list) else None,
            python_on_path=_best_effort_python_on_path(config),
            inspected_at=datetime.now(UTC).isoformat(),
            source=manifest_digest,
            resolved=True,
            detail="fetched manifest + image config successfully",
        )
    finally:
        if owns_client:
            http_client.close()


__all__ = ["BaseImageConfigResult", "inspect_base_image_config"]
