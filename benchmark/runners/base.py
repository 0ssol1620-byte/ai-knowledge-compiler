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
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlencode, urlparse, urlunsplit

from akc_security import UnsafeUrlError, validate_resolved_url


class RunnerUnavailable(RuntimeError):
    pass


# Every environment value a runner sends as a credential. A runner reads one only through
# ``read_credential``; ``seal`` keeps all of them out of what any runner returns or raises.
CREDENTIAL_ENV = ("AKC_BENCHMARK_PROVIDER_TOKEN", "GEMINI_API_KEY", "MISTRAL_API_KEY")
PROVIDER_CREDENTIAL = CREDENTIAL_ENV[0]  # the bearer token of chat and external runners
CREDENTIAL_IN_RESULT = "credential_in_result"

# The endpoint is written into receipts, so its shape is an allow-list, not a deny-list: ASCII
# ``https://host[:port]/path`` with host and path drawn from letters, digits, '.', '-', '_',
# ':' and '/'. A percent sign, query, fragment, user info, whitespace, a control character, any
# non-ASCII or fullwidth form is outside it. No plain HTTP, loopback included (nothing needs it).
_CLEAN_ENDPOINT = re.compile(r"https://[A-Za-z0-9._:-]+(?:/[A-Za-z0-9._:/-]*)?")


def require_clean_endpoint(endpoint: object) -> None:
    """Refuse any endpoint outside the allow-list, with one fixed message."""
    if endpoint is None:
        return
    if not isinstance(endpoint, str) or _CLEAN_ENDPOINT.fullmatch(endpoint) is None:
        raise RunnerUnavailable(
            "endpoint must be https://host[:port]/path in ASCII letters, digits and . - _ : / "
            "only (no percent sign, query, fragment, user info, space or other character); "
            "credentials travel in a header only"
        )


def read_credential(name: str, endpoint: object) -> str | None:
    """The door: check the endpoint and read one declared credential.

    The endpoint must be clean and must not carry any declared credential in any spelling the
    exit guard knows (``carries_credential``). Every message is fixed: none carries a value.
    """
    if name not in CREDENTIAL_ENV:
        raise ValueError("not a declared runner credential")
    require_clean_endpoint(endpoint)
    if isinstance(endpoint, str) and carries_credential(endpoint):
        raise RunnerUnavailable("endpoint contains a declared credential")
    return os.getenv(name) or None


_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@/-]{0,127}")


def guarded(
    name: str,
    endpoint: object,
    provider: str,
    payload: object,
    body: Callable[[str | None], dict[str, Any]],
    *,
    model_revision: object = "",
) -> dict[str, Any]:
    """The shape of every public runner entry point: the door first (credential read, endpoint
    checked) before any other argument is looked at, then everything else, every validation
    and every refusal it raises included, inside ``seal``. ``model_revision`` is the model id
    or revision the caller asked for: the outer seal's failure row names it when it is a
    plain label (``_LABEL``) that carries no credential, and ``""`` otherwise."""
    credential = read_credential(name, endpoint)
    label = ""
    if (
        isinstance(model_revision, str)
        and _LABEL.fullmatch(model_revision)
        and not carries_credential(model_revision)
    ):
        label = model_revision
    return seal(RunnerConfig(provider, label), payload, lambda: body(credential))


def _needles(value: str) -> list[str]:
    """The value as it can appear in a serialised result: itself, JSON-escaped,
    percent-encoded, hex (both cases), inside base64 or URL-safe base64 (raw response bytes
    are stored base64) at each of the three byte alignments, and inside RFC 4648 base32 (upper
    and lower case, padding-free core) at each of the five byte alignments. Case-insensitive
    and NFKC-folded matches of the value itself are made by ``carries_credential``.

    Not modelled, and not claimed: the value reversed, split by separators, interleaved with
    zero-width characters, or encoded as UTF-16 before base64."""
    data = value.encode("utf-8")
    found = {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]}
    found.add(quote(value, safe=""))
    found.update({data.hex(), data.hex().upper()})
    for shift in range(3):
        encoded = base64.b64encode(b"\0" * shift + data).decode("ascii")
        # drop the characters that mix in the padding bytes or whatever follows the value
        core = encoded[(0, 2, 3)[shift] : (8 * (shift + len(data))) // 6]
        if core:
            found.update({core, core.translate(_URLSAFE)})
    for shift in range(5):
        encoded = base64.b32encode(b"\0" * shift + data).decode("ascii")
        # a base32 character is 5 bits: keep only those made of the value's bits alone
        core = encoded[-(-8 * shift // 5) : (8 * (shift + len(data))) // 5]
        if core:
            found.update({core, core.lower()})
    return sorted(found)


_URLSAFE = str.maketrans("+/", "-_")


def carries_credential(text: str) -> bool:
    """Whether ``text`` contains any declared credential that is set in this environment."""
    folded = text.casefold()
    nfkc = unicodedata.normalize("NFKC", text).casefold()
    for name in CREDENTIAL_ENV:
        value = os.getenv(name)
        if not value:
            continue
        plain = unicodedata.normalize("NFKC", value).casefold()
        if value.casefold() in folded or plain in nfkc or any(n in text for n in _needles(value)):
            return True
    return False


def _exception_text(exc: BaseException) -> str:
    """Every text a caller could print or read: each exception of the cause/context chain, its
    notes, its attributes (``vars``: e.g. ``JSONDecodeError.doc``; ``UnicodeError.object``),
    and the members of an exception group."""
    texts: list[str] = []
    seen: set[int] = set()
    pending: list[BaseException | None] = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        texts.append(f"{type(current).__name__}: {current!s} {current.args!r}")
        attributes = list(getattr(current, "__dict__", {}).values())
        if isinstance(current, UnicodeError):
            attributes.append(getattr(current, "object", None))
        for value in attributes:
            if isinstance(value, bytes | bytearray):
                value = bytes(value).decode("utf-8", "replace")
            texts.append(value if isinstance(value, str) else repr(value))
        notes = getattr(current, "__notes__", None)
        texts.append(repr(notes))
        if isinstance(notes, list | tuple):
            texts.extend(str(note) for note in notes)
        pending += [current.__cause__, current.__context__]
        if isinstance(current, BaseExceptionGroup):
            pending += list(current.exceptions)
    return "\n".join(texts)


def _strings(value: Any) -> list[str]:
    """Every string (keys included) of an already-serialisable result, iteratively."""
    found: list[str] = []
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            found.append(current)
        elif isinstance(current, dict):
            pending += [*current.keys(), *current.values()]
        elif isinstance(current, list | tuple):
            pending += list(current)
    return found


_ESCAPE = re.compile(
    r"\\u(d[89ab][0-9a-f]{2})\\u(d[c-f][0-9a-f]{2})|\\u([0-9a-f]{4})|\\/", re.IGNORECASE
)


def _unescape(text: str) -> str:
    """JSON string escapes resolved in text that is not valid JSON: ``\\uXXXX`` (a surrogate
    pair joined; a lone surrogate and a malformed escape left as they are) and ``\\/``."""

    def one(match: re.Match[str]) -> str:
        high, low, single = match.groups()
        if high:
            return chr(0x10000 + ((int(high, 16) - 0xD800) << 10) + (int(low, 16) - 0xDC00))
        if single:
            code = int(single, 16)
            return match.group(0) if 0xD800 <= code <= 0xDFFF else chr(code)
        return "/"

    return _ESCAPE.sub(one, text)


def _result_text(result: Any) -> str:
    """The serialised result, plus each base64 string in it decoded (a stored raw response)
    and, where that is JSON, re-serialised after ``json.loads`` so escapes are resolved; where
    it is not JSON (a broken body), with its JSON escapes resolved by ``_unescape``."""
    views = [json.dumps(result, ensure_ascii=False, sort_keys=True)]
    for text in _strings(result):
        try:
            decoded = base64.b64decode(text, validate=True).decode("utf-8", "replace")
        except ValueError:
            continue
        views.append(decoded)
        try:
            views.append(json.dumps(json.loads(decoded), ensure_ascii=False))
        except (ValueError, RecursionError):
            views.append(_unescape(decoded))
    return "\n".join(views)


def seal(
    config: RunnerConfig, payload: object, produce: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """The exit: where every runner result is finalised. A result that contains a declared
    credential (or cannot be serialised to be checked) becomes a failure row with a fixed
    reason; an exception whose text contains one (or cannot be read) is replaced by a fixed
    one, raised outside the handler so nothing chains back to the original."""
    withheld = False
    try:
        result = produce()
    except Exception as exc:
        try:
            clean = not carries_credential(_exception_text(exc))
        except Exception:  # an exception whose text cannot be read is not shown either
            clean = False
        if clean:
            raise
        withheld = True
    if withheld:
        raise RunnerUnavailable("runner error withheld: its text carried a credential")
    try:
        text = _result_text(result)
    except (TypeError, ValueError, RecursionError):
        reason = "result_not_serialisable"
    else:
        if not carries_credential(text):
            return result
        reason = CREDENTIAL_IN_RESULT
    case_id = payload.get("benchmark_case_id") if isinstance(payload, dict) else None
    failure = {
        "schema_version": "1.0",
        "benchmark_case_id": case_id,
        "provider": config.provider,
        "model_revision": config.model_revision,
        "failure": {"reason": reason},
        "receipt": {"revision_attested": False},
    }
    try:  # the same view as the result check: base64 strings decoded, escapes resolved
        failure_text = _result_text(failure)
    except (TypeError, ValueError, RecursionError):
        raise RunnerUnavailable("runner inputs could not be checked; result withheld") from None
    if carries_credential(failure_text):
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
    """POST over the pinned, allowlisted HTTPS path; returns (status, content type, raw bytes)."""
    return request_bytes(config, "POST", body, headers, max_response_bytes=max_response_bytes)


_METHODS = frozenset({"GET", "POST", "DELETE"})
_QUERY_NAMES = frozenset({"pageSize", "pageToken"})
_QUERY_VALUE = re.compile(r"[A-Za-z0-9._~-]{1,512}")


def request_bytes(
    config: RunnerConfig,
    method: str,
    body: bytes | None,
    headers: dict[str, str],
    *,
    query: dict[str, str] | None = None,
    max_response_bytes: int = 10 * 1024 * 1024,
) -> tuple[int, str, bytes]:
    """One request over the pinned, allowlisted HTTPS path; returns (status, content type, raw
    bytes). Nothing is interpreted here: the caller decides what a status or body means.

    The query is closed: names from ``_QUERY_NAMES`` only, each value unreserved characters
    only, refused before any DNS lookup. It is added to the request target and to nothing else
    (the endpoint, which receipts record, keeps its allow-listed shape)."""
    require_clean_endpoint(config.endpoint)
    if method not in _METHODS:
        raise RunnerUnavailable("request method must be GET, POST or DELETE")
    if query is not None and not (
        isinstance(query, dict)
        and set(query) <= _QUERY_NAMES
        and all(isinstance(v, str) and _QUERY_VALUE.fullmatch(v) for v in query.values())
    ):
        raise RunnerUnavailable("query must be pageSize/pageToken of unreserved characters only")
    if not config.allow_network:
        raise RunnerUnavailable("network runner requires explicit --allow-network")
    if not config.endpoint:
        raise RunnerUnavailable("endpoint missing")
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
    query_text = urlencode(sorted(query.items())) if query else ""
    target = urlunsplit(("", "", parsed.path or "/", query_text, ""))
    try:
        connection.request(method, target, body=body, headers=headers)
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
    """The AKC external-runner protocol: the door, then the exchange inside ``seal``."""
    return guarded(
        PROVIDER_CREDENTIAL,
        config.endpoint,
        config.provider,
        payload,
        lambda token: external_exchange(config, payload, token),
        model_revision=config.model_revision,
    )


def external_exchange(
    config: RunnerConfig, payload: dict[str, Any], bearer_token: str | None
) -> dict[str, Any]:
    """One call with a token the door already read; sealed with the pinned config."""

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
            raise RunnerUnavailable("provider returned a non-200 HTTP status")
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
