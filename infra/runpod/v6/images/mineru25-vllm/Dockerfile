# syntax=docker/dockerfile:1.7
# C3 MinerU2.5-Pro-2605-1.2B serving image (WO-D10-0E). Not built or pushed by the work order
# that wrote it.
#
# The pinned public vLLM 0.22.1 image plus one package, mineru-vl-utils 2.0.9 (Apache-2.0;
# intake row tool_mineru_vl_utils), because the model card's vLLM example loads its
# MinerULogitsProcessor. It is installed from its wheel by hash and without dependencies: if
# the processor needs a package the base image lacks, the import check below fails the build,
# and that package is pinned here by hash, with its own intake row, before anything is served.
# Weights are not baked: as for every A0 candidate they are downloaded at start, checksummed
# on the pod, then served with the hub offline.
#
# Launch (the served name is what the runner `mineru_vlm` attests):
#   vllm serve <weights dir> \
#     --served-model-name opendatalab/MinerU2.5-Pro-2605-1.2B@bff20d4ae2bf202df9f45284b4d43681555a97ed \
#     --logits-processors mineru_vl_utils:MinerULogitsProcessor
FROM vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05

USER root
COPY infra/runpod/v6/images/mineru25-vllm/requirements.txt /opt/folynta/mineru25-requirements.txt
RUN python3 -m pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
      -r /opt/folynta/mineru25-requirements.txt

# The processor must import, and must be the vLLM v1 LogitsProcessor that `vllm serve
# --logits-processors <module:Class>` requires (docs.vllm.ai v0.22.1, custom logits processors).
RUN python3 - <<'PY'
from importlib.metadata import version

expected = {"vllm": "0.22.1", "mineru-vl-utils": "2.0.9"}
actual = {name: version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"image dependency mismatch: {actual!r}")

from mineru_vl_utils import MinerULogitsProcessor
from vllm.v1.sample.logits_processor import LogitsProcessor

if not issubclass(MinerULogitsProcessor, LogitsProcessor):
    raise SystemExit("MinerULogitsProcessor is not a vLLM v1 LogitsProcessor")
PY

RUN { \
      echo "base_image=vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05"; \
      grep -v '^#' /opt/folynta/mineru25-requirements.txt; \
      python3 --version; \
      python3 -m pip freeze | LC_ALL=C sort; \
    } > /opt/folynta/baked-runtime-receipt.txt \
    && chmod 0444 /opt/folynta/baked-runtime-receipt.txt
