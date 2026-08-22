#!/usr/bin/env bash
set -euo pipefail

WORKER_INDEX="${WORKER_INDEX:?WORKER_INDEX is required}"
POD_ID="${POD_ID:?POD_ID is required}"
STALL_THRESHOLD_SECONDS="${STALL_THRESHOLD_SECONDS:-900}"
POLL_SECONDS="${POLL_SECONDS:-60}"
RUNNER_ROOT="${RUNNER_ROOT:-/workspace/folynta/runner}"
RESULT_ROOT="${RESULT_ROOT:-/workspace/folynta/results/full}"

if [[ ! "$POLL_SECONDS" =~ ^[1-9][0-9]*$ ]] || (( POLL_SECONDS < 30 )); then
  echo "POLL_SECONDS must be an integer of at least 30" >&2
  exit 2
fi

while pgrep -f '^bash /workspace/folynta/runner/remote_run_public_core_failover.sh$' \
  >/dev/null; do
  stage_command="$(pgrep -af '/workspace/folynta/runner/mineru_stage2.py' || true)"
  output_dir="$(sed -n 's#.*--output-dir \([^ ]*\).*#\1#p' <<<"$stage_command")"
  if [[ -z "$output_dir" || "$output_dir" != "$RESULT_ROOT/"* ]]; then
    sleep "$POLL_SECONDS"
    continue
  fi
  suite="${output_dir#"$RESULT_ROOT/"}"
  suite="${suite%%/*}"
  if [[ ! "$suite" =~ ^(parsebench|omnidocbench|olmocr-bench)$ ]]; then
    sleep "$POLL_SECONDS"
    continue
  fi

  set +e
  env \
    WORKER_INDEX="$WORKER_INDEX" \
    POD_ID="$POD_ID" \
    SUITE="$suite" \
    STALL_THRESHOLD_SECONDS="$STALL_THRESHOLD_SECONDS" \
    CASE_TIMEOUT_SECONDS=900 \
    BATCH_SIZE=1 \
    bash "$RUNNER_ROOT/remote_recover_stalled_public_core.sh"
  status="$?"
  set -e
  if (( status == 0 )); then
    exit 0
  fi
  if (( status != 4 && status != 5 )); then
    echo "stall recovery guard stopped after unexpected status $status" >&2
    exit "$status"
  fi
  sleep "$POLL_SECONDS"
done

printf '{"event":"public_core_stall_guard_finished_without_recovery","unix":%s}\n' \
  "$(date -u +%s)" >>"$RESULT_ROOT/stall-watchdog.jsonl"
