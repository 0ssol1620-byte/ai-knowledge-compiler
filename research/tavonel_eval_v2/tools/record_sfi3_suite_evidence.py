#!/usr/bin/env python3
"""Run the SFI3 test suite outside the freeze gate and seal its evidence.

The freeze gate is part of the suite it guards, so it cannot certify the run
that currently contains it.  This recorder is deliberately a separate command.
It runs every ``test_*.py`` file in a fresh process, streams output directly to
a write-once transcript, aggregates pytest's JUnit records, and only then writes
an immutable evidence receipt.  The gate may consume that completed *prior* run;
it must never invoke this module itself.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools",):
    sys.path.insert(0, str(NS / _sub))

from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import new_run_id, write_immutable  # noqa: E402

THIS_TOOL = Path(__file__).resolve()
TESTS = NS / "tests"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
OUTPUTS = NS / "receipts" / "suite-output"
STEM = "sfi3-suite-evidence"
SCHEMA = "tavonel.v2.sfi3_suite_evidence.v1"
REENTRY_FLAG = "TAVONEL_SFI3_FREEZE_GATE_RUNNING"

PYTEST_ARGS: tuple[str, ...] = ("-q", "-p", "no:cacheprovider")
TOOLING_DIRS: tuple[Path, ...] = (
    *(
        NS / name
        for name in (
            "acquisition",
            "activation",
            "canonicalization",
            "comparator",
            "compiler",
            "endpoint",
            "facets",
            "oracle",
            "retrieval",
            "source_fact_ir",
            "tools",
        )
    ),
    ROOT / "packages" / "cir-python" / "src" / "akc_cir",
)
TOOLING_FILES: tuple[Path, ...] = (ROOT / "pyproject.toml", ROOT / "uv.lock")


@dataclass(frozen=True)
class JUnitCounts:
    tests: int
    skipped: int
    failures: int
    errors: int


@dataclass(frozen=True)
class ShardResult:
    test_file: str
    command: list[str]
    exit_code: int
    junit_file: str
    junit_file_sha256: str | None
    tests: int
    skipped: int
    failures: int
    errors: int
    peak_rss_bytes: int | None
    junit_error: str | None


def _relative(path: Path) -> str:
    """Repository-relative POSIX path, kept injectable for isolated tests."""
    return rel(path)


def enumerate_tests(tests: Path | None = None) -> tuple[Path, ...]:
    """The exact deterministic suite surface: every recursively named test file."""
    if tests is None:
        tests = TESTS
    return tuple(sorted((path.resolve() for path in tests.rglob("test_*.py")), key=_relative))


def _file_manifest(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        {"path": _relative(path), "sha256": sha_file(path), "bytes": path.stat().st_size}
        for path in sorted({path.resolve() for path in paths}, key=_relative)
    ]


def suite_manifest(tests: tuple[Path, ...] | None = None) -> dict[str, Any]:
    files = enumerate_tests() if tests is None else tests
    body = {
        "schema": "tavonel.v2.sfi3_suite_manifest.v1",
        "selection": "recursive sorted test_*.py; one fresh pytest process per file",
        "pytest_args": list(PYTEST_ARGS),
        "files": _file_manifest(files),
    }
    return {**body, "digest": canonical_sha(body)}


def tooling_manifest() -> dict[str, Any]:
    paths: set[Path] = {path.resolve() for path in TOOLING_FILES if path.is_file()}
    for directory in TOOLING_DIRS:
        if directory.is_dir():
            paths.update(path.resolve() for path in directory.rglob("*.py"))
    body = {
        "schema": "tavonel.v2.sfi3_tooling_manifest.v1",
        "scope": [
            *(_relative(path) for path in TOOLING_DIRS if path.exists()),
            *(_relative(path) for path in TOOLING_FILES if path.exists()),
        ],
        "files": _file_manifest(paths),
    }
    return {**body, "digest": canonical_sha(body)}


def parse_junit(path: Path) -> JUnitCounts:
    """Read pytest's built-in JUnit schema without trusting console prose."""
    root = ET.parse(path).getroot()  # noqa: S314 - locally produced test evidence
    tag = root.tag.rsplit("}", 1)[-1]
    if tag == "testsuite":
        suites = [root]
    elif tag == "testsuites":
        suites = [node for node in root if node.tag.rsplit("}", 1)[-1] == "testsuite"]
    else:
        raise ValueError(f"unexpected JUnit root {root.tag!r}")
    if not suites:
        raise ValueError("JUnit output contains no testsuite")

    def total(field: str) -> int:
        values = [node.attrib.get(field) for node in suites]
        if any(value is None for value in values):
            raise ValueError(f"JUnit testsuite omits {field!r}")
        return sum(int(value or "0") for value in values)

    return JUnitCounts(
        tests=total("tests"),
        skipped=total("skipped"),
        failures=total("failures"),
        errors=total("errors"),
    )


def _windows_peak_rss(process: subprocess.Popen[bytes]) -> int | None:
    """Best-effort peak working set from the retained Windows process handle."""
    if os.name != "nt" or not hasattr(process, "_handle"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            int(process._handle), ctypes.byref(counters), counters.cb
        )
        return int(counters.PeakWorkingSetSize) if ok else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def shard_command(test_file: Path, junit_file: Path) -> list[str]:
    return [
        str(VENV_PYTHON),
        "-m",
        "pytest",
        _relative(test_file),
        *PYTEST_ARGS,
        f"--junitxml={junit_file}",
    ]


def run_shard(test_file: Path, junit_file: Path, transcript: BinaryIO) -> ShardResult:
    command = shard_command(test_file, junit_file)
    transcript.write(
        (
            json.dumps(
                {"event": "shard_start", "test_file": _relative(test_file), "command": command}
            )
            + "\n"
        ).encode("utf-8")
    )
    transcript.flush()
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=str(ROOT),
        stdout=transcript,
        stderr=subprocess.STDOUT,
        env={**os.environ, REENTRY_FLAG: "1", "PYTHONHASHSEED": "0"},
    )
    exit_code = process.wait()
    peak_rss = _windows_peak_rss(process)
    counts = JUnitCounts(0, 0, 0, 0)
    junit_error: str | None = None
    junit_sha: str | None = None
    try:
        counts = parse_junit(junit_file)
        junit_sha = sha_file(junit_file)
    except (OSError, ET.ParseError, TypeError, ValueError) as error:
        junit_error = f"{type(error).__name__}: {error}"
    transcript.write(
        (
            json.dumps(
                {
                    "event": "shard_complete",
                    "test_file": _relative(test_file),
                    "exit_code": exit_code,
                    "counts": asdict(counts),
                    "peak_rss_bytes": peak_rss,
                    "junit_error": junit_error,
                }
            )
            + "\n"
        ).encode("utf-8")
    )
    transcript.flush()
    return ShardResult(
        test_file=_relative(test_file),
        command=command,
        exit_code=exit_code,
        junit_file=_relative(junit_file),
        junit_file_sha256=junit_sha,
        tests=counts.tests,
        skipped=counts.skipped,
        failures=counts.failures,
        errors=counts.errors,
        peak_rss_bytes=peak_rss,
        junit_error=junit_error,
    )


def _aggregate_exit(shards: list[ShardResult]) -> int:
    green = shards and all(row.exit_code == 0 and row.junit_error is None for row in shards)
    return 0 if green else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--receipt-only-on-pass",
        action="store_true",
        help="leave raw evidence but omit the immutable receipt when the suite is not green",
    )
    arguments = parser.parse_args(argv)
    if not VENV_PYTHON.is_file():
        parser.error(f"project interpreter does not exist: {VENV_PYTHON}")
    if Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        parser.error(
            "this evidence command must itself run under the project interpreter: "
            f"expected {VENV_PYTHON}, got {sys.executable}"
        )

    tests = enumerate_tests()
    if not tests:
        parser.error(f"no test_*.py files found below {TESTS}")
    suite = suite_manifest(tests)
    tooling = tooling_manifest()
    run_id = new_run_id(THIS_TOOL)
    run_dir = OUTPUTS / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    transcript_path = run_dir / "pytest-output.log"
    started_at = now()
    started_monotonic = time.monotonic()
    shards: list[ShardResult] = []

    with transcript_path.open("xb") as transcript:
        transcript.write(
            (
                json.dumps({"event": "suite_start", "run_id": run_id, "started_at": started_at})
                + "\n"
            ).encode("utf-8")
        )
        for index, test_file in enumerate(tests, start=1):
            junit_file = run_dir / f"junit-{index:04d}.xml"
            shards.append(run_shard(test_file, junit_file, transcript))
        completed_at = now()
        transcript.write(
            (
                json.dumps(
                    {
                        "event": "suite_complete",
                        "run_id": run_id,
                        "completed_at": completed_at,
                        "shard_count": len(shards),
                        "exit_code": _aggregate_exit(shards),
                    }
                )
                + "\n"
            ).encode("utf-8")
        )

    exit_code = _aggregate_exit(shards)
    completed = len(shards) == len(tests) and all(row.junit_error is None for row in shards)
    command = [
        _relative(Path(sys.executable)),
        _relative(THIS_TOOL),
        *(["--receipt-only-on-pass"] if arguments.receipt_only_on_pass else []),
    ]
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "command": command,
        "completed": completed,
        "exit_code": exit_code,
        "test_count": sum(row.tests for row in shards),
        "skip_count": sum(row.skipped for row in shards),
        "failure_count": sum(row.failures for row in shards),
        "error_count": sum(row.errors for row in shards),
        "test_file_count": len(tests),
        "shard_count": len(shards),
        "output_file": _relative(transcript_path),
        "output_file_sha256": sha_file(transcript_path),
        "suite_manifest_sha256": suite["digest"],
        "tooling_manifest_sha256": tooling["digest"],
        "suite_manifest": suite,
        "tooling_manifest": tooling,
        "started_at": started_at,
        "completed_at": completed_at,
        "wall_clock_seconds": round(time.monotonic() - started_monotonic, 6),
        "peak_rss_bytes": max((row.peak_rss_bytes or 0 for row in shards), default=0) or None,
        "shards": [asdict(row) for row in shards],
        "reentry_guard_set_in_every_shard": REENTRY_FLAG,
        "latest_pointer_is_evidence": False,
    }
    if not (arguments.receipt_only_on_pass and (not completed or exit_code != 0)):
        written = write_immutable(
            STEM,
            body,
            tool=THIS_TOOL,
            run_id=run_id,
            pointer=False,
        )
        print(json.dumps({**written, "completed": completed, "exit_code": exit_code}, indent=2))
    else:
        print(
            json.dumps(
                {
                    "receipt": None,
                    "completed": completed,
                    "exit_code": exit_code,
                    "output_file": _relative(transcript_path),
                    "output_file_sha256": sha_file(transcript_path),
                },
                indent=2,
            )
        )
    return exit_code if completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
