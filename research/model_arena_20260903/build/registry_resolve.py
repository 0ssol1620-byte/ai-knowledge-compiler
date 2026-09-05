"""Read-only, anonymous OCI/Docker-registry digest resolution.

Used by ``generate_build_plan.py`` (offline, to populate ``build_plan.json``)
and by ``registry_check.py`` (to probe whether a target image tag has been
pushed yet). Every network call here is a plain anonymous ``GET``/``HEAD``
against a registry's public HTTP API -- exactly the "Docker Hub / GHCR
anonymous manifest queries for base-image digests" the lane brief allows.

Nothing here ever authenticates with a write-capable credential, never reads
``D:\\Github_API.txt`` or any other secret store (only lane B1's
``arena/provider/secrets.py`` may do that), and never invents a digest: a
network failure, a 404, or a registry that refuses anonymous token issuance
all resolve to ``digest=None`` with a human-readable ``detail`` and the exact
command a person can run instead.

Pure parsing/classification helpers are kept separate from the network I/O
functions so tests can exercise the logic without a live connection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import httpx

_MANIFEST_ACCEPT: Final = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
_DEFAULT_TIMEOUT_SECONDS: Final = 10.0
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_BEARER_RE: Final = re.compile(
    r'Bearer\s+realm="(?P<realm>[^"]+)"(?:,\s*service="(?P<service>[^"]*)")?', re.IGNORECASE
)
_REF_WITH_DIGEST_RE: Final = re.compile(
    r"^(?P<host_and_repo>[^@]+)@(?P<digest>sha256:[0-9a-f]{64})$"
)
_TAG_RE: Final = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


class RegistryResolveError(RuntimeError):
    """Raised only for a malformed *input*, never for a network outcome."""


@dataclass(frozen=True, slots=True)
class ImageRef:
    """A parsed ``registry/repo:tag`` or ``registry/repo@sha256:...`` ref.

    ``registry_host`` defaults to Docker Hub's registry endpoint
    (``registry-1.docker.io``) when the ref has no explicit host segment,
    matching normal Docker CLI resolution (``vllm/vllm-openai`` ==
    ``docker.io/vllm/vllm-openai``).
    """

    registry_host: str
    repository: str
    tag: str | None
    embedded_digest: str | None

    @property
    def display_name(self) -> str:
        host = "" if self.registry_host == "registry-1.docker.io" else f"{self.registry_host}/"
        return f"{host}{self.repository}"


def parse_image_ref(ref: str) -> ImageRef:
    """Parse a Dockerfile-style ``FROM`` reference.

    Accepts ``repo:tag``, ``repo@sha256:..``, ``repo:tag@sha256:..``, and any
    of those prefixed with an explicit registry host (a segment before the
    first ``/`` that contains a ``.`` or a ``:``, or is exactly
    ``localhost``).
    """
    text = ref.strip()
    if not text:
        raise RegistryResolveError("empty image reference")

    embedded_digest: str | None = None
    match = _REF_WITH_DIGEST_RE.match(text)
    if match:
        embedded_digest = match.group("digest")
        text = match.group("host_and_repo")

    tag: str | None = None
    if ":" in text.rsplit("/", 1)[-1]:
        text, _, candidate_tag = text.rpartition(":")
        tag = candidate_tag

    parts = text.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry_host, repository = parts[0], parts[1]
        if registry_host in {"docker.io", "index.docker.io"}:
            # Docker Hub's registry *API* lives on registry-1.docker.io even
            # when a reference spells the host explicitly as docker.io.
            registry_host = "registry-1.docker.io"
            repository = repository if "/" in repository else f"library/{repository}"
    else:
        registry_host = "registry-1.docker.io"
        repository = text if "/" in text else f"library/{text}"

    if tag is not None and not _TAG_RE.fullmatch(tag):
        raise RegistryResolveError(f"invalid tag in image reference: {ref!r}")
    if tag is None and embedded_digest is None:
        raise RegistryResolveError(f"image reference has neither tag nor digest: {ref!r}")

    return ImageRef(
        registry_host=registry_host,
        repository=repository,
        tag=tag,
        embedded_digest=embedded_digest,
    )


def _auth_endpoint(registry_host: str) -> str:
    # Docker Hub's registry host answers WWW-Authenticate itself, but its
    # well-known token issuer lives on a different host; every other
    # docker-v2 registry (GHCR, Harbor-based CCR mirrors, ...) advertises its
    # own realm via WWW-Authenticate and this fallback is unused for them.
    if registry_host in {"registry-1.docker.io", "index.docker.io"}:
        return "https://auth.docker.io/token"
    return ""


@dataclass(frozen=True, slots=True)
class RegistryLookup:
    """Outcome of an anonymous digest resolution attempt.

    ``digest`` is ``None`` whenever the answer is not certain -- a 404, a
    denied anonymous token, a network error, or a non-docker-v2 endpoint.
    ``resolve_command`` is always populated (even on success) so a human can
    reproduce or re-verify the result independently of this process.
    """

    ref: str
    digest: str | None
    resolved: bool
    method: str
    detail: str
    resolve_command: str
    http_status: int | None = None


def _resolve_command(image_ref: ImageRef) -> str:
    target = (
        f"{image_ref.display_name}:{image_ref.tag}" if image_ref.tag else image_ref.display_name
    )
    return f"docker buildx imagetools inspect {target} --format '{{{{json .Manifest.Digest}}}}'"


def resolve_digest(
    ref: str,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> RegistryLookup:
    """Best-effort anonymous digest resolution. Never raises on a network
    outcome -- only on a malformed ``ref`` string (a programming error, not a
    registry condition)."""
    image_ref = parse_image_ref(ref)
    command = _resolve_command(image_ref)

    if image_ref.embedded_digest is not None:
        return RegistryLookup(
            ref=ref,
            digest=image_ref.embedded_digest,
            resolved=True,
            method="embedded_in_reference",
            detail="the reference already pins a digest; no lookup performed",
            resolve_command=command,
        )

    assert image_ref.tag is not None  # parse_image_ref guarantees tag or digest
    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
    try:
        return _resolve_via_manifest_get(image_ref, http_client, command)
    except httpx.HTTPError as exc:
        return RegistryLookup(
            ref=ref,
            digest=None,
            resolved=False,
            method="anonymous_manifest_get",
            detail=f"transport failure: {exc.__class__.__name__}",
            resolve_command=command,
        )
    finally:
        if owns_client:
            http_client.close()


def _manifest_url(image_ref: ImageRef) -> str:
    return f"https://{image_ref.registry_host}/v2/{image_ref.repository}/manifests/{image_ref.tag}"


def _resolve_via_manifest_get(
    image_ref: ImageRef, http_client: httpx.Client, command: str
) -> RegistryLookup:
    url = _manifest_url(image_ref)
    headers = {"Accept": _MANIFEST_ACCEPT}
    response = http_client.get(url, headers=headers)

    if response.status_code == 200:
        digest = response.headers.get("docker-content-digest")
        if digest and _DIGEST_RE.fullmatch(digest):
            return RegistryLookup(
                ref=image_ref.repository,
                digest=digest,
                resolved=True,
                method="anonymous_manifest_get",
                detail="200 with Docker-Content-Digest header",
                resolve_command=command,
                http_status=200,
            )
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_manifest_get",
            detail="200 response carried no valid Docker-Content-Digest header",
            resolve_command=command,
            http_status=200,
        )

    if response.status_code != 401:
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_manifest_get",
            detail=f"unexpected status {response.status_code} before any token exchange",
            resolve_command=command,
            http_status=response.status_code,
        )

    challenge = response.headers.get("www-authenticate", "")
    match = _BEARER_RE.search(challenge)
    if not match:
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_manifest_get",
            detail="401 without a parseable Bearer WWW-Authenticate challenge",
            resolve_command=command,
            http_status=401,
        )

    realm = match.group("realm")
    service = match.group("service") or ""
    token_response = http_client.get(
        realm,
        params={"service": service, "scope": f"repository:{image_ref.repository}:pull"},
    )
    if token_response.status_code != 200:
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_token_exchange",
            detail=f"token endpoint returned {token_response.status_code}",
            resolve_command=command,
            http_status=token_response.status_code,
        )
    try:
        token = str(token_response.json().get("token", ""))
    except ValueError:
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_token_exchange",
            detail="token endpoint returned malformed JSON",
            resolve_command=command,
        )
    if not token:
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_token_exchange",
            detail="token endpoint granted no anonymous pull token (likely private/denied)",
            resolve_command=command,
        )

    authed = http_client.get(
        url, headers={**headers, "Authorization": f"Bearer {token}"}
    )
    if authed.status_code != 200:
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_manifest_get",
            detail=f"authenticated manifest GET returned {authed.status_code}",
            resolve_command=command,
            http_status=authed.status_code,
        )
    digest = authed.headers.get("docker-content-digest")
    if not digest or not _DIGEST_RE.fullmatch(digest):
        return RegistryLookup(
            ref=image_ref.repository,
            digest=None,
            resolved=False,
            method="anonymous_manifest_get",
            detail="authenticated 200 carried no valid Docker-Content-Digest header",
            resolve_command=command,
            http_status=200,
        )
    return RegistryLookup(
        ref=image_ref.repository,
        digest=digest,
        resolved=True,
        method="anonymous_manifest_get",
        detail="200 with Docker-Content-Digest header after anonymous token exchange",
        resolve_command=command,
        http_status=200,
    )


__all__ = [
    "ImageRef",
    "RegistryLookup",
    "RegistryResolveError",
    "parse_image_ref",
    "resolve_digest",
]
