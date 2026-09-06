#!/usr/bin/env bash
# OvisOCR2 pod entrypoint (ARENA_CONTRACT.md section 11.3 item 5).
#
# OvisOCR2 is served through the vLLM offline `LLM` engine loaded in-process
# inside the worker (adapter.py) -- there is no separate `vllm serve` HTTP
# server to start and wait on here. The adapter's own load() call (invoked by
# arena.worker.server on first use) verifies the on-disk weights against
# arena-weights-receipt.json (revision + manifest sha256) before serving a
# single page, so this script does not duplicate that check; it only refuses
# to start if the weights directory itself is missing.
#
# Works identically whichever way the weights got here: baked into the image
# by the Dockerfile, or fetched by runtimes/ovisocr2/bootstrap.sh, which execs
# this script when it finishes.
set -euo pipefail

WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/ovisocr2}"

if [[ ! -d "${WEIGHTS_DIR}" ]]; then
  echo "[arena] entrypoint refuses: weights dir ${WEIGHTS_DIR} does not exist" >&2
  exit 66
fi

echo "[arena] starting OvisOCR2 worker server" >&2
exec python3 -m arena.worker.server
