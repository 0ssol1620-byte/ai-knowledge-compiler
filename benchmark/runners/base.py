"""Provider runner primitives. Local mock output is never a quality claim."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import http.client
import json
import os
import re
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse, urlsplit, urlunsplit

from akc_security import UnsafeUrlError, validate_resolved_url


class RunnerUnavailable(RuntimeError):
    pass


# Every environment value a runner sends as a credential. A runner reads one only through
# ``read_credential``; ``seal`` keeps all of them out of what any runner returns or raises.
CREDENTIAL_ENV = ("AKC_BENCHMARK_PROVIDER_TOKEN", "GEMINI_API_KEY")
CREDENTIAL_IN_RESULT = "credential_in_result"


def require_clean_endpoint(endpoint: str | None) -> None:
    """The endpoint is written into receipts, so it may carry nothing a credential could hide
    in: no query, fragment, user info, or percent sign (no encoding of anything at all)."""
    if endpoint is None:
        return
    parts = urlsplit(endpoint)
    if parts.query or parts.fragment or "?" in endpoint or "#" in endpoint:
        raise RunnerUnavailable(
            "endpoint must not carry a query string or fragment (a key there would be "
            "written into the receipt); credentials travel in a header only"
        )
    if "@" in parts.netloc:
        raise RunnerUnavailable("endpoint must not carry user info")
    if "%" in endpoint:
        raise RunnerUnavailable("endpoint must not carry percent-encoding")


def read_credential(name: str, endpoint: str | None) -> str | None:
    """The door: read one declared credential and refuse an endpoint that contains it.

    With percent-encoding refused outright, the only remaining spelling is the value itself,
    compared without case (a host is case-insensitive). The message never carries the value.
    """
    if name not in CREDENTIAL_ENV:
        raise ValueError(f"{name} is not a declared runner credential")
    require_clean_endpoint(endpoint)
    value = os.getenv(name) or None
    if value is not None and endpoint is not None and value.casefold() in endpoint.casefold():
        raise RunnerUnavailable(f"endpoint contains the value of {name}")
    return value


def _needles(value: str) -> list[str]:
    """The value as it can appear in a serialised result: itself, JSON-escaped,
    percent-encoded, and inside base64 (raw response bytes are stored base64) at each of the
    three byte alignments. Spellings beyond these (a provider that transforms the key) are
    outside what a substring check can see; the door keeps the endpoint free of all of them."""
    data = value.encode("utf-8")
    found = {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]}
    found.add(quote(value, safe=""))
    for shift in range(3):
        encoded = base64.b64encode(b"\0" * shift + data).decode("ascii")
        # drop the characters that mix in the padding bytes or whatever follows the value
        core = encoded[(0, 2, 3)[shift] : (8 * (shift + len(data))) // 6]
        if core:
            found.add(core)
    return sorted(found)


def carries_credential(text: str) -> bool:
    """Whether ``text`` contains any declared credential that is set in this environment."""
    folded = text.casefold()
    for name in CREDENTIAL_ENV:
        value = os.getenv(name)
        if not value:
            continue
        if value.casefold() in folded or any(n in text for n in _needles(value)):
            return True
    return False


def _exception_text(exc: BaseException) -> str:
    texts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        texts.append(f"{type(current).__name__}: {current!s} {current.args!r}")
        current = current.__cause__ or current.__context__
    return "\n".join(texts)


def seal(
    config: RunnerConfig, payload: dict[str, Any], produce: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """The exit: where every runner result is finalised. A result that contains a declared
    credential (or cannot be serialised to be checked) becomes a failure row with a fixed
    reason; an exception whose text contains one is replaced by a fixed one."""
    withheld = False
    try:
        result = produce()
    except Exception as exc:
        if not carries_credential(_exception_text(exc)):
            raise
        withheld = True
    if withheld:  # raised outside the handler, so nothing chains back to the original
        raise RunnerUnavailable("runner error withheld: its text carried a credential")
    try:
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError, RecursionError):
        reason = "result_not_serialisable"
    else:
        if not carries_credential(text):
            return result
        reason = CREDENTIAL_IN_RESULT
    failure = {
        "schema_version": "1.0",
        "benchmark_case_id": payload.get("benchmark_case_id"),
        "provider": config.provider,
        "model_revision": config.model_revision,
        "failure": {"reason": reason},
        "receipt": {"revision_attested": False},
    }
    if carries_credential(json.dumps(failure, ensure_ascii=False, default=str)):
        raise RunnerUnavailable("runner inputs carried a credential; result withheld")
    return failure


@dataclass(frozen=True)
class RunnerConfig:
    provider: str
    model_revision: str
    endpoint: str | None = None
    allow_network: bool = False
    timeout_seconds: int = 180


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        *,
        pinned_ip: str,
        timeout: float,
    ) -> None:
        self._pinned_ip = pinned_ip
        self._ssl_context = ssl.create_default_context()
        super().__init__(
            host=host,
            port=443,
            timeout=timeout,
            context=self._ssl_context,
        )

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
        )
        self.sock = self._ssl_context.wrap_socket(raw_socket, server_hostname=self.host)


def _approved_source_payload(
    case: dict[str, Any],
    *,
    corpus_root: Path,
    maximum_source_bytes: int,
) -> dict[str, Any]:
    source = case.get("source")
    if not isinstance(source, dict):
        raise RunnerUnavailable("real benchmark case requires a source object")
    relative_value = source.get("path")
    if not isinstance(relative_value, str):
        raise RunnerUnavailable("benchmark source path is missing")
    relative = PurePosixPath(relative_value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise RunnerUnavailable("benchmark source path is unsafe")
    root = corpus_root.resolve(strict=True)
    target = root.joinpath(*relative.parts).resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RunnerUnavailable("benchmark source escaped the approved corpus root") from exc
    if not target.is_file():
        raise RunnerUnavailable("benchmark source is not a regular file")
    size = target.stat().st_size
    if size < 1 or size > maximum_source_bytes:
        raise RunnerUnavailable("benchmark source size is outside the configured bound")
    payload = target.read_bytes()
    if len(payload) != size:
        raise RunnerUnavailable("benchmark source changed while it was being read")
    expected_sha256 = source.get("sha256")
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if (
        not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
        or not hmac.compare_digest(actual_sha256, expected_sha256)
    ):
        raise RunnerUnavailable("benchmark source SHA-256 mismatch")
    content_type = source.get("content_type")
    filename = source.get("filename")
    if not isinstance(content_type, str) or not content_type:
        raise RunnerUnavailable("benchmark source content type is missing")
    if not isinstance(filename, str) or not filename or len(filename) > 500:
        raise RunnerUnavailable("benchmark source filename is invalid")
    return {
        "filename": filename,
        "content_type": content_type,
        "sha256": actual_sha256,
        "bytes_base64": base64.b64encode(payload).decode("ascii"),
    }


def build_provider_payload(
    case: dict[str, Any],
    *,
    corpus_root: Path | None,
    maximum_source_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Build provider input without leaking real-case ground truth labels."""

    case_id = case.get("benchmark_case_id")
    if not isinstance(case_id, str) or not case_id:
        raise RunnerUnavailable("benchmark case id is missing")
    if case.get("is_synthetic") is True:
        return {
            "benchmark_case_id": case_id,
            "claim_class": "synthetic_contract",
            "synthetic_fixture": {
                "text": case.get("text") or "",
                "blocks": copy.deepcopy(case.get("blocks") or []),
            },
        }
    if corpus_root is None:
        raise RunnerUnavailable("real external benchmark requires --corpus-root")
    return {
        "benchmark_case_id": case_id,
        "claim_class": "approved_internal_source",
        "page_index": case.get("page_index"),
        "language": case.get("language"),
        "document_class": case.get("document_class"),
        "source": _approved_source_payload(
            case,
            corpus_root=corpus_root,
            maximum_source_bytes=maximum_source_bytes,
        ),
    }


def deterministic_local_mock(case: dict[str, Any]) -> dict[str, Any]:
    if case.get("is_synthetic") is not True:
        raise ValueError("local mock accepts synthetic contract cases only")
    result = {
        "schema_version": "1.0",
        "benchmark_case_id": case["benchmark_case_id"],
        "provider": "local_mock",
        "model_revision": "1111111111111111111111111111111111111111",
        "text": case.get("text") or "",
        "reading_order": copy.deepcopy(case.get("reading_order") or []),
        "blocks": copy.deepcopy(case.get("blocks") or []),
        "generated_claims": copy.deepcopy(case.get("generated_claims") or []),
        "metrics": {
            "latency_ms": 0.0,
            "cold_start_ms": 0.0,
            "gpu_seconds": 0.0,
            "peak_vram_mb": 0.0,
            "estimated_cost_usd": 0.0,
        },
        "warnings": ["synthetic_contract_result_not_for_quality_claims"],
    }
    for field in ("date_unit_annotations", "heading_outline"):
        if field in case:
            result[field] = copy.deepcopy(case[field])
    return result


def post_bytes(
    config: RunnerConfig,
    body: bytes,
    headers: dict[str, str],
    *,
    max_response_bytes: int = 10 * 1024 * 1024,
) -> tuple[int, str, bytes]:
    """POST over the pinned, allowlisted HTTPS path; returns (status, content type, raw bytes).

    Nothing is interpreted here: the caller decides what a status or body means.
    """
    if not config.allow_network:
        raise RunnerUnavailable("network runner requires explicit --allow-network")
    if not config.endpoint:
        raise RunnerUnavailable(f"endpoint missing for {config.provider}")
    parsed = urlparse(config.endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RunnerUnavailable("benchmark endpoint must be an absolute HTTPS URL")
    allowlist = {
        host.strip().lower()
        for host in os.getenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", "").split(",")
        if host.strip()
    }
    if parsed.hostname.lower() not in allowlist:
        raise RunnerUnavailable("benchmark endpoint host is not allowlisted")
    try:
        addresses = {
            record[4][0]
            for record in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        }
        validated_endpoint = validate_resolved_url(config.endpoint, addresses)
    except (OSError, UnsafeUrlError) as exc:
        raise RunnerUnavailable("benchmark endpoint did not resolve to a public address") from exc
    connection = _PinnedHTTPSConnection(
        validated_endpoint.hostname_ascii,
        pinned_ip=validated_endpoint.resolved_ips[0],
        timeout=config.timeout_seconds,
    )
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        connection.request("POST", target, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        content_type = response.headers.get_content_type()
        raw = response.read(max_response_bytes + 1)
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RunnerUnavailable("benchmark provider is unavailable") from exc
    finally:
        connection.close()
    if len(raw) > max_response_bytes:
        raise RunnerUnavailable("provider response exceeds the configured bound")
    return status, content_type, raw


def run_external(config: RunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    bearer_token = read_credential("AKC_BENCHMARK_PROVIDER_TOKEN", config.endpoint)

    def produce() -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-AKC-Benchmark-Provider": config.provider,
            "X-AKC-Input-SHA256": hashlib.sha256(body).hexdigest(),
            "X-AKC-Model-Revision": config.model_revision,
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        status, content_type, raw = post_bytes(config, body, headers)
        if status != 200:
            raise RunnerUnavailable(f"provider returned HTTP {status}")
        if content_type != "application/json":
            raise RunnerUnavailable("provider response must be application/json")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise RunnerUnavailable("provider response must be a JSON object")
        if result.get("provider") != config.provider:
            raise RunnerUnavailable(
                "provider response identity does not match the requested provider"
            )
        if result.get("model_revision") != config.model_revision:
            raise RunnerUnavailable(
                "provider model revision does not match the requested exact revision"
            )
        return result

    return seal(config, payload, produce)
