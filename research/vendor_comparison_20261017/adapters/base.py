"""Adapter contract: document bytes + arm pin -> one ParseResult (COMPETITOR-PROTOCOL §4.2-4.4).

An adapter never opens a socket. Every request goes through an injected ``Transport``; the only
transport in this package is ``ReplayTransport``, which replays SYNTHETIC fixtures. An API key
travels as an environment-variable *name* on the request; resolving it to a value is the job of
a live transport, and none exists until FD-1 and FD-2 are decided (see ``run.py``).

Denominator rule (§4.4): every non-OK result carries ``markdown == ""`` so the evaluator scores
it as an empty prediction over the full N. Operational failures (429, 5xx, timeout, transport
errors) are classified apart from semantic ones (a success response with no content).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    OK = "ok"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    SIZE_REJECTED = "size_rejected"
    HTTP_ERROR = "http_error"
    VENDOR_JOB_FAILED = "vendor_job_failed"
    MALFORMED_RESPONSE = "malformed_response"
    EMPTY_OUTPUT = "empty_output"


FAILURE_CLASS: Mapping[Status, str | None] = {
    Status.OK: None,
    Status.RATE_LIMITED: "operational",
    Status.SERVER_ERROR: "operational",
    Status.TIMEOUT: "operational",
    Status.HTTP_ERROR: "operational",
    Status.VENDOR_JOB_FAILED: "operational",
    Status.MALFORMED_RESPONSE: "operational",
    Status.SIZE_REJECTED: "limit",
    Status.EMPTY_OUTPUT: "semantic",
}

# §4.3: only 429 and 5xx are retried, at most twice, under the same rule for every arm.
MAX_RETRIES = 2

Path = tuple[str, ...]
UsageValue = int | float | str


@dataclass(frozen=True)
class Request:
    operation: str
    method: str
    url: str | None  # None: the endpoint is not in competitor-protocol-receipts, so it is unpinned
    api_key_env: str  # a NAME only; no code in this package reads its value
    timeout_s: float
    json_body: Mapping[str, Any] | None = None
    params: Mapping[str, str] = field(default_factory=dict)
    file_bytes: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


class TransportTimeout(Exception):
    """Raised by a transport when a request exceeded ``Request.timeout_s``."""


Transport = Callable[[Request], Response]


class ReplayExhausted(AssertionError):
    """A fixture scripted fewer exchanges than the adapter made: a harness bug, never a status."""


class ReplayTransport:
    """Replays scripted exchanges in order and records every request it was handed.

    An exchange is ``{"status": int, "json": ...}``, ``{"status": int, "text": str}`` or
    ``{"timeout": true}``.
    """

    def __init__(self, exchanges: Sequence[Mapping[str, Any]]) -> None:
        self._script = list(exchanges)
        self.requests: list[Request] = []

    @property
    def unused(self) -> int:
        return len(self._script)

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        if not self._script:
            raise ReplayExhausted(f"no scripted exchange left for {request.operation!r}")
        step = self._script.pop(0)
        if step.get("timeout"):
            raise TransportTimeout(f"SYNTHETIC timeout after {request.timeout_s} s")
        if "json" in step:
            body = json.dumps(step["json"], ensure_ascii=False).encode("utf-8")
        else:
            body = str(step["text"]).encode("utf-8")
        return Response(int(step["status"]), body)


@dataclass(frozen=True)
class ResponseShape:
    """Where a success payload keeps its fields. ``"*"`` maps over a list; markdown lists join."""

    source: str
    markdown: Path
    page_count: Path | None = None
    usage: Mapping[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class Pin:
    arm_id: str
    api_key_env: str
    timeout_s: float  # per request, and the deadline of an asynchronous job
    config: Mapping[str, str] = field(default_factory=dict)
    response_shape: ResponseShape | None = None  # required where the vendor's was not captured


@dataclass(frozen=True)
class Document:
    doc_id: str
    pdf: bytes = field(repr=False)
    pages: int  # from the corpus manifest, never from any arm's own output


@dataclass(frozen=True)
class ParseResult:
    arm_id: str
    doc_id: str
    source_sha256: str
    status: Status
    markdown: str
    page_count: int | None
    usage: Mapping[str, UsageValue]
    raw_sha256: str | None  # sha256 of the last response body received; None if none arrived
    elapsed_s: float
    attempts: int  # transport calls made, retries included; 0 = nothing reached the vendor
    detail: str = ""

    @property
    def failure_class(self) -> str | None:
        return FAILURE_CLASS[self.status]


class MissingResponseShape(ValueError):
    """The arm has no response shape pinned from vendor docs; the adapter refuses to guess one."""


class Failure(Exception):
    def __init__(self, status: Status, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class _Missing(Exception):
    pass


class Calls:
    """Sends requests with the shared retry rule and remembers attempts and the last body."""

    def __init__(self, transport: Transport, sleep: Callable[[float], None], backoff_s: float):
        self._transport = transport
        self._sleep = sleep
        self._backoff_s = backoff_s
        self.attempts = 0
        self.last_body: bytes | None = None

    def send(self, request: Request) -> Any:
        last_status = 0
        for attempt in range(MAX_RETRIES + 1):
            if attempt:
                self._sleep(self._backoff_s * attempt)
            self.attempts += 1
            try:
                response = self._transport(request)
            except TransportTimeout as exc:  # not retried: §4.3 retries 429/5xx only
                raise Failure(Status.TIMEOUT, f"{request.operation}: {exc}") from exc
            self.last_body = response.body
            last_status = response.status
            if response.status == 429 or 500 <= response.status <= 599:
                continue
            if response.status == 413:
                raise Failure(Status.SIZE_REJECTED, f"{request.operation}: HTTP 413")
            if not 200 <= response.status <= 299:
                raise Failure(Status.HTTP_ERROR, f"{request.operation}: HTTP {response.status}")
            try:
                return json.loads(response.body)
            except ValueError as exc:
                raise Failure(
                    Status.MALFORMED_RESPONSE, f"{request.operation}: body is not JSON ({exc})"
                ) from exc
        status = Status.RATE_LIMITED if last_status == 429 else Status.SERVER_ERROR
        raise Failure(
            status, f"{request.operation}: HTTP {last_status} after {MAX_RETRIES + 1} attempts"
        )


def _resolve(node: Any, path: Path) -> Any:
    for index, key in enumerate(path):
        if key == "*":
            if not isinstance(node, list):
                raise Failure(Status.MALFORMED_RESPONSE, f"{'.'.join(path)}: not a list")
            return [_resolve(item, path[index + 1 :]) for item in node]
        if not isinstance(node, dict) or key not in node:
            raise _Missing(".".join(path))
        node = node[key]
    return node


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def decode_with_shape(
    payload: Any, shape: ResponseShape
) -> tuple[str, int | None, dict[str, UsageValue]]:
    try:
        markdown = _resolve(payload, shape.markdown)
    except _Missing as exc:
        raise Failure(Status.MALFORMED_RESPONSE, f"missing {exc}") from exc
    if isinstance(markdown, list) and all(isinstance(part, str) for part in markdown):
        markdown = "\n\n".join(markdown)
    if not isinstance(markdown, str):
        raise Failure(Status.MALFORMED_RESPONSE, f"{'.'.join(shape.markdown)}: not text")

    page_count: int | None = None
    if shape.page_count is not None:
        try:
            value = _resolve(payload, shape.page_count)
        except _Missing:
            value = None
        if isinstance(value, list):
            value = len(value)
        if value is not None and not (isinstance(value, int) and _is_number(value) and value >= 0):
            raise Failure(Status.MALFORMED_RESPONSE, f"{'.'.join(shape.page_count)}: not a count")
        page_count = value

    usage: dict[str, UsageValue] = {}
    for name, path in shape.usage.items():
        try:
            value = _resolve(payload, path)
        except _Missing:
            continue
        if not (_is_number(value) or isinstance(value, str)):
            raise Failure(Status.MALFORMED_RESPONSE, f"{'.'.join(path)}: not a scalar")
        usage[name] = value
    return markdown, page_count, usage


class Adapter:
    """One vendor's wire facts. Subclasses set the class attributes and override hooks."""

    vendor: str = ""
    endpoint: str | None = None
    wire_source: str = ""  # which receipt documents the wire facts, or that none was captured
    default_shape: ResponseShape | None = None

    def __init__(
        self,
        transport: Transport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        retry_backoff_s: float = 2.0,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._retry_backoff_s = retry_backoff_s

    def parse(self, document: Document, pin: Pin) -> ParseResult:
        shape = pin.response_shape or self.default_shape
        if shape is None:
            raise MissingResponseShape(
                f"{self.vendor}: no response shape was captured from vendor docs; pin one from "
                "a docs receipt before this adapter can read a response"
            )
        self.validate_config(pin)
        start = self._clock()
        calls = Calls(self._transport, self._sleep, self._retry_backoff_s)
        markdown, page_count, detail = "", None, ""
        usage: dict[str, UsageValue] = {}
        try:
            self.preflight(document)
            payload = self.exchange(document, pin, calls)
            markdown, page_count, usage = self.decode(payload, shape)
            if markdown.strip():
                status = Status.OK
            else:
                status, markdown = Status.EMPTY_OUTPUT, ""
                detail = "success response carried no markdown"
        except Failure as failure:
            status, detail = failure.status, failure.detail
        raw = calls.last_body
        return ParseResult(
            arm_id=pin.arm_id,
            doc_id=document.doc_id,
            source_sha256=hashlib.sha256(document.pdf).hexdigest(),
            status=status,
            markdown=markdown,
            page_count=page_count,
            usage=usage,
            raw_sha256=None if raw is None else hashlib.sha256(raw).hexdigest(),
            elapsed_s=self._clock() - start,
            attempts=calls.attempts,
            detail=detail,
        )

    def validate_config(self, pin: Pin) -> None:
        """Refuse a pin this vendor cannot run reproducibly. Raises ValueError."""

    def preflight(self, document: Document) -> None:
        """Refuse a document before any request is sent. Raises Failure."""

    def exchange(self, document: Document, pin: Pin, calls: Calls) -> Any:
        return calls.send(
            Request(
                operation="parse",
                method="POST",
                url=self.endpoint,
                api_key_env=pin.api_key_env,
                timeout_s=pin.timeout_s,
                json_body=dict(pin.config) or None,
                file_bytes=document.pdf,
            )
        )

    def decode(
        self, payload: Any, shape: ResponseShape
    ) -> tuple[str, int | None, dict[str, UsageValue]]:
        return decode_with_shape(payload, shape)
