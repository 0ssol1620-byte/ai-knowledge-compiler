"""Pinned headless print of one excerpt HTML to PDF (WO-LPC-3P).

The renderer runs inside a process container that kills every descendant when
it is closed: a Windows Job Object (child created suspended, assigned, then
resumed, so no grandchild can escape) or, on POSIX, its own session killed by
``killpg``. Cleanup is by the container, never by image name.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

from pypdf import PdfReader

_CREATE_SUSPENDED = 0x00000004
_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_EXTENDED_LIMIT_INFO = 9


def build_argv(
    exe: Path, html: Path, out: Path, profile: Path, timeout_ms: int = 60000
) -> list[str]:
    """The section 2.4 argv. Pure. JavaScript stays on (the caller refuses scripts)."""
    return [
        str(exe),
        "--no-pdf-header-footer",
        "--disable-gpu",
        "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--user-data-dir={profile}",
        f"--timeout={timeout_ms}",
        f"--print-to-pdf={out}",
        html.resolve().as_uri(),
    ]


class _Basic(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _Extended(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _Basic),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _win_run(argv: list[str], timeout_s: float) -> int:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    proc = None
    try:
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
            job, _JOB_EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        # Suspended create -> assign to the job -> resume: no grandchild can escape.
        proc = subprocess.Popen(argv, creationflags=_CREATE_SUSPENDED)
        handle = int(proc._handle)  # type: ignore[attr-defined]
        if not k32.AssignProcessToJobObject(job, handle):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        if ntdll.NtResumeProcess(handle) != 0:
            raise OSError("NtResumeProcess failed")
        return proc.wait(timeout=timeout_s)
    finally:
        k32.TerminateJobObject(job, 1)
        k32.CloseHandle(job)
        if proc is not None:
            if proc.poll() is None:
                proc.kill()  # not in the job (assign/resume failed): TerminateJobObject missed it
            proc.wait()


def _posix_run(argv: list[str], timeout_s: float) -> int:
    proc = subprocess.Popen(argv, start_new_session=True)
    try:
        return proc.wait(timeout=timeout_s)
    finally:
        if sys.platform != "win32":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def print_pdf(exe: Path, html: Path, out: Path, timeout_s: float = 90) -> int:
    """Print ``html`` to ``out`` and return the PDF page count.

    Raises RuntimeError on a non-zero exit or a missing output, and
    subprocess.TimeoutExpired on a hang; the process tree and the profile
    directory are gone in every case.
    """
    profile = Path(tempfile.mkdtemp(prefix="lpc-profile-"))
    try:
        out.unlink(missing_ok=True)  # a stale PDF must never pass as this run's output
        argv = build_argv(exe, html, out, profile)
        run = _win_run if sys.platform == "win32" else _posix_run
        code = run(argv, timeout_s)
        if code != 0:
            raise RuntimeError(f"renderer exited with {code}")
        if not out.is_file():
            raise RuntimeError("renderer produced no PDF")
        return len(PdfReader(out).pages)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
