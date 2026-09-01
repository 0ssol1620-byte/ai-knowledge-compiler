# syntax=docker/dockerfile:1.7
#
# RESEARCH COMPARATOR ONLY. Not eligible for commercial promotion.
# research/experiments/SEM-RISK-CONF-02/protocol.json forbidden ==>
#   "mineru_commercial_promotion_from_this_experiment": true
# benchmark/v6/candidate-registry.yaml mineru-3.4.4-vlm.license ==>
#   { id: "AGPL-3.0-or-upstream-current", status: review_required, commercial_use: unknown }
# See README.md in this directory for the full research-only rationale.
FROM runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84

# Base image digest precedent: this exact digest is already pinned for MinerU
# provisioning in this repo at
# tools/release/provision_folynta_mineru_recovery_worker.ps1:148. Torch and
# torchvision are reinstalled below to the frozen cu128 versions the bootstrap
# recipe pins (infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh:13-15),
# so whatever torch ships in the base image is not relied upon.

LABEL org.opencontainers.image.licenses="AGPL-3.0-or-upstream-current" \
      folynta.research_comparator_only="true" \
      folynta.commercial_promotion="forbidden" \
      folynta.license_status="review_required" \
      folynta.license_note="research/experiments/SEM-RISK-CONF-02/protocol.json forbidden.mineru_commercial_promotion_from_this_experiment=true; benchmark/v6/candidate-registry.yaml mineru-3.4.4-vlm.license.commercial_use=unknown"

# Two independent identities that must never be conflated:
#   SOURCE_REVISION -> opendatalab/MinerU (source checkout, git clone + detach)
#   MODEL_REVISION  -> opendatalab/MinerU2.5-Pro-2605-1.2B (HF weights snapshot_download)
# Confirmed at infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh:8-9,28-37
# and cross-verified against
# tools/release/provision_folynta_mineru_recovery_worker.ps1, which asserts both
# revisions separately and asserts the artifact manifest hash corresponds to the
# WEIGHTS revision, not the source revision.
ARG SOURCE_REVISION=79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7
ARG MODEL_REVISION=bff20d4ae2bf202df9f45284b4d43681555a97ed
ARG ARTIFACT_MANIFEST_SHA256=sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84

ENV DEBIAN_FRONTEND=noninteractive \
    FOLYNTA_SOURCE_ROOT=/opt/folynta/MinerU \
    FOLYNTA_MODEL_ROOT=/opt/folynta/models/MinerU2.5-Pro-2605-1.2B \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    SOURCE_REVISION=${SOURCE_REVISION} \
    MODEL_REVISION=${MODEL_REVISION} \
    ARTIFACT_MANIFEST_SHA256=${ARTIFACT_MANIFEST_SHA256} \
    MINERU_API_MAX_CONCURRENT_REQUESTS=1

# The base image ships two interpreters: `pip` resolves to the CUDA-enabled
# python3.12 under /usr/local/lib/python3.12/dist-packages, while bare `python3`
# resolves to the distro's python3.10. A build on 2026-09-01 installed
# torch==2.8.0 successfully with `pip` and then failed the very next layer with
# `PackageNotFoundError: No package metadata was found for torch`, because the
# dependency assertion ran under 3.10 and could not see what 3.12 had installed.
#
# FOLYNTA_PYTHON pins every interpreter invocation in this image -- build-time
# assertions, the artifact manifest tool, and the runtime verifier -- to the same
# interpreter pip installs into. The sibling paddleocr image solves the same
# problem with an explicit venv; this image cannot use one because MinerU is
# installed against the base image's preinstalled CUDA torch build.
ENV FOLYNTA_PYTHON=/usr/bin/python3.12
RUN test -x "${FOLYNTA_PYTHON}" \
    && "${FOLYNTA_PYTHON}" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'

USER root
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends openssh-server git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /root/.ssh "${FOLYNTA_MODEL_ROOT}"

# Pinned exactly as infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh:13-15.
RUN "${FOLYNTA_PYTHON}" -m pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cu128 \
      'torch==2.8.0' 'torchvision==0.23.0'

# SOURCE_REVISION only -- this is the code checkout, never the weights.
RUN git clone --filter=blob:none --no-checkout https://github.com/opendatalab/MinerU.git "${FOLYNTA_SOURCE_ROOT}" \
    && git -C "${FOLYNTA_SOURCE_ROOT}" checkout --detach "${SOURCE_REVISION}" \
    && test "$(git -C "${FOLYNTA_SOURCE_ROOT}" rev-parse HEAD)" = "${SOURCE_REVISION}"

# Pinned exactly as infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh:22-26.
RUN "${FOLYNTA_PYTHON}" -m pip install --no-cache-dir \
      'accelerate==1.14.0' \
      'transformers==4.57.3' \
      'mineru-vl-utils==1.0.5' \
      "${FOLYNTA_SOURCE_ROOT}[core]"
# OS-layer remediation: kernel headers.
#
# The 2026-09-01 scan flagged 21 CRITICAL kernel CVEs against
# linux-libc-dev 5.15.0-157.167 as shipped in the base image. The highest fix
# any of them requires is 5.15.0-187.197, and jammy-security currently carries
# 5.15.0-190.200 -- checked against the live Ubuntu package index, not assumed
# -- so a single-package upgrade clears all 21.
#
# This is deliberately preferred over the two alternatives. Replacing the
# pinned base image digest would break the claim that the confirmatory run
# uses the same runtime as the 2026-08-01 measurements. Scoping the scanner to
# skip OS packages would turn the receipt's "zero critical vulnerabilities"
# into "zero outside the OS layer" without saying so.
#
# linux-libc-dev is kernel headers: a build-time artifact. Containers run on
# the host kernel, so this upgrades no executable code in the image, and the
# package is absent from verify-runtime.sh, the 2026-08-01 concurrency
# diagnostic manifest and benchmark/v6/candidate-registry.yaml -- it is not
# part of the frozen runtime identity.
RUN apt-get update -qq \
 && apt-get install -y -qq --only-upgrade linux-libc-dev \
 && rm -rf /var/lib/apt/lists/* \
 && installed="$(dpkg-query -W -f='${Version}' linux-libc-dev)" \
 && echo "linux-libc-dev ${installed}" \
 && dpkg --compare-versions "${installed}" ge "5.15.0-187.197" \
      || { echo "linux-libc-dev ${installed} still below 5.15.0-187.197" >&2; exit 1; }

# Attack-surface removal: delete vendor tooling this runtime never uses.
#
# The 2026-09-01 scan flagged four CRITICAL findings in binaries that arrive
# in the runpod/pytorch base image and are referenced nowhere in this one:
#
#   /usr/local/bin/filebrowser        CVE-2026-56854  golang.org/x/crypto/ssh
#                                     authentication bypass
#                                     CVE-2025-68121  Go stdlib
#   /opt/nvidia/nsight-compute        CVE-2024-24790, CVE-2025-68121
#                                     Go stdlib in a bundled profiler plugin
#
# ENTRYPOINT is start-ssh.sh, which validates PUBLIC_KEY and execs sshd. No
# script, no stage, and no runtime path in this image invokes either tool.
#
# Deletion beats upgrading: an unused binary that is gone has no attack
# surface, and an SSH authentication-bypass binary sitting in PATH on a host we
# reach over SSH is worth removing on the merits, independent of the gate.
# Neither package is part of the frozen runtime identity -- neither appears in
# verify-runtime.sh, the 2026-08-01 concurrency diagnostic manifest, nor
# benchmark/v6/candidate-registry.yaml -- so removal cannot change what the
# confirmatory run may claim about matching the 2026-08-01 runtime.
RUN rm -rf /usr/local/bin/filebrowser /opt/nvidia/nsight-compute \
 && test ! -e /usr/local/bin/filebrowser \
 && test ! -e /opt/nvidia/nsight-compute \
 && echo "removed unused vendor tooling: filebrowser, nsight-compute"

# Security remediation, not a capability pin.
#
# The runpod/pytorch base image ships a Jupyter stack this runtime never uses.
# Three packages in it carry CRITICAL advisories with fixes available, and they
# blocked this image's Trivy gate (severity=CRITICAL, ignore-unfixed=true) on
# 2026-09-01:
#
#   jupyter-server 2.17.0  GHSA-fcw5-x6j4-ccmp / CVE-2026-44727
#                          stored XSS in the nbconvert handlers, missing
#                          sandbox CSP directive          -> fixed in 2.20.0
#   jupyterlab     4.4.9   GHSA-mqcg-5x36-vfcg / CVE-2026-42557
#   notebook       7.4.2   command-linker attributes in HTML allow one-click
#                          command execution from untrusted content, CVSS 9.6
#                                                         -> 4.5.7 / 7.5.6
#
# None of these are ours. They arrive in the base image; this Dockerfile never
# installs them. None is part of the frozen runtime identity: they appear in
# neither verify-runtime.sh, the 2026-08-01 concurrency diagnostic manifest,
# nor benchmark/v6/candidate-registry.yaml. Upgrading them therefore cannot
# change what the confirmatory run may claim about running the same runtime as
# the 2026-08-01 measurements -- unlike torch or transformers, which are pinned
# above and must not move.
#
# The image never serves a Jupyter UI: ENTRYPOINT is start-ssh.sh and this is a
# headless inference runtime, so all three attack surfaces are unreachable
# here. That is a reason the real-world risk is low. It is NOT a reason to
# suppress the gate: the qualification receipt asserts zero critical
# vulnerabilities, and an assertion that is quietly false is worth less than no
# assertion at all.
#
# Upgraded as one pip invocation so the resolver settles them together, then
# verified inline -- a constraint that silently fails to apply must not pass as
# remediation.
RUN "${FOLYNTA_PYTHON}" -m pip install --no-cache-dir --upgrade \
      'jupyter-server>=2.20.0' \
      'jupyterlab>=4.5.7' \
      'notebook>=7.5.6' \
 && "${FOLYNTA_PYTHON}" - <<'PY'
from importlib.metadata import version

required = {
    "jupyter_server": (2, 20),
    "jupyterlab": (4, 5, 7),
    "notebook": (7, 5, 6),
}
problems = []
for dist, minimum in required.items():
    installed = version(dist)
    parts = tuple(int(p) for p in installed.split(".")[: len(minimum)] if p.isdigit())
    if parts < minimum:
        problems.append(
            f"{dist} {installed} below {'.'.join(str(n) for n in minimum)}"
        )
    else:
        print(f"{dist} {installed} clears its advisory")
if problems:
    raise SystemExit("; ".join(problems))
PY

RUN "${FOLYNTA_PYTHON}" - <<'PY'
from importlib.metadata import version

# torch and torchvision come from the cu128 wheel index, so their installed
# versions carry a PEP 440 local version identifier ("2.8.0+cu128"). That
# suffix is the CUDA build tag, not a different release, and it is exactly the
# build this image is supposed to contain -- asserting bare equality against
# "2.8.0" rejected the correct wheel on 2026-09-01.
#
# The public version (everything left of "+") is still compared exactly, so a
# drift from 2.8.0 to 2.8.1 still fails. The local tag is compared separately
# against the index this Dockerfile pins, so a CPU-only or cu126 wheel silently
# substituted for the cu128 one also fails.
pinned = {
    "torch": ("2.8.0", "cu128"),
    "torchvision": ("0.23.0", "cu128"),
    "accelerate": ("1.14.0", None),
    "transformers": ("4.57.3", None),
    "mineru-vl-utils": ("1.0.5", None),
}
mismatches = {}
for name, (expected_public, expected_local) in pinned.items():
    installed = version(name)
    public, _, local = installed.partition("+")
    if public != expected_public or (local or None) != expected_local:
        mismatches[name] = installed
if mismatches:
    raise SystemExit(f"image dependency mismatch: {mismatches!r}")
# mineru is installed from the pinned SOURCE_REVISION checkout, not a released
# version number, so it has no fixed version string to assert against.
version("mineru")
PY

# MODEL_REVISION only -- this is the weights snapshot, never the source checkout.
RUN "${FOLYNTA_PYTHON}" - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="opendatalab/MinerU2.5-Pro-2605-1.2B",
    revision=os.environ["MODEL_REVISION"],
    local_dir=os.environ["FOLYNTA_MODEL_ROOT"],
)
PY
RUN find "${FOLYNTA_MODEL_ROOT}" -type f -exec chmod 0444 {} +

# Assert the downloaded weights match the frozen artifact manifest hash. The
# manifest is content over the WEIGHTS revision (MODEL_REVISION), matching
# benchmark/v6/candidate-registry.yaml mineru-3.4.4-vlm.identity.artifact_sha256.
#
# --exclude-prefix .cache is REQUIRED, and omitting it is what failed the
# 2026-09-01 build with
#   artifact manifest sha256 mismatch:
#     'sha256:99ee63b7...' != 'sha256:1611a889...'
# The weights were never in question: the Hugging Face API for revision
# bff20d4a reports exactly 13 files totalling 2,328,028,720 bytes, matching the
# 2026-08-01 evaluation record byte for byte. What differed is that
# snapshot_download also writes .cache/huggingface/ download metadata into
# local_dir, so hashing it made the manifest a function of the huggingface_hub
# release instead of the model.
#
# Both sibling bootstraps already exclude it for exactly this reason -- see
# remote_bootstrap_paddle_recovery.sh:134-141 and
# remote_bootstrap_deepseek_recovery.sh:18,69 ("varies across huggingface_hub
# releases and is not model content"). This image was the one that did not.
#
# The frozen constant was right and this Dockerfile was wrong. Do NOT resolve a
# mismatch here by editing ARTIFACT_MANIFEST_SHA256 to whatever a build
# observed: that value is pinned in six places including the 2026-08-01
# evaluation report, candidate-registry.yaml, rq-01/lineage.json and
# rq-01/SECURITY_REVIEW.md, and rewriting it would silently sever the claim
# that SEM-RISK-CONF-02 runs on the same model those results describe.
COPY benchmark/runpod_eval/artifact_manifest.py /opt/folynta/artifact_manifest.py
RUN "${FOLYNTA_PYTHON}" /opt/folynta/artifact_manifest.py \
      --root "${FOLYNTA_MODEL_ROOT}" \
      --output /opt/folynta/model-artifact-manifest.json \
      --identity "opendatalab/MinerU2.5-Pro-2605-1.2B@${MODEL_REVISION}" \
      --exclude-prefix .cache \
      > /opt/folynta/model-artifact-manifest-receipt.json \
    && "${FOLYNTA_PYTHON}" - <<'PY'
import json
import os

with open("/opt/folynta/model-artifact-manifest-receipt.json", encoding="utf-8") as handle:
    receipt = json.load(handle)
expected = os.environ["ARTIFACT_MANIFEST_SHA256"]
if receipt["sha256"] != expected:
    raise SystemExit(f"artifact manifest sha256 mismatch: {receipt['sha256']!r} != {expected!r}")
PY

# Exact content shape from
# infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh:39-45. The path
# value uses this image's own FOLYNTA_MODEL_ROOT (the bootstrap script's
# MODEL_ROOT is a runtime-local path; this image bakes an equivalent baked path).
RUN cat > /root/mineru.json <<EOF
{
  "models-dir": {"vlm": "${FOLYNTA_MODEL_ROOT}"},
  "model-source": "local",
  "config_version": "1.3.2"
}
EOF

# Pinned runner files, copied and hash-verified against
# research/experiments/SEM-RISK-CONF-02/protocol.json source_hashes -- never
# edited in place.
COPY benchmark/runpod_eval/mineru_stage2.py benchmark/runpod_eval/input_contract.py /opt/folynta/
RUN printf '%s  %s\n%s  %s\n' \
      "e7d84e289d9ea1b123d4451243a185950af3bf236520eb92c54ea2ba80387c77" "/opt/folynta/mineru_stage2.py" \
      "497bada5cba15af8d45a9aca243b58445b975fd84f11ac8d9863e897c51ba310" "/opt/folynta/input_contract.py" \
      | sha256sum --check --strict

# D2 smoke fixture (built by a parallel worktree agent) -- referenced by path only.
COPY infra/runpod/v6/qualification/rq-01/fixtures/rq-01-smoke-001.png /opt/folynta/fixtures/rq-01-smoke-001.png

COPY infra/runpod/v6/images/mineru-3.4.4-vlm-c1/verify-runtime.sh /opt/folynta/verify-runtime.sh
COPY infra/runpod/v6/images/mineru-3.4.4-vlm-c1/start-ssh.sh /opt/folynta/start-ssh.sh
RUN chmod 0555 /opt/folynta/verify-runtime.sh /opt/folynta/start-ssh.sh \
    && { \
      echo "base_image=runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84"; \
      echo "source_repository=opendatalab/MinerU"; \
      echo "source_revision=${SOURCE_REVISION}"; \
      echo "weights_repository=opendatalab/MinerU2.5-Pro-2605-1.2B"; \
      echo "model_revision=${MODEL_REVISION}"; \
      echo "artifact_manifest_sha256=${ARTIFACT_MANIFEST_SHA256}"; \
      "${FOLYNTA_PYTHON}" --version; \
      "${FOLYNTA_PYTHON}" -m pip freeze | LC_ALL=C sort; \
    } > /opt/folynta/baked-runtime-receipt.txt \
    && chmod 0444 /opt/folynta/baked-runtime-receipt.txt \
    && sha256sum /opt/folynta/baked-runtime-receipt.txt | cut -d' ' -f1 > /opt/folynta/baked-runtime-receipt.sha256 \
    && chmod 0444 /opt/folynta/baked-runtime-receipt.sha256

# NOTE: /opt/folynta/baked-runtime-receipt.sha256 is a build-time constant --
# the known-good hash of /opt/folynta/baked-runtime-receipt.txt as baked into
# this image. verify-runtime.sh compares against THIS constant, never against
# the FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256 env var a provider may set at pod
# creation, which per infra/runpod/v6/pod_client.py PodCreateSpec /
# infra/runpod/v6/runtime_qualification.py BakedRuntimeQualification.receipt_sha256
# is the canonical hash of the whole qualification-receipt OBJECT, not any
# file's hash. benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh (lines ~37-41)
# checks a file hash against that env var -- that is the confirmed defect this
# image's verify-runtime.sh does not repeat.

EXPOSE 22
ENTRYPOINT ["/opt/folynta/start-ssh.sh"]
