# syntax=docker/dockerfile:1.7
#
# MinerU 3.4.x pipeline-backend arena runtime.
# Build context is the namespace root: research/model_arena_20260903/
#
#   docker build -f runtimes/mineru_pipeline/Dockerfile \
#     -t <registry>/arena-mineru-pipeline:<campaign> .
#
# Base image is the one MinerU's own docker/global/Dockerfile uses, pinned by
# the digest resolved from the Docker Hub registry on 2026-09-03. Unlike the
# PaddleOCR and HPD images this one is public, so the digest is literal here.

ARG BASE_IMAGE=vllm/vllm-openai:v0.21.0
ARG BASE_IMAGE_DIGEST=sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9

FROM ${BASE_IMAGE}@${BASE_IMAGE_DIGEST}

ARG BASE_IMAGE
ARG BASE_IMAGE_DIGEST
ARG MINERU_REVISION=fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883
ARG MODEL_REPO=opendatalab/PDF-Extract-Kit-1.0
ARG MODEL_REVISION=ed6b654c018d742e65a17671e379c5e6ecc87ec9
ARG WEIGHTS_LARGEST_FILE=models/MFR/unimernet_hf_small_2503/model.safetensors
ARG WEIGHTS_LARGEST_SHA256=9244e2565585c0f89bc3a6eeeea080ef3c588375fc0d536074fe88e80b917cda

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/arena \
    OMP_NUM_THREADS=1 \
    MINERU_MODEL_SOURCE=local \
    MINERU_TOOLS_CONFIG_JSON=/opt/arena/mineru.json \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/mineru_pipeline \
    ARENA_BASE_IMAGE=${BASE_IMAGE} \
    ARENA_BASE_IMAGE_DIGEST=${BASE_IMAGE_DIGEST}

# libgl for opencv and the Noto CJK fonts, exactly as MinerU's own image does.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      fonts-noto-core fonts-noto-cjk fontconfig libgl1 \
 && fc-cache -fv \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# MinerU pinned to an exact commit rather than a floating version range. Upstream
# tagged mineru-3.4.5-released without bumping mineru/version.py, so the git sha
# is the only unambiguous pin. No `pip install -U` anywhere.
RUN python3 -m pip install --no-cache-dir --break-system-packages \
      "mineru[core] @ git+https://github.com/opendatalab/MinerU.git@${MINERU_REVISION}" \
 && python3 -m pip install --no-cache-dir --break-system-packages \
      "transformers==4.57.3" \
      "accelerate==1.14.0" \
      "mineru-vl-utils==1.0.5" \
      "huggingface_hub[cli]==0.35.3" \
 && python3 -m pip cache purge

# Baked weights: only the seven sub-trees the pipeline backend downloads
# (mineru/cli/models_download.py::download_pipeline_models), at the pinned
# repository revision, with the largest of them checked by sha256.
RUN mkdir -p "${ARENA_WEIGHTS_DIR}" \
 && hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" \
      --local-dir "${ARENA_WEIGHTS_DIR}" \
      --include "models/Layout/PP-DocLayoutV2/*" \
      --include "models/MFR/unimernet_hf_small_2503/*" \
      --include "models/MFR/pp_formulanet_plus_m/*" \
      --include "models/OCR/paddleocr_torch/*" \
      --include "models/TabRec/SlanetPlus/slanet-plus.onnx" \
      --include "models/TabRec/UnetStructure/unet.onnx" \
      --include "models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx" \
 && echo "${WEIGHTS_LARGEST_SHA256}  ${ARENA_WEIGHTS_DIR}/${WEIGHTS_LARGEST_FILE}" \
      | sha256sum -c - \
 && printf '%s' "${MODEL_REVISION}" > "${ARENA_WEIGHTS_DIR}/arena-weights-revision.txt"

# Point MinerU at the baked tree. model-source=local means no network probe of
# huggingface.co at import time (resolve_auto_model_source).
RUN printf '{"models-dir": {"pipeline": "%s"}, "model-source": "local", "config_version": "1.3.2"}\n' \
      "${ARENA_WEIGHTS_DIR}" > /opt/arena/mineru.json

COPY arena/ /opt/arena/arena/
COPY runtimes/mineru_pipeline/ /opt/arena/runtime/

# ARENA_CONTRACT D17: the prompt registry travels with the image. The worker
# resolves ARENA_PROMPT_FILE (default /opt/arena/prompt_registry/<prompt_id>.txt
# from runtime.json), fails closed when it is missing, and refuses a run whose
# request prompt_sha256 differs from the file's hash. In bootstrap mode the same
# directory arrives inside the bundle.
COPY prompt_registry/ /opt/arena/prompt_registry/

# Section 38 runtime provenance, captured at build time.
RUN mkdir -p /opt/arena/receipts \
 && python3 -m pip freeze --all | LC_ALL=C sort > /opt/arena/receipts/pip-freeze.txt \
 && (dpkg-query -W -f='${Package}=${Version}\n' 2>/dev/null | LC_ALL=C sort \
      > /opt/arena/receipts/apt-snapshot.txt || true) \
 && printf '%s\n' "${MINERU_REVISION}" > /opt/arena/receipts/mineru-git-revision.txt \
 && sha256sum /opt/arena/receipts/pip-freeze.txt /opt/arena/receipts/apt-snapshot.txt \
      /opt/arena/receipts/mineru-git-revision.txt > /opt/arena/receipts/build-files.sha256

# ARENA_CONTRACT section 11.3 item 6: the baked image and the bootstrap path
# share one entrypoint under /opt/arena/runtime/, so a runtime script never has
# to know which mode it is running in.
RUN chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

# ---------------------------------------------------------------- non-root ----
# Trivy DS-0002. Everything above ran as root and stays root-owned, so weights,
# receipts and code are read-only to the runtime: a boot can verify them but never
# rewrite them. No chown of /opt/arena -- that would copy the weight layer and hand
# the receipts to the process they constrain. Only the three directories below are
# writable. /workspace/arena is used when nothing is mounted over it; a root-owned
# RunPod volume masks it, and arena.worker.config.resolve_state_dir then falls back
# to ARENA_STATE_FALLBACK_DIR and says so on the pod log and in /v1/ready.
# uid/gid 10001 is the one services/api uses.
RUN groupadd --system --gid 10001 arena \
 && useradd --system --uid 10001 --gid arena --home-dir /home/arena --create-home \
      --shell /usr/sbin/nologin arena \
 && install -d -o arena -g arena -m 0750 /var/lib/arena /var/lib/arena/state /workspace/arena
ENV HOME=/home/arena \
    ARENA_FATAL_FILE=/var/lib/arena/FATAL \
    ARENA_MODEL_SERVER_LOG=/var/lib/arena/model-server.log \
    ARENA_STATE_FALLBACK_DIR=/var/lib/arena/state
USER 10001:10001

EXPOSE 8000
WORKDIR /opt/arena
ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]
