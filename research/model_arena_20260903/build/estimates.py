"""Hand-curated, explicitly unmeasured per-model build estimates.

Every number in ``PER_MODEL_ESTIMATES`` is an engineering guess derived from
public, general knowledge about each model family's parameter count and the
base image's own known footprint (vLLM/PyTorch/CUDA base images are public
and their sizes are common knowledge) -- never from a Hugging Face API call,
never from downloading a weight file, and never presented as measured. No
value here is ``calibrated`` in the repo's sense (CLAUDE.md: "No threshold
here is calibrated"); every entry carries ``estimate_confidence`` and the
first real build of that model_key must update this file's numbers with the
observed size/build-time, then rerun ``generate_build_plan.py`` to refresh
``build/build_plan.json`` -- never hand-edit the generated JSON directly.

Do not add a 12th key here beyond ``arena.constants.GPU_MODEL_KEYS`` and do
not invent a number for a key this module does not name.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class SizeEstimate:
    estimated_image_gb: float
    estimated_build_minutes: int
    weights_size_gb: float | None
    weights_size_reason: str
    estimate_confidence: str  # "low" | "unmeasured_placeholder"
    estimate_method: str
    risks: tuple[str, ...]


_BASE_RISK = (
    "estimated_image_gb and estimated_build_minutes are engineering guesses, "
    "not measurements; no image in this campaign has been built yet.",
)

PER_MODEL_ESTIMATES: MappingProxyType[str, SizeEstimate] = MappingProxyType(
    {
        "paddleocr_vl_1_6": SizeEstimate(
            estimated_image_gb=14.0,
            estimated_build_minutes=12,
            weights_size_gb=2.0,
            weights_size_reason=(
                "PaddleOCR-VL-1.6 is a ~0.9B-parameter VLM (NaViT vision encoder + "
                "ERNIE-4.5-0.3B decoder per the model card); ~2GB bf16 is a rough "
                "order-of-magnitude, not a measured artifact size."
            ),
            estimate_confidence="low",
            estimate_method=(
                "base image is the official PaddleOCR-VL Docker image, which already "
                "bundles PaddlePaddle + CUDA + the pipeline stages; image_gb assumes "
                "that stack (~10-12GB observed for comparable Paddle GPU images) plus "
                "the ~2GB VLM weights and our thin worker layer."
            ),
            risks=(
                *_BASE_RISK,
                "base_image is the digest-pinned official "
                "'paddleocr-vl:paddleocr3.6-nvidia-gpu' image (ARENA_CONTRACT D43: "
                "PaddleOCR v3.6.0 is the release that shipped PaddleOCR-VL-1.6; no "
                "3.7 VL image exists upstream). Residual risk: "
                "'paddleocr install_genai_server_deps vllm' resolves unpinned "
                "paddlex/transformers versions after the version assertion; the "
                "canary's bootstrap-pip-freeze.txt is the record of what it moved.",
            ),
        ),
        "mineru_pipeline": SizeEstimate(
            estimated_image_gb=13.0,
            estimated_build_minutes=18,
            weights_size_gb=3.0,
            weights_size_reason=(
                "MinerU pipeline mode composes several small models (layout, formula, "
                "table, PP-OCRv6 text) rather than one LLM; combined weights are "
                "commonly a few GB. Not measured."
            ),
            estimate_confidence="low",
            estimate_method=(
                "base image vllm/vllm-openai:v0.21.0 (~8GB observed for recent vLLM "
                "OpenAI images) plus MinerU's own pip dependencies and small-model "
                "weights."
            ),
            risks=_BASE_RISK,
        ),
        "mineru_vlm": SizeEstimate(
            estimated_image_gb=11.0,
            estimated_build_minutes=15,
            weights_size_gb=2.5,
            weights_size_reason=(
                "MinerU2.5-Pro-2605-1.2B is a 1.2B-parameter model; ~2.5GB bf16 is an "
                "order-of-magnitude estimate, not measured."
            ),
            estimate_confidence="low",
            estimate_method=(
                "same vllm-openai:v0.21.0 base as mineru_pipeline plus the 1.2B checkpoint."
            ),
            risks=(
                *_BASE_RISK,
                "MASTERPLAN SECTION 14 history: this exact model previously failed "
                "48/54 pages at worker concurrency 3. The build plan does not change "
                "that; max_concurrency_per_worker stays 1 regardless of image size.",
            ),
        ),
        "deepseek_ocr2": SizeEstimate(
            estimated_image_gb=17.0,
            estimated_build_minutes=25,
            weights_size_gb=6.0,
            weights_size_reason=(
                "DeepSeek-OCR-2 is publicly described as a small (few-billion "
                "parameter class) OCR-specialist decoder; ~6GB bf16 is a rough order "
                "of magnitude, not measured."
            ),
            estimate_confidence="low",
            estimate_method=(
                "base image pytorch/pytorch:2.6.0-cuda11.8-cudnn9-devel is a *devel* "
                "(not runtime) image bundling the full CUDA toolkit and compilers, "
                "commonly 8-10GB by itself -- larger than the vLLM-based lanes."
            ),
            risks=_BASE_RISK,
        ),
        "ovisocr2": SizeEstimate(
            estimated_image_gb=24.0,
            estimated_build_minutes=30,
            weights_size_gb=16.0,
            weights_size_reason=(
                "gpu_min_vram_gb=24 in runtime.json bounds the checkpoint plus KV "
                "cache to a 24GB card; ~16GB bf16 weights is a headroom-based guess, "
                "not a measured artifact size."
            ),
            estimate_confidence="low",
            estimate_method="vllm-openai base (~8GB) plus a headroom-derived weights guess.",
            risks=(
                *_BASE_RISK,
                "Masterplan section 4 / hypothesis H3 flags a historical discrepancy: "
                "the 2026-08 TAVONEL measurement of this model was abnormally low "
                "against the vendor's own OmniDocBench score. A build-time size "
                "estimate has no bearing on that open question.",
            ),
        ),
        "unlimited_ocr": SizeEstimate(
            estimated_image_gb=21.0,
            estimated_build_minutes=28,
            weights_size_gb=14.0,
            weights_size_reason=(
                "gpu_min_vram_gb=24 bounds the model; ~14GB bf16 weights is a "
                "headroom-based guess, not measured."
            ),
            estimate_confidence="low",
            estimate_method=(
                "base image nvidia/cuda:...-cudnn-runtime (a *runtime*, not devel, "
                "CUDA image, ~3-4GB) plus a from-scratch pip install of torch + "
                "transformers (no pre-baked ML framework in this base, unlike the "
                "vLLM/PyTorch-based lanes), which itself adds several GB."
            ),
            risks=_BASE_RISK,
        ),
        "infinity_parser2_pro": SizeEstimate(
            estimated_image_gb=10.0,
            estimated_build_minutes=15,
            weights_size_gb=75.0,
            weights_size_reason=(
                "runtime.json's own notes give an HF blob-listing total of "
                "70,214,492,328 bytes (70.21GB) of safetensors across 15 shards for "
                "this checkpoint -- that figure is recorded by lane C3 from a source, "
                "not invented here; 75GB rounds it up for filesystem overhead. Because "
                "weights_strategy is volume_cache (not baked), this size does NOT sit "
                "inside estimated_image_gb."
            ),
            estimate_confidence="low",
            estimate_method=(
                "runtime.json states explicitly: 'a baked image would be roughly "
                "75GB'; C3 chose volume_cache specifically to avoid that, so the "
                "*image* build here is base (~8GB vLLM-openai) plus worker code only."
            ),
            risks=(
                *_BASE_RISK,
                "gpu_min_vram_gb=160 is an AGGREGATE across two 80GB devices per "
                "runtime.json (tensor-parallel-size 2), not a single-card figure; the "
                "builder pod does not need a GPU at all, but the eventual inference "
                "pods for this model_key are the most expensive in the portfolio.",
                "70-75GB of weights must be populated onto a RunPod network volume "
                "before any canary; that population step is a real download this "
                "phase does not perform (no lane downloads model weights yet).",
            ),
        ),
        "monkeyocrv2_b": SizeEstimate(
            estimated_image_gb=13.0,
            estimated_build_minutes=18,
            weights_size_gb=2.1,
            weights_size_reason=(
                "runtime.json's own notes give a measured 1,755,925,032 bytes of "
                "safetensors plus 293MB of preprocessor files = 2.05GB, recorded by "
                "lane C3 from the HF blob listing -- carried through here, not "
                "invented by this module."
            ),
            estimate_confidence="low",
            estimate_method=(
                "vllm-openai:v0.11.2 base (~6GB, an older/smaller vLLM image) plus the "
                "2.05GB weights."
            ),
            risks=_BASE_RISK,
        ),
        "olmocr2": SizeEstimate(
            estimated_image_gb=14.0,
            estimated_build_minutes=20,
            weights_size_gb=10.06,
            weights_size_reason=(
                "runtime.json's own notes give a measured 10,061,929,760 bytes "
                "(10.06GB) of FP8 safetensors from the HF blob listing, recorded by "
                "lane C3 -- carried through here, not invented by this module."
            ),
            estimate_confidence="low",
            estimate_method=(
                "same vllm-openai:v0.11.2 base as monkeyocrv2_b plus the 10.06GB FP8 checkpoint."
            ),
            risks=(
                *_BASE_RISK,
                "runtime.json flags that native FP8 execution needs compute "
                "capability >= 8.9 (Ada/Hopper); an Ampere A40 build target would "
                "silently change numeric behaviour, not just speed. This build plan "
                "does not resolve that; it is a canary-time question.",
            ),
        ),
        "hpd_parsing": SizeEstimate(
            estimated_image_gb=140.0,
            estimated_build_minutes=10,
            weights_size_gb=None,
            weights_size_reason=(
                "the '-offline' base image tag is the official vendor's self-"
                "contained bundle; its weights are already inside the base image "
                "layers rather than added by this build, and their standalone size "
                "has not been measured independently -- null with this reason rather "
                "than a fabricated split."
            ),
            estimate_confidence="unmeasured_placeholder",
            estimate_method=(
                "gpu_min_vram_gb=160 for the official offline-bundled image implies a "
                "very large baked artifact; 140GB matches the '100-150GB for the "
                "largest images' band this lane brief names, not a pulled/measured "
                "manifest size."
            ),
            risks=(
                *_BASE_RISK,
                "base_image tag ':latest-nvidia-gpu-offline' is a floating tag on "
                "Baidu's CCR/Harbor registry; it currently resolves (confirmed by an "
                "anonymous manifest GET on generation) but is not digest-pinned in "
                "runtimes/hpd_parsing/runtime.json, violating the frozen "
                "runtime.schema.json base_image pattern and risking a silent upstream "
                "content change between build and canary.",
                "pulling and re-pushing a ~140GB image needs a builder pod disk far "
                "above the other lanes' -- this is the model that drives the "
                "100-150GB disk floor in BUILD_PLAN.md.",
            ),
        ),
        "glm_ocr": SizeEstimate(
            estimated_image_gb=16.0,
            estimated_build_minutes=22,
            weights_size_gb=9.0,
            weights_size_reason=(
                "GLM-OCR is a compact specialist OCR checkpoint; ~9GB bf16 is an "
                "order-of-magnitude guess, not measured."
            ),
            estimate_confidence="low",
            estimate_method=(
                "vllm-openai:v0.19.0 base (~7GB) plus an order-of-magnitude weights guess."
            ),
            risks=_BASE_RISK,
        ),
    }
)


__all__ = ["PER_MODEL_ESTIMATES", "SizeEstimate"]
