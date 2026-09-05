"""D47: the entrypoint's sticky-failure file (``ARENA_FATAL_FILE``).

After the real GLM-OCR pod crash-loop, every runtime's ``entrypoint.sh``
writes ``/opt/arena/FATAL`` (reason + last 200 server-log lines) and sleeps
forever when the model server dies or never becomes ready. These tests cover
the worker side: a worker that finds the file must never look healthy over
``/v1/ready``, whether the file was already there at startup or appears
later, and must refuse ``/v1/run`` once it is CRASHED.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from harness import worker


def _wait_for_file(path: Path, timeout: float = 10.0) -> None:
    """``worker-info.json`` is written in the readiness thread's ``finally``,
    after the HTTP-visible stage flips to CRASHED -- give it a moment."""
    deadline = time.monotonic() + timeout
    while not path.is_file():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path} was never written")
        time.sleep(0.02)


def test_fatal_file_present_at_startup_crashes_without_loading_the_model(
    tmp_path: Path,
) -> None:
    fatal = tmp_path / "FATAL"
    fatal.write_text(
        "model server never became healthy\n--- last 200 lines ---\nboom\n",
        encoding="utf-8",
    )
    with worker(tmp_path, env_overrides={"ARENA_FATAL_FILE": str(fatal)}) as handle:
        body = handle.wait_for_stage(("READY", "CRASHED"))
        assert body["stage"] == "CRASHED"
        assert body["load_receipt"] is None
        assert body["warmup_receipt"] is None
        assert "model server never became healthy" in body["last_error"]

        # No model load was attempted: _prepare() never ran, so the worker
        # never resolved a runtime and worker-info.json shows no adapter.
        info_path = handle.state_dir / "worker-info.json"
        _wait_for_file(info_path)
        info = json.loads(info_path.read_text(encoding="utf-8"))
        assert info["adapter_model_key"] is None
        assert info["canonicalizer"] is None


def test_fatal_file_appearing_after_ready_is_reported_on_the_next_poll(
    tmp_path: Path,
) -> None:
    fatal = tmp_path / "FATAL"
    with worker(tmp_path, env_overrides={"ARENA_FATAL_FILE": str(fatal)}) as handle:
        ready_body = handle.wait_for_stage(("READY",))
        assert ready_body["stage"] == "READY"

        fatal.write_text("model server exited: -11\n", encoding="utf-8")

        status, body = handle.get("/v1/ready")
        assert status == 200
        assert body["stage"] == "CRASHED"
        assert "model server exited: -11" in body["last_error"]


def test_run_is_refused_once_crashed_by_the_fatal_file(tmp_path: Path) -> None:
    fatal = tmp_path / "FATAL"
    with worker(tmp_path, env_overrides={"ARENA_FATAL_FILE": str(fatal)}) as handle:
        handle.wait_for_stage(("READY",))
        fatal.write_text("model server exited: -11\n", encoding="utf-8")
        # A poll of /v1/ready is what notices the fatal file (matching how the
        # controller learns a pod is unhealthy before dispatching a page).
        assert handle.get("/v1/ready")[1]["stage"] == "CRASHED"

        status, body = handle.post("/v1/run", handle.run_payload())
        assert status == 409
        assert body["error"] == "NOT_ACCEPTING"
        assert body["stage"] == "CRASHED"


def test_no_fatal_file_is_unchanged_behaviour(tmp_path: Path) -> None:
    # ARENA_FATAL_FILE points at a path that is never created; the default
    # (/opt/arena/FATAL) would not exist on a test machine either.
    fatal = tmp_path / "never-created" / "FATAL"
    with worker(tmp_path, env_overrides={"ARENA_FATAL_FILE": str(fatal)}) as handle:
        body = handle.wait_for_stage(("READY",))
        assert body["stage"] == "READY"
        assert body["last_error"] is None

        status, run_body = handle.post("/v1/run", handle.run_payload())
        assert status == 200
        assert run_body["status"] == "SUCCESS"


def test_default_fatal_file_env_knob(tmp_path: Path) -> None:
    from arena.worker.config import DEFAULT_FATAL_FILE, WorkerEnv

    env = WorkerEnv.from_env(
        {
            "ARENA_WORKER_TOKEN": "tok",
            "ARENA_MODEL_KEY": "paddleocr_vl_1_6",
            "ARENA_MODEL_REVISION": "a" * 40,
            "ARENA_RUNTIME_MODE": "baked",
            "ARENA_IMAGE_DIGEST": "sha256:" + "b" * 64,
        }
    )
    assert env.fatal_file == DEFAULT_FATAL_FILE
    assert env.public()["fatal_file"] == str(DEFAULT_FATAL_FILE)

    env2 = WorkerEnv.from_env(
        {
            "ARENA_WORKER_TOKEN": "tok",
            "ARENA_MODEL_KEY": "paddleocr_vl_1_6",
            "ARENA_MODEL_REVISION": "a" * 40,
            "ARENA_RUNTIME_MODE": "baked",
            "ARENA_IMAGE_DIGEST": "sha256:" + "b" * 64,
            "ARENA_FATAL_FILE": "/opt/custom/FATAL",
        }
    )
    assert env2.fatal_file == Path("/opt/custom/FATAL")


def test_the_crash_reason_reaches_stdout_so_the_container_log_carries_it(
    tmp_path: Path, capsys
) -> None:
    """The pod is deleted moments after the driver sees CRASHED.

    Its container log is the only evidence that survives, so the reason is
    printed there too rather than living only in the ``/v1/ready`` body -- the
    2026-09-03 GLM-OCR log tail said nothing about why the worker died.
    """

    fatal = tmp_path / "FATAL"
    fatal.write_text("model server exited with status 70\n", encoding="utf-8")
    with worker(tmp_path, env_overrides={"ARENA_FATAL_FILE": str(fatal)}) as handle:
        assert handle.wait_for_stage(("READY", "CRASHED"))["stage"] == "CRASHED"
        # Poll again: the fatal file is re-read on every /v1/ready.
        handle.get("/v1/ready")
        handle.get("/v1/ready")

    printed = capsys.readouterr().out
    lines = [line for line in printed.splitlines() if line.startswith("[arena] worker CRASHED:")]
    # Once per transition into CRASHED, not once per poll.
    assert len(lines) == 1
    assert "model server exited with status 70" in lines[0]


def test_a_prepare_failure_also_names_itself_on_stdout(tmp_path: Path, capsys) -> None:
    """Not only the fatal file: any road to CRASHED says why in the log."""

    from harness import worker as make_worker

    with make_worker(tmp_path, write_prompt=False) as handle:
        assert handle.wait_for_stage(("CRASHED",))["stage"] == "CRASHED"

    printed = capsys.readouterr().out
    lines = [line for line in printed.splitlines() if line.startswith("[arena] worker CRASHED:")]
    assert len(lines) == 1
    assert "prompt file not found" in lines[0]
