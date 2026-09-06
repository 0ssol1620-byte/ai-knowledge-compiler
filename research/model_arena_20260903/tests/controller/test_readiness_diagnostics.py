"""Readiness that reads the container log — the 2026-09-03 GLM-OCR failure.

The pod that provoked all of this rented a GPU and produced nothing: its model
server died ten seconds after start (Transformers did not know the
architecture), ``entrypoint.sh`` exited 70, RunPod restarted the container, and
the cycle repeated every two minutes. From the readiness poll's point of view
nothing was wrong -- ``/v1/ready`` answered 404 because nothing was listening,
and the v1 pod record said ``desired_status: RUNNING`` the entire time. The
poll would have waited out all forty-five minutes on a billed GPU.

Everything the poll now uses to notice that is injected, so each signature is a
test rather than a hope.
"""

from __future__ import annotations

import pytest
from arena.controller.run import (
    POD_MISSING,
    ReadinessError,
    _LogWatch,
    poll_until_ready,
    scrub_log_lines,
)
from arena.provider.runpod_pods import RunPodClientError
from arena.provider.worker_client import WorkerClient
from tests.controller.fake_worker import FakeWorkerTransport, fake_worker_client


def _worker(transport: FakeWorkerTransport) -> WorkerClient:
    return fake_worker_client(transport)


def _logs(*lines: str, ts: str = "2026-09-03T12:00:00Z") -> list[dict[str, object]]:
    """One SSE entry per line, in the shape ``get_logs`` yields."""

    return [
        {"source": "stdout", "ts": f"{ts}#{index}", "line": text}
        for index, text in enumerate(lines)
    ]


class _Ticks:
    """A clock the fake sleep advances, so a deadline passes in no time."""

    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.moment = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)

    def __call__(self):
        return self.moment

    def sleep(self, seconds: float) -> None:
        from datetime import timedelta

        self.moment += timedelta(seconds=seconds)


# ------------------------------------------------------- fatal log markers


@pytest.mark.parametrize(
    ("line", "error_class"),
    [
        ("[arena] FATAL model server never became healthy", "MODEL_LOAD"),
        ("[arena] model server exited with status 70", "MODEL_LOAD"),
        ("[arena] model server did not answer /health in 1200 s", "MODEL_LOAD"),
        ("Traceback (most recent call last):", "DEPENDENCY"),
    ],
)
def test_a_fatal_container_log_line_ends_the_wait_at_once(
    line: str, error_class: str
) -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=2700.0,
            sleep=ticks.sleep,
            now=ticks,
            log_tail=lambda: _logs("bootstrap: extracting bundle", line),
        )
    client.close()
    # Section 15.9 retries neither class. Waiting is not going to help.
    assert caught.value.error_class == error_class
    assert caught.value.signature is not None and caught.value.signature in line
    assert caught.value.polls == 1  # not at the 45-minute deadline
    assert "will not come up" in str(caught.value)
    assert caught.value.log_tail  # the evidence travels with the failure


def test_a_clean_bootstrap_log_does_not_end_the_wait() -> None:
    transport = FakeWorkerTransport(ready_answers=[404, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()
    stage, _ = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
        log_tail=lambda: _logs(
            "[arena] bootstrap: bundle verified",
            "[arena] bootstrap: weights cache hit",
        ),
    )
    client.close()
    assert stage == "READY"


# ------------------------------------------------------------- crash loops


def test_two_container_starts_are_a_crash_loop() -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=2700.0,
            sleep=ticks.sleep,
            now=ticks,
            log_tail=lambda: _logs(
                "start container for vllm/vllm-openai:v0.11.0: begin",
                "bootstrap: weights cache hit",
                "start container for vllm/vllm-openai:v0.11.0: begin",
            ),
        )
    client.close()
    assert caught.value.error_class == "MODEL_LOAD"
    assert caught.value.signature is not None
    assert "start container for" in caught.value.signature


def test_one_container_start_is_not_a_crash_loop() -> None:
    """A pod that started once is starting, not restarting."""

    transport = FakeWorkerTransport(ready_answers=[404, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()
    stage, _ = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
        log_tail=lambda: _logs("start container for vllm/vllm-openai: begin"),
    )
    client.close()
    assert stage == "READY"


def test_restart_markers_are_counted_across_reads_not_within_one_tail() -> None:
    """A bounded tail scrolls; the first start can be gone by the second."""

    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    tails = [
        _logs("start container for img: begin", ts="t1"),
        _logs("bootstrap: installing runtime", ts="t2"),
        _logs("start container for img: begin", ts="t3"),
    ]
    reads = 0

    def tail() -> list[dict[str, object]]:
        nonlocal reads
        answer = tails[min(reads, len(tails) - 1)]
        reads += 1
        return answer

    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=2700.0,
            sleep=ticks.sleep,
            now=ticks,
            log_tail=tail,
            log_every_polls=1,
        )
    client.close()
    assert caught.value.error_class == "MODEL_LOAD"
    assert caught.value.polls == 3  # the second start, three polls in


def test_the_same_restart_line_read_twice_is_still_one_restart() -> None:
    """Otherwise a stable tail would condemn a pod on the second read."""

    transport = FakeWorkerTransport(ready_answers=[404, 404, 404, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()
    stage, _ = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
        log_tail=lambda: _logs("start container for img: begin"),
        log_every_polls=1,
    )
    client.close()
    assert stage == "READY"


# ------------------------------------------------------------- log cadence


def test_the_log_read_cadence_defaults_to_about_two_minutes() -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    reads = 0

    def tail() -> list[dict[str, object]]:
        nonlocal reads
        reads += 1
        return []

    with pytest.raises(ReadinessError):
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=600.0,
            sleep=ticks.sleep,
            now=ticks,
            log_tail=tail,
        )
    client.close()
    # Ten minutes at one poll per 20 s is 31 polls; a read at poll 1 and then
    # every sixth is six reads, not thirty-one.
    assert reads == 6


def test_a_log_endpoint_that_fails_is_not_a_verdict() -> None:
    """Diagnostics never condemn a pod. The deadline does that."""

    transport = FakeWorkerTransport(ready_answers=[404, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()

    def boom() -> list[dict[str, object]]:
        raise RuntimeError("the log stream dropped")

    stage, _ = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
        log_tail=boom,
    )
    client.close()
    assert stage == "READY"


# ---------------------------------------------------------------- pod gone


def test_a_pod_deleted_out_from_under_the_driver_fails_fast() -> None:
    """Two consecutive "no such pod" reads, not 45 minutes of proxy 404s."""

    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    with pytest.raises(ReadinessError, match="pod gone") as caught:
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=2700.0,
            sleep=ticks.sleep,
            now=ticks,
            pod_status=lambda: POD_MISSING,
        )
    client.close()
    assert caught.value.provider_status == POD_MISSING
    assert caught.value.signature == "pod gone"
    assert caught.value.polls == 2


def test_one_missing_read_is_not_a_deleted_pod() -> None:
    """v1 404s right after a create. That is eventual consistency."""

    answers = [POD_MISSING, "RUNNING", "RUNNING"]
    transport = FakeWorkerTransport(ready_answers=[404, 404, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()
    stage, _ = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
        pod_status=lambda: answers.pop(0) if answers else "RUNNING",
    )
    client.close()
    assert stage == "READY"


def test_an_unreadable_provider_does_not_count_towards_pod_gone() -> None:
    """``None`` means "could not read", which is evidence of nothing."""

    transport = FakeWorkerTransport(ready_answers=[404, 404, 200], stages=["READY"])
    client = _worker(transport)
    ticks = _Ticks()
    stage, _ = poll_until_ready(
        client,
        max_attempts=None,
        poll_seconds=20.0,
        deadline_seconds=2700.0,
        sleep=ticks.sleep,
        now=ticks,
        pod_status=lambda: None,
    )
    client.close()
    assert stage == "READY"


# ------------------------------------------------------------- log hygiene


def test_only_the_offending_log_lines_are_dropped() -> None:
    """Losing 198 useful lines to protect one is the wrong trade."""

    kept, dropped = scrub_log_lines(
        _logs(
            "[arena] bootstrap: fetching bundle",
            "curl https://acct.r2.cloudflarestorage.com/b/o?X-Amz-Signature=abc",
            'GET /v1/ready -H "Authorization: Bearer sometoken"',
            "signed with Signature=deadbeef",
            "[arena] model server healthy",
        )
    )
    assert dropped == 3
    assert [entry["line"] for entry in kept] == [
        "[arena] bootstrap: fetching bundle",
        "[arena] model server healthy",
    ]


def test_a_line_carrying_a_loaded_credential_is_dropped() -> None:
    from arena.provider.safety import register_live_secret

    bearer = "arena-worker-value-0123456789abcdefZ"
    register_live_secret(bearer)
    kept, dropped = scrub_log_lines(
        _logs("[arena] worker starting", f"ARENA_WORKER_TOKEN={bearer}")
    )
    assert dropped == 1
    assert len(kept) == 1


def test_a_fatal_line_is_recognised_even_when_the_tail_around_it_is_scrubbed() -> None:
    """Signatures are matched on the raw text; only the receipt is scrubbed."""

    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=2700.0,
            sleep=ticks.sleep,
            now=ticks,
            log_tail=lambda: _logs(
                "curl https://acct.r2.cloudflarestorage.com/b/o?X-Amz-Signature=abc",
                "[arena] FATAL model server never became healthy",
            ),
        )
    client.close()
    assert caught.value.error_class == "MODEL_LOAD"
    lines = [entry.get("line") for entry in caught.value.log_tail]
    assert lines == ["[arena] FATAL model server never became healthy"]
    assert caught.value.log_note is not None and "withheld" in caught.value.log_note


# --------------------------------------------------------------- progress


def test_progress_reports_state_changes_and_a_heartbeat() -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    lines: list[str] = []
    with pytest.raises(ReadinessError):
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=900.0,
            sleep=ticks.sleep,
            now=ticks,
            progress=lines.append,
            heartbeat_seconds=300.0,
            log_tail=lambda: _logs("[arena] bootstrap: downloading weights"),
        )
    client.close()
    assert any("HTTP 404" in line for line in lines)
    beats = [line for line in lines if "still waiting" in line]
    assert len(beats) == 3  # fifteen minutes, one every five
    assert "[arena] bootstrap: downloading weights" in beats[0]
    assert "elapsed" in beats[0]


def test_a_failed_log_fetch_is_named_in_the_heartbeat_not_reported_as_silence() -> None:
    """The 45 minutes of "no [arena] milestone" while every read was failing.

    A pod that has printed nothing and a log endpoint the driver cannot read
    are two different problems, and the heartbeat is the only place an operator
    would see either. Saying the first when it is the second is what made the
    GLM-OCR run unreadable.
    """

    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    lines: list[str] = []

    def failing_read():
        raise RunPodClientError("RunPod log stream failed for pod abc: ReadTimeout")

    with pytest.raises(ReadinessError):
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=900.0,
            sleep=ticks.sleep,
            now=ticks,
            progress=lines.append,
            heartbeat_seconds=300.0,
            log_tail=failing_read,
        )
    client.close()
    beats = [line for line in lines if "still waiting" in line]
    assert beats
    assert all("log fetch failed" in beat for beat in beats)
    assert "ReadTimeout" in beats[0]
    assert not any("no [arena] milestone" in beat for beat in beats)


def test_an_empty_log_still_reads_as_silence_not_as_a_failure() -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    client = _worker(transport)
    ticks = _Ticks()
    lines: list[str] = []
    with pytest.raises(ReadinessError):
        poll_until_ready(
            client,
            max_attempts=None,
            poll_seconds=20.0,
            deadline_seconds=900.0,
            sleep=ticks.sleep,
            now=ticks,
            progress=lines.append,
            heartbeat_seconds=300.0,
            log_tail=lambda: [],
        )
    client.close()
    beats = [line for line in lines if "still waiting" in line]
    assert beats
    assert all("no [arena] milestone" in beat for beat in beats)
    assert not any("log fetch failed" in beat for beat in beats)


def test_a_read_that_recovers_stops_reporting_the_old_failure() -> None:
    """A transient failure must not stick to every heartbeat after it."""

    watch = _LogWatch()

    def failing():
        raise RunPodClientError("RunPod log stream failed for pod abc: ReadTimeout")

    watch.refresh(failing)
    assert "log fetch failed" in watch.status_note
    assert "ReadTimeout" in watch.status_note

    watch.refresh(lambda: _logs("[arena] bootstrap: downloading weights"))
    assert watch.status_note == "[arena] bootstrap: downloading weights"
    assert watch.fetch_error is None
    assert watch.note is not None and "line(s) from the provider" in watch.note


def test_a_credential_in_the_error_text_is_reduced_to_the_exception_class() -> None:
    """The heartbeat text reaches the console and the receipt."""

    from arena.provider.safety import register_live_secret

    watch = _LogWatch()
    bearer = "arena-live-bearer-" + "9" * 24
    register_live_secret(bearer)

    def leaking():
        raise RunPodClientError(f"stream failed with Authorization: Bearer {bearer}")

    watch.refresh(leaking)
    assert bearer not in watch.status_note
    assert watch.status_note == "log fetch failed: RunPodClientError"


# ------------------------------------------- the ready body behind the stage


def test_a_terminal_stage_keeps_the_body_that_carried_last_error() -> None:
    """"HTTP 200 stage=CRASHED" is the stage; ``last_error`` is the reason.

    Pod jdwdnvg8a2rzx6 answered exactly that at 18:39:20Z on 2026-09-03 and the
    driver receipt kept only the six words of the status line, so nothing on
    disk said what had killed ``_prepare``.
    """

    transport = FakeWorkerTransport(
        stages=["CRASHED"],
        ready_extra={"last_error": "ValueError: unrecognised model_type glm_ocr"},
    )
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(_worker(transport), max_attempts=1, poll_seconds=0.0)

    body = caught.value.last_ready_response
    assert body is not None
    assert body["stage"] == "CRASHED"
    assert body["last_error"] == "ValueError: unrecognised model_type glm_ocr"
    assert caught.value.last_status == "HTTP 200 stage=CRASHED"


def test_a_deadline_keeps_the_last_body_it_managed_to_parse() -> None:
    """The wait can also end on the deadline; the last body still travels."""

    transport = FakeWorkerTransport(
        stages=["MODEL_LOADING"], ready_extra={"last_error": None}
    )
    ticks = _Ticks()
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(
            _worker(transport),
            max_attempts=None,
            deadline_seconds=30.0,
            poll_seconds=10.0,
            sleep=ticks.sleep,
            now=ticks,
        )

    body = caught.value.last_ready_response
    assert body is not None and body["stage"] == "MODEL_LOADING"


def test_a_ready_body_field_carrying_a_credential_is_dropped_not_the_body() -> None:
    from arena.provider.safety import register_live_secret

    bearer = "arena-live-bearer-" + "7" * 24
    register_live_secret(bearer)
    transport = FakeWorkerTransport(
        stages=["CRASHED"],
        ready_extra={
            "last_error": "adapter refused",
            "debug_curl": f"curl -H 'Authorization: Bearer {bearer}'",
        },
    )
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(_worker(transport), max_attempts=1, poll_seconds=0.0)

    body = caught.value.last_ready_response
    assert body is not None
    assert body["last_error"] == "adapter refused"
    assert "debug_curl" not in body
    assert body["_withheld_field_count"] == 1
    assert bearer not in str(body)


def test_a_wait_that_never_parsed_a_body_carries_none() -> None:
    transport = FakeWorkerTransport(ready_answers=[404])
    ticks = _Ticks()
    with pytest.raises(ReadinessError) as caught:
        poll_until_ready(
            _worker(transport),
            max_attempts=None,
            deadline_seconds=20.0,
            poll_seconds=10.0,
            sleep=ticks.sleep,
            now=ticks,
        )
    assert caught.value.last_ready_response is None
