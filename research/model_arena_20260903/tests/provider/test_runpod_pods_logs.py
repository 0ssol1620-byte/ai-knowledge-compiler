"""The log drain that let the 2026-09-03 GLM-OCR pod burn 45 billed minutes.

``GET /v2/pods/{id}/logs`` is an SSE stream that sends its backfill and then
**stays open**, waiting for live lines. The first version of ``get_logs``
drained it until ``max_lines`` or end of stream, neither of which a quiet pod
ever produces, so:

* while the pod was spewing pip output the call returned quickly and the log
  watch worked (12:30Z);
* once the model server died and the container went silent, the call blocked
  until the 30 s client timeout -- and a stream that stays open while sending
  keepalives never returned at all, because keepalives are not ``data:`` lines
  and never counted toward ``max_lines``.

Both are reproduced here against a fake transport that honours the per-request
read timeout the way a real one does, so the bound is a test rather than a
hope. The last case is the other half of the same failure: the endpoint returns
container and system as separate sequences, and the caller must be able to ask
for one.
"""

from __future__ import annotations

import time

import httpx
import pytest
from arena.provider.runpod_pods import RunPodClientError, RunPodPodsClient
from tests.provider.conftest import RecordingTransport

BACKFILL = (
    '{"source":"container","ts":"2026-09-03T13:14:19Z","line":"[arena] weights cache hit"}',
    '{"source":"container","ts":"2026-09-03T13:14:20Z","line":"[arena] FATAL model server"}',
    '{"source":"container","ts":"2026-09-03T13:14:21Z","line":"exit 70"}',
)


class _OpenStream(httpx.SyncByteStream):
    """A backfill, then a stream that stays open the way RunPod's does."""

    def __init__(
        self,
        payloads: tuple[str, ...],
        *,
        read_timeout: float,
        keepalive: bool,
        ends: bool,
    ) -> None:
        self._payloads = payloads
        self._read_timeout = read_timeout
        self._keepalive = keepalive
        self._ends = ends

    def __iter__(self):
        for payload in self._payloads:
            yield f"data: {payload}\n".encode()
        if self._ends:
            return
        if self._keepalive:
            # Never quiet, never finished: only a wall-clock bound stops this.
            while True:
                time.sleep(0.005)
                yield b": keepalive\n"
        time.sleep(self._read_timeout)
        raise httpx.ReadTimeout("read timed out", request=None)


class FakeLogTransport(httpx.BaseTransport):
    def __init__(
        self,
        payloads: tuple[str, ...] = BACKFILL,
        *,
        keepalive: bool = False,
        ends: bool = False,
    ) -> None:
        self.payloads = payloads
        self.keepalive = keepalive
        self.ends = ends
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        timeout = request.extensions.get("timeout") or {}
        read = timeout.get("read")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_OpenStream(
                self.payloads,
                read_timeout=float(read if read is not None else 30.0),
                keepalive=self.keepalive,
                ends=self.ends,
            ),
        )


def _client(transport: httpx.BaseTransport, key, **kwargs) -> RunPodPodsClient:
    return RunPodPodsClient(key=key, execute=True, transport=transport, **kwargs)


def _stopped_because(client: RunPodPodsClient) -> object:
    return client.receipts[-1].summary["stopped_because"]


# ------------------------------------------------------- the four stop rules


def test_max_lines_ends_the_drain_without_waiting_for_the_stream(runpod_key) -> None:
    client = _client(FakeLogTransport(keepalive=True), runpod_key)
    started = time.monotonic()
    lines = client.get_logs("pod_test0001", max_lines=2, quiet_seconds=5.0, total_seconds=30.0)
    spent = time.monotonic() - started
    client.close()

    assert isinstance(lines, tuple) and len(lines) == 2
    assert spent < 2.0  # neither the quiet window nor the deadline was waited out
    assert _stopped_because(client) == "max_lines"


def test_a_pod_that_goes_quiet_returns_its_backfill_instead_of_blocking(runpod_key) -> None:
    """The GLM-OCR case: the container died, so nothing more is ever sent.

    ``tail`` is the number of lines asked for, and the quiet rule may only end
    the read once that many have arrived (see the backfill-pause test below).
    Here the whole backfill *is* what was asked for, so the read ends as quiet
    rather than as a truncated backfill -- bounded by ``total_seconds``, which
    is the timeout the request is opened with while any backfill is owed.
    """

    transport = FakeLogTransport()
    client = _client(transport, runpod_key, timeout_seconds=30.0)
    started = time.monotonic()
    lines = client.get_logs(
        "pod_test0001", tail=3, max_lines=3000, quiet_seconds=0.2, total_seconds=1.0
    )
    spent = time.monotonic() - started
    client.close()

    assert isinstance(lines, tuple) and len(lines) == 3
    # Before the fix this waited the full 30 s client timeout.
    assert spent < 4.0
    assert _stopped_because(client) == "quiet"
    assert any("FATAL" in str(entry["line"]) for entry in lines)


def test_a_stream_that_never_goes_quiet_is_bounded_by_the_total_deadline(runpod_key) -> None:
    """Keepalives are not ``data:`` lines, so no line bound can ever end this."""

    client = _client(FakeLogTransport(keepalive=True), runpod_key)
    started = time.monotonic()
    lines = client.get_logs("pod_test0001", max_lines=3000, quiet_seconds=1.0, total_seconds=0.4)
    spent = time.monotonic() - started
    client.close()

    assert isinstance(lines, tuple) and len(lines) == 3
    assert 0.3 <= spent < 3.0
    assert _stopped_because(client) == "deadline"


def test_a_stream_that_ends_returns_at_once(runpod_key) -> None:
    client = _client(FakeLogTransport(ends=True), runpod_key)
    started = time.monotonic()
    lines = client.get_logs("pod_test0001", max_lines=3000, quiet_seconds=5.0, total_seconds=30.0)
    spent = time.monotonic() - started
    client.close()

    assert isinstance(lines, tuple) and len(lines) == 3
    assert spent < 2.0
    assert _stopped_because(client) == "stream_end"


# ------------------------------- the backfill pause that truncated the tail


class _PausingStream(httpx.SyncByteStream):
    """A backfill with a pause in the middle, longer than ``quiet_seconds``.

    This is what pod jdwdnvg8a2rzx6 did on 2026-09-03: the replay stalled
    between chunks, the per-read timeout fired, and the 194 lines that came
    back stopped at 18:38:25Z -- a minute before the crash they were read to
    explain. The pause is honoured against the *request's* read timeout, so a
    read still owing backfill must be given more than ``quiet_seconds`` or the
    second half never arrives.
    """

    def __init__(self, payloads: tuple[str, ...], *, read_timeout: float, pause: float) -> None:
        self._payloads = payloads
        self._read_timeout = read_timeout
        self._pause = pause

    def __iter__(self):
        half = len(self._payloads) // 2
        for payload in self._payloads[:half]:
            yield f"data: {payload}\n".encode()
        if self._pause >= self._read_timeout:
            time.sleep(self._read_timeout)
            raise httpx.ReadTimeout("read timed out", request=None)
        time.sleep(self._pause)
        for payload in self._payloads[half:]:
            yield f"data: {payload}\n".encode()


class PausingLogTransport(httpx.BaseTransport):
    def __init__(self, payloads: tuple[str, ...], *, pause: float) -> None:
        self.payloads = payloads
        self.pause = pause
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        timeout = request.extensions.get("timeout") or {}
        read = timeout.get("read")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_PausingStream(
                self.payloads,
                read_timeout=float(read if read is not None else 30.0),
                pause=self.pause,
            ),
        )


LONG_BACKFILL = tuple(
    f'{{"source":"container","ts":"2026-09-03T18:3{i // 60}:{i % 60:02d}Z",'
    f'"line":"[arena] step {i}"}}'
    for i in range(20)
)


def test_a_pause_inside_the_backfill_no_longer_truncates_the_tail(runpod_key) -> None:
    transport = PausingLogTransport(LONG_BACKFILL, pause=0.3)
    client = _client(transport, runpod_key, timeout_seconds=30.0)
    lines = client.get_logs(
        "pod_test0001", tail=20, max_lines=3000, quiet_seconds=0.05, total_seconds=5.0
    )
    client.close()

    # The pause is six times ``quiet_seconds``; before the fix the read stopped
    # at the halfway mark and the second half was never seen.
    assert isinstance(lines, tuple) and len(lines) == 20
    assert _stopped_because(client) == "stream_end"
    assert client.receipts[-1].summary["tail_requested"] == 20


def test_a_short_backfill_is_bounded_by_total_seconds_not_by_quiet(runpod_key) -> None:
    """Fewer lines than were asked for: quiet must not be the reason it stops."""

    transport = FakeLogTransport()  # three lines, then silence forever
    client = _client(transport, runpod_key, timeout_seconds=30.0)
    started = time.monotonic()
    lines = client.get_logs(
        "pod_test0001", tail=400, max_lines=3000, quiet_seconds=0.05, total_seconds=1.0
    )
    spent = time.monotonic() - started
    client.close()

    assert isinstance(lines, tuple) and len(lines) == 3
    # Bounded by ``total_seconds``, never by the 30 s client timeout.
    assert 0.9 <= spent < 4.0
    assert _stopped_because(client) == "deadline_before_tail"


def test_the_receipt_says_what_was_asked_for_and_what_came_back(runpod_key) -> None:
    client = _client(FakeLogTransport(ends=True), runpod_key)
    client.get_logs("pod_test0001", tail=400, source="container", total_seconds=5.0)
    client.close()

    summary = client.receipts[-1].summary
    assert summary["tail_requested"] == 400
    assert summary["line_count"] == 3
    assert summary["source"] == "container"
    assert summary["stopped_because"] == "stream_end"


# ------------------------------------------------------------ still an error


def test_a_read_timeout_with_no_lines_at_all_is_reported(runpod_key) -> None:
    """Nothing was learned. Silence and a failed read must not look alike."""

    client = _client(FakeLogTransport(payloads=()), runpod_key)
    with pytest.raises(RunPodClientError) as caught:
        client.get_logs("pod_test0001", max_lines=100, quiet_seconds=0.1, total_seconds=5.0)
    client.close()
    assert "log stream failed" in str(caught.value)
    assert "ReadTimeout" in str(caught.value)


def test_a_non_200_is_an_error_not_an_empty_log(runpod_key) -> None:
    transport = RecordingTransport(lambda _: httpx.Response(503, text="upstream"))
    client = _client(transport, runpod_key)
    with pytest.raises(RunPodClientError) as caught:
        client.get_logs("pod_test0001")
    client.close()
    assert "HTTP 503" in str(caught.value)
    assert "body withheld" in str(caught.value)


# ------------------------------------------------------------- source select


def test_the_source_is_sent_on_the_query_and_validated(runpod_key) -> None:
    transport = FakeLogTransport(ends=True)
    client = _client(transport, runpod_key)
    client.get_logs("pod_test0001", tail=120, source="container", total_seconds=5.0)
    client.close()

    assert transport.requests[0].url.params["source"] == "container"
    assert transport.requests[0].url.params["tail"] == "120"


def test_an_unknown_source_is_refused(runpod_key) -> None:
    client = _client(FakeLogTransport(ends=True), runpod_key)
    with pytest.raises(RunPodClientError) as caught:
        client.get_logs("pod_test0001", source="stdout")
    client.close()
    assert "log source must be one of" in str(caught.value)


def test_a_dry_run_names_the_source_without_opening_a_socket(runpod_key) -> None:
    client = RunPodPodsClient(key=runpod_key, execute=False)
    receipt = client.get_logs("pod_test0001", source="system")
    assert receipt.mode == "dry_run"
    assert receipt.summary["would_send"] == {"tail": 200, "source": "system"}
