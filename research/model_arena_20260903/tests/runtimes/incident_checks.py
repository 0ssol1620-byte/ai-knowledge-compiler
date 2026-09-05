"""Checks for the 2026-09-03 GLM-OCR canary incident, shared by the runtime tests.

These live in their own module rather than in ``conftest.py`` on purpose. The test
files call them from inside a test function, and ``tests/`` holds one
``conftest.py`` per lane; under whole-tree collection a bare ``import conftest``
inside a function can resolve to a different lane's file. ``incident_checks`` is
unique in the repository, so it cannot be shadowed that way.
"""

from __future__ import annotations

from pathlib import Path

from conftest import load_runtime_json, runtime_dir

#: This module resolves runtimes/ through its OWN global rather than through
#: ``conftest.RUNTIMES_ROOT``. Every lane under tests/ ships a file named
#: conftest.py and they all load into ``sys.modules["conftest"]``, so the last one
#: imported wins; a check that reached through that name would read - and a test
#: that patched it would patch - whichever lane got there first.
RUNTIMES_ROOT = Path(__file__).resolve().parents[2] / "runtimes"

#: Re-exported so a test can reach every helper it needs through this one
#: unshadowable module name, rather than importing ``conftest`` from inside a
#: function (which resolves to another lane's conftest under whole-tree collection).
__all__ = [
    "FATAL_LOG_PREFIX",
    "FATAL_LOG_TAIL_LINES",
    "RUNTIMES_ROOT",
    "assert_architecture_preflight",
    "assert_no_model_server_to_hold",
    "assert_sticky_model_server_failure",
    "load_runtime_json",
    "read_runtime_script",
    "runtime_dir",
]

# --------------------------------------------------------------------------- #
# 2026-09-03 GLM-OCR canary incident.
#
# The canary reached the model-server start and died because the base image's
# Transformers did not know the checkpoint's model_type. RunPod then restarted the
# exited start command, so the pod crash-looped and burned GPU time invisibly.
# Two things close that for every runtime, and both are string-level facts about
# the shipped scripts:
#
#   * bootstrap.sh asserts the pinned framework versions AND that the framework
#     recognises this checkpoint's architecture, after the installs and before any
#     server starts, recording the result in the bootstrap receipt;
#   * entrypoint.sh, for a runtime that starts a model server, makes a start
#     failure sticky: it writes /opt/arena/FATAL, prints the prefix the controller
#     condemns on, and holds the container instead of exiting.
# --------------------------------------------------------------------------- #

#: arena.controller.run.FATAL_LOG_SIGNATURES matches on this exact prefix, and
#: arena.controller.run.LOG_TAIL_LINES is the same 200. Both are asserted against
#: the controller itself in tests/runtimes/test_c3_bootstrap_contract.py rather
#: than only duplicated here.
FATAL_LOG_PREFIX = "[arena] FATAL"
FATAL_LOG_TAIL_LINES = 200

#: The two spellings of the hand-off at the end of bootstrap.sh (11.3 item 4).
_ENTRYPOINT_HANDOFFS = (
    'exec "${RUNTIME_DIR}/entrypoint.sh"',
    'exec bash "${ARENA_ROOT}/runtime/entrypoint.sh"',
    "exec /opt/arena/runtime/entrypoint.sh",
)


def read_runtime_script(model_key: str, name: str) -> str:
    """Read one shipped script out of ``runtimes/<model_key>/``."""

    return (RUNTIMES_ROOT / model_key / name).read_text(encoding="utf-8")


def assert_architecture_preflight(model_key: str) -> None:
    """bootstrap.sh proves the framework knows this checkpoint before a server starts."""

    text = read_runtime_script(model_key, "bootstrap.sh")
    start = text.find('ARCH_PREFLIGHT="$(')
    assert start != -1, f"{model_key}: bootstrap.sh has no architecture preflight block"
    assert "[arena] architecture preflight PASS " in text, (
        f"{model_key}: the preflight must say PASS on the pod log"
    )
    assert f"{FATAL_LOG_PREFIX} architecture preflight: " in text, (
        f"{model_key}: a preflight failure must carry the prefix the controller condemns on"
    )
    assert "raise SystemExit(64)" in text, f"{model_key}: the preflight must exit 64 on failure"
    assert "architecture_preflight=${ARCH_PREFLIGHT}" in text, (
        f"{model_key}: the preflight result must land in the bootstrap receipt"
    )
    handoffs = [text.find(spelling) for spelling in _ENTRYPOINT_HANDOFFS]
    handoff = min(index for index in handoffs if index != -1)
    assert start < handoff, (
        f"{model_key}: the preflight runs after the hand-off to entrypoint.sh, which is too late"
    )


def assert_sticky_model_server_failure(model_key: str) -> None:
    """entrypoint.sh holds the container on a model-server failure instead of exiting."""

    text = read_runtime_script(model_key, "entrypoint.sh")
    assert "exit 70" not in text, f"{model_key}: exiting is exactly what RunPod restarts"
    assert "/opt/arena/FATAL" in text, f"{model_key}: no FATAL file is written"
    assert 'echo "[arena] FATAL ${reason}" >&2' in text, (
        f"{model_key}: arena.controller.run.FATAL_LOG_SIGNATURES matches on this exact prefix"
    )
    assert "sleep infinity" in text, f"{model_key}: the container must hold, not exit"
    assert f"FATAL_LOG_TAIL_LINES={FATAL_LOG_TAIL_LINES}" in text
    assert 'tail -n "${FATAL_LOG_TAIL_LINES}" "${SERVER_LOG}"' in text, (
        f"{model_key}: the FATAL file must carry the server log tail"
    )
    assert '> >(tee -a "${SERVER_LOG}" >&2) 2>&1 &' in text, (
        f"{model_key}: the server log has to reach both ${{SERVER_LOG}} and the pod log"
    )
    assert text.count("fatal_and_hold") >= 2, (
        f"{model_key}: fatal_and_hold is defined but never called"
    )


def assert_no_model_server_to_hold(model_key: str) -> None:
    """An in-process runtime gets the preflight only: there is nothing to hold open."""

    text = read_runtime_script(model_key, "entrypoint.sh")
    assert "fatal_and_hold" not in text, (
        f"{model_key}: this runtime starts no model server, so it has no server failure to hold"
    )
    assert "wait_for_model_server" not in text
    assert "sleep infinity" not in text
