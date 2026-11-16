"""Isolated HWP worker boundary: the engine runs in a child process that gets bytes on stdin only.

The parent verifies the source hash and signature, spawns the child with an empty cwd and a
minimal environment, bounds stdout, kills on timeout and maps every failure to a typed
`Held` / `Retryable`. It never retries (retry policy belongs to the caller) and never logs
child stderr (only its length and sha256 are recorded in `warnings`).

ponytail: the child's network denial is Python-level only (sockets monkey-patched) and the
`resource` limits are POSIX-only. Kernel isolation (the worker's bubblewrap launcher: no
egress, read-only filesystem) is the real control; this module is the typed boundary.
Interpreter flags: `-I` as specified, but the module is started through a `-c` bootstrap that
re-adds the parent's import path, because `-I` ignores PYTHONPATH and user site and the child
could not otherwise import this package from a non-installed checkout.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from .hwp_contract import (
    Accepted,
    FixtureEngine,
    Held,
    HwpAdapterRequest,
    HwpEngine,
    HwpEngineHold,
    HwpOutcome,
    Retryable,
    UnavailableEngine,
)
from .hwp_signature import detect_hwp_format

EngineName = Literal["unavailable", "fixture"]
_ENGINES: dict[str, type[HwpEngine]] = {"unavailable": UnavailableEngine, "fixture": FixtureEngine}
MAX_REQUEST_BYTES = 1024 * 1024
DEFAULT_MAX_RESULT_BYTES = 8 * 1024 * 1024
_BOOT = (
    "import sys,json;sys.path[:0]=json.loads(sys.argv.pop(1));"
    "from akc_native_parsers.hwp_boundary import _child_main;_child_main(sys.argv[1:])"
)
_OUTCOME: TypeAdapter[HwpOutcome] = TypeAdapter(HwpOutcome)


def run_isolated(
    request: HwpAdapterRequest,
    data: bytes,
    *,
    engine: EngineName,
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
) -> HwpOutcome:
    if hashlib.sha256(data).hexdigest() != request.source_sha256:
        return Held(reason_code="HWP_SOURCE_HASH_MISMATCH")
    if len(data) > request.max_bytes:
        return Held(reason_code="HWP_CONTAINER_LIMIT", detail="INPUT_TOO_LARGE")
    detected = detect_hwp_format(data)
    if isinstance(detected, Held):
        return detected
    if engine not in _ENGINES:
        raise ValueError("unknown engine")

    payload = _frame(request.model_dump_json(by_alias=True).encode()) + _frame(data)
    env = (
        {"SYSTEMROOT": os.environ["SYSTEMROOT"]}
        if os.name == "nt" and "SYSTEMROOT" in os.environ
        else {}
    )
    argv = [
        sys.executable,
        "-I",
        "-c",
        _BOOT,
        json.dumps([p for p in sys.path if p]),
        "--engine",
        engine,
    ]
    with tempfile.TemporaryDirectory(prefix="hwp-") as cwd:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, closed engine set
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out: list[bytes] = []
        err: dict[str, Any] = {"len": 0, "sha": hashlib.sha256()}
        threads = [
            threading.Thread(target=_feed, args=(proc, payload), daemon=True),
            threading.Thread(target=_read_bounded, args=(proc, out, max_result_bytes), daemon=True),
            threading.Thread(target=_drain, args=(proc, err), daemon=True),
        ]
        for t in threads:
            t.start()
        try:
            proc.wait(timeout=request.max_runtime_ms / 1000)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return Retryable(reason_code="PARSER_TIMEOUT")
        for t in threads:
            t.join(timeout=5)
    body = out[0] if out else b""
    if len(body) > max_result_bytes:
        return Held(reason_code="PARSER_RESULT_TOO_LARGE")
    if proc.returncode != 0:
        return Retryable(reason_code="PARSER_PROCESS_CRASH")
    try:
        outcome = _OUTCOME.validate_json(body)
    except ValidationError:
        return Held(reason_code="PARSER_RESULT_INVALID")
    if isinstance(outcome, Retryable):
        return Held(reason_code="PARSER_RESULT_INVALID")
    if isinstance(outcome, Accepted):
        if outcome.result.manifest.source_sha256 != request.source_sha256:
            return Held(reason_code="HWP_SOURCE_HASH_MISMATCH")
        if err["len"]:
            note = f"child_stderr len={err['len']} sha256={err['sha'].hexdigest()}"
            outcome = outcome.model_copy(
                update={
                    "result": outcome.result.model_copy(
                        update={"warnings": (*outcome.result.warnings, note)}
                    )
                }
            )
    return outcome


def _frame(blob: bytes) -> bytes:
    return struct.pack(">I", len(blob)) + blob


def _feed(proc: subprocess.Popen[bytes], payload: bytes) -> None:
    try:
        assert proc.stdin is not None
        proc.stdin.write(payload)
        proc.stdin.close()
    except OSError:  # child died before reading; its exit code is reported
        pass


def _read_bounded(proc: subprocess.Popen[bytes], out: list[bytes], limit: int) -> None:
    assert proc.stdout is not None
    body = proc.stdout.read(limit + 1)
    out.append(body)
    if len(body) > limit:
        proc.kill()


def _drain(proc: subprocess.Popen[bytes], err: dict[str, Any]) -> None:
    assert proc.stderr is not None
    while chunk := proc.stderr.read(65536):
        err["len"] += len(chunk)
        err["sha"].update(chunk)


# ---- child side -------------------------------------------------------------------------


def _disable_network() -> None:
    import socket

    def denied(*_args: object, **_kwargs: object) -> Any:
        raise PermissionError("parser_network_disabled")

    socket_module: Any = socket
    socket_module.socket = denied
    socket_module.create_connection = denied


def _install_resource_limits() -> None:
    if os.name == "nt":
        return
    resource: Any = importlib.import_module("resource")

    memory = 2 * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    os.umask(0o077)


def _read_frame(stream: Any, cap: int) -> bytes:
    (size,) = struct.unpack(">I", stream.read(4))
    if size > cap:
        raise ValueError("frame too large")
    blob: bytes = stream.read(size)
    if len(blob) != size:
        raise ValueError("truncated frame")
    return blob


def _child_main(argv: list[str]) -> None:
    _disable_network()
    _install_resource_limits()
    if len(argv) != 2 or argv[0] != "--engine" or argv[1] not in _ENGINES:
        sys.exit(64)
    request = HwpAdapterRequest.model_validate_json(
        _read_frame(sys.stdin.buffer, MAX_REQUEST_BYTES)
    )
    data = _read_frame(sys.stdin.buffer, request.max_bytes)
    outcome: HwpOutcome
    try:
        result = _ENGINES[argv[1]]().parse(data, request)
        outcome = Accepted(result=result)
    except HwpEngineHold as hold:
        outcome = Held(reason_code=hold.reason_code)
    except ValueError as exc:  # pydantic ValidationError included: result caps vs bad shape
        text = str(exc)
        too_big = "too many" in text or "too large" in text
        outcome = Held(
            reason_code="PARSER_RESULT_TOO_LARGE" if too_big else "PARSER_RESULT_INVALID"
        )
    sys.stdout.buffer.write(_OUTCOME.dump_json(outcome, by_alias=True))
    sys.stdout.buffer.flush()


if __name__ == "__main__":  # pragma: no cover - the parent starts the child through _BOOT
    _child_main(sys.argv[1:])
