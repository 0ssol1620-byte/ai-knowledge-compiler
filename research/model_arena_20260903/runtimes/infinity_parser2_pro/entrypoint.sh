#!/usr/bin/env bash
# Infinity-Parser2-Pro pod entrypoint.
#
#   1. make sure the pinned checkpoint is where weights_strategy says it is --
#      baked into the image at /opt/arena/weights (ARENA_CONTRACT D36) -- with the
#      revision and largest-file sha256 verified; a revision mismatch aborts the pod
#   2. start the official vLLM server with the exact flags the model card prints
#   3. poll the server's /v1/models endpoint until it answers (ARENA_CONTRACT D19)
#   4. run the arena worker server as a CHILD and wait on it, so the EXIT trap
#      still fires and the vLLM process is never orphaned; the worker's exit code
#      is the pod's exit code
#
# D19 is why step 4 is not `exec`: exec replaces this shell, which discards the
# trap and leaves vLLM running with nothing supervising it.
#
# Fail closed: any step that cannot do its job stops the pod instead of serving a
# model nobody pinned.
set -euo pipefail

WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/infinity_parser2_pro}"
VLLM_PORT="${ARENA_VLLM_PORT:-8100}"
TENSOR_PARALLEL_SIZE="${ARENA_TENSOR_PARALLEL_SIZE:-2}"
GPU_MEMORY_UTILIZATION="${ARENA_GPU_MEMORY_UTILIZATION:-0.85}"
MAX_MODEL_LEN="${ARENA_MAX_MODEL_LEN:-65536}"
SERVED_MODEL_NAME="infinity-parser2-pro"

# --- D19 model-server readiness -------------------------------------------
# The deadline has to cover a cold load of a 70 GB checkpoint across two GPUs.
# ARENA_CONTRACT D19 sets a 20-minute floor; this runtime defaults above it and
# refuses a shorter one rather than calling a still-loading server ready.
READY_TIMEOUT_S="${ARENA_MODEL_SERVER_READY_TIMEOUT_S:-2400}"
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
        echo "model_key=infinity_parser2_pro"
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

echo "[arena] resolving weights into ${WEIGHTS_DIR}" >&2
python3 /opt/arena/runtime/fetch_weights.py --weights-dir "${WEIGHTS_DIR}"

# The weights are on disk and hashed by now, so nothing the worker or vLLM runs
# may reach the Hugging Face hub. Set here, not in the image, because
# fetch_weights.py above is the only thing allowed to download.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

echo "[arena] starting vLLM ${SERVED_MODEL_NAME} on port ${VLLM_PORT}" >&2
# Flags verbatim from https://huggingface.co/infly/Infinity-Parser2-Pro
# ("To start a vLLM server"), with the local weights path substituted for the repo
# id so nothing is downloaded from the network at serve time.
vllm serve "${WEIGHTS_DIR}" \
    --served-model-name "${SERVED_MODEL_NAME}" \
    --trust-remote-code \
    --reasoning-parser qwen3 \
    --host 127.0.0.1 \
    --port "${VLLM_PORT}" \
    --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --mm-encoder-tp-mode data \
    --mm-processor-cache-type shm \
    --enable-prefix-caching \
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
# stops vLLM. The worker's exit code becomes the pod's exit code.
echo "[arena] starting worker server" >&2
python3 -m arena.worker.server &
WORKER_PID=$!
set +e
wait "${WORKER_PID}"
WORKER_STATUS=$?
set -e
echo "[arena] worker server exited with status ${WORKER_STATUS}" >&2
exit "${WORKER_STATUS}"
