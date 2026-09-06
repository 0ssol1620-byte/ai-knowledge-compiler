"""Worker-side prompt enforcement, model-server readiness and the pod-age fuse.

ARENA_CONTRACT 11.5 D17 (prompt registry), D19 (bounded retry on a local model
server that is still loading), D20 (the worker exits by itself when
ARENA_MAX_POD_AGE_HOURS elapses) and D34 (prompt kinds).

These are the paths a real pod takes and a unit test does not: readiness runs in
its own thread, the fuse runs in another, and both have to reach a state the
controller can read over HTTP.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from arena.worker import server as server_module
from arena.worker.adapter_api import AdapterError
from arena.worker.server import (
    ADAPTER_CONFIG_ACCEPTS_PROMPT_SHA256,
    MAX_POD_AGE_EXIT_CODE,
    PodAgeWatchdog,
    is_connection_refused,
    retry_while_connection_refused,
)
from arena.worker.util import sha256_label
from harness import worker

# -- D17 / D34: the prompt the worker will demand ---------------------------


def test_ready_worker_resolved_the_prompt_from_the_registry(tmp_path: Path) -> None:
    with worker(tmp_path, prompt_text="Transcribe this page.\n") as handle:
        assert handle.wait_for_stage(("READY",))["stage"] == "READY"
        info = json.loads((handle.state_dir / "worker-info.json").read_text(encoding="utf-8"))
        assert info["prompt_id"] == handle.descriptor["prompt_id"]
        assert info["prompt_kind"] == "text"
        assert info["prompt_source"] == "prompt_registry"
        assert info["prompt_sha256"] == sha256_label(b"Transcribe this page.\n")
        assert info["prompt_file"].endswith(f"{handle.descriptor['prompt_id']}.txt")


def test_prompt_file_missing_crashes_the_worker_with_a_reason(tmp_path: Path) -> None:
    """D17: fail closed. A worker with no prompt never reaches READY."""
    with worker(tmp_path, write_prompt=False) as handle:
        body = handle.wait_for_stage(("CRASHED",))
        assert body["stage"] == "CRASHED"
        assert "prompt file not found" in body["last_error"]
        assert "D17" in body["last_error"]


def test_prompt_kind_none_wants_an_empty_file(tmp_path: Path) -> None:
    with worker(
        tmp_path, descriptor_overrides={"prompt_kind": "none"}, prompt_text=""
    ) as handle:
        assert handle.wait_for_stage(("READY",))["stage"] == "READY"
        assert handle.prompt_sha256 == sha256_label(b"")


def test_prompt_kind_none_refuses_a_prompt_that_should_not_exist(tmp_path: Path) -> None:
    with worker(
        tmp_path,
        descriptor_overrides={"prompt_kind": "none"},
        prompt_text="a prompt this pipeline never sends\n",
    ) as handle:
        body = handle.wait_for_stage(("CRASHED",))
        assert "prompt_kind is 'none'" in body["last_error"]


def test_prompt_kind_text_refuses_an_empty_registry_file(tmp_path: Path) -> None:
    with worker(tmp_path, prompt_text="") as handle:
        body = handle.wait_for_stage(("CRASHED",))
        assert "empty or blank" in body["last_error"]


def test_prompt_env_override_is_honoured(tmp_path: Path) -> None:
    with worker(tmp_path, prompt_via_env_file=True, prompt_text="override\n") as handle:
        assert handle.wait_for_stage(("READY",))["stage"] == "READY"
        info = json.loads((handle.state_dir / "worker-info.json").read_text(encoding="utf-8"))
        assert info["prompt_source"] == "ARENA_PROMPT_FILE"


def test_run_is_refused_when_the_request_prompt_hash_differs(tmp_path: Path) -> None:
    """D17: the worker refuses a run whose prompt_sha256 is not the file's hash."""
    with worker(tmp_path, prompt_text="the campaign prompt\n") as handle:
        handle.wait_for_stage(("READY",))
        status, body = handle.post(
            "/v1/run", handle.run_payload(prompt_sha256="sha256:" + "1" * 64)
        )
        assert status == 422, body
        assert body["error"] == "PROMPT_MISMATCH"
        assert handle.prompt_sha256 is not None
        assert handle.prompt_sha256 in body["detail"]


def test_the_adapter_is_given_the_registry_text(tmp_path: Path) -> None:
    """D34 'text': the adapter sends AdapterConfig.prompt_text, non-empty."""
    with worker(tmp_path, prompt_text="Transcribe this page.\n") as handle:
        ready = handle.wait_for_stage(("READY",))
        provenance = ready["load_receipt"]["runtime_provenance"]
        assert provenance["prompt_chars"] == len("Transcribe this page.\n")
        info = json.loads((handle.state_dir / "worker-info.json").read_text(encoding="utf-8"))
        assert info["adapter_config_prompt_sha256_delivered"] is (
            ADAPTER_CONFIG_ACCEPTS_PROMPT_SHA256
        )


# -- D19: a bounded, logged retry on connection refused ---------------------


class _Recorder:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_is_connection_refused_recognises_the_three_shapes() -> None:
    assert is_connection_refused(ConnectionRefusedError(111, "refused"))
    assert is_connection_refused(OSError(111, "Connection refused"))
    assert is_connection_refused(
        AdapterError("MODEL_LOAD", "vllm health check: Connection refused")
    )
    wrapped = RuntimeError("adapter blew up")
    wrapped.__cause__ = ConnectionRefusedError(111, "refused")
    assert is_connection_refused(wrapped)


def test_is_connection_refused_says_no_to_a_real_failure() -> None:
    assert not is_connection_refused(AdapterError("CUDA_OOM", "out of memory"))
    assert not is_connection_refused(ValueError("bad shape"))
    assert not is_connection_refused(OSError(2, "No such file or directory"))


def test_is_connection_refused_survives_a_cyclic_cause() -> None:
    first = RuntimeError("a")
    second = RuntimeError("b")
    first.__cause__ = second
    second.__cause__ = first
    assert not is_connection_refused(first)


def test_retry_returns_as_soon_as_the_server_answers() -> None:
    recorder = _Recorder()
    attempts: list[int] = []

    def call() -> str:
        attempts.append(len(attempts))
        if len(attempts) < 4:
            raise ConnectionRefusedError(111, "not yet")
        return "loaded"

    result = retry_while_connection_refused(
        call,
        what="model load",
        budget_seconds=1200.0,
        poll_seconds=5.0,
        clock=recorder.clock,
        sleep=recorder.sleep,
    )
    assert result == "loaded"
    assert len(attempts) == 4
    assert recorder.slept == [5.0, 5.0, 5.0]


def test_retry_gives_up_at_the_budget_and_says_so() -> None:
    recorder = _Recorder()

    def call() -> str:
        raise ConnectionRefusedError(111, "never up")

    with pytest.raises(AdapterError) as excinfo:
        retry_while_connection_refused(
            call,
            what="model load",
            budget_seconds=30.0,
            poll_seconds=10.0,
            clock=recorder.clock,
            sleep=recorder.sleep,
        )
    assert excinfo.value.error_class == "MODEL_LOAD"
    assert "ARENA_MODEL_SERVER_WAIT_SECONDS" in str(excinfo.value)
    assert sum(recorder.slept) == pytest.approx(30.0)


def test_retry_never_swallows_a_real_failure() -> None:
    def call() -> str:
        raise AdapterError("CUDA_OOM", "out of memory")

    with pytest.raises(AdapterError) as excinfo:
        retry_while_connection_refused(
            call, what="model load", budget_seconds=1200.0, poll_seconds=1.0
        )
    assert excinfo.value.error_class == "CUDA_OOM"


def test_retry_logs_every_attempt(caplog: pytest.LogCaptureFixture) -> None:
    recorder = _Recorder()
    calls: list[int] = []

    def call() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionRefusedError(111, "not yet")
        return "ok"

    with caplog.at_level("WARNING", logger="arena.worker"):
        retry_while_connection_refused(
            call,
            what="warm-up",
            budget_seconds=60.0,
            poll_seconds=2.0,
            clock=recorder.clock,
            sleep=recorder.sleep,
        )
    retries = [record for record in caplog.records if "refused the connection" in record.message]
    assert len(retries) == 2


def test_readiness_waits_out_a_model_server_that_is_still_loading(tmp_path: Path) -> None:
    """End to end: two refusals on load, one on warm-up, then READY."""
    with worker(
        tmp_path,
        descriptor_overrides={
            "inference_config": {
                "max_new_tokens": 4096,
                "fake_load_refusals": 2,
                "fake_warmup_refusals": 1,
            }
        },
        env_overrides={
            "ARENA_MODEL_SERVER_WAIT_SECONDS": "30",
            "ARENA_MODEL_SERVER_POLL_SECONDS": "0.01",
        },
    ) as handle:
        assert handle.wait_for_stage(("READY",))["stage"] == "READY"
        assert handle.core.stage == "READY"


def test_readiness_crashes_when_the_model_server_never_comes_up(tmp_path: Path) -> None:
    with worker(
        tmp_path,
        descriptor_overrides={
            "inference_config": {"max_new_tokens": 4096, "fake_load_refusals": 10_000}
        },
        env_overrides={
            "ARENA_MODEL_SERVER_WAIT_SECONDS": "0.05",
            "ARENA_MODEL_SERVER_POLL_SECONDS": "0.01",
        },
    ) as handle:
        body = handle.wait_for_stage(("CRASHED",))
        assert "still refusing connections" in body["last_error"]


# -- D20: the pod's own lifetime fuse ---------------------------------------


class _FakeCore:
    """Just enough of WorkerCore for the fuse."""

    def __init__(self, *, busy_polls: int = 0) -> None:
        self.drained = 0
        self.stopped = 0
        self._busy_polls = busy_polls

    @property
    def active_jobs(self) -> int:
        if self._busy_polls > 0:
            self._busy_polls -= 1
            return 1
        return 0

    def drain(self) -> dict[str, Any]:
        self.drained += 1
        return {"stage": "DRAINING"}

    def stop(self) -> None:
        self.stopped += 1


def _watchdog(core: Any, recorder: _Recorder, **kwargs: Any) -> PodAgeWatchdog:
    return PodAgeWatchdog(
        core,
        clock=recorder.clock,
        sleep=recorder.sleep,
        **kwargs,
    )


def test_fuse_drains_and_exits_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    exits: list[int] = []
    monkeypatch.setattr(server_module, "_exit_process", exits.append)
    core = _FakeCore()
    recorder = _Recorder()
    fuse = _watchdog(
        core, recorder, max_age_seconds=7200.0, drain_grace_seconds=300.0, poll_seconds=600.0
    )
    fuse.run()
    assert core.drained == 1
    assert core.stopped == 1
    assert exits == [MAX_POD_AGE_EXIT_CODE]
    assert MAX_POD_AGE_EXIT_CODE != 0, "a pod that ran out of lifetime did not finish its work"
    assert recorder.now >= 7200.0


def test_fuse_waits_for_a_page_in_flight_then_leaves(monkeypatch: pytest.MonkeyPatch) -> None:
    exits: list[int] = []
    monkeypatch.setattr(server_module, "_exit_process", exits.append)
    core = _FakeCore(busy_polls=3)
    recorder = _Recorder()
    fuse = _watchdog(
        core, recorder, max_age_seconds=10.0, drain_grace_seconds=300.0, poll_seconds=5.0
    )
    fuse.expire()
    assert core.drained == 1
    assert exits == [MAX_POD_AGE_EXIT_CODE]
    assert recorder.slept[-3:] == [1.0, 1.0, 1.0]


def test_fuse_leaves_even_when_a_page_will_not_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    exits: list[int] = []
    monkeypatch.setattr(server_module, "_exit_process", exits.append)
    core = _FakeCore(busy_polls=10_000)
    recorder = _Recorder()
    fuse = _watchdog(
        core, recorder, max_age_seconds=10.0, drain_grace_seconds=3.0, poll_seconds=5.0
    )
    fuse.expire()
    assert exits == [MAX_POD_AGE_EXIT_CODE]
    assert sum(recorder.slept) == pytest.approx(3.0)


def test_fuse_can_be_stopped_before_it_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    exits: list[int] = []
    monkeypatch.setattr(server_module, "_exit_process", exits.append)
    core = _FakeCore()
    fuse = PodAgeWatchdog(core, max_age_seconds=3600.0, drain_grace_seconds=1.0, poll_seconds=0.01)
    fuse.start()
    fuse.stop()
    for _ in range(200):
        if fuse._thread is not None and not fuse._thread.is_alive():
            break
        threading.Event().wait(0.01)
    assert exits == []
    assert core.drained == 0


def test_fuse_refuses_a_non_positive_lifetime() -> None:
    with pytest.raises(ValueError, match="max_age_seconds"):
        PodAgeWatchdog(_FakeCore(), max_age_seconds=0.0, drain_grace_seconds=1.0)


def test_worker_arms_the_fuse_only_when_the_pod_env_asks(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        assert handle.core.pod_age_watchdog is None


def test_worker_arms_the_fuse_from_arena_max_pod_age_hours(tmp_path: Path) -> None:
    with worker(tmp_path, env_overrides={"ARENA_MAX_POD_AGE_HOURS": "2"}) as handle:
        fuse = handle.core.pod_age_watchdog
        assert fuse is not None
        assert fuse.max_age_seconds == 7200.0
        assert not fuse.fired, "a two-hour fuse must not fire during a test"


def test_a_real_worker_exits_when_the_fuse_fires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole D20 path over a running server, with the exit call intercepted."""
    exits: list[int] = []
    fired = threading.Event()

    def record(code: int) -> None:
        exits.append(code)
        fired.set()

    monkeypatch.setattr(server_module, "_exit_process", record)
    with worker(
        tmp_path,
        env_overrides={
            "ARENA_MAX_POD_AGE_HOURS": "0.0006",  # ~2.2 s: long enough to serve first
            "ARENA_POD_AGE_DRAIN_SECONDS": "1",
        },
        wait_ready=False,
    ) as handle:
        assert handle.wait_for_stage(("READY",))["stage"] == "READY"
        assert fired.wait(20.0), "the pod age fuse never fired"
        assert exits == [MAX_POD_AGE_EXIT_CODE]
        assert handle.core.stage == "DRAINING"
        status, body = handle.post("/v1/run", handle.run_payload())
        assert status == 409, body
        assert body["error"] == "NOT_ACCEPTING"
