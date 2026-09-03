#!/usr/bin/env python3
"""Finish a Stage-1 run whose controller died, using the persisted control token.

A Pod outlives its controller. That is not a rare accident here -- it happened
twice on 2026-08-18, once when a session was torn down mid-run and once when the
controller had to be stopped deliberately, because `base.curl_get` wrote every
download to a mangled path and the 200-document retrieval was certain to fail
*after* the GPU work was already paid for.

The Pod keeps working either way: the same-Pod driver is a child process on the
Pod, not on this machine. What is lost is the control token, and without it port
8002 answers 401 to everyone. `v16` persists it to `<run-dir>/reattach-secret.json`
precisely so that loss is recoverable, and this script is the thing that spends it.

It deliberately reuses `v10.fetch_and_validate_results` rather than fetching the
archive itself. Every check that makes the output evidence -- archive size and
sha256 against the Pod's own `done` status, the archive-shape validation, the
`ground_truth_mounted is False` and `input_count == 200` contracts, the assembly
id match, the retrieval receipt -- lives in that function. A second retrieval
path that re-implemented them would be a second place for them to drift, and the
whole point of the run is that its output can be trusted.

Not a campaign driver: it creates no Pod, draws no host, and starts no run. It
attaches to one Pod that already exists and finishes it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

V10_PATH = Path(__file__).with_name("run_stage1_v29_r2_v10_runtime_ready.py")
_spec = importlib.util.spec_from_file_location("stage1_v10_for_harvest", V10_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v10 module cannot be loaded")
v10 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v10
_spec.loader.exec_module(v10)

base = v10.base

POLL_SECONDS = 20
# The campaign's own bound is 105 minutes for the whole run. This attaches to a
# run already in flight, so it waits out the remainder, not the whole thing.
MAX_WAIT_SECONDS = 105 * 60


def read_reattach_secret(run_dir: Path) -> str:
    path = run_dir / "reattach-secret.json"
    if not path.is_file():
        raise RuntimeError(
            f"{path} does not exist. Runs before the v14/v16 slot-collision fix "
            "never wrote it, and their Pods cannot be driven -- only "
            "control_token_sha256 survives, which does not open port 8002."
        )
    token = str(json.loads(path.read_text(encoding="utf-8"))["control_token"])
    if not token:
        raise RuntimeError(f"{path} holds no control token")
    return token


def wait_for_done(pod_id: str, token: str, run_dir: Path) -> dict[str, Any]:
    """Poll the Pod until its driver reports done, mirroring status as it moves."""
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    last_state = ""
    while time.monotonic() < deadline:
        error = base.proxy_json(pod_id, "stage1-error.json", token, port=8002)
        if error is not None:
            v10.harvest_failure_evidence(pod_id, token, run_dir)
            raise RuntimeError(
                f"Stage-1 same-Pod driver failed: {error.get('error_type', 'unknown')}: "
                f"{str(error.get('message', ''))[:500]}"
            )
        status = base.proxy_json(pod_id, "stage1-status.json", token, port=8002)
        if status is not None:
            state = str(status.get("state", ""))
            if state and state != last_state:
                last_state = state
                print(f"[harvest] state={state}", flush=True)
                (run_dir / "last-stage1-status.json").write_text(
                    json.dumps(status, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if state == "done" and status.get("passed") is True:
                return status
        time.sleep(POLL_SECONDS)
    raise TimeoutError("reattached Stage-1 Pod did not reach done within the bound")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=base.ROOT / ".env")
    parser.add_argument(
        "--keep-pod",
        action="store_true",
        help="leave the Pod running after retrieval (it keeps billing)",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    state = base.read_object(run_dir / "internal-active-state.json")
    pod_id = str(state["active_pod_id"])
    label = str(state["active_credential_label"])
    token = read_reattach_secret(run_dir)
    ready = base.read_object(base.READY)
    assembly_id = str(ready["assembly_id"])
    run_id = run_dir.name.removeprefix("run-")

    key = v10.read_labeled_secret(args.credential_file.resolve(), label)
    transport = v10.RunPodCurlTransport(api_key=key)
    if transport.verify_deleted(pod_id):
        raise RuntimeError(f"Pod {pod_id} no longer exists; nothing to harvest")
    print(f"[harvest] attached to {pod_id} on {label}", flush=True)

    done = wait_for_done(pod_id, token, run_dir)

    # The bundle carries the 200 inputs. It is deleted as soon as the Pod has
    # them, so retrieval must not be what keeps a copy of customer-shaped data
    # sitting in object storage.
    r2_deleted = bool(state.get("r2_deleted"))
    if state.get("r2_uploaded") and not r2_deleted:
        client, _bucket = base.make_r2_client(
            args.credential_file.resolve(), args.env_file.resolve()
        )
        r2_deleted = base.r2_delete_verify(client, str(state["bucket"]), str(state["r2_key"]))
        v10.write_internal_active_state(
            run_dir / "internal-active-state.json",
            bucket=str(state["bucket"]),
            r2_key=str(state["r2_key"]),
            r2_uploaded=True,
            r2_deleted=r2_deleted,
            active_pod_id=pod_id,
            active_credential_label=label,
        )
        if not r2_deleted:
            raise RuntimeError("temporary Stage-1 R2 object deletion was not verified")

    v10.fetch_and_validate_results(
        pod_id=pod_id,
        control_token=token,
        run_dir=run_dir,
        done_payload=done,
        assembly_id=assembly_id,
        r2_deleted=r2_deleted,
        run_id=run_id,
    )
    print(f"[harvest] results validated into {run_dir / 'results'}", flush=True)

    if args.keep_pod:
        print(f"[harvest] Pod {pod_id} left running by request; it is still billing", flush=True)
        return 0
    transport.delete_pod(pod_id)
    for _ in range(24):
        time.sleep(5)
        if transport.verify_deleted(pod_id):
            print(f"[harvest] Pod {pod_id} deletion verified", flush=True)
            (run_dir / "reattach-secret.json").unlink(missing_ok=True)
            return 0
    raise RuntimeError(f"Pod {pod_id} deletion could not be verified -- it is still billing")


if __name__ == "__main__":
    raise SystemExit(main())
