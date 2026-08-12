#!/usr/bin/env bash
set -euo pipefail

stall_seconds="${1:-1200}"
poll_seconds="${2:-60}"
result_root="${3:-/workspace/folynta/results/full}"
evidence="$result_root/stall-watchdog.jsonl"

if ! [[ "$stall_seconds" =~ ^[0-9]+$ ]] || (( stall_seconds < 300 )); then
  echo "stall threshold must be an integer of at least 300 seconds" >&2
  exit 2
fi
if ! [[ "$poll_seconds" =~ ^[0-9]+$ ]] || (( poll_seconds < 10 )); then
  echo "poll interval must be an integer of at least 10 seconds" >&2
  exit 2
fi

runner_pattern='/workspace/folynta/runner/(run-mineru-|remote_run_operational_retry\.sh|remote_run_mineru_quality_retry\.sh)'
while pgrep -f "$runner_pattern" >/dev/null; do
  stage_command="$(pgrep -af '/workspace/folynta/runner/mineru_stage2.py' | head -n 1 || true)"
  if [[ -z "$stage_command" ]]; then
    sleep "$poll_seconds"
    continue
  fi
  output_dir="$(sed -n 's#.*--output-dir \([^ ]*\).*#\1#p' <<<"$stage_command")"
  if [[ -z "$output_dir" || "$output_dir" != "$result_root/"* ]]; then
    sleep "$poll_seconds"
    continue
  fi
  suite="${output_dir#"$result_root/"}"
  suite="${suite%%/*}"
  if [[ ! "$suite" =~ ^(parsebench|omnidocbench|olmocr-bench)$ ]]; then
    sleep "$poll_seconds"
    continue
  fi
  repeat_root="$result_root/$suite/repeat-1"
  # The repeat directory is created only after the first batch completes. With
  # `set -euo pipefail`, a missing directory would otherwise terminate the
  # watchdog during the exact startup window it is meant to supervise.
  completed="$(find "$repeat_root" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l || true)"
  newest="$(find "$repeat_root" -type f -printf '%T@\n' 2>/dev/null | sort -nr | head -n 1 | cut -d. -f1 || true)"
  now="$(date -u +%s)"
  if [[ "$completed" -gt 0 && -n "$newest" && $((now - newest)) -ge "$stall_seconds" ]]; then
    age="$((now - newest))"
    printf '{"event":"suite_stall_detected","suite":"%s","completed_directories":%s,"seconds_since_output":%s,"unix":%s}\n' \
      "$suite" "$completed" "$age" "$now" >>"$evidence"
    pkill -TERM -f 'mineru.cli.fast_api' || true
    sleep 180
  else
    sleep "$poll_seconds"
  fi
done

printf '{"event":"stall_watchdog_finished","unix":%s}\n' "$(date -u +%s)" >>"$evidence"
