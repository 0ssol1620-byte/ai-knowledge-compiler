#!/usr/bin/env bash
# PaddleOCR-VL 1.6 - arena runtime entrypoint (ARENA_CONTRACT.md section 11.3 item 5,
# amended by D19).
#
# One entrypoint for both modes. The baked image sets
# ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]; in bootstrap mode the B2
# start command extracts the bundle, symlinks /opt/arena/runtime ->
# /opt/arena/runtimes/paddleocr_vl_1_6, and runtimes/paddleocr_vl_1_6/bootstrap.sh execs
# this file. Nothing below knows or cares which of the two happened.
#
# D19 - process ownership. This runtime is NOT in-process: the official
# PaddleOCR-VL pipeline splits the VLM stage out into a
# `paddleocr genai_server --backend vllm` service on loopback, and the pipeline
# client in adapter.py talks to it over HTTP. That is a model server, so the
# entrypoint owns it rather than the adapter. It does:
#
#   1. render the `paddleocr genai_server` argv, env and readiness probe from
#      `adapter.py --print-server-plan`, so the entrypoint and the adapter can
#      never launch two different engines;
#   2. start the server and poll its /v1/models endpoint until it answers, with
#      a hard deadline (runtime.json genai_server.ready_timeout_seconds, floored at
#      the D19 minimum of 1200 s) and a hard failure on timeout;
#   3. run the worker as a CHILD and `wait` on it - never `exec`, which would
#      discard the trap and orphan the server;
#   4. stop the server from a trap on any exit, and propagate the worker's exit
#      code as this script's exit code.

set -euo pipefail

export ARENA_MODEL_KEY="paddleocr_vl_1_6"
export ARENA_RUNTIME_DIR="${ARENA_RUNTIME_DIR:-/opt/arena/runtime}"
export PYTHONPATH="${PYTHONPATH:-/opt/arena}"
PYTHON_BIN="${PYTHON_BIN:-python}"
export ARENA_WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/paddleocr_vl_1_6}"
# D19 floor: twenty minutes, whatever runtime.json says.
READY_DEADLINE_FLOOR_SECONDS=1200

for required in runtime.json adapter.py canonical.py; do
  if [ ! -f "${ARENA_RUNTIME_DIR}/${required}" ]; then
    echo "entrypoint: ${ARENA_RUNTIME_DIR}/${required} is missing; refusing to start" >&2
    exit 1
  fi
done

# --------------------------------------------------------------------------- #
# 1. the launch plan, from the one builder in adapter.py
# --------------------------------------------------------------------------- #

READY_PROBE=""
READY_TIMEOUT=0
SERVER_ARGV=()
while IFS=$'\t' read -r field value; do
  case "${field}" in
    probe) READY_PROBE="${value}" ;;
    timeout) READY_TIMEOUT="${value}" ;;
    env) export "${value}" ;;
    argv) SERVER_ARGV+=("${value}") ;;
    *)
      echo "entrypoint: unknown server-plan field '${field}'; refusing to start" >&2
      exit 1
      ;;
  esac
done < <("${PYTHON_BIN}" "${ARENA_RUNTIME_DIR}/adapter.py" --print-server-plan)

if [ "${#SERVER_ARGV[@]}" -eq 0 ] || [ -z "${READY_PROBE}" ]; then
  echo "entrypoint: adapter.py produced no model-server plan; refusing to start" >&2
  exit 1
fi

READY_DEADLINE_SECONDS="${READY_TIMEOUT}"
if [ "${READY_DEADLINE_SECONDS}" -lt "${READY_DEADLINE_FLOOR_SECONDS}" ]; then
  READY_DEADLINE_SECONDS="${READY_DEADLINE_FLOOR_SECONDS}"
fi

# --------------------------------------------------------------------------- #
# 2. start the model server; the trap owns it from here
# --------------------------------------------------------------------------- #

SERVER_PID=""

# --- sticky failure -------------------------------------------------------
# RunPod restarts an exited start command. A deterministic startup failure (the
# 2026-09-03 GLM-OCR incident: the model server died on an unknown model_type)
# therefore becomes an invisible crash loop that keeps billing the GPU. When the
# model server dies or never answers, this entrypoint records why, says FATAL on
# the pod log, and holds the container instead of exiting: the controller's
# log-based crash-loop detector and the lifetime fuse (D20) stop the pod.
FATAL_FILE="${ARENA_FATAL_FILE:-/opt/arena/FATAL}"
SERVER_LOG="${ARENA_MODEL_SERVER_LOG:-/opt/arena/model-server.log}"
# The controller reads the same number of lines out of the pod log (LOG_TAIL_LINES).
FATAL_LOG_TAIL_LINES=200

fatal_and_hold() {
  local reason="$1"
  {
    echo "model_key=paddleocr_vl_1_6"
    echo "reason=${reason}"
    echo "at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "server_log=${SERVER_LOG}"
    echo "--- last ${FATAL_LOG_TAIL_LINES} lines of the model-server log ---"
    tail -n "${FATAL_LOG_TAIL_LINES}" "${SERVER_LOG}" 2>/dev/null || echo "(no model-server log was written)"
  } > "${FATAL_FILE}" 2>&1 || true
  echo "[arena] FATAL ${reason}" >&2
  sleep infinity
}

stop_server() {
  if [ -z "${SERVER_PID}" ]; then
    return 0
  fi
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    return 0
  fi
  echo "entrypoint: stopping the model server (pid ${SERVER_PID})" >&2
  kill -TERM "${SERVER_PID}" 2>/dev/null || true
  for _ in $(seq 1 60); do
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  kill -KILL "${SERVER_PID}" 2>/dev/null || true
}

trap stop_server EXIT INT TERM

"${SERVER_ARGV[@]}" > >(tee -a "${SERVER_LOG}" >&2) 2>&1 &
SERVER_PID=$!
echo "entrypoint: model server started as pid ${SERVER_PID}" >&2

# --------------------------------------------------------------------------- #
# 3. poll until it answers, or fail hard
# --------------------------------------------------------------------------- #

probe_once() {
  "${PYTHON_BIN}" -c 'import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=10) as response:
    sys.exit(0 if 200 <= int(response.status) < 400 else 1)
' "${READY_PROBE}" >/dev/null 2>&1
}

READY_DEADLINE=$(( SECONDS + READY_DEADLINE_SECONDS ))
until probe_once; do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    fatal_and_hold "the model server exited before it became ready at ${READY_PROBE}"
  fi
  if [ "${SECONDS}" -ge "${READY_DEADLINE}" ]; then
    fatal_and_hold "model server not ready within ${READY_DEADLINE_SECONDS}s at ${READY_PROBE}"
  fi
  sleep 5
done
echo "entrypoint: model server is ready at ${READY_PROBE}" >&2

# --------------------------------------------------------------------------- #
# 4. the worker is a child, not an exec; its exit code is ours
# --------------------------------------------------------------------------- #

export ARENA_MODEL_SERVER_MANAGED_BY="entrypoint"

"${PYTHON_BIN}" -m arena.worker.server &
WORKER_PID=$!
WORKER_STATUS=0
wait "${WORKER_PID}" || WORKER_STATUS=$?
stop_server
exit "${WORKER_STATUS}"
