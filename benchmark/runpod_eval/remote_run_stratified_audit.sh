#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: remote_run_stratified_audit.sh SUITE INPUT_ROOT OUTPUT_ROOT" >&2
  exit 2
fi

suite="$1"
input_root="$2"
output_root="$3"
python_bin="/usr/bin/python3.11"
runner="/workspace/folynta/runner/mineru_stage2.py"
repository_revision="79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
artifact_sha256="1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84"

case "$suite" in
  parsebench|omnidocbench|olmocr-bench) ;;
  *) echo "unsupported audit suite: $suite" >&2; exit 2 ;;
esac
test -x "$python_bin"
test -f "$runner"
test -d "$input_root/$suite"
test ! -e "$output_root"
manifest="$input_root/$suite/stratified-audit.json"
parent="$input_root/$suite/parent-input-manifest.json"

"$python_bin" "$runner" \
  --input-dir "$input_root/$suite" \
  --output-dir "$output_root" \
  --mineru-cli /usr/local/bin/mineru \
  --repository-revision "$repository_revision" \
  --artifact-manifest-sha256 "$artifact_sha256" \
  --backend vlm-engine \
  --method ocr \
  --repeats 3 \
  --repeat-start-index 1 \
  --limit 0 \
  --evidence-class stratified-audit \
  --expected-input-count 128 \
  --input-manifest "$manifest" \
  --parent-input-manifest "$parent" \
  --batch-size 1 \
  --timeout-seconds 600 \
  >"$output_root.runner.stdout.log" \
  2>"$output_root.runner.stderr.log"
