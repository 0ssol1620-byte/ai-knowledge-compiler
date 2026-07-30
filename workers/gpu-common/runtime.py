"""Hardened Runpod handler runtime with deterministic local adapters."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.client
import importlib
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import unquote, urlsplit, urlunsplit

PROCESS_STARTED = time.perf_counter()
EXACT_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ADAPTER_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$")
SAFE_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")
FLOATING_REVISIONS = {"", "main", "master", "latest", "head", "dev"}
LOCAL_MOCK_REVISION = "1" * 40
CANONICAL_ORIGINS = {
    "native_extracted",
    "ocr_extracted",
    "rule_reconstructed",
    "ai_reconstructed",
    "ai_summarized",
    "ai_inferred",
    "user_edited",
}


class SafeWorkerError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@runtime_checkable
class Adapter(Protocol):
    def self_test(self) -> None: ...

    def process(self, input_path: Path, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WorkerConfig:
    worker_kind: str
    provider_key: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    max_input_bytes: int
    max_output_bytes: int
    max_direct_response_bytes: int
    gpu_usd_per_second: float
    allowed_input_hosts: frozenset[str]
    allowed_output_hosts: frozenset[str]
    allow_inline_input: bool
    allow_http_localhost: bool
    experimental: bool
    experiment_enabled: bool
    adapter_mode: str
    adapter_module: str | None
    callback_hmac_secret: bytes | None
    callback_audience: str
    require_callback_auth: bool

    @classmethod
    def from_env(
        cls, worker_kind: str, provider_key: str, *, experimental: bool = False
    ) -> WorkerConfig:
        revision = os.getenv("MODEL_REVISION", "").strip().lower()
        adapter_mode = os.getenv("AKC_ADAPTER_MODE", "mock").strip().lower()
        if revision in FLOATING_REVISIONS or not EXACT_REVISION.fullmatch(revision):
            raise SafeWorkerError("exact_model_revision_required")
        if adapter_mode == "production" and revision == LOCAL_MOCK_REVISION:
            raise SafeWorkerError("production_model_revision_required")
        runtime_image_digest = (
            os.getenv(
                "RUNTIME_IMAGE_DIGEST",
                "sha256:" + ("0" * 64),
            )
            .strip()
            .lower()
        )
        adapter_version = os.getenv(
            "ADAPTER_VERSION",
            "mock-adapter-1.0.0",
        ).strip()
        if not IMAGE_DIGEST.fullmatch(runtime_image_digest):
            raise SafeWorkerError("runtime_image_digest_required")
        if not ADAPTER_VERSION.fullmatch(adapter_version):
            raise SafeWorkerError("adapter_version_required")
        if adapter_mode == "production" and runtime_image_digest == "sha256:" + ("0" * 64):
            raise SafeWorkerError("production_runtime_image_digest_required")
        if adapter_mode == "production" and adapter_version.startswith("mock-"):
            raise SafeWorkerError("production_adapter_version_required")
        price = float(os.getenv("GPU_USD_PER_SECOND", "0"))
        if not math.isfinite(price) or price < 0:
            raise SafeWorkerError("invalid_gpu_price")
        require_callback_auth = _bool_env(
            "REQUIRE_CALLBACK_AUTH",
            adapter_mode == "production",
        )
        if adapter_mode == "production" and not require_callback_auth:
            raise SafeWorkerError("production_callback_auth_required")
        callback_secret_text = os.getenv("CALLBACK_HMAC_SECRET", "")
        callback_secret = callback_secret_text.encode() or None
        if require_callback_auth and (callback_secret is None or len(callback_secret) < 32):
            raise SafeWorkerError("callback_auth_secret_required")
        max_input_bytes = int(os.getenv("MAX_INPUT_BYTES", str(25 * 1024 * 1024)))
        max_output_bytes = int(os.getenv("MAX_OUTPUT_BYTES", str(10 * 1024 * 1024)))
        max_direct_response_bytes = int(os.getenv("MAX_DIRECT_RESPONSE_BYTES", str(1024 * 1024)))
        if (
            max_input_bytes <= 0
            or max_output_bytes <= 0
            or max_direct_response_bytes <= 0
            or max_direct_response_bytes > max_output_bytes
        ):
            raise SafeWorkerError("invalid_worker_size_limit")
        return cls(
            worker_kind=worker_kind,
            provider_key=provider_key,
            model_revision=revision,
            runtime_image_digest=runtime_image_digest,
            adapter_version=adapter_version,
            max_input_bytes=max_input_bytes,
            max_output_bytes=max_output_bytes,
            max_direct_response_bytes=max_direct_response_bytes,
            gpu_usd_per_second=price,
            allowed_input_hosts=_host_set("INPUT_HOST_ALLOWLIST"),
            allowed_output_hosts=_host_set("OUTPUT_HOST_ALLOWLIST"),
            allow_inline_input=_bool_env("ALLOW_INLINE_INPUT", False),
            allow_http_localhost=_bool_env("ALLOW_HTTP_LOCALHOST", False),
            experimental=experimental,
            experiment_enabled=_bool_env("EXPERIMENT_ENABLED", False),
            adapter_mode=adapter_mode,
            adapter_module=os.getenv("MODEL_ADAPTER_MODULE") or None,
            callback_hmac_secret=callback_secret,
            callback_audience=os.getenv("CALLBACK_TOKEN_AUDIENCE", "akc-gpu-worker"),
            require_callback_auth=require_callback_auth,
        )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _host_set(name: str) -> frozenset[str]:
    return frozenset(
        item.strip().lower() for item in os.getenv(name, "").split(",") if item.strip()
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _validate_identifier(value: Any, field: str) -> str:
    text = str(value or "")
    if (
        not text
        or len(text) > 160
        or any(
            character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
            for character in text
        )
    ):
        raise SafeWorkerError(f"invalid_{field}")
    return text


@dataclass(frozen=True)
class _ValidatedEndpoint:
    url: str
    scheme: str
    host: str
    port: int
    request_target: str
    pinned_ip: str


def _validate_url(
    url: str,
    allowed_hosts: frozenset[str],
    config: WorkerConfig,
) -> _ValidatedEndpoint:
    if len(url) > 4096 or any(ord(character) < 0x20 for character in url):
        raise SafeWorkerError("invalid_scoped_url")
    parsed = urlsplit(url)
    raw_host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.username or parsed.password or not raw_host or parsed.fragment:
        raise SafeWorkerError("invalid_scoped_url")
    try:
        host = raw_host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SafeWorkerError("invalid_scoped_url") from exc
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (
        config.allow_http_localhost and parsed.scheme == "http" and is_local
    ):
        raise SafeWorkerError("https_required")
    if host not in allowed_hosts:
        raise SafeWorkerError("scoped_url_host_not_allowlisted")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise SafeWorkerError("invalid_scoped_url") from exc
    try:
        addresses = {
            ipaddress.ip_address(item[4][0]).compressed
            for item in socket.getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        }
    except socket.gaierror as exc:
        raise SafeWorkerError("scoped_url_dns_failed", retryable=True) from exc
    if not addresses:
        raise SafeWorkerError("scoped_url_dns_failed", retryable=True)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global and not (config.allow_http_localhost and is_local):
            raise SafeWorkerError("scoped_url_private_address_forbidden")
    path = parsed.path or "/"
    request_target = urlunsplit(("", "", path, parsed.query, ""))
    return _ValidatedEndpoint(
        url=url,
        scheme=parsed.scheme,
        host=host,
        port=port,
        request_target=request_target,
        # The connection uses this exact validated address. The hostname is not
        # resolved again, closing the DNS-rebinding time-of-check/time-of-use gap.
        pinned_ip=sorted(addresses)[0],
    )


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        pinned_ip: str,
        *,
        timeout: float,
    ) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(host=host, port=port, timeout=timeout)

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        pinned_ip: str,
        *,
        timeout: float,
    ) -> None:
        self._pinned_ip = pinned_ip
        self._tls_context = ssl.create_default_context()
        super().__init__(
            host=host,
            port=port,
            timeout=timeout,
            context=self._tls_context,
        )

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
        )
        # TLS verifies the allowlisted hostname while TCP stays pinned to the
        # address validated above.
        self.sock = self._tls_context.wrap_socket(
            raw_socket,
            server_hostname=self.host,
        )


def _pinned_connection(
    endpoint: _ValidatedEndpoint,
    *,
    timeout: float,
) -> http.client.HTTPConnection:
    connection_type = (
        _PinnedHTTPSConnection if endpoint.scheme == "https" else _PinnedHTTPConnection
    )
    return connection_type(
        endpoint.host,
        endpoint.port,
        endpoint.pinned_ip,
        timeout=timeout,
    )


def _validate_tenant_object_key(
    value: Any,
    *,
    tenant_id: str,
    field: str,
) -> str:
    if not SAFE_TENANT_ID.fullmatch(tenant_id):
        raise SafeWorkerError("invalid_tenant_id")
    key = _validate_identifier(value, field)
    normalized = unquote(key).replace("\\", "/")
    if normalized != key or "//" in normalized:
        raise SafeWorkerError(f"invalid_{field}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SafeWorkerError(f"invalid_{field}")
    expected_prefix = f"tenants/{tenant_id}/"
    if not normalized.startswith(expected_prefix) or len(normalized) == len(expected_prefix):
        raise SafeWorkerError(f"{field}_tenant_scope_mismatch")
    return normalized


def _require_key_in_url_path(
    endpoint: _ValidatedEndpoint,
    *,
    object_key: str,
    field: str,
) -> None:
    decoded_path = unquote(urlsplit(endpoint.url).path).replace("\\", "/")
    path_without_leading_slash = decoded_path.lstrip("/")
    if path_without_leading_slash != object_key and not path_without_leading_slash.endswith(
        f"/{object_key}"
    ):
        raise SafeWorkerError(f"{field}_url_scope_mismatch")


def _decode_jwt_part(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise SafeWorkerError("callback_token_invalid") from exc


def _numeric_date(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise TypeError("numeric date must be a string or number")
    return int(value)


def _validate_callback_auth(
    request: dict[str, Any],
    config: WorkerConfig,
    *,
    job_id: str,
    tenant_id: str,
) -> None:
    if not config.require_callback_auth:
        return
    token = request.get("callback_token")
    if not isinstance(token, str) or len(token) > 4096:
        raise SafeWorkerError("callback_token_required")
    parts = token.split(".")
    if len(parts) != 3:
        raise SafeWorkerError("callback_token_invalid")
    encoded_header, encoded_claims, encoded_signature = parts
    try:
        header = json.loads(_decode_jwt_part(encoded_header))
        claims = json.loads(_decode_jwt_part(encoded_claims))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeWorkerError("callback_token_invalid") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise SafeWorkerError("callback_token_algorithm_forbidden")
    if not isinstance(claims, dict):
        raise SafeWorkerError("callback_token_invalid")
    if config.callback_hmac_secret is None:
        raise SafeWorkerError("callback_auth_secret_required")
    expected_signature = hmac.new(
        config.callback_hmac_secret,
        f"{encoded_header}.{encoded_claims}".encode(),
        hashlib.sha256,
    ).digest()
    actual_signature = _decode_jwt_part(encoded_signature)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise SafeWorkerError("callback_token_signature_invalid")
    now = int(time.time())
    try:
        expires_at = _numeric_date(claims["exp"])
        not_before = _numeric_date(claims.get("nbf", claims.get("iat", now)))
        issued_at = _numeric_date(claims.get("iat", not_before))
    except (KeyError, TypeError, ValueError) as exc:
        raise SafeWorkerError("callback_token_claims_invalid") from exc
    if not_before > now + 30 or issued_at > now + 30:
        raise SafeWorkerError("callback_token_not_yet_valid")
    if expires_at <= now:
        raise SafeWorkerError("callback_token_expired")
    if expires_at - now > 3600 or now - issued_at > 3600:
        raise SafeWorkerError("callback_token_lifetime_invalid")
    audience = claims.get("aud")
    if audience != config.callback_audience:
        raise SafeWorkerError("callback_token_audience_invalid")
    if claims.get("tenant_id") != tenant_id or claims.get("job_id") != job_id:
        raise SafeWorkerError("callback_token_scope_mismatch")
    scope = claims.get("scope")
    scopes = scope.split() if isinstance(scope, str) else scope
    if not isinstance(scopes, list) or "gpu:execute" not in scopes:
        raise SafeWorkerError("callback_token_scope_invalid")


def _download_input(request: dict[str, Any], target: Path, config: WorkerConfig) -> tuple[str, int]:
    inline = request.get("inline_bytes_b64")
    input_url = request.get("input_url")
    if inline is not None:
        if not config.allow_inline_input or input_url is not None:
            raise SafeWorkerError("inline_input_forbidden")
        try:
            payload = base64.b64decode(str(inline), validate=True)
        except ValueError as exc:
            raise SafeWorkerError("invalid_inline_base64") from exc
        if len(payload) > config.max_input_bytes:
            raise SafeWorkerError("input_too_large")
        target.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest(), len(payload)
    if not isinstance(input_url, str):
        raise SafeWorkerError("input_reference_required")
    tenant_id = _validate_identifier(request.get("tenant_id"), "tenant_id")
    object_key = _validate_tenant_object_key(
        request.get("input_object_key"),
        tenant_id=tenant_id,
        field="input_object_key",
    )
    endpoint = _validate_url(input_url, config.allowed_input_hosts, config)
    _require_key_in_url_path(
        endpoint,
        object_key=object_key,
        field="input_object_key",
    )
    connection = _pinned_connection(endpoint, timeout=120)
    sha256 = hashlib.sha256()
    total = 0
    try:
        connection.request(
            "GET",
            endpoint.request_target,
            headers={
                "Accept": "application/octet-stream",
                "Host": endpoint.host,
            },
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise SafeWorkerError("redirect_forbidden")
        if response.status != 200:
            raise SafeWorkerError("input_download_failed", retryable=response.status >= 500)
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise SafeWorkerError("invalid_input_content_length") from exc
            if declared_size < 0 or declared_size > config.max_input_bytes:
                raise SafeWorkerError("input_too_large")
        with target.open("wb") as handle:
            while True:
                chunk = response.read(min(1024 * 1024, config.max_input_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > config.max_input_bytes:
                    raise SafeWorkerError("input_too_large")
                sha256.update(chunk)
                handle.write(chunk)
    except SafeWorkerError:
        raise
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        raise SafeWorkerError("input_download_failed", retryable=True) from exc
    finally:
        connection.close()
    return sha256.hexdigest(), total


def _upload_result(
    url: str,
    body: bytes,
    config: WorkerConfig,
    *,
    tenant_id: str,
    output_object_key: Any,
) -> None:
    if len(body) > config.max_output_bytes:
        raise SafeWorkerError("output_too_large")
    object_key = _validate_tenant_object_key(
        output_object_key,
        tenant_id=tenant_id,
        field="output_object_key",
    )
    endpoint = _validate_url(url, config.allowed_output_hosts, config)
    _require_key_in_url_path(
        endpoint,
        object_key=object_key,
        field="output_object_key",
    )
    connection = _pinned_connection(endpoint, timeout=120)
    try:
        connection.request(
            "PUT",
            endpoint.request_target,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Host": endpoint.host,
                "If-None-Match": "*",
                "X-Content-SHA256": hashlib.sha256(body).hexdigest(),
            },
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise SafeWorkerError("redirect_forbidden")
        if response.status == 412:
            raise SafeWorkerError("output_already_exists")
        if response.status not in {200, 201, 204}:
            raise SafeWorkerError("output_upload_failed", retryable=response.status >= 500)
        # Bound even an unexpected response body from the object store.
        if len(response.read(64 * 1024 + 1)) > 64 * 1024:
            raise SafeWorkerError("output_response_too_large")
    except SafeWorkerError:
        raise
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        raise SafeWorkerError("output_upload_failed", retryable=True) from exc
    finally:
        connection.close()


def _source_ref(request: dict[str, Any]) -> dict[str, Any]:
    raw_options = request.get("options")
    options: dict[str, Any] = raw_options if isinstance(raw_options, dict) else {}
    bbox = options.get("bbox1000", [0, 0, 1000, 1000])
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(not isinstance(value, int) or isinstance(value, bool) for value in bbox)
        or any(value < 0 or value > 1000 for value in bbox)
        or bbox[0] >= bbox[2]
        or bbox[1] >= bbox[3]
    ):
        raise SafeWorkerError("invalid_bbox1000")
    try:
        page_index0 = int(request.get("page_index0", request.get("page_index", 0)))
    except (TypeError, ValueError) as exc:
        raise SafeWorkerError("invalid_page_index0") from exc
    if page_index0 < 0:
        raise SafeWorkerError("invalid_page_index0")
    return {
        "document_id": _validate_identifier(
            request.get("document_id", "urn:akmp:doc:local"),
            "document_id",
        ),
        "document_version_id": _validate_identifier(
            request.get("document_version_id", "urn:akmp:doc-version:local-v1"),
            "document_version_id",
        ),
        "page_index0": page_index0,
        "page_number1": page_index0 + 1,
        "bbox1000": bbox,
    }


_BLOCK_TYPES = frozenset(
    {
        "title",
        "heading",
        "paragraph",
        "list",
        "table",
        "figure",
        "caption",
        "formula",
        "code",
        "quote",
        "footnote",
        "header",
        "footer",
        "page_number",
        "unknown",
    }
)
_ADAPTER_TOP_LEVEL_FIELDS = {
    "parser": frozenset(
        {"blocks", "generated_claims", "warnings", "provider_metrics", "provider_raw"}
    ),
    "knowledge": frozenset(
        {
            "knowledge_bundle",
            "knowledge_stage_result",
            "warnings",
            "provider_metrics",
            "provider_raw",
        }
    ),
}
_ADAPTER_REQUEST_FIELDS = frozenset(
    {
        "tenant_id",
        "document_id",
        "document_version_id",
        "job_id",
        "page_id",
        "page_index",
        "page_index0",
        "options",
    }
)
_SENSITIVE_OPTION_KEYS = frozenset(
    {
        "api_key",
        "callback_token",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)


def _validate_warning_list(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 256:
        raise SafeWorkerError("invalid_adapter_warnings")
    warnings: list[str] = []
    for warning in value:
        if not isinstance(warning, str) or not warning or len(warning) > 1000:
            raise SafeWorkerError("invalid_adapter_warnings")
        warnings.append(warning)
    return warnings


def _validate_source_refs(value: Any, request: dict[str, Any]) -> None:
    if not isinstance(value, list) or not value or len(value) > 128:
        raise SafeWorkerError("invalid_adapter_source_refs")
    expected_document = request.get("document_id")
    expected_version = request.get("document_version_id")
    expected_page = request.get("page_index0")
    for source_ref in value:
        if not isinstance(source_ref, dict):
            raise SafeWorkerError("invalid_adapter_source_ref")
        if expected_document and source_ref.get("document_id") != expected_document:
            raise SafeWorkerError("adapter_document_scope_mismatch")
        if expected_version and source_ref.get("document_version_id") != expected_version:
            raise SafeWorkerError("adapter_document_version_scope_mismatch")
        page_index = source_ref.get("page_index0")
        page_number = source_ref.get("page_number1")
        if (
            not isinstance(page_index, int)
            or isinstance(page_index, bool)
            or page_index < 0
            or page_number != page_index + 1
            or (
                expected_page is not None
                and (
                    not isinstance(expected_page, int)
                    or isinstance(expected_page, bool)
                    or page_index != expected_page
                )
            )
        ):
            raise SafeWorkerError("invalid_adapter_page_reference")
        bbox = source_ref.get("bbox1000")
        if bbox is not None and (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item < 0 or item > 1000
                for item in bbox
            )
            or bbox[0] >= bbox[2]
            or bbox[1] >= bbox[3]
        ):
            raise SafeWorkerError("invalid_adapter_bbox1000")


def _validate_parser_output(output: dict[str, Any], request: dict[str, Any]) -> None:
    blocks = output.get("blocks")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 10_000:
        raise SafeWorkerError("invalid_adapter_blocks")
    block_ids: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict):
            raise SafeWorkerError("invalid_adapter_block")
        block_id = _validate_identifier(block.get("block_id"), "adapter_block_id")
        if block_id in block_ids:
            raise SafeWorkerError("duplicate_adapter_block_id")
        block_ids.add(block_id)
        if block.get("type") not in _BLOCK_TYPES:
            raise SafeWorkerError("invalid_adapter_block_type")
        text = block.get("text")
        if not isinstance(text, str) or len(text) > 1_000_000:
            raise SafeWorkerError("invalid_adapter_block_text")
        if block.get("origin") not in CANONICAL_ORIGINS:
            raise SafeWorkerError("invalid_adapter_block_origin")
        _validate_source_refs(block.get("source_refs"), request)
        _validate_warning_list(block.get("quality_flags", []))
    claims = output.get("generated_claims", [])
    if not isinstance(claims, list) or len(claims) > 10_000:
        raise SafeWorkerError("invalid_adapter_generated_claims")
    for claim in claims:
        if not isinstance(claim, dict):
            raise SafeWorkerError("invalid_adapter_generated_claim")
        evidence = claim.get("evidence_block_ids")
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(item not in block_ids for item in evidence)
        ):
            raise SafeWorkerError("adapter_claim_evidence_required")


def _validate_legacy_knowledge_output(
    output: dict[str, Any],
    request: dict[str, Any],
    *,
    require_notes: bool = True,
) -> None:
    knowledge_input = request.get("knowledge_input")
    if not isinstance(knowledge_input, dict):
        raise SafeWorkerError("knowledge_blocks_required")
    source_blocks = knowledge_input.get("blocks")
    if not isinstance(source_blocks, list) or not source_blocks:
        raise SafeWorkerError("knowledge_blocks_required")
    source_block_ids: set[str] = set()
    for source_block in source_blocks:
        if not isinstance(source_block, dict):
            continue
        source_block_id = source_block.get("block_id")
        if isinstance(source_block_id, str):
            source_block_ids.add(source_block_id)
    bundle = output.get("knowledge_bundle")
    if not isinstance(bundle, dict) or set(bundle) != {
        "schemaVersion",
        "documentId",
        "notes",
        "relations",
        "conflicts",
    }:
        raise SafeWorkerError("invalid_knowledge_bundle")
    if (
        bundle.get("schemaVersion") != "knowledge-1.0.0"
        or bundle.get("documentId") != knowledge_input.get("document_id")
    ):
        raise SafeWorkerError("knowledge_bundle_scope_mismatch")
    notes = bundle.get("notes")
    if (
        not isinstance(notes, list)
        or (require_notes and not notes)
        or len(notes) > 10_000
    ):
        raise SafeWorkerError("invalid_adapter_notes")
    note_ids: set[str] = set()
    for note in notes:
        if (
            not isinstance(note, dict)
            or set(note)
            - {
                "noteId",
                "title",
                "noteType",
                "contentOrigin",
                "evidenceBlockIds",
                "summary",
                "claims",
                "aliases",
                "tags",
                "relatedNoteCandidates",
                "reviewStatus",
            }
            or not {
                "noteId",
                "title",
                "noteType",
                "contentOrigin",
                "evidenceBlockIds",
                "claims",
                "aliases",
                "tags",
                "relatedNoteCandidates",
                "reviewStatus",
            }.issubset(note)
        ):
            raise SafeWorkerError("invalid_adapter_note")
        note_id = _validate_identifier(note.get("noteId"), "note_id")
        if len(note_id) > 128 or note_id in note_ids:
            raise SafeWorkerError("duplicate_or_oversized_note_id")
        note_ids.add(note_id)
        if not isinstance(note.get("title"), str) or not note["title"] or len(note["title"]) > 500:
            raise SafeWorkerError("invalid_adapter_note_title")
        if note.get("noteType") not in {
            "concept",
            "document",
            "person",
            "organization",
            "project",
            "glossary",
            "question",
            "moc",
        }:
            raise SafeWorkerError("invalid_adapter_note_type")
        if note.get("contentOrigin") not in CANONICAL_ORIGINS:
            raise SafeWorkerError("invalid_adapter_note_origin")
        if note.get("reviewStatus") not in {
            "pending",
            "auto_with_warnings",
            "user_verified",
            "rejected",
        }:
            raise SafeWorkerError("invalid_adapter_review_status")
        summary = note.get("summary")
        if summary is not None and (
            not isinstance(summary, str) or len(summary) > 2_000_000
        ):
            raise SafeWorkerError("invalid_adapter_note_summary")
        evidence = note.get("evidenceBlockIds")
        if (
            not isinstance(evidence, list)
            or not evidence
            or len(evidence) > 10_000
            or len(evidence) != len(set(evidence))
            or any(item not in source_block_ids for item in evidence)
        ):
            raise SafeWorkerError("knowledge_evidence_required")
        claims = note.get("claims")
        if not isinstance(claims, list) or len(claims) > 10_000:
            raise SafeWorkerError("invalid_adapter_claims")
        if not claims and not summary:
            raise SafeWorkerError("knowledge_note_substance_required")
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) != {
                "text",
                "origin",
                "sourceBlockIds",
                "confidence",
            }:
                raise SafeWorkerError("invalid_adapter_claim")
            if (
                not isinstance(claim.get("text"), str)
                or not claim["text"]
                or claim.get("origin") not in CANONICAL_ORIGINS
            ):
                raise SafeWorkerError("invalid_adapter_claim")
            _validate_evidence_ids(
                claim.get("sourceBlockIds"),
                available=source_block_ids,
                containing=set(evidence),
            )
            _validate_confidence(claim.get("confidence"))
        aliases = note.get("aliases")
        tags = note.get("tags")
        if not _bounded_strings(aliases, max_items=1000, max_length=500) or not _bounded_strings(
            tags,
            max_items=1000,
            max_length=200,
        ):
            raise SafeWorkerError("invalid_adapter_note_metadata")
        candidates = note.get("relatedNoteCandidates")
        if not isinstance(candidates, list) or len(candidates) > 10_000:
            raise SafeWorkerError("invalid_adapter_note_candidates")
        for candidate in candidates:
            if not isinstance(candidate, dict) or set(candidate) != {
                "targetId",
                "relation",
                "reason",
                "sourceBlockIds",
                "confidence",
            }:
                raise SafeWorkerError("invalid_adapter_note_candidate")
            _validate_identifier(candidate.get("targetId"), "candidate_target_id")
            if (
                not isinstance(candidate.get("relation"), str)
                or not candidate["relation"]
                or not isinstance(candidate.get("reason"), str)
                or not candidate["reason"]
            ):
                raise SafeWorkerError("invalid_adapter_note_candidate")
            _validate_evidence_ids(
                candidate.get("sourceBlockIds"),
                available=source_block_ids,
                containing=set(evidence),
            )
            _validate_confidence(candidate.get("confidence"))

    relations = bundle.get("relations")
    if not isinstance(relations, list) or len(relations) > 10_000:
        raise SafeWorkerError("invalid_adapter_relations")
    relation_ids: set[str] = set()
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {
            "id",
            "subject",
            "predicate",
            "object",
            "assertionStatus",
            "confidence",
            "evidenceBlockIds",
            "reviewStatus",
        }:
            raise SafeWorkerError("invalid_adapter_relation")
        relation_id = _validate_identifier(relation.get("id"), "relation_id")
        if relation_id in relation_ids:
            raise SafeWorkerError("duplicate_relation_id")
        relation_ids.add(relation_id)
        _validate_identifier(relation.get("subject"), "relation_subject")
        _validate_identifier(relation.get("object"), "relation_object")
        if not isinstance(relation.get("predicate"), str) or not relation["predicate"]:
            raise SafeWorkerError("invalid_adapter_relation")
        if relation.get("assertionStatus") not in {
            "extracted",
            "ai_summarized",
            "ai_inferred",
            "user_verified",
        } or relation.get("reviewStatus") not in {
            "pending",
            "auto_with_warnings",
            "user_verified",
            "rejected",
        }:
            raise SafeWorkerError("invalid_adapter_relation")
        _validate_evidence_ids(
            relation.get("evidenceBlockIds"),
            available=source_block_ids,
        )
        _validate_confidence(relation.get("confidence"))

    conflicts = bundle.get("conflicts")
    if not isinstance(conflicts, list) or len(conflicts) > 10_000:
        raise SafeWorkerError("invalid_adapter_conflicts")
    conflict_ids: set[str] = set()
    for conflict in conflicts:
        if not isinstance(conflict, dict) or set(conflict) != {
            "id",
            "statementA",
            "statementB",
            "dimension",
            "resolution",
            "requiresReview",
            "evidenceBlockIds",
        }:
            raise SafeWorkerError("invalid_adapter_conflict")
        conflict_id = _validate_identifier(conflict.get("id"), "conflict_id")
        if conflict_id in conflict_ids:
            raise SafeWorkerError("duplicate_conflict_id")
        conflict_ids.add(conflict_id)
        if (
            not isinstance(conflict.get("statementA"), dict)
            or not isinstance(conflict.get("statementB"), dict)
            or conflict.get("dimension")
            not in {
                "version_or_time",
                "contradictory_claim",
                "definition",
                "numeric_value",
                "other",
            }
            or not isinstance(conflict.get("resolution"), str)
            or not isinstance(conflict.get("requiresReview"), bool)
        ):
            raise SafeWorkerError("invalid_adapter_conflict")
        evidence = _validate_evidence_ids(
            conflict.get("evidenceBlockIds"),
            available=source_block_ids,
        )
        if len(set(evidence)) < 2:
            raise SafeWorkerError("invalid_adapter_conflict_evidence")

    options = request.get("options")
    metrics = output.get("provider_metrics")
    if not isinstance(options, dict) or not isinstance(metrics, dict):
        raise SafeWorkerError("invalid_adapter_provider_metrics")
    if (
        options.get("artifact_contract") != "akc-knowledge-bundle-1.0.0"
        or metrics.get("prompt_sha256") != options.get("prompt_revision")
        or metrics.get("knowledge_schema_sha256")
        != options.get("knowledge_schema_sha256")
        or metrics.get("unsupported_claim_count") != 0
    ):
        raise SafeWorkerError("knowledge_attestation_mismatch")


def _validate_classification(
    value: Any,
    *,
    camel_case: bool,
    available_evidence: set[str] | None = None,
) -> None:
    fields = (
        {
            "documentType",
            "secondaryTypes",
            "language",
            "languages",
            "topics",
            "domain",
            "structureProfile",
            "riskTier",
            "contains",
            "evidenceBlockIds",
            "confidence",
        }
        if camel_case
        else {
            "document_type",
            "secondary_types",
            "language",
            "languages",
            "topics",
            "domain",
            "structure_profile",
            "risk_tier",
            "contains",
            "evidence_block_ids",
            "confidence",
        }
    )
    if not isinstance(value, dict) or set(value) != fields:
        raise SafeWorkerError("invalid_knowledge_classification")
    document_type = value["documentType" if camel_case else "document_type"]
    language = value["language"]
    structure_profile = value[
        "structureProfile" if camel_case else "structure_profile"
    ]
    risk_tier = value["riskTier" if camel_case else "risk_tier"]
    if any(
        not isinstance(item, str) or not item or len(item) > 500
        for item in (document_type, language, structure_profile, risk_tier)
    ):
        raise SafeWorkerError("invalid_knowledge_classification")
    secondary_types = value[
        "secondaryTypes" if camel_case else "secondary_types"
    ]
    languages = value["languages"]
    topics = value["topics"]
    domain = value["domain"]
    if (
        not _bounded_strings(secondary_types, max_items=100, max_length=500)
        or not _bounded_strings(languages, max_items=100, max_length=100)
        or not _bounded_strings(topics, max_items=100, max_length=500)
        or not _bounded_strings(domain, max_items=100, max_length=500)
    ):
        raise SafeWorkerError("invalid_knowledge_classification")
    contains = value["contains"]
    if (
        not isinstance(contains, dict)
        or set(contains)
        != {
            "tables",
            "formulas",
            "figures",
            "citations",
            "personalData" if camel_case else "personal_data",
        }
        or any(not isinstance(flag, bool) for flag in contains.values())
    ):
        raise SafeWorkerError("invalid_knowledge_classification")
    evidence = value[
        "evidenceBlockIds" if camel_case else "evidence_block_ids"
    ]
    if (
        not isinstance(evidence, list)
        or not evidence
        or len(evidence) > 10_000
        or len(evidence) != len(set(evidence))
        or any(not isinstance(item, str) or not item for item in evidence)
        or (
            available_evidence is not None
            and not set(evidence).issubset(available_evidence)
        )
    ):
        raise SafeWorkerError("invalid_knowledge_classification")
    _validate_confidence(value["confidence"])


def _validate_stage_a_result(
    result: dict[str, Any],
    *,
    knowledge_input: dict[str, Any],
    evidence_ids: set[str],
) -> None:
    if set(result) != {
        "schemaVersion",
        "stage",
        "unitId",
        "classification",
        "sections",
    }:
        raise SafeWorkerError("invalid_knowledge_stage_result")
    _validate_classification(
        result.get("classification"),
        camel_case=True,
        available_evidence=evidence_ids,
    )
    sections = result.get("sections")
    if not isinstance(sections, list) or not sections or len(sections) > 2_000:
        raise SafeWorkerError("invalid_knowledge_stage_a_sections")
    section_ids: set[str] = set()
    observed: list[str] = []
    for section in sections:
        if (
            not isinstance(section, dict)
            or set(section) != {"sectionId", "title", "blockIds"}
        ):
            raise SafeWorkerError("invalid_knowledge_stage_a_section")
        section_id = _validate_identifier(section.get("sectionId"), "section_id")
        if len(section_id) > 128 or section_id in section_ids:
            raise SafeWorkerError("invalid_knowledge_stage_a_section")
        section_ids.add(section_id)
        title = section.get("title")
        if not isinstance(title, str) or not title or len(title) > 500:
            raise SafeWorkerError("invalid_knowledge_stage_a_section")
        block_ids = _validate_evidence_ids(
            section.get("blockIds"),
            available=evidence_ids,
        )
        observed.extend(block_ids)
    if len(observed) != len(set(observed)) or set(observed) != evidence_ids:
        raise SafeWorkerError("knowledge_stage_a_coverage_invalid")
    if not isinstance(knowledge_input.get("title"), str):
        raise SafeWorkerError("knowledge_stage_a_input_invalid")


def _validate_stage_b_result(
    result: dict[str, Any],
    *,
    knowledge_input: dict[str, Any],
    evidence_ids: set[str],
    output: dict[str, Any],
    request: dict[str, Any],
) -> None:
    if set(result) != {
        "schemaVersion",
        "stage",
        "unitId",
        "sectionId",
        "notes",
        "relations",
        "conflicts",
    } or result.get("sectionId") != knowledge_input.get("section_id"):
        raise SafeWorkerError("invalid_knowledge_stage_result")
    options = request["options"]
    legacy_request = {
        "knowledge_input": {
            "document_id": knowledge_input["document_id"],
            "blocks": [{"block_id": block_id} for block_id in sorted(evidence_ids)],
        },
        "options": {
            "artifact_contract": "akc-knowledge-bundle-1.0.0",
            "prompt_revision": options.get("prompt_revision"),
            "knowledge_schema_sha256": options.get("knowledge_schema_sha256"),
        },
    }
    legacy_output = {
        "knowledge_bundle": {
            "schemaVersion": "knowledge-1.0.0",
            "documentId": knowledge_input["document_id"],
            "notes": result.get("notes"),
            "relations": result.get("relations"),
            "conflicts": result.get("conflicts"),
        },
        "provider_metrics": {
            "prompt_sha256": output["provider_metrics"].get("prompt_sha256"),
            "knowledge_schema_sha256": output["provider_metrics"].get(
                "knowledge_schema_sha256"
            ),
            "unsupported_claim_count": output["provider_metrics"].get(
                "unsupported_claim_count"
            ),
        },
    }
    _validate_legacy_knowledge_output(
        legacy_output,
        legacy_request,
        require_notes=False,
    )
    note_ids = {
        note["noteId"]
        for note in result["notes"]
        if isinstance(note, dict) and isinstance(note.get("noteId"), str)
    }
    if any(
        not isinstance(relation, dict)
        or relation.get("subject") not in note_ids
        or relation.get("object") not in note_ids
        for relation in result["relations"]
    ):
        raise SafeWorkerError("knowledge_stage_b_relation_scope_invalid")


def _validate_stage_c_result(
    result: dict[str, Any],
    *,
    knowledge_input: dict[str, Any],
) -> None:
    if set(result) != {
        "schemaVersion",
        "stage",
        "unitId",
        "mergeGroups",
    }:
        raise SafeWorkerError("invalid_knowledge_stage_result")
    candidates = knowledge_input.get("candidates")
    if not isinstance(candidates, list):
        raise SafeWorkerError("knowledge_stage_c_input_invalid")
    candidates_by_id = {
        candidate["candidate_id"]: candidate
        for candidate in candidates
        if isinstance(candidate, dict) and isinstance(candidate.get("candidate_id"), str)
    }
    expected = set(candidates_by_id)
    groups = result.get("mergeGroups")
    if (
        not isinstance(groups, list)
        or not groups
        or len(groups) > 1_000
        or len(expected) != len(candidates)
    ):
        raise SafeWorkerError("invalid_knowledge_stage_c_groups")
    group_ids: set[str] = set()
    canonical_ids: set[str] = set()
    members: list[str] = []
    parent_by_canonical: dict[str, str | None] = {}
    for group in groups:
        if (
            not isinstance(group, dict)
            or not {
                "groupId",
                "canonicalCandidateId",
                "memberCandidateIds",
                "comparedCandidateIds",
                "evidenceBlockIds",
                "reason",
            }.issubset(group)
            or set(group)
            - {
                "groupId",
                "canonicalCandidateId",
                "memberCandidateIds",
                "comparedCandidateIds",
                "evidenceBlockIds",
                "reason",
                "parentCandidateId",
            }
        ):
            raise SafeWorkerError("invalid_knowledge_stage_c_group")
        group_id = _validate_identifier(group.get("groupId"), "merge_group_id")
        canonical = _validate_identifier(
            group.get("canonicalCandidateId"),
            "canonical_candidate_id",
        )
        if group_id in group_ids or canonical in canonical_ids:
            raise SafeWorkerError("invalid_knowledge_stage_c_group")
        group_ids.add(group_id)
        canonical_ids.add(canonical)
        group_members = group.get("memberCandidateIds")
        if (
            not isinstance(group_members, list)
            or not group_members
            or len(group_members) != len(set(group_members))
            or any(
                not isinstance(member, str) or member not in expected
                for member in group_members
            )
            or canonical not in group_members
        ):
            raise SafeWorkerError("invalid_knowledge_stage_c_group")
        compared = group.get("comparedCandidateIds")
        evidence = group.get("evidenceBlockIds")
        reason = group.get("reason")
        expected_evidence = {
            block_id
            for member in group_members
            for block_id in candidates_by_id[member]["evidence_block_ids"]
        }
        if (
            not isinstance(compared, list)
            or len(compared) != len(set(compared))
            or set(compared) != set(group_members)
            or not isinstance(evidence, list)
            or len(evidence) != len(set(evidence))
            or set(evidence) != expected_evidence
            or not isinstance(reason, str)
            or not reason.strip()
            or reason.casefold().strip()
            in {"duplicate", "duplicates", "merge", "same", "similar"}
        ):
            raise SafeWorkerError("invalid_knowledge_stage_c_group")
        if len(group_members) > 1:
            semantic_values = [
                {
                    str(value).casefold().strip()
                    for value in (
                        candidates_by_id[member]["normalized_title"],
                        *candidates_by_id[member]["aliases"],
                        *candidates_by_id[member]["tags"],
                        *[
                            claim["signature_sha256"]
                            for claim in candidates_by_id[member]["claims"]
                            if isinstance(claim, dict)
                        ],
                    )
                    if str(value).strip()
                }
                for member in group_members
            ]
            semantic_tokens = [
                {
                    token
                    for token in re.findall(
                        r"[\w-]+",
                        (
                            f"{candidates_by_id[member]['normalized_title']} "
                            f"{candidates_by_id[member]['summary']}"
                        ).casefold(),
                    )
                    if len(token) >= 4
                }
                for member in group_members
            ]
            adjacency: dict[int, set[int]] = {
                index: set() for index in range(len(group_members))
            }
            for left in range(len(group_members)):
                for right in range(left + 1, len(group_members)):
                    overlap = semantic_tokens[left] & semantic_tokens[right]
                    union = semantic_tokens[left] | semantic_tokens[right]
                    if semantic_values[left] & semantic_values[right] or (
                        len(overlap) >= 2
                        and union
                        and len(overlap) / len(union) >= 0.5
                    ):
                        adjacency[left].add(right)
                        adjacency[right].add(left)
            reachable: set[int] = {0}
            pending: list[int] = [0]
            while pending:
                current_index = pending.pop()
                for neighbor in adjacency[current_index] - reachable:
                    reachable.add(neighbor)
                    pending.append(neighbor)
            if len(reachable) != len(group_members):
                raise SafeWorkerError("knowledge_stage_c_merge_semantics_unsupported")
        parent = group.get("parentCandidateId")
        if parent is not None and not isinstance(parent, str):
            raise SafeWorkerError("invalid_knowledge_stage_c_group")
        parent_by_canonical[canonical] = parent
        members.extend(group_members)
    if len(members) != len(set(members)) or set(members) != expected:
        raise SafeWorkerError("knowledge_stage_c_coverage_invalid")
    if any(
        parent is not None and parent not in canonical_ids
        for parent in parent_by_canonical.values()
    ):
        raise SafeWorkerError("knowledge_stage_c_parent_scope_invalid")
    for start in canonical_ids:
        seen: set[str] = set()
        current: str | None = start
        while current is not None:
            if current in seen:
                raise SafeWorkerError("knowledge_stage_c_hierarchy_cycle")
            seen.add(current)
            current = parent_by_canonical[current]


def _validate_stage_d_result(
    result: dict[str, Any],
    *,
    knowledge_input: dict[str, Any],
) -> None:
    if set(result) != {
        "schemaVersion",
        "stage",
        "unitId",
        "retrievalStatus",
        "links",
    } or result.get("retrievalStatus") != knowledge_input.get("retrieval_status"):
        raise SafeWorkerError("invalid_knowledge_stage_result")
    links = result.get("links")
    status = knowledge_input.get("retrieval_status")
    if (
        not isinstance(links, list)
        or len(links) > 1_000
        or (status != "ready" and links)
    ):
        raise SafeWorkerError("invalid_knowledge_stage_d_links")
    sources = {
        candidate["candidate_id"]: set(candidate["evidence_block_ids"])
        for candidate in knowledge_input.get("source_candidates", [])
        if isinstance(candidate, dict)
    }
    targets = {
        candidate["stable_id"]
        for candidate in knowledge_input.get("retrieval_candidates", [])
        if isinstance(candidate, dict)
    }
    for link in links:
        if not isinstance(link, dict) or set(link) != {
            "sourceCandidateId",
            "targetStableId",
            "relation",
            "reason",
            "evidenceBlockIds",
            "confidence",
        }:
            raise SafeWorkerError("invalid_knowledge_stage_d_link")
        source_id = link.get("sourceCandidateId")
        target_id = link.get("targetStableId")
        if (
            source_id not in sources
            or target_id not in targets
            or not isinstance(link.get("relation"), str)
            or not link["relation"]
            or not isinstance(link.get("reason"), str)
            or not link["reason"]
        ):
            raise SafeWorkerError("invalid_knowledge_stage_d_link")
        _validate_evidence_ids(
            link.get("evidenceBlockIds"),
            available=sources[source_id],
        )
        _validate_confidence(link.get("confidence"))


def _validate_pipeline_knowledge_output(
    output: dict[str, Any],
    request: dict[str, Any],
) -> None:
    knowledge_input = request.get("knowledge_input")
    options = request.get("options")
    metrics = output.get("provider_metrics")
    if (
        "knowledge_bundle" in output
        or not isinstance(knowledge_input, dict)
        or not isinstance(options, dict)
        or not isinstance(metrics, dict)
    ):
        raise SafeWorkerError("invalid_knowledge_stage_result")
    stage = knowledge_input.get("stage")
    unit_id = knowledge_input.get("unit_id")
    result = output.get("knowledge_stage_result")
    if (
        stage not in {"A", "B", "C", "D"}
        or not isinstance(unit_id, str)
        or not isinstance(result, dict)
        or result.get("schemaVersion") != "knowledge-pipeline-result-1.0.0"
        or result.get("stage") != stage
        or result.get("unitId") != unit_id
    ):
        raise SafeWorkerError("knowledge_stage_scope_mismatch")
    if (
        options.get("artifact_contract")
        != "akc-knowledge-pipeline-stage-1.0.0"
        or options.get("knowledge_stage") != stage
        or options.get("knowledge_unit_id") != unit_id
        or metrics.get("prompt_sha256") != options.get("prompt_revision")
        or metrics.get("knowledge_schema_sha256")
        != options.get("knowledge_schema_sha256")
        or metrics.get("knowledge_stage") != stage
        or metrics.get("knowledge_unit_id") != unit_id
        or metrics.get("unsupported_claim_count") != 0
    ):
        raise SafeWorkerError("knowledge_attestation_mismatch")
    if stage == "A":
        evidence_ids = {
            block["block_id"]
            for block in knowledge_input.get("blocks", [])
            if isinstance(block, dict) and isinstance(block.get("block_id"), str)
        }
        _validate_stage_a_result(
            result,
            knowledge_input=knowledge_input,
            evidence_ids=evidence_ids,
        )
    elif stage == "B":
        evidence_ids = {
            fragment["evidence_block_id"]
            for fragment in knowledge_input.get("fragments", [])
            if isinstance(fragment, dict)
            and isinstance(fragment.get("evidence_block_id"), str)
        }
        _validate_stage_b_result(
            result,
            knowledge_input=knowledge_input,
            evidence_ids=evidence_ids,
            output=output,
            request=request,
        )
    elif stage == "C":
        _validate_stage_c_result(result, knowledge_input=knowledge_input)
    else:
        _validate_stage_d_result(result, knowledge_input=knowledge_input)


def _validate_knowledge_output(
    output: dict[str, Any],
    request: dict[str, Any],
) -> None:
    options = request.get("options")
    contract = options.get("artifact_contract") if isinstance(options, dict) else None
    if contract == "akc-knowledge-bundle-1.0.0":
        if "knowledge_stage_result" in output:
            raise SafeWorkerError("invalid_knowledge_bundle")
        _validate_legacy_knowledge_output(output, request)
        return
    if contract == "akc-knowledge-pipeline-stage-1.0.0":
        _validate_pipeline_knowledge_output(output, request)
        return
    raise SafeWorkerError("knowledge_artifact_contract_invalid")


def _validate_evidence_ids(
    value: Any,
    *,
    available: set[str],
    containing: set[str] | None = None,
) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 10_000
        or len(value) != len(set(value))
        or any(not isinstance(item, str) or item not in available for item in value)
        or (containing is not None and not set(value).issubset(containing))
    ):
        raise SafeWorkerError("knowledge_evidence_required")
    return value


def _validate_confidence(value: Any) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise SafeWorkerError("invalid_adapter_confidence")


def _bounded_strings(value: Any, *, max_items: int, max_length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= max_items
        and all(isinstance(item, str) and len(item) <= max_length for item in value)
    )


def _legacy_knowledge_input(
    input_path: Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    try:
        value = json.loads(input_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeWorkerError("knowledge_input_schema_invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {
            "schema_version",
            "document_id",
            "document_version_id",
            "title",
            "blocks",
        }
        or value.get("schema_version") != "knowledge-input-1.0.0"
        or value.get("document_id") != request.get("document_id")
        or value.get("document_version_id") != request.get("document_version_id")
        or not isinstance(value.get("title"), str)
        or not value["title"]
        or len(value["title"]) > 500
    ):
        raise SafeWorkerError("knowledge_input_schema_invalid")
    blocks = value.get("blocks")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 10_000:
        raise SafeWorkerError("knowledge_blocks_required")
    block_ids: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict) or set(block) != {
            "block_id",
            "text",
            "source_refs",
        }:
            raise SafeWorkerError("invalid_knowledge_block")
        block_id = _validate_identifier(block.get("block_id"), "knowledge_block_id")
        if block_id in block_ids:
            raise SafeWorkerError("duplicate_knowledge_block_id")
        block_ids.add(block_id)
        text = block.get("text")
        if not isinstance(text, str) or not text or len(text) > 1_000_000:
            raise SafeWorkerError("invalid_knowledge_block")
        _validate_source_refs(block.get("source_refs"), request)
    return value


def _validate_stage_semantic_descriptor(
    candidate: Any,
    *,
    expected_id_field: str,
    allow_claims: bool,
) -> set[str]:
    common = {
        expected_id_field,
        "normalized_title" if expected_id_field == "candidate_id" else "title",
        "note_type",
        "summary",
        "tags",
        "evidence_block_ids",
        "evidence",
    }
    if expected_id_field == "candidate_id":
        common.add("aliases")
        if allow_claims:
            common.add("claims")
    if not isinstance(candidate, dict) or set(candidate) != common:
        raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
    identity = candidate.get(expected_id_field)
    title_field = (
        "normalized_title" if expected_id_field == "candidate_id" else "title"
    )
    title = candidate.get(title_field)
    summary = candidate.get("summary")
    tags = candidate.get("tags")
    evidence_ids = candidate.get("evidence_block_ids")
    evidence = candidate.get("evidence")
    if (
        not isinstance(identity, str)
        or not 3 <= len(identity) <= (128 if expected_id_field == "candidate_id" else 240)
        or not isinstance(title, str)
        or not 1 <= len(title) <= 300
        or not isinstance(candidate.get("note_type"), str)
        or not candidate["note_type"]
        or not isinstance(summary, str)
        or len(summary) > 2_000
        or not _bounded_strings(tags, max_items=20, max_length=200)
        or not isinstance(evidence_ids, list)
        or not evidence_ids
        or len(evidence_ids) > 256
        or len(evidence_ids) != len(set(evidence_ids))
        or any(not isinstance(item, str) or not item for item in evidence_ids)
        or not isinstance(evidence, list)
        or not evidence
        or len(evidence) != len(evidence_ids)
    ):
        raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
    available = set(evidence_ids)
    described: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {
            "block_id",
            "snippet",
            "snippet_sha256",
        }:
            raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
        block_id = item.get("block_id")
        snippet = item.get("snippet")
        snippet_sha = item.get("snippet_sha256")
        if (
            not isinstance(block_id, str)
            or block_id not in available
            or block_id in described
            or not isinstance(snippet, str)
            or not 1 <= len(snippet) <= 240
            or not isinstance(snippet_sha, str)
            or snippet_sha != hashlib.sha256(snippet.encode()).hexdigest()
        ):
            raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
        described.add(block_id)
    if described != available:
        raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
    if expected_id_field == "candidate_id":
        if not _bounded_strings(
            candidate.get("aliases"),
            max_items=20,
            max_length=200,
        ):
            raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
        claims = candidate.get("claims", [])
        if not isinstance(claims, list) or len(claims) > 20:
            raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) != {
                "text",
                "signature_sha256",
                "evidence_block_ids",
            }:
                raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
            text = claim.get("text")
            claim_evidence = claim.get("evidence_block_ids")
            signature = claim.get("signature_sha256")
            if (
                not isinstance(text, str)
                or not 1 <= len(text) <= 500
                or not isinstance(claim_evidence, list)
                or not claim_evidence
                or len(claim_evidence) > 32
                or len(claim_evidence) != len(set(claim_evidence))
                or not set(claim_evidence).issubset(available)
                or not isinstance(signature, str)
                or signature
                != hashlib.sha256(
                    "\0".join((text, *claim_evidence)).encode()
                ).hexdigest()
            ):
                raise SafeWorkerError("knowledge_semantic_descriptor_invalid")
    return available


def _pipeline_knowledge_input(
    value: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    options = request.get("options")
    stage = value.get("stage")
    unit_id = value.get("unit_id")
    if (
        value.get("schema_version") != "knowledge-pipeline-input-1.0.0"
        or stage not in {"A", "B", "C", "D"}
        or not isinstance(unit_id, str)
        or not 3 <= len(unit_id) <= 128
        or value.get("document_id") != request.get("document_id")
        or value.get("document_version_id") != request.get("document_version_id")
        or not isinstance(options, dict)
        or options.get("artifact_contract")
        != "akc-knowledge-pipeline-stage-1.0.0"
        or options.get("knowledge_stage") != stage
        or options.get("knowledge_unit_id") != unit_id
    ):
        raise SafeWorkerError("knowledge_pipeline_input_invalid")

    if stage == "A":
        if set(value) != {
            "schema_version",
            "stage",
            "unit_id",
            "document_id",
            "document_version_id",
            "title",
            "headings",
            "blocks",
        }:
            raise SafeWorkerError("knowledge_stage_a_input_invalid")
        title = value.get("title")
        blocks = value.get("blocks")
        headings = value.get("headings")
        if (
            not isinstance(title, str)
            or not title
            or len(title) > 500
            or not isinstance(blocks, list)
            or not blocks
            or len(blocks) > 10_000
            or not isinstance(headings, list)
            or len(headings) > 2_000
        ):
            raise SafeWorkerError("knowledge_stage_a_input_invalid")
        block_ids: set[str] = set()
        heading_paths: list[list[str]] = []
        for block in blocks:
            if not isinstance(block, dict) or set(block) != {
                "block_id",
                "block_type",
                "page_number1",
                "char_count",
                "preview",
                "heading_path",
            }:
                raise SafeWorkerError("knowledge_stage_a_input_invalid")
            block_id = _validate_identifier(
                block.get("block_id"),
                "knowledge_block_id",
            )
            block_type = block.get("block_type")
            page_number = block.get("page_number1")
            char_count = block.get("char_count")
            preview = block.get("preview")
            heading_path = block.get("heading_path")
            if (
                block_id in block_ids
                or len(block_id) > 160
                or not isinstance(block_type, str)
                or not block_type
                or len(block_type) > 40
                or not isinstance(page_number, int)
                or isinstance(page_number, bool)
                or page_number < 1
                or not isinstance(char_count, int)
                or isinstance(char_count, bool)
                or not 1 <= char_count <= 10_000_000
                or not isinstance(preview, str)
                or not 1 <= len(preview) <= 240
                or not isinstance(heading_path, list)
                or len(heading_path) > 32
                or any(not isinstance(item, str) for item in heading_path)
            ):
                raise SafeWorkerError("knowledge_stage_a_input_invalid")
            block_ids.add(block_id)
            heading_paths.append(heading_path)
        heading_ids: set[str] = set()
        heading_parents: list[str | None] = []
        for heading in headings:
            if (
                not isinstance(heading, dict)
                or not {"heading_id", "block_id", "level", "title_preview"}.issubset(
                    heading
                )
                or set(heading)
                - {
                    "heading_id",
                    "block_id",
                    "level",
                    "title_preview",
                    "parent_heading_id",
                }
            ):
                raise SafeWorkerError("knowledge_stage_a_input_invalid")
            heading_id = _validate_identifier(
                heading.get("heading_id"),
                "knowledge_heading_id",
            )
            heading_block_id = heading.get("block_id")
            level = heading.get("level")
            title_preview = heading.get("title_preview")
            parent = heading.get("parent_heading_id")
            if (
                heading_id in heading_ids
                or len(heading_id) > 160
                or heading_block_id not in block_ids
                or not isinstance(level, int)
                or isinstance(level, bool)
                or not 1 <= level <= 32
                or not isinstance(title_preview, str)
                or not 1 <= len(title_preview) <= 240
                or (parent is not None and not isinstance(parent, str))
            ):
                raise SafeWorkerError("knowledge_stage_a_input_invalid")
            heading_ids.add(heading_id)
            heading_parents.append(parent)
        if any(
            parent is not None and parent not in heading_ids
            for parent in heading_parents
        ) or any(
            not set(heading_path).issubset(heading_ids)
            for heading_path in heading_paths
        ):
            raise SafeWorkerError("knowledge_stage_a_input_invalid")
        return value

    if stage == "B":
        if set(value) != {
            "schema_version",
            "stage",
            "unit_id",
            "document_id",
            "document_version_id",
            "section_id",
            "section_title",
            "classification",
            "shard_index0",
            "shard_count",
            "fragments",
        }:
            raise SafeWorkerError("knowledge_stage_b_input_invalid")
        section_id = value.get("section_id")
        section_title = value.get("section_title")
        shard_index = value.get("shard_index0")
        shard_count = value.get("shard_count")
        fragments = value.get("fragments")
        if (
            not isinstance(section_id, str)
            or not 3 <= len(section_id) <= 128
            or not isinstance(section_title, str)
            or not 1 <= len(section_title) <= 500
            or not isinstance(shard_index, int)
            or isinstance(shard_index, bool)
            or not isinstance(shard_count, int)
            or isinstance(shard_count, bool)
            or not 0 <= shard_index < shard_count <= 10_000
            or not isinstance(fragments, list)
            or not fragments
            or len(fragments) > 64
        ):
            raise SafeWorkerError("knowledge_stage_b_input_invalid")
        _validate_classification(value.get("classification"), camel_case=False)
        fragment_ids: set[str] = set()
        for fragment in fragments:
            if not isinstance(fragment, dict) or set(fragment) != {
                "fragment_id",
                "evidence_block_id",
                "text",
                "source_refs",
            }:
                raise SafeWorkerError("knowledge_stage_b_input_invalid")
            fragment_id = _validate_identifier(
                fragment.get("fragment_id"),
                "knowledge_fragment_id",
            )
            evidence_id = _validate_identifier(
                fragment.get("evidence_block_id"),
                "knowledge_block_id",
            )
            text = fragment.get("text")
            if (
                fragment_id in fragment_ids
                or len(fragment_id) > 200
                or len(evidence_id) > 160
                or not isinstance(text, str)
                or not 1 <= len(text) <= 64_000
            ):
                raise SafeWorkerError("knowledge_stage_b_input_invalid")
            fragment_ids.add(fragment_id)
            _validate_source_refs(fragment.get("source_refs"), request)
        return value

    if stage == "C":
        if set(value) != {
            "schema_version",
            "stage",
            "unit_id",
            "document_id",
            "document_version_id",
            "candidates",
        }:
            raise SafeWorkerError("knowledge_stage_c_input_invalid")
        candidates = value.get("candidates")
        if (
            not isinstance(candidates, list)
            or not candidates
            or len(candidates) > 1_000
        ):
            raise SafeWorkerError("knowledge_stage_c_input_invalid")
        candidate_ids: set[str] = set()
        for candidate in candidates:
            _validate_stage_semantic_descriptor(
                candidate,
                expected_id_field="candidate_id",
                allow_claims=True,
            )
            candidate_id = _validate_identifier(
                candidate.get("candidate_id"),
                "knowledge_candidate_id",
            )
            if candidate_id in candidate_ids or len(candidate_id) > 128:
                raise SafeWorkerError("knowledge_stage_c_input_invalid")
            candidate_ids.add(candidate_id)
        return value

    if set(value) != {
        "schema_version",
        "stage",
        "unit_id",
        "tenant_id",
        "document_id",
        "document_version_id",
        "allowed_project_ids",
        "acl_attestation",
        "source_candidates",
        "retrieval_status",
        "retrieval_candidates",
    } or value.get("tenant_id") != request.get("tenant_id"):
        raise SafeWorkerError("knowledge_stage_d_input_invalid")
    allowed_projects = value.get("allowed_project_ids")
    sources = value.get("source_candidates")
    retrieval_status = value.get("retrieval_status")
    retrieval = value.get("retrieval_candidates")
    acl_attestation = value.get("acl_attestation")
    if (
        not isinstance(allowed_projects, list)
        or not allowed_projects
        or len(allowed_projects) > 50
        or len(allowed_projects) != len(set(allowed_projects))
        or any(not isinstance(item, str) or not item for item in allowed_projects)
        or not isinstance(acl_attestation, dict)
        or set(acl_attestation)
        != {"tenant_id", "allowed_project_ids", "scope_sha256"}
        or acl_attestation.get("tenant_id") != value.get("tenant_id")
        or acl_attestation.get("allowed_project_ids") != allowed_projects
        or acl_attestation.get("scope_sha256")
        != hashlib.sha256(
            "\0".join((str(value.get("tenant_id")), *allowed_projects)).encode()
        ).hexdigest()
        or not isinstance(sources, list)
        or not sources
        or len(sources) > 1_000
        or retrieval_status
        not in {"provider_unverified", "no_candidates", "ready"}
        or not isinstance(retrieval, list)
        or len(retrieval) > 15
        or (retrieval_status != "ready" and retrieval)
        or (retrieval_status == "ready" and not retrieval)
    ):
        raise SafeWorkerError("knowledge_stage_d_input_invalid")
    source_ids: set[str] = set()
    for candidate in sources:
        _validate_stage_semantic_descriptor(
            candidate,
            expected_id_field="candidate_id",
            allow_claims=True,
        )
        candidate_id = _validate_identifier(
            candidate.get("candidate_id"),
            "knowledge_candidate_id",
        )
        if candidate_id in source_ids or len(candidate_id) > 128:
            raise SafeWorkerError("knowledge_stage_d_input_invalid")
        source_ids.add(candidate_id)
    retrieval_ids: set[str] = set()
    for candidate in retrieval:
        if not isinstance(candidate, dict) or set(candidate) != {
            "stable_id",
            "project_id",
            "title",
            "note_type",
            "summary",
            "tags",
            "evidence_block_ids",
            "evidence",
            "score",
            "source_hash",
        }:
            raise SafeWorkerError("knowledge_stage_d_input_invalid")
        _validate_stage_semantic_descriptor(
            {
                key: item
                for key, item in candidate.items()
                if key not in {"project_id", "score", "source_hash"}
            },
            expected_id_field="stable_id",
            allow_claims=False,
        )
        stable_id = candidate.get("stable_id")
        project_id = candidate.get("project_id")
        evidence = candidate.get("evidence_block_ids")
        score = candidate.get("score")
        source_hash = candidate.get("source_hash")
        if (
            not isinstance(stable_id, str)
            or not 3 <= len(stable_id) <= 240
            or stable_id in retrieval_ids
            or project_id not in allowed_projects
            or not isinstance(evidence, list)
            or not evidence
            or len(evidence) > 100
            or len(evidence) != len(set(evidence))
            or any(not isinstance(item, str) or not item for item in evidence)
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or not -1 <= score <= 1
            or not isinstance(source_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
        ):
            raise SafeWorkerError("knowledge_stage_d_input_invalid")
        retrieval_ids.add(stable_id)
    return value


def _knowledge_input(input_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    try:
        body = input_path.read_bytes()
        value = json.loads(body)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeWorkerError("knowledge_input_schema_invalid") from exc
    if not isinstance(value, dict):
        raise SafeWorkerError("knowledge_input_schema_invalid")
    if value.get("schema_version") == "knowledge-input-1.0.0":
        return _legacy_knowledge_input(input_path, request)
    if (
        value.get("schema_version") == "knowledge-pipeline-input-1.0.0"
        and 0 < len(body) <= 8 * 1024 * 1024
    ):
        return _pipeline_knowledge_input(value, request)
    raise SafeWorkerError("knowledge_input_schema_invalid")


def _validate_adapter_output(
    value: Any,
    *,
    worker_kind: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SafeWorkerError("invalid_adapter_response")
    try:
        allowed_fields = _ADAPTER_TOP_LEVEL_FIELDS[worker_kind]
    except KeyError as exc:
        raise SafeWorkerError("invalid_worker_kind") from exc
    unexpected_fields = set(value) - allowed_fields
    if unexpected_fields:
        raise SafeWorkerError("adapter_response_reserved_or_unknown_field")
    if worker_kind == "parser":
        _validate_parser_output(value, request)
    else:
        _validate_knowledge_output(value, request)
    _validate_warning_list(value.get("warnings", []))
    provider_metrics = value.get("provider_metrics", {})
    if not isinstance(provider_metrics, dict) or len(provider_metrics) > 128:
        raise SafeWorkerError("invalid_adapter_provider_metrics")
    provider_raw = value.get("provider_raw")
    if provider_raw is not None and not isinstance(provider_raw, (dict, list)):
        raise SafeWorkerError("invalid_adapter_provider_raw")
    # This also rejects NaN/infinity and non-JSON values before composition.
    _canonical_json(value)
    return value


def _adapter_request(request: dict[str, Any]) -> dict[str, Any]:
    sanitized = {key: value for key, value in request.items() if key in _ADAPTER_REQUEST_FIELDS}
    options = sanitized.get("options", {})
    if not isinstance(options, dict) or len(options) > 256:
        raise SafeWorkerError("invalid_adapter_options")
    for key in options:
        if not isinstance(key, str):
            raise SafeWorkerError("invalid_adapter_option_key")
        folded = key.casefold()
        if folded in _SENSITIVE_OPTION_KEYS or folded.endswith(
            ("_api_key", "_credential", "_password", "_secret", "_url")
        ):
            raise SafeWorkerError("sensitive_adapter_option_forbidden")
    if len(_canonical_json(options)) > 1024 * 1024:
        raise SafeWorkerError("adapter_options_too_large")
    sanitized["options"] = options
    # Return a JSON-deep-copy so adapter mutation cannot affect the caller's
    # authenticated request or later scope validation.
    cloned = json.loads(_canonical_json(sanitized))
    if not isinstance(cloned, dict):
        raise SafeWorkerError("invalid_adapter_request")
    return cloned


class MockParserAdapter:
    def __init__(self, provider_key: str, *, experimental: bool = False) -> None:
        self.provider_key = provider_key
        self.experimental = experimental

    def self_test(self) -> None:
        result = self.process(Path(__file__), {"options": {"mock_text": "self-test"}})
        if not result.get("blocks"):
            raise RuntimeError("mock parser self-test failed")

    def process(self, input_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        raw_options = request.get("options")
        options: dict[str, Any] = raw_options if isinstance(raw_options, dict) else {}
        text = str(options.get("mock_text") or "[mock parser output]")[:100_000]
        block_id = "blk_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        warnings = ["mock_adapter_result_not_for_production"]
        if self.experimental:
            warnings.append("experimental_shadow_result")
        return {
            "blocks": [
                {
                    "block_id": block_id,
                    "type": str(options.get("block_type") or "paragraph"),
                    "text": text,
                    "origin": "ocr_extracted",
                    "source_refs": [_source_ref(request)],
                    "quality_flags": warnings.copy(),
                }
            ],
            "generated_claims": [],
            "warnings": warnings,
        }


class MockKnowledgeAdapter:
    def self_test(self) -> None:
        request = {
            "document_id": "urn:akmp:doc:selftest",
            "document_version_id": "urn:akmp:doc-version:selftest-v1",
            "options": {
                "artifact_contract": "akc-knowledge-bundle-1.0.0",
                "prompt_revision": "sha256:" + ("1" * 64),
                "knowledge_schema_sha256": "sha256:" + ("2" * 64),
            },
            "knowledge_input": {
                "schema_version": "knowledge-input-1.0.0",
                "document_id": "urn:akmp:doc:selftest",
                "document_version_id": "urn:akmp:doc-version:selftest-v1",
                "title": "Self-test",
                "blocks": [
                    {
                        "block_id": "blk_selftest",
                        "text": "self-test",
                        "source_refs": [
                            {
                                "document_id": "urn:akmp:doc:selftest",
                                "document_version_id": "urn:akmp:doc-version:selftest-v1",
                                "page_index0": 0,
                                "page_number1": 1,
                                "bbox1000": [0, 0, 10, 10],
                            }
                        ],
                    }
                ],
            },
        }
        if not self.process(Path(__file__), request).get("knowledge_bundle"):
            raise RuntimeError("mock knowledge self-test failed")

    def process(self, input_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        del input_path
        raw_options = request.get("options")
        options: dict[str, Any] = raw_options if isinstance(raw_options, dict) else {}
        knowledge_input = request.get("knowledge_input")
        if (
            isinstance(knowledge_input, dict)
            and knowledge_input.get("schema_version")
            == "knowledge-pipeline-input-1.0.0"
        ):
            stage = knowledge_input.get("stage")
            unit_id = knowledge_input.get("unit_id")
            if stage not in {"A", "B", "C", "D"} or not isinstance(unit_id, str):
                raise SafeWorkerError("knowledge_pipeline_input_invalid")
            result: dict[str, Any] = {
                "schemaVersion": "knowledge-pipeline-result-1.0.0",
                "stage": stage,
                "unitId": unit_id,
            }
            if stage == "A":
                blocks = knowledge_input.get("blocks")
                if not isinstance(blocks, list):
                    raise SafeWorkerError("knowledge_stage_a_input_invalid")
                evidence_ids = [
                    block["block_id"]
                    for block in blocks
                    if isinstance(block, dict)
                    and isinstance(block.get("block_id"), str)
                ]
                if not evidence_ids:
                    raise SafeWorkerError("knowledge_evidence_required")
                result.update(
                    {
                        "classification": {
                            "documentType": "document",
                            "secondaryTypes": [],
                            "language": "und",
                            "languages": [],
                            "topics": [],
                            "domain": [],
                            "structureProfile": "sectioned",
                            "riskTier": "low",
                            "contains": {
                                "tables": False,
                                "formulas": False,
                                "figures": False,
                                "citations": False,
                                "personalData": False,
                            },
                            "evidenceBlockIds": [evidence_ids[0]],
                            "confidence": 0.5,
                        },
                        "sections": [
                            {
                                "sectionId": f"section.{unit_id}",
                                "title": str(knowledge_input.get("title") or "Document")[
                                    :500
                                ],
                                "blockIds": evidence_ids,
                            }
                        ],
                    }
                )
            elif stage == "B":
                fragments = knowledge_input.get("fragments")
                if not isinstance(fragments, list) or not fragments:
                    raise SafeWorkerError("knowledge_evidence_required")
                evidence_ids = list(
                    dict.fromkeys(
                        fragment["evidence_block_id"]
                        for fragment in fragments
                        if isinstance(fragment, dict)
                        and isinstance(fragment.get("evidence_block_id"), str)
                    )
                )
                stable = hashlib.sha256(
                    _canonical_json([unit_id, *evidence_ids])
                ).hexdigest()[:24]
                result.update(
                    {
                        "sectionId": knowledge_input.get("section_id"),
                        "notes": [
                            {
                                "noteId": f"mock.{stable}",
                                "title": str(
                                    knowledge_input.get("section_title")
                                    or "Mock knowledge note"
                                )[:500],
                                "noteType": "concept",
                                "contentOrigin": "ai_summarized",
                                "evidenceBlockIds": evidence_ids,
                                "summary": "\n\n".join(
                                    str(fragment.get("text") or "")
                                    for fragment in fragments
                                    if isinstance(fragment, dict)
                                )[:100_000],
                                "claims": [],
                                "aliases": [],
                                "tags": [],
                                "relatedNoteCandidates": [],
                                "reviewStatus": "pending",
                            }
                        ],
                        "relations": [],
                        "conflicts": [],
                    }
                )
            elif stage == "C":
                candidates = knowledge_input.get("candidates")
                if not isinstance(candidates, list) or not candidates:
                    raise SafeWorkerError("knowledge_stage_c_input_invalid")
                result["mergeGroups"] = [
                    {
                        "groupId": "group."
                        + hashlib.sha256(
                            str(candidate["candidate_id"]).encode()
                        ).hexdigest()[:24],
                        "canonicalCandidateId": candidate["candidate_id"],
                        "memberCandidateIds": [candidate["candidate_id"]],
                        "comparedCandidateIds": [candidate["candidate_id"]],
                        "evidenceBlockIds": candidate["evidence_block_ids"],
                        "reason": "Kept separate because no other candidate was compared.",
                    }
                    for candidate in candidates
                    if isinstance(candidate, dict)
                    and isinstance(candidate.get("candidate_id"), str)
                ]
            else:
                result.update(
                    {
                        "retrievalStatus": knowledge_input.get("retrieval_status"),
                        "links": [],
                    }
                )
            return {
                "knowledge_stage_result": result,
                "warnings": ["mock_adapter_result_not_for_production"],
                "provider_metrics": {
                    "prompt_sha256": options.get("prompt_revision"),
                    "knowledge_schema_sha256": options.get(
                        "knowledge_schema_sha256"
                    ),
                    "knowledge_stage": stage,
                    "knowledge_unit_id": unit_id,
                    "unsupported_claim_count": 0,
                },
            }
        blocks = (
            knowledge_input.get("blocks") if isinstance(knowledge_input, dict) else None
        )
        if not isinstance(blocks, list) or not blocks:
            raise SafeWorkerError("knowledge_blocks_required")
        evidence_ids = [
            str(block.get("block_id"))
            for block in blocks
            if isinstance(block, dict) and block.get("block_id") and block.get("source_refs")
        ]
        if not evidence_ids:
            raise SafeWorkerError("knowledge_evidence_required")
        title = str(
            knowledge_input.get("title")
            if isinstance(knowledge_input, dict)
            else "Mock knowledge note"
        )[:200]
        stable = hashlib.sha256(_canonical_json(evidence_ids)).hexdigest()[:24]
        return {
            "knowledge_bundle": {
                "schemaVersion": "knowledge-1.0.0",
                "documentId": request["document_id"],
                "notes": [
                    {
                        "noteId": f"mock.{stable}",
                        "title": title,
                        "noteType": "concept",
                        "contentOrigin": "ai_summarized",
                        "evidenceBlockIds": evidence_ids,
                        "summary": "\n\n".join(
                            str(block.get("text") or "") for block in blocks
                        )[:100_000],
                        "claims": [],
                        "aliases": [],
                        "tags": [],
                        "relatedNoteCandidates": [],
                        "reviewStatus": "pending",
                    }
                ],
                "relations": [],
                "conflicts": [],
            },
            "warnings": ["mock_adapter_result_not_for_production"],
            "provider_metrics": {
                "prompt_sha256": options.get("prompt_revision"),
                "knowledge_schema_sha256": options.get("knowledge_schema_sha256"),
                "unsupported_claim_count": 0,
            },
        }


def _load_adapter(config: WorkerConfig) -> Adapter:
    if config.adapter_mode == "mock":
        if config.worker_kind == "knowledge":
            return MockKnowledgeAdapter()
        return MockParserAdapter(config.provider_key, experimental=config.experimental)
    if config.adapter_mode != "production" or not config.adapter_module:
        raise SafeWorkerError("production_adapter_module_required")
    module = importlib.import_module(config.adapter_module)
    adapter = module.create_adapter(model_revision=config.model_revision)
    if not isinstance(adapter, Adapter):
        raise SafeWorkerError("invalid_production_adapter")
    return adapter


class HandlerRuntime:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.adapter = _load_adapter(config)
        self.adapter.self_test()
        self.loaded_at = time.perf_counter()
        self._cache: OrderedDict[str, tuple[str, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def _cached(self, key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                return None
            cached_hash, payload = value
            if cached_hash != request_hash:
                raise SafeWorkerError("idempotency_conflict")
            self._cache.move_to_end(key)
            return payload

    def _remember(self, key: str, request_hash: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._cache[key] = (request_hash, payload)
            self._cache.move_to_end(key)
            while len(self._cache) > 256:
                self._cache.popitem(last=False)

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            if self.config.experimental and not self.config.experiment_enabled:
                raise SafeWorkerError("experimental_worker_disabled")
            raw = event.get("input")
            if not isinstance(raw, dict):
                raise SafeWorkerError("input_object_required")
            job_id = _validate_identifier(raw.get("job_id"), "job_id")
            tenant_id = _validate_identifier(raw.get("tenant_id"), "tenant_id")
            idempotency_key = _validate_identifier(raw.get("idempotency_key"), "idempotency_key")
            _validate_callback_auth(
                raw,
                self.config,
                job_id=job_id,
                tenant_id=tenant_id,
            )
            expected_attestation = {
                "expected_model_revision": self.config.model_revision,
                "expected_runtime_image_digest": self.config.runtime_image_digest,
                "expected_adapter_version": self.config.adapter_version,
            }
            for field, expected in expected_attestation.items():
                if raw.get(field) != expected:
                    raise SafeWorkerError("worker_attestation_mismatch")
            request_hash = hashlib.sha256(_canonical_json(raw)).hexdigest()
            cached = self._cached(f"{tenant_id}:{idempotency_key}", request_hash)
            if cached is not None:
                return {**cached, "idempotent_replay": True}

            with tempfile.TemporaryDirectory(prefix="akc-job-") as temp_directory:
                input_path = Path(temp_directory) / "input.bin"
                input_sha256, input_bytes = _download_input(raw, input_path, self.config)
                declared_sha = str(raw.get("input_sha256") or "").removeprefix("sha256:")
                if declared_sha and declared_sha != input_sha256:
                    raise SafeWorkerError("input_checksum_mismatch")
                model_started = time.perf_counter()
                validation_request = _adapter_request(raw)
                if self.config.worker_kind == "knowledge":
                    validation_request["knowledge_input"] = _knowledge_input(
                        input_path,
                        validation_request,
                    )
                model_request = json.loads(_canonical_json(validation_request))
                adapter_output = _validate_adapter_output(
                    self.adapter.process(input_path, model_request),
                    worker_kind=self.config.worker_kind,
                    request=validation_request,
                )
                model_elapsed = time.perf_counter() - model_started

            elapsed = time.perf_counter() - started
            result_id = hashlib.sha256(
                f"{tenant_id}\0{idempotency_key}\0{request_hash}\0{self.config.model_revision}".encode()
            ).hexdigest()
            payload = {
                "ok": True,
                "schema_version": "1.0",
                "result_id": f"sha256:{result_id}",
                "job_id": job_id,
                "tenant_id": tenant_id,
                "provider": self.config.provider_key,
                "worker_kind": self.config.worker_kind,
                "model_revision": self.config.model_revision,
                "runtime_image_digest": self.config.runtime_image_digest,
                "adapter_version": self.config.adapter_version,
                "input_sha256": f"sha256:{input_sha256}",
                "input_bytes": input_bytes,
                "idempotency_key": idempotency_key,
                "idempotent_replay": False,
                **adapter_output,
                "metrics": {
                    "wall_time_ms": round(elapsed * 1000, 3),
                    "model_time_ms": round(model_elapsed * 1000, 3),
                    "gpu_seconds": round(model_elapsed, 6),
                    "cold_start_ms": round((self.loaded_at - PROCESS_STARTED) * 1000, 3),
                    "estimated_cost_usd": round(model_elapsed * self.config.gpu_usd_per_second, 9),
                    "metering_source": "worker_estimate_not_provider_invoice",
                },
            }
            body = _canonical_json(payload)
            if len(body) > self.config.max_output_bytes:
                raise SafeWorkerError("output_too_large")
            output_url = raw.get("output_url")
            if output_url is not None:
                if not isinstance(output_url, str):
                    raise SafeWorkerError("invalid_output_url")
                output_object_key = _validate_tenant_object_key(
                    raw.get("output_object_key"),
                    tenant_id=tenant_id,
                    field="output_object_key",
                )
                _upload_result(
                    output_url,
                    body,
                    self.config,
                    tenant_id=tenant_id,
                    output_object_key=output_object_key,
                )
                response_payload = {
                    "ok": True,
                    "schema_version": "1.0",
                    "result_id": payload["result_id"],
                    "job_id": job_id,
                    "tenant_id": tenant_id,
                    "provider": self.config.provider_key,
                    "worker_kind": self.config.worker_kind,
                    "model_revision": self.config.model_revision,
                    "runtime_image_digest": self.config.runtime_image_digest,
                    "adapter_version": self.config.adapter_version,
                    "output_object_key": output_object_key,
                    "output_sha256": f"sha256:{hashlib.sha256(body).hexdigest()}",
                    "output_bytes": len(body),
                    "idempotency_key": idempotency_key,
                    "idempotent_replay": False,
                    "metrics": payload["metrics"],
                    "warnings": adapter_output.get("warnings", []),
                }
            else:
                if len(body) > self.config.max_direct_response_bytes:
                    raise SafeWorkerError("direct_response_too_large")
                response_payload = payload
            self._remember(
                f"{tenant_id}:{idempotency_key}",
                request_hash,
                response_payload,
            )
            return response_payload
        except SafeWorkerError as exc:
            return {
                "ok": False,
                "error": {"code": exc.code, "retryable": exc.retryable},
                "provider": self.config.provider_key,
                "model_revision": self.config.model_revision,
                "runtime_image_digest": self.config.runtime_image_digest,
                "adapter_version": self.config.adapter_version,
            }
        except Exception:
            return {
                "ok": False,
                "error": {"code": "unexpected_worker_error", "retryable": False},
                "provider": self.config.provider_key,
                "model_revision": self.config.model_revision,
                "runtime_image_digest": self.config.runtime_image_digest,
                "adapter_version": self.config.adapter_version,
            }


def build_handler(
    worker_kind: str,
    provider_key: str,
    *,
    experimental: bool = False,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    runtime = HandlerRuntime(
        WorkerConfig.from_env(worker_kind, provider_key, experimental=experimental)
    )
    return runtime.handle


def serve(worker_kind: str, provider_key: str, *, experimental: bool = False) -> None:
    handler = build_handler(worker_kind, provider_key, experimental=experimental)
    if _bool_env("AKC_LOCAL_SELF_TEST", False):
        options: dict[str, Any]
        input_body = b"safe-local-test"
        if worker_kind == "knowledge":
            options = {
                "artifact_contract": "akc-knowledge-bundle-1.0.0",
                "prompt_revision": "sha256:" + ("1" * 64),
                "knowledge_schema_sha256": "sha256:" + ("2" * 64),
            }
            input_body = _canonical_json(
                {
                    "schema_version": "knowledge-input-1.0.0",
                    "document_id": "urn:akmp:doc:local-self-test",
                    "document_version_id": "urn:akmp:doc-version:local-self-test-v1",
                    "title": "Safe local self-test",
                    "blocks": [
                        {
                            "block_id": "blk_local_self_test",
                            "text": "safe local self-test",
                            "source_refs": [
                                {
                                    "document_id": "urn:akmp:doc:local-self-test",
                                    "document_version_id": (
                                        "urn:akmp:doc-version:local-self-test-v1"
                                    ),
                                    "page_index0": 0,
                                    "page_number1": 1,
                                    "bbox1000": [0, 0, 1000, 1000],
                                }
                            ],
                        }
                    ],
                }
            )
        else:
            options = {"mock_text": "safe local self-test"}
        payload = {
            "input": {
                "job_id": "job-local-self-test",
                "tenant_id": "tenant-local",
                "idempotency_key": "self-test-1",
                "expected_model_revision": os.getenv("MODEL_REVISION", ""),
                "expected_runtime_image_digest": os.getenv(
                    "RUNTIME_IMAGE_DIGEST",
                    "sha256:" + ("0" * 64),
                ),
                "expected_adapter_version": os.getenv(
                    "ADAPTER_VERSION",
                    "mock-adapter-1.0.0",
                ),
                "inline_bytes_b64": base64.b64encode(input_body).decode(),
                "document_id": "urn:akmp:doc:local-self-test",
                "document_version_id": "urn:akmp:doc-version:local-self-test-v1",
                "options": options,
            }
        }
        print(json.dumps(handler(payload), sort_keys=True))
        return
    runpod_module = importlib.import_module("runpod")
    serverless = getattr(runpod_module, "serverless", None)
    start = getattr(serverless, "start", None)
    if not callable(start):
        raise RuntimeError("runpod serverless runtime is unavailable")
    start({"handler": handler})
