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
    && apt-get install -y -qq --no-install-recommends openssh-server ca-certificates curl \
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
# fastdeploy-gpu 2.3.0 is installed from a wheel we rebuilt ourselves, because
# the published wheel no longer exists anywhere reachable:
#
#   PyPI project fastdeploy-gpu                                  404
#   paddle-whl.cdn.bcebos.com stable/cu126 2.3.0 cp310/311/312    404
#   same prefix, 2.5.0 cp310 (control)                            200, 1.77 GB
#   FastDeploy GitHub release v2.3.0                              0 assets
#   network volume o9eslyovmd (held the 2026-08-01 venv)          empty
#
# The control returning 200 on the identical prefix is what makes those 404s
# evidence of withdrawal rather than a wrong URL. See INC-RUNPOD-05.
#
# The replacement was built from tag v2.3.0 (annotated tag b8dd9d64 -> commit
# cba7b2912f3fc046eff6829a647c29cc537b1fc8) on an RTX 4090 with driver
# 570.172.08, because FastDeploy's setup.py imports paddle at build time and
# paddle cannot be imported without libcuda.so.1 -- which is why this cannot be
# built in CI, and why a source install here failed four times.
#
# It reaches the SAME frozen identity, and that is verified rather than
# asserted:
#
#   * the wheel reports version 2.3.0, which is what
#     benchmark/reports/paddleocr-vl-1.6-fastdeploy-runtime-manifest-2026-08-01
#     pins and what the importlib.metadata gate below compares against
#     (FASTDEPLOY_VERSION was set explicitly at build time; setup.py otherwise
#     falls back to 2.3.0-dev)
#   * fastdeploy/input/text_processor.py inside the wheel hashes to
#     b50570cb...a396d, 29,698 bytes -- exactly the pre-patch value the
#     compatibility gate below asserts before applying its sed
#
# The download is digest-checked before pip sees it, so a substituted or
# truncated artifact fails closed rather than silently installing.
#
# This is deliberately NOT a version bump. 2.5.0 is available and would have
# been the one-line fix; it would also void the runtime assertion, the patch
# gate, and the claim that the confirmatory run uses the same runtime as the
# 2026-08-01 measurements.
# Fetch the rebuilt wheel through the authenticated release asset API.
#
# The repository is private, so the plain releases/download URL returns 404
# (GitHub hides private content rather than answering 401). The asset API
# endpoint with a bearer token and Accept: application/octet-stream returns the
# bytes -- verified: HTTP 200, 1,121,709 bytes, sha256 171a1a142fa1462f...
#
# The token is a BuildKit secret mount, never an ARG or ENV, so it is not
# written into any layer and does not appear in `docker history`. That is why
# this is its own RUN: --mount is a directive on RUN and cannot appear midway
# through a chained command.
#
# The digest is checked here, before the install step ever sees the file, so an
# authenticated download of the wrong bytes fails closed.
RUN --mount=type=secret,id=gh_token \
    curl -fsSL \
      -H "Authorization: Bearer $(cat /run/secrets/gh_token)" \
      -H 'Accept: application/octet-stream' \
      -o /opt/folynta/fastdeploy_gpu-2.3.0-py3-none-any.whl \
      'https://api.github.com/repos/0ssol1620-byte/ai-knowledge-compiler/releases/assets/540096418' \
 && echo '171a1a142fa1462f34c21270a0b11da7d921a9580c76673ab9a839d8a71dd5fe  /opt/folynta/fastdeploy_gpu-2.3.0-py3-none-any.whl' | sha256sum -c -

RUN python3.11 -m venv /opt/folynta/venv \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir --quiet --progress-bar off --upgrade 'pip==25.1.1' \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir --quiet --progress-bar off \
         'paddlepaddle-gpu==3.2.1' \
         --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir --quiet --progress-bar off 'paddleocr[doc-parser]==3.7.0' \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir --quiet --progress-bar off \
         'paddleformers==1.2.0' \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir --quiet --progress-bar off \
         /opt/folynta/fastdeploy_gpu-2.3.0-py3-none-any.whl \
    && /opt/folynta/venv/bin/python -m pip install --no-cache-dir --quiet --progress-bar off 'protobuf==6.33.6' \
    && rm -rf /root/.cache/pip

# Why fastdeploy-gpu and paddleformers are installed directly rather than via
# `paddleocr install_genai_server_deps fastdeploy`, which is what
# remote_bootstrap_paddle_recovery.sh:38 calls:
#
# That bootstrap runs ON A GPU POD. The installer imports paddle to inspect the
# device before resolving what to install, and paddle's C extension links
# against the NVIDIA driver. A GitHub Actions runner has no GPU and no driver,
# so on 2026-09-01 the build reached that command and died with
#   ImportError: libcuda.so.1: cannot open shared object file
# That is structural, not a PATH or disk problem: the installer cannot run in
# any GPU-less build environment, and the image build is necessarily GPU-less.
#
# The two packages named here are exactly the two that installer contributes,
# at exactly the versions the bootstrap freezes and this image already asserts
# below (fastdeploy-gpu 2.3.0, paddleformers 1.2.0 -- see the frozen runtime
# check further down, and remote_bootstrap_paddle_recovery.sh:70-80). So this
# does not relax the pin set; it reaches the same frozen versions by a route
# that does not require a device at build time. If the assertion below ever
# fails, that is the check catching a drift this substitution introduced, and
# the substitution is what should be revisited -- not the assertion.

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
# Clear the CRITICAL findings the security gate reports on this base image.
# Measured on 2026-09-01 from the preserved Trivy JSON: 26 CRITICAL, none of
# them in a package this image pins.
#
#   21  linux-libc-dev 5.15.0-157.167   kernel headers
#    1  jupyter_server 2.17.0           stored XSS (GHSA-fcw5-x6j4-ccmp)
#    1  golang.org/x/crypto v0.40.0     SSH auth bypass (CVE-2026-56854)
#    3  stdlib v1.22.3 / v1.24.0        Go binaries
#
# The sibling MinerU image, built from the same base, cleared exactly this set
# and its build receipt reports critical_vulnerability_count: 0. This ports
# that remediation rather than inventing a new one.
#
# Preferred over the alternatives, deliberately. Replacing the pinned base
# image digest would break the claim that the confirmatory run uses the same
# runtime as the 2026-08-01 measurements. Scoping the scanner to skip OS
# packages would turn the receipt's "zero critical vulnerabilities" into "zero
# outside the OS layer" without saying so.
#
# None of these packages appears in verify-runtime.sh, the 2026-08-01 runtime
# manifest, or benchmark/v6/candidate-registry.yaml, so none is part of the
# frozen runtime identity. paddlepaddle-gpu, paddleocr, fastdeploy-gpu and
# paddleformers are untouched.
#
# linux-libc-dev is kernel headers: a build-time artifact. Containers run on
# the host kernel, so upgrading it changes no executable code in the image.
# jammy-security carries 5.15.0-190.200, above the highest required fix of
# 5.15.0-187.197 -- checked against the live Ubuntu index, not assumed.
RUN apt-get update -qq \
 && apt-get install -y -qq --only-upgrade linux-libc-dev \
 && rm -rf /var/lib/apt/lists/* \
 && installed="$(dpkg-query -W -f='${Version}' linux-libc-dev)" \
 && echo "linux-libc-dev ${installed}" \
 && dpkg --compare-versions "$installed" ge 5.15.0-187.197 \
      || { echo "linux-libc-dev ${installed} is below the required 5.15.0-187.197" >&2; exit 33; }

# Jupyter ships in the base image; this image never starts a notebook server
# (ENTRYPOINT is start-ssh.sh), but an unpatched stored-XSS is still a real
# finding and the upgrade is free.
# The scan located the vulnerable copy exactly:
#   usr/local/lib/python3.12/dist-packages/jupyter_server-2.17.0.dist-info
# The previous attempt used `python3` and ended in `2>/dev/null || true`,
# finished in 1.7 seconds, reported success, and left 2.17.0 in place. The
# script addresses python3.12 explicitly, keeps stderr, and fails the build
# if the upgrade does not take.
COPY infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/upgrade-jupyter.sh /tmp/upgrade-jupyter.sh
RUN sh /tmp/upgrade-jupyter.sh && rm -f /tmp/upgrade-jupyter.sh

# filebrowser and nsight-compute are vendor tooling this image never invokes.
# Deleting an unused binary is strictly better than upgrading it: the finding
# disappears and so does the attack surface. CVE-2026-56854 in particular is an
# SSH authentication bypass, and this image is reached over SSH.
RUN rm -rf /usr/local/bin/filebrowser /opt/nvidia/nsight-compute \
 && test ! -e /usr/local/bin/filebrowser \
 && test ! -e /opt/nvidia/nsight-compute \
 && echo "removed unused vendor tooling: filebrowser, nsight-compute"

# Re-assert the pinned runtime AFTER the remediation steps above.
#
# The dependency gate earlier in this file runs before them, so on its own it
# could not see a package moved by a later install. This repeats the check at
# the last point anything could have disturbed it, which is what makes the
# frozen identity a verified property of the finished image rather than of an
# intermediate layer.
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
    raise SystemExit(f"remediation disturbed the pinned runtime: {observed!r}")
print("pinned runtime intact after remediation")
PY

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
