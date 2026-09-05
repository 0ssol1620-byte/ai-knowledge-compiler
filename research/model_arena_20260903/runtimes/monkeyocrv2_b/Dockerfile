# syntax=docker/dockerfile:1.7
# MonkeyOCRv2-B-Parsing arena runtime.
#
# Build context is the namespace root: research/model_arena_20260903/
#   docker build -f runtimes/monkeyocrv2_b/Dockerfile -t <tag> .
#
# vLLM 0.11.2 is the non-DFlash serving path the v2 README documents for systems
# without CUDA 12.9 ("uv pip install vllm==0.11.2 ... Inference will still work
# normally, but DFlash acceleration will not be available"). DFlash is deliberately
# out of scope for this campaign — see runtime.json.notes and README.md.
#
# Sources:
#   https://github.com/Yuliang-Liu/MonkeyOCRv2  (Document Parsing quick start)
#   https://github.com/Yuliang-Liu/MonkeyOCRv2/blob/main/parsing/requirements.txt
#   https://hub.docker.com/r/vllm/vllm-openai/tags  (digest resolved 2026-09-03)
FROM vllm/vllm-openai:v0.11.2@sha256:2c908d5a84ed251b6a17d179f42d06df1aff353007779ac5eecd8a0ea3fe9331

ARG MONKEYOCRV2_REVISION=d46699fb6a4c71d61588e4a71fce03bff4f1ba33

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/arena:/opt/monkeyocrv2/parsing \
    ARENA_MODEL_KEY=monkeyocrv2_b \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/monkeyocrv2_b \
    ARENA_MONKEYOCRV2_DIR=/opt/monkeyocrv2 \
    ARENA_VLLM_PORT=8888 \
    HF_HUB_ENABLE_HF_TRANSFER=0

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# The official runtime, at an exact commit. `git clone` then `checkout` (not a
# branch clone) so the image records the revision it actually built from.
RUN git clone --filter=blob:none https://github.com/Yuliang-Liu/MonkeyOCRv2.git /opt/monkeyocrv2 \
 && git -C /opt/monkeyocrv2 checkout --detach "${MONKEYOCRV2_REVISION}" \
 && git -C /opt/monkeyocrv2 rev-parse HEAD > /opt/monkeyocrv2/.arena_revision \
 && test "$(cat /opt/monkeyocrv2/.arena_revision)" = "${MONKEYOCRV2_REVISION}"

# D58 upstream patch: parsing/serve.py compares `installed == (0, 11)` against
# `vllm_version_tuple()`, which parses the full installed version into a
# (major, minor, patch) tuple. A 3-tuple never equals the vendor's literal
# 2-tuple, so the vendor's own documented legacy install (README: "pip install
# vllm==0.11.2" for systems without CUDA 12.9 / DFlash) always falls through to
# `raise SystemExit("Unsupported vLLM version: ...")`. Widen the comparison to
# major.minor, matching what the vendor's own message says it wants
# ("==0.11 for legacy support"). See ARENA_CONTRACT.md section 11.7 D58.
RUN sed -i \
        's/^if installed == (0, 11):$/if installed[:2] == (0, 11):  # ARENA D58 patch: vllm_version_tuple() returns a full (major, minor, patch) tuple; upstream compared it to a 2-tuple, so no released 0.11.x ever matched/' \
        /opt/monkeyocrv2/parsing/serve.py \
 && grep -q '^if installed\[:2\] == (0, 11):' /opt/monkeyocrv2/parsing/serve.py

# parsing/requirements.txt pins gradio==5.30.0 and pypdfium2==5.10.1. Only
# pypdfium2 is installed: gradio is imported by demo/gradio_demo.py alone and
# core_runner.py does not touch it, so pulling its dependency tree into a headless
# worker would add unpinned transitive packages to a pinned image. Stated here, not
# silently skipped (see runtime.json.notes).
RUN python3 -m pip install --no-cache-dir "pypdfium2==5.10.1"

WORKDIR /opt/arena

COPY arena/ /opt/arena/arena/
# D17: the prompt registry travels with the image; the worker resolves
# /opt/arena/prompt_registry/<prompt_id>.txt and fails closed when it is missing.
COPY prompt_registry/ /opt/arena/prompt_registry/
COPY runtimes/monkeyocrv2_b/ /opt/arena/runtime/

# weights_strategy is baked: 2.05 GB, small enough that every replica should start
# from the image rather than a download (masterplan 15.1/15.2).
RUN python3 /opt/arena/runtime/fetch_weights.py \
        --weights-dir /opt/arena/weights/monkeyocrv2_b \
        --manifest

# Fail the build if the pieces the adapter drives are not importable, or if the
# vLLM registration module for this vLLM major is missing.
RUN python3 - <<'PY'
import importlib, sys
sys.path.insert(0, "/opt/monkeyocrv2/parsing")
import vllm
assert vllm.__version__.startswith("0.11.2"), vllm.__version__
importlib.import_module("modeling.modeling_monkeyocrv2_vllm_011")
core_runner = importlib.import_module("core_runner")
for name in ("BackendConfig", "PipelineConfig", "run_pipeline", "ALL_PROMPT"):
    assert hasattr(core_runner, name), name
print("core_runner prompts:", sorted(core_runner.ALL_PROMPT))
PY

RUN python3 -c "import arena.constants as c; assert 'monkeyocrv2_b' in c.MODEL_KEYS" \
 && chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

EXPOSE 8000
ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]
