#!/usr/bin/env bash
# MonkeyOCRv2-B-Parsing pod entrypoint.
#
# The server is started through the vendor's own parsing/serve.py, not a raw
# `vllm serve`: serve.py imports modeling/modeling_monkeyocrv2_vllm_011.py to
# register MonkeyOCRv2ForCausalLM with vLLM 0.11 and then builds the argv itself.
# No --draft-model is passed, so DFlash speculative decoding stays off.
set -euo pipefail

WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/monkeyocrv2_b}"
MONKEY_DIR="${ARENA_MONKEYOCRV2_DIR:-/opt/monkeyocrv2}"
VLLM_PORT="${ARENA_VLLM_PORT:-8888}"
TENSOR_PARALLEL_SIZE="${ARENA_TENSOR_PARALLEL_SIZE:-1}"
GPU_MEMORY_UTILIZATION="${ARENA_GPU_MEMORY_UTILIZATION:-0.5}"
MAX_MODEL_LEN="${ARENA_MAX_MODEL_LEN:-16384}"
MAX_NUM_SEQS="${ARENA_MAX_NUM_SEQS:-128}"

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
        echo "model_key=monkeyocrv2_b"
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

echo "[arena] MonkeyOCRv2 runtime revision $(cat "${MONKEY_DIR}/.arena_revision")" >&2

echo "[arena] starting MonkeyOCRv2 vLLM server on port ${VLLM_PORT} (DFlash off)" >&2
(
    cd "${MONKEY_DIR}/parsing"
    exec python3 serve.py \
        --model-path "${WEIGHTS_DIR}" \
        --served-model-name MonkeyOCRv2 \
        --host 127.0.0.1 \
        --port "${VLLM_PORT}" \
        --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}" \
        --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
        --max-model-len "${MAX_MODEL_LEN}" \
        --max-num-seqs "${MAX_NUM_SEQS}"
) > >(tee -a "${SERVER_LOG}" >&2) 2>&1 &
VLLM_PID=$!

terminate() {
    echo "[arena] shutting down MonkeyOCRv2 server (${VLLM_PID})" >&2
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
