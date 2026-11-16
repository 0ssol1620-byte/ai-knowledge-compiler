"""WO-LPC-3P: argv, process-tree cleanup on success / hang / failure, page count.

The renderer is a fake Python script; no browser is started.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from benchmark.local_public import sec_print

FAKE = r"""
import subprocess, sys, time
from pathlib import Path
out, mode, pidfile, profile, pages = sys.argv[1:6]
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path(pidfile).write_text(str(g.pid))
if mode == "hang":
    time.sleep(60)
def pdf(n):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{3+i} 0 R" for i in range(n))
            + f"] /Count {n} >>"]
    objs += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>"] * n
    body = b"%PDF-1.4\n"; offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(body)); body += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(body)
    body += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for o in offs: body += f"{o:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return body
Path(out).write_bytes(pdf(int(pages)))
sys.exit(3 if mode == "fail" else 0)
"""


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "fake_renderer.py"
    script.write_text(FAKE, encoding="utf-8")
    state: dict = {"mode": "ok", "pages": 1, "profile": None}
    pidfile = tmp_path / "grandchild.pid"

    def argv(exe, html, out, profile, timeout_ms=60000):
        state["profile"] = profile
        return [
            sys.executable,
            str(script),
            str(out),
            state["mode"],
            str(pidfile),
            str(profile),
            str(state["pages"]),
        ]

    monkeypatch.setattr(sec_print, "build_argv", argv)
    yield state, pidfile
    if pidfile.exists():  # never leave what the test started
        pid = int(pidfile.read_text())
        if _alive(pid):
            cmd = (
                ["taskkill", "/PID", str(pid), "/F"]
                if sys.platform == "win32"
                else ["kill", "-9", str(pid)]
            )
            subprocess.run(cmd, capture_output=True)


def _gone(pid: int) -> bool:
    for _ in range(50):
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_argv(tmp_path):
    argv = sec_print.build_argv(
        Path("r.exe"), tmp_path / "a.html", tmp_path / "o.pdf", tmp_path / "prof"
    )
    assert "--host-resolver-rules=MAP * ~NOTFOUND" in argv
    assert f"--user-data-dir={tmp_path / 'prof'}" in argv
    assert not any("scriptEnabled" in a for a in argv)
    assert argv[-1].startswith("file:///")


def test_success_returns_pages_and_kills_grandchild(fake, tmp_path):
    state, pidfile = fake
    state["pages"] = 2
    assert sec_print.print_pdf(Path("x"), tmp_path / "a.html", tmp_path / "o.pdf") == 2
    assert _gone(int(pidfile.read_text()))
    assert not state["profile"].exists()


def test_hang_times_out_and_kills_grandchild(fake, tmp_path):
    state, pidfile = fake
    state["mode"] = "hang"
    with pytest.raises(subprocess.TimeoutExpired):
        sec_print.print_pdf(Path("x"), tmp_path / "a.html", tmp_path / "o.pdf", timeout_s=3)
    assert _gone(int(pidfile.read_text()))
    assert not state["profile"].exists()


def test_failure_kills_grandchild(fake, tmp_path):
    state, pidfile = fake
    state["mode"] = "fail"
    with pytest.raises(RuntimeError, match="exited with 3"):
        sec_print.print_pdf(Path("x"), tmp_path / "a.html", tmp_path / "o.pdf")
    assert _gone(int(pidfile.read_text()))
    assert not state["profile"].exists()
