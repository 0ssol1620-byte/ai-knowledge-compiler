#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: remote_run_dedicated_recovery.sh MODEL INPUT_ROOT OUTPUT_ROOT" >&2
  exit 2
fi

model="$1"
input_root="$2"
output_root="$3"
paddle_revision="66317acc4c9fc17bd154591ce650735cd2855f3e"
paddle_artifact="sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
deepseek_revision="aaa02f3811945a91062062994c5c4a3f4c0af2b0"
deepseek_artifact="sha256:77137d41428555c636b04ec5a1617e72c7e3e98afd81502b5c8659f6430421bc"

case "$model" in
  paddleocr-vl-1.6)
    python_bin="/workspace/folynta/venvs/paddle-fastdeploy-r1/bin/python"
    runner="/workspace/folynta/runner/paddleocr_vl_stage2.py"
    runtime_identity="/workspace/folynta/bootstrap/paddle-r1/runtime-identity.json"
    ;;
  deepseek-ocr-2)
    python_bin="/workspace/folynta/venvs/deepseek-ocr2-r1/bin/python"
    runner="/workspace/folynta/runner/deepseek_ocr2_stage2.py"
    runtime_identity="/workspace/folynta/bootstrap/deepseek-r1/runtime-identity.json"
    ;;
  *)
    echo "unsupported dedicated recovery model: $model" >&2
    exit 2
    ;;
esac

test -x "$python_bin"
test -f "$runner"
test -f "$runtime_identity"
test -d "$input_root"
test ! -e "$output_root"
mkdir -p "$output_root"
state="$output_root/campaign-state.jsonl"
printf '{"event":"dedicated_recovery_started","model":"%s","unix":%s}\n' \
  "$model" "$(date -u +%s)" >>"$state"

for worker_index in 0 1 2 3; do
  worker_name="worker-0$worker_index"
  worker_input="$input_root/$worker_name"
  [[ -d "$worker_input" ]] || continue
  worker_output="$output_root/$worker_name"
  mkdir -p "$worker_output"
  printf '{"event":"logical_worker_started","model":"%s","worker_index":%s,"unix":%s}\n' \
    "$model" "$worker_index" "$(date -u +%s)" >>"$state"
  for suite in parsebench omnidocbench olmocr-bench; do
    suite_root="$worker_input/suites/$suite"
    [[ -d "$suite_root" ]] || continue
    manifest="$suite_root/shard-input-manifest.json"
    parent="$suite_root/parent-input-manifest.json"
    expected="$($python_bin -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["input_count"])' "$manifest")"
    if ! [[ "$expected" =~ ^[1-9][0-9]*$ ]]; then
      echo "invalid dedicated recovery count: $worker_name/$suite" >&2
      exit 2
    fi
    printf '{"event":"suite_started","model":"%s","worker_index":%s,"suite":"%s","input_count":%s,"unix":%s}\n' \
      "$model" "$worker_index" "$suite" "$expected" "$(date -u +%s)" >>"$state"
    if [[ "$model" == "paddleocr-vl-1.6" ]]; then
      "$python_bin" "$runner" \
        --input-dir "$suite_root" \
        --output-dir "$worker_output/$suite" \
        --model-revision "$paddle_revision" \
        --artifact-manifest-sha256 "$paddle_artifact" \
        --vl-backend fastdeploy-server \
        --vl-server-url http://127.0.0.1:8118/v1 \
        --vl-max-concurrency 8 \
        --repeats 1 \
        --limit 0 \
        --evidence-class public-core-shard \
        --expected-input-count "$expected" \
        --input-manifest "$manifest" \
        --parent-input-manifest "$parent" \
        --case-timeout-seconds 600 \
        >"$worker_output/$suite.runner.stdout.log" \
        2>"$worker_output/$suite.runner.stderr.log"
    else
      "$python_bin" "$runner" \
        --input-dir "$suite_root" \
        --output-dir "$worker_output/$suite" \
        --model-path /workspace/folynta/cache/deepseek-ocr2-r1/model \
        --model-revision "$deepseek_revision" \
        --artifact-manifest-sha256 "$deepseek_artifact" \
        --repeats 1 \
        --limit 0 \
        --evidence-class public-core-shard \
        --expected-input-count "$expected" \
        --input-manifest "$manifest" \
        --parent-input-manifest "$parent" \
        --case-timeout-seconds 900 \
        >"$worker_output/$suite.runner.stdout.log" \
        2>"$worker_output/$suite.runner.stderr.log"
    fi
    printf '{"event":"suite_completed","model":"%s","worker_index":%s,"suite":"%s","unix":%s}\n' \
      "$model" "$worker_index" "$suite" "$(date -u +%s)" >>"$state"
  done
  printf '{"event":"logical_worker_completed","model":"%s","worker_index":%s,"unix":%s}\n' \
    "$model" "$worker_index" "$(date -u +%s)" >>"$state"
done

printf '{"event":"dedicated_recovery_completed","model":"%s","unix":%s}\n' \
  "$model" "$(date -u +%s)" >>"$state"
