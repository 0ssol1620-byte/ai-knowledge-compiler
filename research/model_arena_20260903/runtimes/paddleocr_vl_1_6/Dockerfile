# syntax=docker/dockerfile:1.7
#
# PaddleOCR-VL 1.6 arena runtime.
# Build context is the namespace root: research/model_arena_20260903/
#
#   docker build -f runtimes/paddleocr_vl_1_6/Dockerfile \
#     -t <registry>/arena-paddleocr-vl-1-6:<campaign> .
#
# The base image is the official PaddleOCR-VL image, unmodified: it already
# carries PaddleOCR-VL-1.6. PaddleOCR v3.6.0 is the release that shipped
# PaddleOCR-VL-1.6, `pipeline_version` defaults to v1.6 there, and this image's
# build history downloads PaddleOCR-VL-1.6_infer.tar. The registry publishes no
# paddleocr3.7-* image on any PaddleOCR repository (full anonymous tag listings,
# 2026-09-03) and would not help if it did: v3.7.0 released PP-OCRv6, a separate
# non-VL family. It is pinned by the documented version tag rather than
# `latest-nvidia-gpu` because `latest-*` moves; both resolve to this digest today.
# Every listing, digest and label is recorded in provenance.json.

ARG BASE_IMAGE=ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:paddleocr3.6-nvidia-gpu
ARG BASE_IMAGE_DIGEST=sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db

FROM ${BASE_IMAGE}@${BASE_IMAGE_DIGEST}

ARG BASE_IMAGE
ARG BASE_IMAGE_DIGEST
ARG MODEL_REPO=PaddlePaddle/PaddleOCR-VL-1.6
ARG MODEL_REVISION=c5630abae1d940eafe0697512a0325494b02ab42
ARG WEIGHTS_LARGEST_FILE=model.safetensors
ARG WEIGHTS_LARGEST_SHA256=85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db

# The official image ends on `USER paddleocr` (uid 1000) with HOME=/home/paddleocr,
# and /opt is root-owned, so every step below that writes under /opt/arena needs
# root. Same posture as the HPD-Parsing image, which already does this.
USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/arena \
    ARENA_MODEL_KEY=paddleocr_vl_1_6 \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/paddleocr_vl_1_6 \
    ARENA_BASE_IMAGE=${BASE_IMAGE} \
    ARENA_BASE_IMAGE_DIGEST=${BASE_IMAGE_DIGEST}

# Nothing is installed over the vendor's paddleocr/paddlex pairing. The digest
# is asserted to carry what runtime.json says it carries, so a moved tag or a
# re-tagged image fails the build instead of silently changing the model.
RUN python -c "import importlib.metadata as m, sys; \
found = {n: m.version(n) for n in ('paddleocr', 'paddlex')}; \
sys.exit(0 if found == {'paddleocr': '3.6.0', 'paddlex': '3.6.1'} else f'base image carries {found}, expected paddleocr 3.6.0 / paddlex 3.6.1')"

# FlashAttention 2.8.2 is required by vLLM and the official docs publish this
# exact prebuilt wheel for the paddleocr-vl image, which ships no nvcc.
RUN python -m pip install --no-cache-dir \
      "https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.3.14/flash_attn-2.8.2+cu128torch2.8-cp310-cp310-linux_x86_64.whl"

# The official resolver. PaddleOCR pins the compatible vLLM stack itself; the
# docs publish no == versions, so the resolved set is frozen below into the
# image receipt instead of being guessed here. Never `pip install -U`.
RUN paddleocr install_genai_server_deps vllm

# Baked weights: pinned revision, then the sha256 of the largest weight file is
# checked against the value in runtime.json. A mismatch fails the build.
RUN python -m pip install --no-cache-dir "huggingface_hub[cli]==0.35.3" \
 && mkdir -p "${ARENA_WEIGHTS_DIR}" \
 && hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" \
      --local-dir "${ARENA_WEIGHTS_DIR}" \
 && echo "${WEIGHTS_LARGEST_SHA256}  ${ARENA_WEIGHTS_DIR}/${WEIGHTS_LARGEST_FILE}" \
      | sha256sum -c - \
 && printf '%s' "${MODEL_REVISION}" > "${ARENA_WEIGHTS_DIR}/arena-weights-revision.txt"

COPY arena/ /opt/arena/arena/
COPY runtimes/paddleocr_vl_1_6/ /opt/arena/runtime/

# ARENA_CONTRACT D17: the prompt registry travels with the image. The worker
# resolves ARENA_PROMPT_FILE (default /opt/arena/prompt_registry/<prompt_id>.txt
# from runtime.json), fails closed when it is missing, and refuses a run whose
# request prompt_sha256 differs from the file's hash. In bootstrap mode the same
# directory arrives inside the bundle.
COPY prompt_registry/ /opt/arena/prompt_registry/

# Section 38 runtime provenance, captured at build time and never regenerated.
RUN mkdir -p /opt/arena/receipts \
 && python -m pip freeze --all | LC_ALL=C sort > /opt/arena/receipts/pip-freeze.txt \
 && (dpkg-query -W -f='${Package}=${Version}\n' 2>/dev/null | LC_ALL=C sort \
      > /opt/arena/receipts/apt-snapshot.txt || true) \
 && sha256sum /opt/arena/receipts/pip-freeze.txt /opt/arena/receipts/apt-snapshot.txt \
      > /opt/arena/receipts/build-files.sha256

# ARENA_CONTRACT section 11.3 item 6: the baked image and the bootstrap path
# share one entrypoint under /opt/arena/runtime/, so a runtime script never has
# to know which mode it is running in.
RUN chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

EXPOSE 8000
WORKDIR /opt/arena
ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]
