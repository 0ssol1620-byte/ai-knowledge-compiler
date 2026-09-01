# syntax=docker/dockerfile:1.7
#
# Base image digest: found in tools/release/provision_folynta_dedicated_recovery_pod.ps1
# (line ~111/184), tools/release/provision_folynta_mineru_recovery_worker.ps1
# (line ~148) and tools/release/provision_folynta_mineru_retry_expansion.ps1
# (line ~78) -- the same pinned runpod/pytorch digest already used elsewhere
# in this repo for a CUDA-capable RunPod Pod base. Reused here rather than
# inventing a new digest for this image.
FROM runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84

# Frozen identity: benchmark/v6/candidate-registry.yaml candidate id
# `paddleocr-vl-1.6` (verified against the live file 2026-08-31).
# ARTIFACT_MANIFEST_SHA256 is kept as raw hex (no "sha256:" prefix), mirroring
# the ARG MODEL_SAFETENSORS_SHA256 convention in
# infra/runpod/v6/images/ovisocr2-m1/Dockerfile, even though the registry
# records the value with a "sha256:" prefix
# (sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53).
ARG MODEL_REVISION=66317acc4c9fc17bd154591ce650735cd2855f3e
ARG ARTIFACT_MANIFEST_SHA256=40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53

ENV DEBIAN_FRONTEND=noninteractive \
    FOLYNTA_MODEL_ROOT=/opt/folynta/models/PaddleOCR-VL-1.6 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    HF_HOME=/opt/folynta/cache/huggingface \
    PADDLE_PDX_MODEL_SOURCE=HF \
    PADDLEX_HOME=/opt/folynta/cache/paddlex \
    MODEL_REVISION=${MODEL_REVISION} \
    ARTIFACT_MANIFEST_SHA256=${ARTIFACT_MANIFEST_SHA256}

USER root
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends openssh-server ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /root/.ssh /opt/folynta/models /opt/folynta/runner \
       /opt/folynta/fixtures "${HF_HOME}" "${PADDLEX_HOME}"

# Pinned Paddle/FastDeploy runtime, mirroring the package set and install
# order in benchmark/runpod_eval/remote_bootstrap_paddle_recovery.sh (venv
# creation, paddlepaddle-gpu from the cu126 index, paddleocr[doc-parser], the
# genai-server FastDeploy dependency installer, then a pinned protobuf).
# --no-cache-dir on every install: without it pip keeps a second copy of every
# wheel it downloads under ~/.cache/pip, and this layer pulls several
# multi-hundred-MB CUDA wheels (nvidia-cublas-cu12 alone is 393 MB). A build on
# 2026-09-01 died here with "[Errno 28] No space left on device" partway through
# that download, on a runner where the cleanup step had already freed 13G -> 33G.
# The sibling MinerU image already passes this flag; this one did not.
RUN python3.11 -m venv /opt/folynta/venv \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir --upgrade 'pip==25.1.1' \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir \
         'paddlepaddle-gpu==3.2.1' \
         --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir 'paddleocr[doc-parser]==3.7.0' \
    && PATH="/opt/folynta/venv/bin:${PATH}" /opt/folynta/venv/bin/paddleocr install_genai_server_deps fastdeploy \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir 'protobuf==6.33.6' \
    && rm -rf /root/.cache/pip

# FastDeploy compatibility patch, copied verbatim (before/after hashes and the
# sed expression) from remote_bootstrap_paddle_recovery.sh lines ~50-65: newer
# paddleformers moved llm_utils out of paddleformers.trl, and FastDeploy
# 2.3.0's text_processor.py still imports the old path.
RUN patch_file=/opt/folynta/venv/lib/python3.11/site-packages/fastdeploy/input/text_processor.py \
    && before_patch=b50570cb2c13f29f2a7f8803d6bdb3368111e906152425f9666d0ca4818a396d \
    && after_patch=3be4e76c7e0fedd11c77eb5a704763a8c46ed0fd2ae1cf851e25aa08b7808fa9 \
    && test -f "$patch_file" \
    && observed_before="$(sha256sum "$patch_file" | cut -d' ' -f1)" \
    && if [ "$observed_before" = "$before_patch" ]; then \
         sed -i \
           's/from paddleformers\.trl\.llm_utils import/from paddleformers.cli.utils.llm_utils import/' \
           "$patch_file"; \
       elif [ "$observed_before" != "$after_patch" ]; then \
         echo "unexpected FastDeploy compatibility target hash: $observed_before" >&2; \
         exit 31; \
       fi \
    && observed_after="$(sha256sum "$patch_file" | cut -d' ' -f1)" \
    && if [ "$observed_after" != "$after_patch" ]; then \
         echo "FastDeploy compatibility patch hash mismatch: $observed_after" >&2; \
         exit 32; \
       fi

# Verify all 6 pinned package versions at build time (fail closed), mirroring
# the inline check in remote_bootstrap_paddle_recovery.sh lines ~67-83.
RUN /opt/folynta/venv/bin/python - <<'PY'
import importlib.metadata

expected = {
    "paddlepaddle-gpu": "3.2.1",
    "paddleocr": "3.7.0",
    "paddlex": "3.7.2",
    "fastdeploy-gpu": "2.3.0",
    "paddleformers": "1.2.0",
    "protobuf": "6.33.6",
}
observed = {name: importlib.metadata.version(name) for name in expected}
if observed != expected:
    raise SystemExit(f"image dependency mismatch: {observed!r}")
PY

# Download the pinned model revision, lock file permissions, then run the
# frozen artifact_manifest.py against it and assert the output hash equals
# the pinned ARTIFACT_MANIFEST_SHA256 (fail closed).
RUN /opt/folynta/venv/bin/python - <<PY
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="PaddlePaddle/PaddleOCR-VL-1.6",
    revision="${MODEL_REVISION}",
    local_dir="${FOLYNTA_MODEL_ROOT}",
)
PY
COPY benchmark/runpod_eval/artifact_manifest.py /opt/folynta/artifact_manifest.py
RUN find "${FOLYNTA_MODEL_ROOT}" -type f -exec chmod 0444 {} + \
    && /opt/folynta/venv/bin/python /opt/folynta/artifact_manifest.py \
         --root "${FOLYNTA_MODEL_ROOT}" \
         --output /opt/folynta/model-artifact-manifest.json \
         --identity "PaddlePaddle/PaddleOCR-VL-1.6@${MODEL_REVISION}" \
         --exclude-prefix .cache \
    && observed_artifact="$(sha256sum /opt/folynta/model-artifact-manifest.json | cut -d' ' -f1)" \
    && if [ "$observed_artifact" != "${ARTIFACT_MANIFEST_SHA256}" ]; then \
         echo "PaddleOCR-VL artifact manifest hash mismatch: $observed_artifact" >&2; \
         exit 35; \
       fi \
    && chmod 0444 /opt/folynta/model-artifact-manifest.json /opt/folynta/artifact_manifest.py

# Copy the 3 pinned runner files and assert each against the exact sha256 pin
# read from research/experiments/SEM-RISK-CONF-02/protocol.json's
# `source_hashes` map (verified against the live file 2026-08-31). This
# proves the image can never silently drift from the frozen runner code.
COPY benchmark/runpod_eval/paddleocr_vl_stage2.py /opt/folynta/runner/paddleocr_vl_stage2.py
COPY benchmark/runpod_eval/input_contract.py /opt/folynta/runner/input_contract.py
COPY benchmark/runpod_eval/isolated_case_process.py /opt/folynta/runner/isolated_case_process.py
RUN set -e \
    && check() { \
         observed="$(sha256sum "$1" | cut -d' ' -f1)"; \
         if [ "$observed" != "$2" ]; then \
           echo "runner file hash mismatch for $1: observed=$observed expected=$2" >&2; \
           exit 36; \
         fi; \
       } \
    && check /opt/folynta/runner/paddleocr_vl_stage2.py 414b5b876f71c527e0c2ac3baadde37dca53fb9d49d5eb270501c5ba71c8f120 \
    && check /opt/folynta/runner/input_contract.py 497bada5cba15af8d45a9aca243b58445b975fd84f11ac8d9863e897c51ba310 \
    && check /opt/folynta/runner/isolated_case_process.py 05559dba43b6c250dcf8f077600f48e72dfd0238af3c137836e32d7667a34372 \
    && chmod 0444 /opt/folynta/runner/*.py

# D2 smoke fixture. Produced by a parallel agent under
# infra/runpod/v6/qualification/rq-01/fixtures/rq-01-smoke-001.png; referenced
# by its expected final path. Not required to exist for this definitions-only
# round -- the image is not built in this round.
COPY infra/runpod/v6/qualification/rq-01/fixtures/rq-01-smoke-001.png /opt/folynta/fixtures/rq-01-smoke-001.png

COPY infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/backend-config.yaml /opt/folynta/backend-config.yaml
COPY infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/verify-runtime.sh /opt/folynta/verify-runtime.sh
COPY infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/start-ssh.sh /opt/folynta/start-ssh.sh
RUN chmod 0555 /opt/folynta/verify-runtime.sh /opt/folynta/start-ssh.sh \
    && chmod 0444 /opt/folynta/backend-config.yaml /opt/folynta/fixtures/rq-01-smoke-001.png \
    && { \
      echo "base_image=runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84"; \
      echo "model_revision=${MODEL_REVISION}"; \
      echo "artifact_manifest_sha256=sha256:${ARTIFACT_MANIFEST_SHA256}"; \
      echo "compatibility_patch_before_sha256=sha256:b50570cb2c13f29f2a7f8803d6bdb3368111e906152425f9666d0ca4818a396d"; \
      echo "compatibility_patch_after_sha256=sha256:3be4e76c7e0fedd11c77eb5a704763a8c46ed0fd2ae1cf851e25aa08b7808fa9"; \
      python3 --version; \
      /opt/folynta/venv/bin/python -m pip freeze | LC_ALL=C sort; \
    } > /opt/folynta/baked-runtime-receipt.txt \
    && chmod 0444 /opt/folynta/baked-runtime-receipt.txt \
    && sha256sum /opt/folynta/baked-runtime-receipt.txt | cut -d' ' -f1 \
         > /opt/folynta/baked-runtime-receipt.sha256 \
    && chmod 0444 /opt/folynta/baked-runtime-receipt.sha256

EXPOSE 22
ENTRYPOINT ["/opt/folynta/start-ssh.sh"]
