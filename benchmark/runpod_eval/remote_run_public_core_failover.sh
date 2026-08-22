#!/usr/bin/env bash
set -euo pipefail

WORKER_INDEX="${WORKER_INDEX:?WORKER_INDEX is required}"
POD_ID="${POD_ID:?POD_ID is required}"
EXPECTED_ARCHIVE_SHA256="${EXPECTED_ARCHIVE_SHA256:?EXPECTED_ARCHIVE_SHA256 is required}"
ARCHIVE_PATH="${ARCHIVE_PATH:-/workspace/folynta/input-upload/worker-$(printf '%02d' "$WORKER_INDEX").tar}"
INPUT_ROOT="${INPUT_ROOT:-/workspace/folynta/public-core-input}"
RUNNER_ROOT="${RUNNER_ROOT:-/workspace/folynta/runner}"
RESULT_ROOT="${RESULT_ROOT:-/workspace/folynta/results/full}"
RECEIPT_ROOT="${RECEIPT_ROOT:-/workspace/folynta/receipts}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-3600}"
FAILOVER_REASON="${FAILOVER_REASON:-original_host_gpu_capacity_unavailable}"

mkdir -p "$INPUT_ROOT" "$RESULT_ROOT" "$RECEIPT_ROOT"
STATE="$RECEIPT_ROOT/public-core-failover-worker-$(printf '%02d' "$WORKER_INDEX").jsonl"

record_state() {
  local event="$1"
  local detail="${2:-}"
  python3 - "$event" "$detail" "$WORKER_INDEX" "$POD_ID" >>"$STATE" <<'PY'
import json
import sys
from datetime import datetime, timezone

print(json.dumps({
    "event": sys.argv[1],
    "detail": sys.argv[2],
    "worker_index": int(sys.argv[3]),
    "pod_id": sys.argv[4],
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
}, sort_keys=True))
PY
}

on_error() {
  local code=$?
  record_state failover_failed "exit-$code"
  touch "$RECEIPT_ROOT/PUBLIC_CORE_FAILOVER_FAILED"
  exit "$code"
}
trap on_error ERR

record_state wait_started
deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
while true; do
  if [[ -f "$RECEIPT_ROOT/BOOTSTRAP_COMPLETE" && -f "$ARCHIVE_PATH" ]]; then
    break
  fi
  if (( SECONDS >= deadline )); then
    record_state readiness_timeout
    exit 2
  fi
  sleep 10
done
record_state dependencies_ready

actual_sha256="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
if [[ "$actual_sha256" != "$EXPECTED_ARCHIVE_SHA256" ]]; then
  record_state archive_hash_mismatch "$actual_sha256"
  exit 3
fi
record_state archive_hash_verified "$actual_sha256"

rm -rf "$INPUT_ROOT/worker-$(printf '%02d' "$WORKER_INDEX")"
tar -xf "$ARCHIVE_PATH" -C "$INPUT_ROOT"
worker_root="$INPUT_ROOT/worker-$(printf '%02d' "$WORKER_INDEX")"
test -d "$worker_root/suites"
record_state archive_extracted "$worker_root"

python3 - "$RECEIPT_ROOT" "$WORKER_INDEX" "$POD_ID" "$actual_sha256" "$FAILOVER_REASON" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

receipt_root = pathlib.Path(sys.argv[1])
runtime_path = receipt_root / "runtime-identity.json"
runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
value = {
    "schema": "folynta.public-core-failover.v1",
    "worker_index": int(sys.argv[2]),
    "pod_id": sys.argv[3],
    "archive_sha256": f"sha256:{sys.argv[4]}",
    "reason": sys.argv[5],
    "gpu": runtime.get("gpu"),
    "mineru_revision": runtime.get("mineru_revision"),
    "model_revision": runtime.get("model_revision"),
    "started_at_utc": datetime.now(timezone.utc).isoformat(),
}
(receipt_root / f"public-core-failover-worker-{int(sys.argv[2]):02d}.json").write_text(
    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)
PY

record_state inference_started
env \
  WORKER_ROOT="$worker_root" \
  RUNNER_ROOT="$RUNNER_ROOT" \
  RESULT_ROOT="$RESULT_ROOT" \
  bash "$RUNNER_ROOT/run-mineru-3.4.4-public-core-worker.sh"
record_state inference_completed
touch "$RECEIPT_ROOT/PUBLIC_CORE_FAILOVER_COMPLETE"
