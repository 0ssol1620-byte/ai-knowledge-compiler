#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: remote_run_mineru_quality_retry.sh WORKER_INDEX INPUT_ROOT OUTPUT_ROOT" >&2
  exit 2
fi

worker_index="$1"
input_root="$2"
output_root="$3"
python_bin="/usr/bin/python3.11"
runner="/workspace/folynta/runner/mineru_stage2.py"
repository_revision="79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
artifact_sha256="1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84"

if ! [[ "$worker_index" =~ ^[0-9]{1,2}$ ]] || (( 10#$worker_index > 99 )); then
  echo "worker index must be between 0 and 99" >&2
  exit 2
fi
if [[ -e "$output_root" ]]; then
  echo "MinerU quality retry output already exists: $output_root" >&2
  exit 2
fi
if [[ ! -x "$python_bin" || ! -f "$runner" || ! -d "$input_root" ]]; then
  echo "MinerU quality retry runtime or input is missing" >&2
  exit 2
fi

mkdir -p "$output_root"
state="$output_root/worker-state.jsonl"
printf '{"event":"quality_retry_worker_started","worker_index":%s,"unix":%s}\n' \
  "$worker_index" "$(date -u +%s)" >>"$state"

for suite in parsebench omnidocbench olmocr-bench; do
  suite_root="$input_root/suites/$suite"
  if [[ ! -d "$suite_root" ]]; then
    continue
  fi
  manifest="$suite_root/shard-input-manifest.json"
  parent="$suite_root/parent-input-manifest.json"
  expected="$($python_bin -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["input_count"])' "$manifest")"
  if ! [[ "$expected" =~ ^[1-9][0-9]*$ ]]; then
    echo "invalid MinerU quality retry input count for $suite" >&2
    exit 2
  fi
  printf '{"event":"quality_retry_suite_started","suite":"%s","input_count":%s,"unix":%s}\n' \
    "$suite" "$expected" "$(date -u +%s)" >>"$state"
  "$python_bin" "$runner" \
    --input-dir "$suite_root" \
    --output-dir "$output_root/$suite" \
    --mineru-cli /usr/local/bin/mineru \
    --repository-revision "$repository_revision" \
    --artifact-manifest-sha256 "$artifact_sha256" \
    --backend vlm-engine \
    --method ocr \
    --repeats 1 \
    --limit 0 \
    --evidence-class public-core-shard \
    --expected-input-count "$expected" \
    --input-manifest "$manifest" \
    --parent-input-manifest "$parent" \
    --batch-size 1 \
    --timeout-seconds 1800 \
    >"$output_root/$suite.runner.log" 2>&1
  printf '{"event":"quality_retry_suite_completed","suite":"%s","unix":%s}\n' \
    "$suite" "$(date -u +%s)" >>"$state"
done

printf '{"event":"quality_retry_worker_completed","worker_index":%s,"unix":%s}\n' \
  "$worker_index" "$(date -u +%s)" >>"$state"
