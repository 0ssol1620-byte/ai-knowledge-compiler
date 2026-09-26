#!/usr/bin/env bash
# GLM-OCR pod entrypoint.
#
# vLLM flags are the SDK README's launch line, with the local weights path
# substituted for the repo id so nothing is downloaded at serve time:
#   vllm serve zai-org/GLM-OCR --port 8080 \
#       --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}' \
#       --served-model-name glm-ocr
# MTP speculative decoding is the vendor's own default here (the model is trained
# with a Multi-Token Prediction head), unlike MonkeyOCRv2's DFlash which is a
# separate checkpoint. --max-model-len and --gpu-memory-utilization are added
# because the README says to set them for the machine.
set -euo pipefail

WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/glm_ocr}"
LAYOUT_DIR="${ARENA_LAYOUT_DIR:-/opt/arena/weights/pp_doclayoutv3_safetensors}"
VLLM_PORT="${ARENA_VLLM_PORT:-8080}"
TENSOR_PARALLEL_SIZE="${ARENA_TENSOR_PARALLEL_SIZE:-1}"
GPU_MEMORY_UTILIZATION="${ARENA_GPU_MEMORY_UTILIZATION:-0.75}"
MAX_MODEL_LEN="${ARENA_MAX_MODEL_LEN:-16384}"
SERVED_MODEL_NAME="glm-ocr"

# --- D19 model-server readiness -------------------------------------------
# ARENA_CONTRACT D19: poll the model server until it answers, with a deadline no
# shorter than the model's cold load time (20-minute floor), and fail hard rather
# than hand a still-loading server to the worker.
READY_TIMEOUT_S="${ARENA_MODEL_SERVER_READY_TIMEOUT_S:-1800}"
READY_POLL_INTERVAL_S="${ARENA_MODEL_SERVER_POLL_INTERVAL_S:-5}"
READY_TIMEOUT_FLOOR_S=1200
READINESS_URL="http://127.0.0.1:${VLLM_PORT}/v1/models"
SERVER_LOG="${ARENA_MODEL_SERVER_LOG:-/opt/arena/model-server.log}"
FATAL_FILE="${ARENA_FATAL_FILE:-/opt/arena/FATAL}"
FATAL_LOG_TAIL_LINES=200

# --- sticky failure --------------------------------------------------------
# RunPod restarts the container when its start command exits, so the old `exit 70`
# turned a deterministic model-load failure into an invisible crash loop that
# billed a 4090 while the v1 pod record still said RUNNING -- exactly what
# happened to this runtime on 2026-09-03. Stay up instead and leave evidence:
# arena.controller.run.FATAL_LOG_SIGNATURES already classifies a "[arena] FATAL"
# line as MODEL_LOAD with zero retries, so the driver condemns the pod at its
# next log read (about two minutes) and deletes it in the D20 `finally` block.
# The worker never starts on this path, so the worker's own
# ARENA_MAX_POD_AGE_HOURS fuse is not what ends the pod; the driver is.
write_fatal() {
    local reason="$1"
    mkdir -p "$(dirname "${FATAL_FILE}")"
    {
        echo "reason=${reason}"
        echo "model_key=glm_ocr"
        echo "at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "server_log=${SERVER_LOG}"
        echo "--- last ${FATAL_LOG_TAIL_LINES} lines ---"
        tail -n "${FATAL_LOG_TAIL_LINES}" "${SERVER_LOG}" 2>/dev/null \
            || echo "(no model server log at ${SERVER_LOG})"
    } > "${FATAL_FILE}"
    echo "[arena] FATAL ${reason}" >&2
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
    return 1
}

echo "[arena] verifying GLM-OCR weights in ${WEIGHTS_DIR}" >&2
python3 /opt/arena/runtime/fetch_weights.py --weights-dir "${WEIGHTS_DIR}"

echo "[arena] verifying PP-DocLayoutV3 layout model in ${LAYOUT_DIR}" >&2
python3 /opt/arena/runtime/fetch_layout_model.py --layout-dir "${LAYOUT_DIR}"

# The worker must look for both checkpoints where this script just verified them.
# runtime.json's inference_config pins the BAKED paths; the bootstrap path puts
# both under /workspace, and on 2026-09-03 pod jdwdnvg8a2rzx6 the adapter looked
# for the layout model under /opt while bootstrap.sh had fetched it to /workspace.
# adapter.resolve_layout_model_dir reads ARENA_LAYOUT_DIR, so export the resolved
# value rather than leaving it to whoever set the variable upstream.
export ARENA_WEIGHTS_DIR="${WEIGHTS_DIR}"
export ARENA_LAYOUT_DIR="${LAYOUT_DIR}"

echo "[arena] starting vLLM ${SERVED_MODEL_NAME} on port ${VLLM_PORT}" >&2
mkdir -p "$(dirname "${SERVER_LOG}")"
# tee, not a plain redirect: the pod log is what the driver's readiness poll
# reads, and ${SERVER_LOG} is what write_fatal quotes back when the server dies.
vllm serve "${WEIGHTS_DIR}" \
    --served-model-name "${SERVED_MODEL_NAME}" \
    --host 127.0.0.1 \
    --port "${VLLM_PORT}" \
    --allowed-local-media-path / \
    --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}' \
    --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --max-model-len "${MAX_MODEL_LEN}" \
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
    # wait_for_model_server has already printed which of the two happened -- the
    # server exited during load, or the deadline passed -- and both of those lines
    # are FATAL_LOG_SIGNATURES in their own right.
    write_fatal "vLLM did not become ready on ${READINESS_URL} (deadline ${READY_TIMEOUT_S}s)"
    # Deliberately not `exit 70`: see write_fatal. Exiting hands the pod back to
    # RunPod, which starts the container again and hides the failure.
    sleep infinity
fi

# Both checkpoints are on disk and hashed by now, so nothing the worker runs may
# reach the Hugging Face hub. The glmocr layout stage calls
# `PPDocLayoutV3ImageProcessor.from_pretrained(model_dir)`, which silently treats
# a path it cannot find as a repo id and downloads an unpinned checkpoint; offline
# turns that into an exception instead. Set here, not in the image, because
# fetch_weights.py and fetch_layout_model.py above are the two things that are
# allowed to download, and vLLM has already loaded from the local path.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

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
