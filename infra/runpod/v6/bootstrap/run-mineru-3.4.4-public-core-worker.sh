#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.11}"
WORKER_ROOT="${WORKER_ROOT:?WORKER_ROOT is required}"
RUNNER_ROOT="${RUNNER_ROOT:-/workspace/folynta/runner}"
RESULT_ROOT="${RESULT_ROOT:-/workspace/folynta/results/full}"
REPOSITORY_REVISION="79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
ARTIFACT_MANIFEST_SHA256="1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84"
CASE_TIMEOUT_SECONDS="${CASE_TIMEOUT_SECONDS:-900}"
BATCH_SIZE="${BATCH_SIZE:-1}"

if [[ ! "$CASE_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "CASE_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi
if [[ ! "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  echo "BATCH_SIZE must be a positive integer" >&2
  exit 2
fi

export MINERU_API_MAX_CONCURRENT_REQUESTS=1
export MINERU_MODEL_SOURCE=local
export MINERU_TOOLS_CONFIG_JSON=/root/mineru.json

mkdir -p "$RESULT_ROOT"
STATE="$RESULT_ROOT/worker-state.jsonl"

record_state() {
  local event="$1"
  local suite="${2:-}"
  "$PYTHON_BIN" - "$event" "$suite" >> "$STATE" <<'PY'
import json
import sys
import time
print(json.dumps({"event": sys.argv[1], "suite": sys.argv[2], "unix": time.time()}, sort_keys=True))
PY
}

on_error() {
  local code=$?
  record_state worker_failed "exit-$code"
  touch "$RESULT_ROOT/WORKER_FAILED"
  exit "$code"
}
trap on_error ERR

record_state worker_started
for suite in parsebench omnidocbench olmocr-bench; do
  suite_root="$WORKER_ROOT/suites/$suite"
  shard_manifest="$suite_root/shard-input-manifest.json"
  parent_manifest="$suite_root/parent-input-manifest.json"
  expected_count="$($PYTHON_BIN - "$shard_manifest" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["input_count"])
PY
  )"
  if [[ -s "$RESULT_ROOT/$suite/run-summary.json" ]]; then
    record_state suite_reused_complete "$suite"
    continue
  fi
  resume_args=()
  if [[ -d "$RESULT_ROOT/$suite" ]]; then
    resume_args+=(--resume-interrupted)
    record_state suite_resume_started "$suite"
  fi
  record_state suite_started "$suite"
  "$PYTHON_BIN" "$RUNNER_ROOT/mineru_stage2.py" \
    --input-dir "$suite_root" \
    --output-dir "$RESULT_ROOT/$suite" \
    --mineru-cli /usr/local/bin/mineru \
    --repository-revision "$REPOSITORY_REVISION" \
    --artifact-manifest-sha256 "$ARTIFACT_MANIFEST_SHA256" \
    --backend vlm-engine \
    --method ocr \
    --repeats 1 \
    --limit 0 \
    --evidence-class public-core-shard \
    --expected-input-count "$expected_count" \
    --input-manifest "$shard_manifest" \
    --parent-input-manifest "$parent_manifest" \
    --batch-size "$BATCH_SIZE" \
    --timeout-seconds "$CASE_TIMEOUT_SECONDS" \
    "${resume_args[@]}"
  record_state suite_completed "$suite"
done

record_state worker_completed
touch "$RESULT_ROOT/WORKER_COMPLETE"
