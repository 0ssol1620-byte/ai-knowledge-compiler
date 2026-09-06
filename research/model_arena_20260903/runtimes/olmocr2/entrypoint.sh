#!/usr/bin/env bash
# olmOCR-2-7B-1025-FP8 pod entrypoint.
#
# vLLM flags are the ones olmocr/pipeline.py v0.4.27 builds in `vllm_server_task`:
#   --served-model-name olmocr --tensor-parallel-size 1 --data-parallel-size 1
#   --limit-mm-per-prompt '{"video": 0}' --max-model-len 16384
# OMP_NUM_THREADS=1 is set for the same reason the toolkit sets it.
set -euo pipefail

WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/olmocr2}"
VLLM_PORT="${ARENA_VLLM_PORT:-8100}"
TENSOR_PARALLEL_SIZE="${ARENA_TENSOR_PARALLEL_SIZE:-1}"
DATA_PARALLEL_SIZE="${ARENA_DATA_PARALLEL_SIZE:-1}"
MAX_MODEL_LEN="${ARENA_MAX_MODEL_LEN:-16384}"
SERVED_MODEL_NAME="olmocr"

# --- D19 model-server readiness -------------------------------------------
# ARENA_CONTRACT D19: poll the model server until it answers, with a deadline no
# shorter than the model's cold load time (20-minute floor), and fail hard rather
# than hand a still-loading server to the worker.
READY_TIMEOUT_S="${ARENA_MODEL_SERVER_READY_TIMEOUT_S:-1800}"
READY_POLL_INTERVAL_S="${ARENA_MODEL_SERVER_POLL_INTERVAL_S:-5}"
READY_TIMEOUT_FLOOR_S=1200
READINESS_URL="http://127.0.0.1:${VLLM_PORT}/v1/models"

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
READINESS_FAILURE_REASON=""

fatal_and_hold() {
    local reason="$1"
    {
        echo "model_key=olmocr2"
        echo "reason=${reason}"
        echo "at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "server_log=${SERVER_LOG}"
        echo "--- last ${FATAL_LOG_TAIL_LINES} lines of the model-server log ---"
        tail -n "${FATAL_LOG_TAIL_LINES}" "${SERVER_LOG}" 2>/dev/null || echo "(no model-server log was written)"
    } > "${FATAL_FILE}" 2>&1 || true
    echo "[arena] FATAL ${reason}" >&2
    sleep infinity
}

if [ "${READY_TIMEOUT_S}" -lt "${READY_TIMEOUT_FLOOR_S}" ]; then
    echo "[arena] refusing: readiness deadline ${READY_TIMEOUT_S}s is below the" \
        "${READY_TIMEOUT_FLOOR_S}s floor (ARENA_CONTRACT D19)" >&2
    exit 64
fi

wait_for_model_server() {
    local url="$1" deadline_s="$2" interval_s="$3" server_pid="$4"
    local waited=0
    while [ "${waited}" -lt "${deadline_s}" ]; do
        if ! kill -0 "${server_pid}" 2>/dev/null; then
            echo "[arena] model server exited after ${waited}s without becoming ready" >&2
            READINESS_FAILURE_REASON="model server exited after ${waited}s without becoming ready"
            return 1
        fi
        if python3 - "${url}" <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
        then
            echo "[arena] model server answered ${url} after ${waited}s" >&2
            return 0
        fi
        sleep "${interval_s}"
        waited=$((waited + interval_s))
    done
    echo "[arena] model server did not answer ${url} within ${deadline_s}s" >&2
    READINESS_FAILURE_REASON="model server did not answer ${url} within ${deadline_s}s"
    return 1
}

echo "[arena] verifying weights in ${WEIGHTS_DIR}" >&2
python3 /opt/arena/runtime/fetch_weights.py --weights-dir "${WEIGHTS_DIR}"

echo "[arena] recording the resolved quantisation path" >&2
# Masterplan 47/13.2: never infer capability from a GPU's name. Print what the
# device actually reports so the canary receipt carries the compute capability the
# FP8 kernels will be selected against.
python3 - <<'PY' || echo "[arena] WARNING: could not read device capability" >&2
import torch
if torch.cuda.is_available():
    for index in range(torch.cuda.device_count()):
        major, minor = torch.cuda.get_device_capability(index)
        name = torch.cuda.get_device_name(index)
        native_fp8 = (major, minor) >= (8, 9)
        print(f"[arena] gpu{index} {name} sm_{major}{minor} native_fp8={native_fp8}")
else:
    print("[arena] no CUDA device visible")
PY

echo "[arena] starting vLLM ${SERVED_MODEL_NAME} on port ${VLLM_PORT}" >&2
OMP_NUM_THREADS=1 vllm serve "${WEIGHTS_DIR}" \
    --served-model-name "${SERVED_MODEL_NAME}" \
    --host 127.0.0.1 \
    --port "${VLLM_PORT}" \
    --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}" \
    --data-parallel-size "${DATA_PARALLEL_SIZE}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --limit-mm-per-prompt '{"video": 0}' \
    --uvicorn-log-level warning \
    > >(tee -a "${SERVER_LOG}" >&2) 2>&1 &
VLLM_PID=$!

terminate() {
    echo "[arena] shutting down vLLM (${VLLM_PID})" >&2
    kill "${VLLM_PID}" 2>/dev/null || true
    wait "${VLLM_PID}" 2>/dev/null || true
}
trap terminate EXIT INT TERM

echo "[arena] waiting for ${READINESS_URL} (deadline ${READY_TIMEOUT_S}s)" >&2
if ! wait_for_model_server \
    "${READINESS_URL}" "${READY_TIMEOUT_S}" "${READY_POLL_INTERVAL_S}" "${VLLM_PID}"; then
    fatal_and_hold "${READINESS_FAILURE_REASON:-model server never became ready at ${READINESS_URL}}"
fi

# D19: the worker runs as a child, not through exec, so the EXIT trap above still
# stops the model server. The worker's exit code becomes the pod's exit code.
echo "[arena] starting worker server" >&2
python3 -m arena.worker.server &
WORKER_PID=$!
set +e
wait "${WORKER_PID}"
WORKER_STATUS=$?
set -e
echo "[arena] worker server exited with status ${WORKER_STATUS}" >&2
exit "${WORKER_STATUS}"
