#!/usr/bin/env python3
"""Run hard-200 with v15's pipeline, keeping a surviving Pod reachable.

Pod `bea8tq6hf3sf6t` reached the one state this campaign has been chasing since
2026-08-17: image pulled, container started, both control ports answering. Then
the controlling process died with the session, and the Pod became unusable --
not because anything failed on it, but because its control token existed only in
that process's memory. It was deleted while healthy.

The controller has now died twice in one working day: once to `WinError 1455`
inside `verify_deleted`, once to session teardown. Treating that as rare is not
supported by the evidence.

So the token is written next to the run's other state, and the Pod id with it.
Three properties make that acceptable rather than a secret leak:

  * `.chatgpt2codex/` is git-ignored (`.gitignore:38`), so it cannot reach a
    commit, which is what the handoff's rule protects.
  * It is never printed, never passed to a subprocess argument, and never
    written into a receipt -- receipts keep `control_token_sha256`, as before.
  * It is deleted when the campaign deletes the Pod, so it outlives nothing.

What this file deliberately does NOT do is reattach automatically. Resuming a
half-finished Stage-1 run is a decision about evidence -- which documents were
processed, whether the archive is still coherent -- and a wrapper that guessed
at that would be worse than a human reading the file and deciding.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

V15_PATH = Path(__file__).with_name("run_stage1_v29_r2_v15_proxy_readiness.py")
_spec = importlib.util.spec_from_file_location("stage1_v15_for_v16", V15_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v15 module cannot be loaded")
v15 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v15
_spec.loader.exec_module(v15)

v14, v13, v12, v11, v10 = v15.v14, v15.v13, v15.v12, v15.v11, v15.v10

REATTACH_FILENAME = "reattach-secret.json"
# Wraps v14, not v13. Both v14 and v16 install into the *same* v13 slot, and
# v14.main() runs after v16.main() in the descending call chain, so binding to
# v13 here meant v14 silently overwrote this wrapper and no control token was
# ever written. Wrapping the function v14 installs keeps both in the path.
_ORIGINAL_BUILD_PAYLOAD = v14.build_payload_on_community_hosts


def write_reattach_secret(run_dir: Path, pod_name: str, control_token: str) -> Path:
    """Persist what a human would need to drive a Pod the controller lost."""
    path = Path(run_dir) / REATTACH_FILENAME
    path.write_text(
        json.dumps(
            {
                "schema": "tavonel.stage1-reattach-secret.v1",
                "pod_name": pod_name,
                "control_token": control_token,
                "note": (
                    "Secret. Git-ignored, never in a receipt, deleted with the Pod. "
                    "Present only so a Pod that outlived its controller is not thrown away."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with contextlib.suppress(OSError):  # Windows ignores POSIX mode bits
        path.chmod(0o600)
    return path


def build_payload_recording_the_token(**kwargs: Any) -> dict[str, Any]:
    payload = _ORIGINAL_BUILD_PAYLOAD(**kwargs)
    run_dir = getattr(v10, "RUN_DIR", None) or _run_dir_from_active_state()
    if run_dir is not None:
        write_reattach_secret(Path(run_dir), str(kwargs["name"]), str(kwargs["control_token"]))
    return payload


def _run_dir_from_active_state() -> Path | None:
    """v10 does not export its run directory, so find the one it is writing."""
    root = v10.base.SCRATCH / "formal-runtime-v29" / "stage1"
    if not root.is_dir():
        return None
    active = [p for p in root.glob("run-*/internal-active-state.json")]
    if not active:
        return None
    return max(active, key=lambda p: p.stat().st_mtime).parent


def main() -> int:
    v14.build_payload_on_community_hosts = build_payload_recording_the_token
    print(
        f"[v16] control token written to <run-dir>/{REATTACH_FILENAME} so a Pod "
        "that outlives its controller can still be reached; git-ignored, never "
        "in a receipt, deleted with the Pod",
        flush=True,
    )
    return int(v15.main())


if __name__ == "__main__":
    raise SystemExit(main())
