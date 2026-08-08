#!/usr/bin/env bash
set -euo pipefail

WORKER_INDEX="${WORKER_INDEX:?WORKER_INDEX is required}"
POD_ID="${POD_ID:?POD_ID is required}"
STALL_THRESHOLD_SECONDS="${STALL_THRESHOLD_SECONDS:-900}"
CASE_TIMEOUT_SECONDS="${CASE_TIMEOUT_SECONDS:-900}"
BATCH_SIZE="${BATCH_SIZE:-1}"
SUITE="${SUITE:-parsebench}"
RESULT_ROOT="${RESULT_ROOT:-/workspace/folynta/results/full}"
RECEIPT_ROOT="${RECEIPT_ROOT:-/workspace/folynta/receipts}"
RUNNER_ROOT="${RUNNER_ROOT:-/workspace/folynta/runner}"

for value in "$STALL_THRESHOLD_SECONDS" "$CASE_TIMEOUT_SECONDS" "$BATCH_SIZE"; do
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "recovery numeric parameters must be positive integers" >&2
    exit 2
  fi
done
if [[ ! "$SUITE" =~ ^(parsebench|omnidocbench|olmocr-bench)$ ]]; then
  echo "SUITE is invalid" >&2
  exit 2
fi

worker_tag="$(printf '%02d' "$WORKER_INDEX")"
suite_root="$RESULT_ROOT/$SUITE"
receipt="$RECEIPT_ROOT/public-core-failover-worker-$worker_tag.json"
test -s "$receipt"
test -d "$suite_root/repeat-1"
test ! -e "$RESULT_ROOT/WORKER_COMPLETE"

read -r receipt_pod archive_sha output_count last_output_unix current_case < <(
  python3 - "$receipt" "$suite_root" <<'PY'
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
root = pathlib.Path(sys.argv[2])
outputs = sorted((root / "repeat-1").glob("*/vlm/*.md"))
last = max((item.stat().st_mtime for item in outputs), default=0.0)
completed = {item.parents[1].name for item in outputs}
pending = sorted(
    item.stem for item in (root / "frozen-input").iterdir() if item.stem not in completed
)
print(
    receipt["pod_id"],
    str(receipt["archive_sha256"]).removeprefix("sha256:"),
    len(outputs),
    f"{last:.6f}",
    pending[0] if pending else "none",
)
PY
)
if (( output_count < 1 )); then
  echo "worker has no completed output to establish a stall boundary" >&2
  exit 4
fi
if [[ "$receipt_pod" != "$POD_ID" ]]; then
  echo "recovery Pod identity differs from failover receipt" >&2
  exit 3
fi
if [[ ! "$archive_sha" =~ ^[0-9a-f]{64}$ ]]; then
  echo "recovery archive hash is invalid" >&2
  exit 3
fi

now="$(date +%s)"
stall_seconds="$(python3 - "$now" "$last_output_unix" <<'PY'
import sys
print(max(0, int(float(sys.argv[1]) - float(sys.argv[2]))))
PY
)"
if (( stall_seconds < STALL_THRESHOLD_SECONDS )); then
  echo "worker has not crossed the stall threshold" >&2
  exit 4
fi

mapfile -t roots < <(
  pgrep -f '^bash /workspace/folynta/runner/remote_run_public_core_failover.sh$' || true
)
if (( ${#roots[@]} != 1 )); then
  echo "expected exactly one public-core failover root process" >&2
  exit 5
fi
root_pid="${roots[0]}"
stage_command="$(pgrep -af '/workspace/folynta/runner/mineru_stage2.py' || true)"
if [[ "$stage_command" != *"--output-dir $suite_root"* ]]; then
  echo "stalled stage identity differs from parsebench worker" >&2
  exit 5
fi

mkdir -p "$RESULT_ROOT" "$suite_root"
python3 - "$RESULT_ROOT/stall-watchdog.jsonl" "$WORKER_INDEX" "$POD_ID" \
  "$root_pid" "$output_count" "$stall_seconds" "$current_case" "$SUITE" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

path = pathlib.Path(sys.argv[1])
event = {
    "event": "live_stall_detected_case_bounded_recovery",
    "worker_index": int(sys.argv[2]),
    "pod_id": sys.argv[3],
    "root_pid": int(sys.argv[4]),
    "completed_markdown_count": int(sys.argv[5]),
    "stall_seconds": int(sys.argv[6]),
    "first_pending_case_id": sys.argv[7],
    "suite": sys.argv[8],
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
}
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(event, sort_keys=True) + "\n")
PY
printf '%s\n' \
  "pod_id=$POD_ID" \
  "worker_index=$WORKER_INDEX" \
  "completed_markdown_count=$output_count" \
  "stall_seconds=$stall_seconds" \
  "first_pending_case_id=$current_case" \
  >"$suite_root/straggler-live-stall-recovery.txt"

python3 - "$root_pid" <<'PY'
import os
import signal
import subprocess
import sys
import time

root = int(sys.argv[1])
rows = subprocess.check_output(
    ["ps", "-eo", "pid=,ppid="], text=True
).splitlines()
children: dict[int, list[int]] = {}
for row in rows:
    pid, parent = (int(value) for value in row.split())
    children.setdefault(parent, []).append(pid)
ordered: list[int] = []
stack = [root]
while stack:
    pid = stack.pop()
    ordered.append(pid)
    stack.extend(children.get(pid, []))
for pid in reversed(ordered):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
time.sleep(5)
for pid in reversed(ordered):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        continue
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
PY

incident="$RECEIPT_ROOT/recovery-incidents/$(date -u +%Y%m%dT%H%M%SZ)-worker-$worker_tag"
mkdir -p "$incident"
for marker in \
  "$RESULT_ROOT/WORKER_FAILED" \
  "$RECEIPT_ROOT/PUBLIC_CORE_FAILOVER_FAILED"; do
  if [[ -e "$marker" ]]; then
    mv "$marker" "$incident/"
  fi
done

nohup env \
  WORKER_INDEX="$WORKER_INDEX" \
  POD_ID="$POD_ID" \
  EXPECTED_ARCHIVE_SHA256="$archive_sha" \
  FAILOVER_REASON=live_stall_recovery_case_bounded \
  CASE_TIMEOUT_SECONDS="$CASE_TIMEOUT_SECONDS" \
  BATCH_SIZE="$BATCH_SIZE" \
  bash "$RUNNER_ROOT/remote_run_public_core_failover.sh" \
  >"$RECEIPT_ROOT/public-core-failover.stdout.log" \
  2>"$RECEIPT_ROOT/public-core-failover.stderr.log" < /dev/null &
relaunched_pid="$!"

verified=""
for _ in $(seq 1 60); do
  command="$(pgrep -af '/workspace/folynta/runner/mineru_stage2.py' || true)"
  if [[ 
    "$command" == *"--output-dir $suite_root"* &&
    "$command" == *"--batch-size $BATCH_SIZE"* &&
    "$command" == *"--timeout-seconds $CASE_TIMEOUT_SECONDS"* &&
    "$command" == *"--resume-interrupted"*
  ]]; then
    verified="$command"
    break
  fi
  sleep 2
done
if [[ -z "$verified" ]]; then
  echo "case-bounded resume command was not observed" >&2
  exit 6
fi

python3 - "$RESULT_ROOT/stall-watchdog.jsonl" "$WORKER_INDEX" "$POD_ID" \
  "$relaunched_pid" "$output_count" "$stall_seconds" "$SUITE" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

path = pathlib.Path(sys.argv[1])
event = {
    "event": "live_stall_recovery_relaunched",
    "worker_index": int(sys.argv[2]),
    "pod_id": sys.argv[3],
    "relaunched_pid": int(sys.argv[4]),
    "preserved_markdown_count": int(sys.argv[5]),
    "detected_stall_seconds": int(sys.argv[6]),
    "suite": sys.argv[7],
    "batch_size": 1,
    "case_timeout_seconds": 900,
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
}
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(event, sort_keys=True) + "\n")
print(json.dumps(event, sort_keys=True))
PY
