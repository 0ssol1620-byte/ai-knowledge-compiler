#!/usr/bin/env python3
"""Fail-safe cleanup for the Stage-1 v8 host-retry campaign."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = ROOT / ".chatgpt2codex"
sys.path.insert(0, str(SCRATCH))

from runpod_curl_transport_v2 import RunPodCurlTransport  # noqa: E402
from runpod_registry_auth_v27 import read_labeled_secret  # noqa: E402

BASE_PATH = Path(__file__).with_name("run_stage1_v29_r2_v7_r2_verified.py")
_spec = importlib.util.spec_from_file_location("stage1_v7_watchdog", BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v7 module cannot be loaded by watchdog")
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--deadline-seconds", type=int, default=160 * 60)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        run_dir.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError("watchdog run directory escaped project root") from exc
    cleanup_path = run_dir / "cleanup-receipt.json"
    receipt_path = run_dir / "host-retry-watchdog-receipt.json"
    active_path = run_dir / "internal-active-state.json"
    deadline = time.monotonic() + args.deadline_seconds

    while time.monotonic() < deadline:
        cleanup = read_json(cleanup_path)
        if cleanup is not None:
            pod_ok = cleanup.get("pod_absence_verified") is True
            r2_ok = cleanup.get("r2_absence_verified") is True
            if pod_ok and r2_ok:
                receipt_path.write_text(
                    json.dumps(
                        {
                            "schema": "tavonel.stage1-host-retry-watchdog.v1",
                            "completed_at": now(),
                            "action": "NOOP_CONTROLLER_CLEANUP_VERIFIED",
                            "pod_absence_verified": True,
                            "r2_absence_verified": True,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return 0
        time.sleep(15)

    state = read_json(active_path) or {}
    errors: list[str] = []
    pod_absent = True
    r2_absent = True
    pod_id = str(state.get("active_pod_id") or "")
    label = str(state.get("active_credential_label") or "")
    if pod_id:
        if label not in {"Runpod_A", "Runpod_B"}:
            errors.append("pod:missing_credential_label")
            pod_absent = False
        else:
            try:
                key = read_labeled_secret(args.credential_file.resolve(), label)
                transport = RunPodCurlTransport(api_key=key)
                if not transport.verify_deleted(pod_id):
                    transport.delete_pod(pod_id)
                    for _ in range(30):
                        if transport.verify_deleted(pod_id):
                            break
                        time.sleep(2)
                pod_absent = transport.verify_deleted(pod_id)
            except Exception as exc:
                errors.append("pod:" + type(exc).__name__)
                pod_absent = False

    if state.get("r2_uploaded") is True and state.get("r2_deleted") is not True:
        bucket = str(state.get("bucket") or "")
        key = str(state.get("r2_key") or "")
        if not bucket or not key:
            errors.append("r2:missing_identity")
            r2_absent = False
        else:
            try:
                client, _ = base.make_r2_client(
                    args.credential_file.resolve(), args.env_file.resolve()
                )
                r2_absent = base.r2_delete_verify(client, bucket, key)
            except Exception as exc:
                errors.append("r2:" + type(exc).__name__)
                r2_absent = False

    receipt = {
        "schema": "tavonel.stage1-host-retry-watchdog.v1",
        "completed_at": now(),
        "action": "DEADLINE_CLEANUP",
        "pod_absence_verified": pod_absent,
        "r2_absence_verified": r2_absent,
        "cleanup_errors": errors,
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if pod_absent and r2_absent and not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
