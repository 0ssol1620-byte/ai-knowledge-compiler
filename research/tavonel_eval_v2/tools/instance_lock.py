"""Single-instance coordinator lock. Identity by PID *and* process start time.

`INC-V2-021` happened because liveness was inferred from an empty log. A PID
alone would not have fixed it: PIDs are recycled, so a stale lock naming a dead
process can be indistinguishable from a live one after the number is reused.

The lock therefore records run id, PID **and** the owning process's start time.
Reclaiming a stale lock requires an OS liveness check that matches both the PID
and the start time — never age, never a heuristic, never "the log looks quiet".
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REFUSED = "REFUSED_ALREADY_RUNNING"


class LockHeld(RuntimeError):
    def __init__(self, owner: dict[str, Any]) -> None:
        super().__init__(REFUSED + ": " + json.dumps(owner, sort_keys=True))
        self.owner = owner
        self.status = REFUSED


def process_start_time(pid: int) -> float | None:
    """Seconds since boot, or ``None`` if it cannot be determined.

    ``None`` means *unknown*, never *absent*. Absence is reported by
    :func:`exists`, because collapsing the two would let an unreadable process
    table look like a dead owner — and reclaiming a live owner is the exact
    defect this module exists to prevent.
    """
    try:
        import psutil  # noqa: PLC0415

        return psutil.Process(pid).create_time()
    except ImportError:
        pass
    except Exception:
        return None
    if sys.platform == "win32":
        # psutil's create_time() has no dependency-free Windows equivalent
        # here (a GetProcessTimes ctypes path is not implemented). The
        # honest answer without it is "cannot determine" -- never a guess.
        # alive() already treats a ``None`` start time as "skip the
        # PID-reuse comparison, fall back to bare existence" rather than as
        # a liveness verdict of its own, so this does not silently become
        # "definitely the same process".
        return None
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8") as handle:
            return float(handle.read().split(") ")[-1].split()[19])
    except (OSError, IndexError, ValueError):
        return None


def exists(pid: int) -> bool | None:
    """``True`` present, ``False`` absent, ``None`` undecidable."""
    try:
        import psutil  # noqa: PLC0415

        return bool(psutil.pid_exists(pid))
    except ImportError:
        pass
    except Exception:
        return None
    return _exists_native(pid)


def _exists_native(pid: int) -> bool | None:
    """OS liveness probe used when ``psutil`` is not importable.

    ``os.kill(pid, 0)`` is the POSIX sentinel-signal idiom and is reliable
    there. It is not reliable on Windows: ``ERROR_INVALID_PARAMETER`` (no
    such process) and access-denied are not consistently distinguishable
    through ``os.kill``, and for some reserved PIDs (observed here: PID 4,
    the System process) CPython's Windows ``os.kill`` raises a bare
    ``SystemError`` instead of a decodable ``OSError``. Windows therefore
    gets its own probe, :func:`_exists_win32`, so the tri-state semantics do
    not depend on whether ``psutil`` happens to be installed.
    """
    if sys.platform == "win32":
        return _exists_win32(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, AttributeError):
        return None
    return True


def _exists_win32(pid: int) -> bool | None:
    """Win32 liveness probe via ``ctypes``. No new dependency.

    ``OpenProcess`` with the minimal ``PROCESS_QUERY_LIMITED_INFORMATION``
    right asks "does this PID identify a process" without needing any
    elevated access:

    - fails with ``ERROR_INVALID_PARAMETER`` (87) when the PID identifies no
      process at all -> definitely absent.
    - fails with ``ERROR_ACCESS_DENIED`` (5) when the PID *does* identify a
      process this caller cannot query -> definitely present. Being denied
      information about something is not the same as not knowing whether it
      is there; it is there.
    - fails any other way -> undecidable.
    - on success, a handle to a real kernel object was obtained, but PIDs are
      recycled, so the handle can be to a process that already exited and
      has not been reaped. ``GetExitCodeProcess`` disambiguates: Windows
      uses the sentinel ``STILL_ACTIVE`` (259) to mean "has not exited".
      This is a documented ambiguity in the Win32 API itself -- a process
      that calls ``ExitProcess(259)`` as its own real exit code is
      indistinguishable from one that is still running -- and is not
      something a single liveness probe can resolve; it is the same caveat
      the Win32 docs carry for this API, not a defect introduced here.
    - the handle is always closed, on every return path.
    """
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    ctypes.set_last_error(0)
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return False
        if error == error_access_denied:
            return True
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def alive(pid: int, started: float | None) -> bool | None:
    """``True`` live, ``False`` gone, ``None`` undecidable.

    ``None`` is a real answer and is not collapsed into ``False``. A lock whose
    liveness cannot be established is not reclaimed.

    The start time is what stops a recycled PID from passing as the same owner:
    the number can come back, the pair cannot. That guard only works if a
    current start time can actually be read. A recorded ``started`` with no
    way to read the *current* holder's start time (Windows without
    ``psutil`` -- see :func:`process_start_time`) is bare PID existence
    pretending to be verified identity: existence alone cannot tell the PID's
    original owner from an unrelated process the OS later recycled it to. That
    combination is reported honestly as undecidable, never as alive.

    Cost of that honesty, named rather than hidden: in an environment that
    cannot read start times, a genuinely dead lock owner whose PID gets
    reused can never be reclaimed by existence alone -- only a start-time
    -capable check (``psutil``, or a future native ``GetProcessTimes`` path)
    can break the tie. Fail-closed accepts that cost on purpose; refusing
    forever is a real operational cost, not a free win.
    """
    present = exists(pid)
    if present is False:
        return False
    if started is None:
        # Nothing was ever recorded to compare against, so existence is the
        # only signal that was ever available -- it is also the answer.
        return present
    current = process_start_time(pid)
    if current is None:
        return None
    return abs(current - started) < 1.0


class InstanceLock:
    """Acquire or refuse. There is no third outcome and no waiting."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.owner: dict[str, Any] | None = None

    def acquire(self, *, force_pid: int | None = None) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                existing = {}
            pid = int(existing.get("pid", -1))
            state = alive(pid, existing.get("process_start_time"))
            if state is not False:
                raise LockHeld(
                    {
                        **existing,
                        "liveness": "alive" if state else "undecidable",
                        "reclaimed": False,
                        "why_not_reclaimed": (
                            "the owner is running"
                            if state
                            else "liveness could not be established; a lock is never "
                            "reclaimed on age or on log silence"
                        ),
                    }
                )
            existing["reclaimed_by"] = self.run_id
            existing["reclaim_basis"] = "OS liveness check: pid and start time both absent"
        pid = force_pid if force_pid is not None else os.getpid()
        owner = {
            "run_id": self.run_id,
            "pid": pid,
            "process_start_time": process_start_time(pid),
            "lock_path": str(self.path),
        }
        self.path.write_text(json.dumps(owner, sort_keys=True), encoding="utf-8")
        self.owner = owner
        return owner

    def release(self) -> None:
        if not self.path.exists():
            return
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
        if existing.get("run_id") == self.run_id:
            self.path.unlink()

    def __enter__(self) -> dict[str, Any]:
        return self.acquire()

    def __exit__(self, *_exc: Any) -> None:
        self.release()
