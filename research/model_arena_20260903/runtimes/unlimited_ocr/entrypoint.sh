#!/usr/bin/env bash
# Unlimited-OCR pod entrypoint (ARENA_CONTRACT.md section 11.3 item 5).
#
# Unlimited-OCR is served through the Transformers `AutoModel.infer()` path
# in-process inside the worker (adapter.py), not a standalone model server --
# there is nothing here to start and wait on. The adapter's own load() call
# (invoked by arena.worker.server on first use) verifies the on-disk weights
# against arena-weights-receipt.json (revision + manifest sha256) before
# serving a single page, so this script does not duplicate that check; it
# only refuses to start if the weights directory itself is missing.
#
# Works identically whichever way the weights got here: baked into the image
# by the Dockerfile, or fetched by runtimes/unlimited_ocr/bootstrap.sh, which
# execs this script when it finishes. PATH already carries /opt/arena/venv/bin
# (baked image ENV, and bootstrap.sh activates the same venv before exec'ing
# here), so `python` resolves to the venv interpreter in both modes.
set -euo pipefail

WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/unlimited_ocr}"

if [[ ! -d "${WEIGHTS_DIR}" ]]; then
  echo "[arena] entrypoint refuses: weights dir ${WEIGHTS_DIR} does not exist" >&2
  exit 66
fi

echo "[arena] starting Unlimited-OCR worker server" >&2
exec python -m arena.worker.server
