# syntax=docker/dockerfile:1.7
#
# HPD-Parsing arena runtime.
# Build context is the namespace root: research/model_arena_20260903/
#
#   docker build -f runtimes/hpd_parsing/Dockerfile \
#     -t <registry>/arena-hpd-parsing:<campaign> .
#
# Masterplan section 15.1: HPD-Parsing needs a customized vLLM (0.17.1 fork with
# dynamic request forking and P-MTP), so the official image IS the runtime and
# nothing is compiled here. The *offline* variant is used because it bakes the
# weights, which removes the model download from pod boot entirely.
#
# The registry ccr-2vdh3abv-pub.cnc.bj.baidubce.com answers 401 on the first,
# unauthenticated hop but advertises a Bearer realm and issues an anonymous pull
# token; through that flow the digest below was resolved on 2026-09-03 and it is
# the same value lane F recorded in build/build_plan.json. The image declares its
# own ENTRYPOINT (/bin/bash /home/hpd/entrypoint.sh), which the baked build
# replaces here and bootstrap mode overrides via REST v1 dockerEntrypoint (D2).

ARG BASE_IMAGE=ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/hpd-parsing-vllm:latest-nvidia-gpu-offline
ARG BASE_IMAGE_DIGEST=sha256:1493923dd6b7e368c56b5497f2c82ade2599be9c69aa7498a71417b5c6d9948a

FROM ${BASE_IMAGE}@${BASE_IMAGE_DIGEST}

ARG BASE_IMAGE
ARG BASE_IMAGE_DIGEST
ARG MODEL_REPO=PaddlePaddle/HPD-Parsing
ARG MODEL_REVISION=91de80054c23ab4238e3d7073fa2b83c2a7e301e
ARG WEIGHTS_LARGEST_FILE=model.safetensors
ARG WEIGHTS_LARGEST_SHA256=f82b9c83ca8a85931b51b717143c24858281aa8cd1f016dd5a7a1ec5d40a7d91
ARG PMTP_SHA256=a84e697098ce5242a5a10cb95ae05a8cc579134ae01d615ed7bd64f97cddec3a

USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/arena \
    MAX_PATCHES_WITH_RESIZE=true \
    ARENA_MODEL_KEY=hpd_parsing \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/hpd_parsing \
    ARENA_BASE_IMAGE=${BASE_IMAGE} \
    ARENA_BASE_IMAGE_DIGEST=${BASE_IMAGE_DIGEST}

# The offline image already carries a copy of the weights, but the arena pins a
# revision and the image tag does not name one. Re-materialise the pinned
# revision into a directory the adapter owns, then verify both checkpoints.
# `--revision` plus `sha256sum -c` is the whole guarantee: a moved repository
# fails the build instead of scoring as a different model.
RUN python -m pip install --no-cache-dir "huggingface_hub[cli]==0.35.3" \
 && mkdir -p "${ARENA_WEIGHTS_DIR}" \
 && hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" \
      --local-dir "${ARENA_WEIGHTS_DIR}" \
 && echo "${WEIGHTS_LARGEST_SHA256}  ${ARENA_WEIGHTS_DIR}/${WEIGHTS_LARGEST_FILE}" \
      | sha256sum -c - \
 && echo "${PMTP_SHA256}  ${ARENA_WEIGHTS_DIR}/P-MTP/model.safetensors" | sha256sum -c - \
 && test -f "${ARENA_WEIGHTS_DIR}/config.json" \
 && test -f "${ARENA_WEIGHTS_DIR}/P-MTP/config.json" \
 && printf '%s' "${MODEL_REVISION}" > "${ARENA_WEIGHTS_DIR}/arena-weights-revision.txt"

COPY arena/ /opt/arena/arena/
COPY runtimes/hpd_parsing/ /opt/arena/runtime/

# ARENA_CONTRACT D17: the prompt registry travels with the image. The worker
# resolves ARENA_PROMPT_FILE (default /opt/arena/prompt_registry/<prompt_id>.txt
# from runtime.json), fails closed when it is missing, and refuses a run whose
# request prompt_sha256 differs from the file's hash. In bootstrap mode the same
# directory arrives inside the bundle.
COPY prompt_registry/ /opt/arena/prompt_registry/

# Section 38 runtime provenance, captured at build time.
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
