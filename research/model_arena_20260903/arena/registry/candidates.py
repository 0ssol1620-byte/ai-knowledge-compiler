"""Frozen candidate specification for the arena models (incl. Infinity-Parser2-Flash).

Everything here that is a *number the campaign will act on* comes from an
official source that is named in ``official_source_urls`` and recorded in a
fixture under ``tests/registry/fixtures/``. Everything that is an *estimate*
carries ``estimated: True`` and a ``basis`` string naming what it was derived
from. Nothing is invented: a field the upstream does not document is ``None``
with a matching ``*_unresolved_reason``.

Sizing rule for ``gpu_min_vram_gb`` when the upstream does not state one
(masterplan section 13.3 says its GPU table is a starting point, not a spec):

    required_gb = weights_gb * 1.6 + 4      # KV cache, activations, CUDA context
    value       = smallest catalog VRAM tier >= required_gb

``estimated`` is then True and ``basis`` names the weight byte total the rule
consumed. A canary measurement replaces the estimate; the registry never
promotes an estimate to a measurement on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

RuntimeType = Literal["vllm", "transformers", "pipeline", "paddle", "custom", "subscription"]
WeightsStrategy = Literal["baked", "volume_cache", "boot_download"]
LicenseStatus = Literal["approved", "review_required", "blocked", "verified"]
#: "verified" added 2026-09-03 (founder licence decisions for infinity_parser2_pro,
#: mineru_pipeline, mineru_vlm) to agree with runtime.json's license.status vocabulary
#: (arena/core/schemas/runtime.schema.json), which already had a "verified" value this
#: registry's own three-value union did not.

#: FTO caveats repeated verbatim into every licence note (CLAUDE.md, FTO blueprint).
FTO_CAVEAT: Final = (
    "An OSS licence is not patent freedom to operate. A repository without a LICENSE "
    "file is readable but not reusable. Code, model weights, dataset and hosted-API "
    "terms are four separate licences and clearing one clears none of the others."
)


@dataclass(frozen=True, slots=True)
class WeightsSpec:
    """The Hugging Face repository the arena actually loads weights from."""

    repo: str
    #: Prefer this file as ``largest_file`` when several tie; None = pick the largest.
    expected_largest_file: str | None = None
    license_status_override: LicenseStatus | None = None
    license_note: str = ""


@dataclass(frozen=True, slots=True)
class CodeSpec:
    """A GitHub repository that supplies the official runtime for a model."""

    repo: str
    #: When set, resolve this tag instead of the default branch head.
    tag: str | None = None
    role: str = "official_runtime"


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    model_key: str
    display_name: str
    role: str
    runtime_type: RuntimeType
    runtime_version: str | None
    runtime_version_source: str
    weights: WeightsSpec | None
    code: tuple[CodeSpec, ...]
    container_image: str | None
    container_image_source: str | None
    cuda: str | None
    torch: str | None
    official_inference_config: dict[str, Any]
    max_concurrency_per_worker: int
    #: ARENA_CONTRACT section 3.7 / arena/core/schemas: exactly {per_worker, scale}
    #: with scale in {replicas_only, replicas_and_concurrency}.
    concurrency_policy: dict[str, Any]
    #: Everything the two-key policy above cannot carry (post-canary intent,
    #: the Opus worker ramp, and why the value is what it is).
    concurrency_plan: dict[str, Any]
    recommended_gpu_pool: tuple[str, ...]
    gpu_pool_priority: tuple[str, ...]
    shard_size_hint: int
    shard_size_hint_basis: str
    weights_strategy: WeightsStrategy
    runtime_mode_allowed: tuple[str, ...]
    official_source_urls: tuple[str, ...]
    license_status: LicenseStatus
    license_note: str
    notes: tuple[str, ...] = ()
    #: masterplan section 5.1 controlled-comparison row, when the model appeared there.
    historical_evidence: dict[str, Any] | None = None
    #: benchmark/v6/candidate-registry.yaml revision recorded on 2026-08-01.
    previous_registry_revision: str | None = None
    #: Explicit override; otherwise derived from the weight byte total.
    gpu_min_vram_gb_value: int | None = None
    gpu_min_vram_gb_basis: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_A6000 = "NVIDIA RTX A6000"
_A40 = "NVIDIA A40"
_L40S = "NVIDIA L40S"
_RTX4090 = "NVIDIA GeForce RTX 4090"
_A100_PCIE = "NVIDIA A100 80GB PCIe"
_A100_SXM = "NVIDIA A100-SXM4-80GB"
_H100_PCIE = "NVIDIA H100 PCIe"
_H100_HBM3 = "NVIDIA H100 80GB HBM3"
_RTXPRO6000 = "NVIDIA RTX PRO 6000 Blackwell Server Edition"

_MP_POOL_NOTE = (
    "masterplan section 13.3 names this model's starting GPU; the priority list adds "
    "same-VRAM-class alternatives ordered by the 2026-09-03 catalog price and "
    "availability, because section 13.3 states the table is a starting point and the "
    "canary holds the final decision."
)


CANDIDATES: Final[tuple[CandidateSpec, ...]] = (
    CandidateSpec(
        model_key="paddleocr_vl_1_6",
        display_name="PaddleOCR-VL 1.6",
        role="fast high-quality document VLM",
        runtime_type="paddle",
        runtime_version=(
            'paddlepaddle-gpu==3.2.1 (cu126) + "paddleocr[doc-parser]>=3.6.0", '
            "pipeline_version=v1.6"
        ),
        runtime_version_source="https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6",
        weights=WeightsSpec(repo="PaddlePaddle/PaddleOCR-VL-1.6"),
        code=(CodeSpec(repo="PaddlePaddle/PaddleOCR"),),
        container_image=(
            "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/"
            "paddleocr-genai-vllm-server:latest-nvidia-gpu"
        ),
        container_image_source="https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6",
        cuda="12.6",
        torch=None,
        official_inference_config={
            "entrypoint": "paddleocr doc_parser",
            "pipeline_version": "v1.6",
            "vl_rec_backend": "vllm-server",
            "task": "page_level_document_parsing",
            "note": (
                "The model card marks the paddleocr doc_parser pipeline as the official "
                "page-level path; the transformers example is element-level only."
            ),
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_RTX4090,),
        gpu_pool_priority=(_RTX4090, _A6000, _L40S),
        shard_size_hint=200,
        shard_size_hint_basis=(
            "masterplan section 19 historical 3.525 sec/page -> fast lane; section 15.6 "
            "fast band is 100-250 samples/shard"
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=(
            "https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6",
            "https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/"
            "algorithm/PaddleOCR-VL/PaddleOCR-VL-1.6.en.md",
        ),
        license_status="approved",
        license_note="Apache-2.0 declared in the model card front matter. " + FTO_CAVEAT,
        historical_evidence={
            "source": "masterplan section 5.1 (18-page OmniDocBench demo, 3 repeats)",
            "text_edit_distance": 0.038209,
            "formula_edit_distance": 0.113618,
            "table_teds": 0.906065,
            "structure_teds": 0.938370,
            "reading_order": 0.091270,
            "seconds_per_page": 3.525,
            "scope_warning": "18-page controlled subset, not a leaderboard result",
        },
        previous_registry_revision="66317acc4c9fc17bd154591ce650735cd2855f3e",
        notes=(_MP_POOL_NOTE,),
    ),
    CandidateSpec(
        model_key="mineru_pipeline",
        display_name="MinerU 3.4.5 Pipeline (PP-OCRv6)",
        role="fast/stable structural baseline",
        runtime_type="pipeline",
        runtime_version="MinerU release tag mineru-3.4.5-released",
        runtime_version_source="https://github.com/opendatalab/MinerU/tags",
        weights=WeightsSpec(
            repo="opendatalab/PDF-Extract-Kit-1.0",
            license_note=(
                "opendatalab/PDF-Extract-Kit-1.0 itself carries NO LICENSE file and no "
                "cardData.license field on 2026-09-03. The founder's 2026-09-03 licence "
                "decision (receipts/registry-updates/license-mineru_pipeline.json) clears "
                "the mineru_pipeline lane as a whole - runtime code plus the seven "
                "PDF-Extract-Kit-1.0 sub-trees it downloads - for research benchmark "
                "execution under the MinerU Open Source License; it does not put a "
                "separate licence on this weights repository by itself. " + FTO_CAVEAT
            ),
        ),
        code=(CodeSpec(repo="opendatalab/MinerU", tag="mineru-3.4.5-released"),),
        container_image=None,
        container_image_source=None,
        cuda=None,
        torch=None,
        official_inference_config={
            "backend": "pipeline",
            "model_source": "huggingface",
            "downloaded_model_paths": [
                "models/Layout/PP-DocLayoutV2",
                "models/MFR/unimernet_hf_small_2503",
                "models/OCR/paddleocr_torch",
                "models/TabRec/SlanetPlus/slanet-plus.onnx",
                "models/TabRec/UnetStructure/unet.onnx",
                "models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx",
                "models/MFR/pp_formulanet_plus_m",
            ],
            "ocr_weights": "ch_PP-OCRv6_small_det_infer / ch_PP-OCRv6_small_rec_infer",
            "note": (
                "Paths come from mineru/cli/models_download.py and "
                "mineru/utils/enum_class.py at tag mineru-3.4.5-released."
            ),
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_RTX4090, _A40),
        gpu_pool_priority=(_RTX4090, _A6000, _A40),
        shard_size_hint=200,
        shard_size_hint_basis=(
            "masterplan section 19 historical 6.959 sec/page -> fast lane; section 15.6 "
            "fast band is 100-250 samples/shard"
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=(
            "https://github.com/opendatalab/MinerU",
            "https://huggingface.co/opendatalab/PDF-Extract-Kit-1.0",
        ),
        license_status="verified",
        license_note=(
            "MinerU LICENSE.md is Apache-2.0 PLUS additional terms (the 'MinerU Open "
            "Source License': a commercial-licence threshold at 100M MAU / USD 20M "
            "monthly revenue, an online-service attribution obligation, and automatic "
            "termination on breach), so the GitHub API reports NOASSERTION and it is NOT "
            "plain Apache-2.0. The pipeline weight repository "
            "opendatalab/PDF-Extract-Kit-1.0 has no LICENSE of its own. Founder decision "
            "2026-09-03 clears the lane for research benchmark execution "
            "(receipts/registry-updates/license-mineru_pipeline.json); commercial use "
            "still depends on staying under the section 1 thresholds. " + FTO_CAVEAT
        ),
        extra={"license_id": "LicenseRef-MinerU-Open-Source-License"},
        historical_evidence={
            "source": "masterplan section 5.1 (18-page OmniDocBench demo, 3 repeats)",
            "measured_release": "MinerU 3.4.4 Pipeline",
            "text_edit_distance": 0.036507,
            "formula_edit_distance": 0.153424,
            "table_teds": 0.890803,
            "structure_teds": 0.946825,
            "reading_order": 0.095701,
            "seconds_per_page": 6.959,
            "scope_warning": (
                "18-page controlled subset measured on 3.4.4; this campaign pins 3.4.5, "
                "so the row is a baseline expectation and not a comparable result"
            ),
        },
        previous_registry_revision="79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7",
        gpu_min_vram_gb_value=24,
        gpu_min_vram_gb_basis=(
            "Pipeline loads several small sub-models (layout, MFR, OCR, table) rather "
            "than one checkpoint, so the weight-total rule does not apply; the "
            "PDF-Extract-Kit-1.0 repository is 14.61 GB in total but not all resident. "
            "masterplan section 13.3 starting pool is RTX 4090 / A40."
        ),
        notes=(
            _MP_POOL_NOTE,
            "masterplan section 4 records that MinerU 3.4 moved pipeline OCR to PP-OCRv6; "
            "PP-OCRv6 is not a separately versioned MinerU asset repository. The pipeline "
            "pulls torch-converted PP-OCRv6 weights from opendatalab/PDF-Extract-Kit-1.0 "
            "under models/OCR/paddleocr_torch. The standalone PaddlePaddle/PP-OCRv6_* "
            "Hugging Face repositories are a different distribution and are NOT what "
            "MinerU loads.",
        ),
    ),
    CandidateSpec(
        model_key="mineru_vlm",
        display_name="MinerU VLM (MinerU2.5-Pro-2605-1.2B)",
        role="complex table/layout specialist",
        runtime_type="vllm",
        runtime_version='mineru-vl-utils[vllm] (vllm >= 0.10.1 for MinerULogitsProcessor)',
        runtime_version_source="https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B",
        weights=WeightsSpec(repo="opendatalab/MinerU2.5-Pro-2605-1.2B"),
        code=(CodeSpec(repo="opendatalab/MinerU", tag="mineru-3.4.5-released"),),
        container_image=None,
        container_image_source=None,
        cuda=None,
        torch=None,
        official_inference_config={
            "backend": "vllm-engine",
            "client": "mineru_vl_utils.MinerUClient",
            "extraction": "two_step_extract",
            "logits_processors": ["MinerULogitsProcessor"],
            "image_analysis": False,
            "post_process": "mineru_vl_utils.post_process.json2md",
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_only",
            "reason": (
                "masterplan section 14 is a hard rule and the canary cannot relax it: "
                "per-worker concurrency stays 1 forever and throughput scales by "
                "horizontal replicas only."
            ),
        },
        recommended_gpu_pool=(_A40, _RTX4090),
        gpu_pool_priority=(_A6000, _A40, _RTX4090),
        shard_size_hint=50,
        shard_size_hint_basis=(
            "masterplan section 19 historical 34.708 sec/page -> slow lane; section 15.6 "
            "slow band is 25-100 samples/shard"
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=(
            "https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B",
            "https://github.com/opendatalab/MinerU",
        ),
        license_status="verified",
        license_note=(
            "The weight card declares apache-2.0, and the MinerU runtime that loads it "
            "(LICENSE.md at tag mineru-3.4.5-released, the 'MinerU Open Source License') "
            "is Apache-2.0 plus additional terms: a commercial-licence threshold at 100M "
            "MAU / USD 20M monthly revenue, an online-service attribution obligation, and "
            "automatic termination on breach. Weights and code are separate licences, "
            "both cleared. Founder decision 2026-09-03 clears the lane for research "
            "benchmark execution (receipts/registry-updates/license-mineru_vlm.json); "
            "commercial use still depends on staying under the section 1 thresholds. "
            + FTO_CAVEAT
        ),
        historical_evidence={
            "source": "masterplan section 5.1 (18-page OmniDocBench demo, 3 repeats)",
            "measured_release": "MinerU 3.4.4 VLM concurrency 1",
            "text_edit_distance": 0.034258,
            "formula_edit_distance": 0.122975,
            "table_teds": 0.959696,
            "structure_teds": 0.984524,
            "reading_order": 0.076693,
            "seconds_per_page": 34.708,
            "incident": (
                "masterplan section 14: at worker concurrency 3, 48 of 54 pages failed "
                "with tensor-shape errors. Concurrency is 1 and scaling is replicas only."
            ),
            "scope_warning": "18-page controlled subset, not a leaderboard result",
        },
        previous_registry_revision=None,
        notes=(
            _MP_POOL_NOTE,
            "masterplan section 14 is a hard rule: per-worker concurrency stays 1 and "
            "throughput scales by horizontal replicas only.",
        ),
        extra={
            "license_id": "LicenseRef-MinerU-Open-Source-License",
            "previous_registry_revision_unresolved_reason": (
                "benchmark/v6/candidate-registry.yaml pinned mineru-3.4.4-vlm by the "
                "MinerU *code* revision 79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7 plus an "
                "artifact hash, never by the MinerU2.5-Pro-2605-1.2B weight revision. "
                "There is no previous weight revision to compare against, so this field "
                "is null rather than a code revision pretending to be a weight one."
            )
        },
    ),
    CandidateSpec(
        model_key="deepseek_ocr2",
        display_name="DeepSeek-OCR-2",
        role="text-fidelity challenger",
        runtime_type="transformers",
        runtime_version="transformers==4.46.3 + flash-attn==2.7.3",
        runtime_version_source="https://huggingface.co/deepseek-ai/DeepSeek-OCR-2",
        weights=WeightsSpec(repo="deepseek-ai/DeepSeek-OCR-2"),
        code=(CodeSpec(repo="deepseek-ai/DeepSeek-OCR-2"),),
        container_image=None,
        container_image_source=None,
        cuda=None,
        torch="2.6.0",
        official_inference_config={
            "prompt": "<image>\n<|grounding|>Convert the document to markdown. ",
            "base_size": 1024,
            "image_size": 768,
            "crop_mode": True,
            "entrypoint": "model.infer(tokenizer, prompt=..., image_file=..., ...)",
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_A40, _RTX4090),
        gpu_pool_priority=(_A6000, _A40, _RTX4090),
        shard_size_hint=50,
        shard_size_hint_basis=(
            "masterplan section 19 historical 47.200 sec/page -> slow lane; section 15.6 "
            "slow band is 25-100 samples/shard"
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=(
            "https://huggingface.co/deepseek-ai/DeepSeek-OCR-2",
            "https://github.com/deepseek-ai/DeepSeek-OCR-2",
        ),
        license_status="approved",
        license_note=(
            "apache-2.0 on the model card and on the GitHub repository. " + FTO_CAVEAT
        ),
        historical_evidence={
            "source": "masterplan section 5.1 (18-page OmniDocBench demo, 3 repeats)",
            "text_edit_distance": 0.032428,
            "formula_edit_distance": 0.139538,
            "table_teds": 0.871838,
            "structure_teds": 0.912497,
            "reading_order": 0.100267,
            "seconds_per_page": 47.200,
            "scope_warning": "18-page controlled subset, not a leaderboard result",
        },
        previous_registry_revision="aaa02f3811945a91062062994c5c4a3f4c0af2b0",
        notes=(_MP_POOL_NOTE,),
    ),
    CandidateSpec(
        model_key="ovisocr2",
        display_name="OvisOCR2",
        role="compact end-to-end challenger",
        runtime_type="vllm",
        runtime_version="vllm==0.22.1",
        runtime_version_source="https://huggingface.co/ATH-MaaS/OvisOCR2",
        weights=WeightsSpec(repo="ATH-MaaS/OvisOCR2"),
        code=(),
        container_image=None,
        container_image_source=None,
        cuda=None,
        torch=None,
        official_inference_config={
            "tensor_parallel_size": 1,
            "gpu_memory_utilization": 0.8,
            "gdn_prefill_backend": "triton",
            "max_tokens": 16384,
            "temperature": 0.0,
            "enable_thinking": False,
            "min_pixels": 200704,
            "max_pixels": 8294400,
            "post_process": "_clean_truncated_repeats (official card helper)",
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_RTX4090,),
        gpu_pool_priority=(_RTX4090, _A6000),
        shard_size_hint=200,
        shard_size_hint_basis=(
            "masterplan section 19 historical 6.171 sec/page -> fast lane; section 15.6 "
            "fast band is 100-250 samples/shard"
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=("https://huggingface.co/ATH-MaaS/OvisOCR2",),
        license_status="approved",
        license_note="apache-2.0 declared in the model card front matter. " + FTO_CAVEAT,
        historical_evidence={
            "source": "masterplan section 5.1 (18-page OmniDocBench demo, 3 repeats)",
            "text_edit_distance": 0.097963,
            "formula_edit_distance": 0.138752,
            "table_teds": 0.894063,
            "structure_teds": 0.938370,
            "reading_order": 0.142573,
            "seconds_per_page": 6.171,
            "discrepancy": (
                "masterplan section 4: the historical TAVONEL measurement was abnormally "
                "low against the official OmniDocBench v1.6 score of 96.58. This campaign "
                "must re-verify with the official checkpoint, prompt and runtime."
            ),
            "scope_warning": "18-page controlled subset, not a leaderboard result",
        },
        previous_registry_revision="65c619d374b55d4152e85150fc1b003700bc1f0c",
        notes=(_MP_POOL_NOTE,),
    ),
    CandidateSpec(
        model_key="unlimited_ocr",
        display_name="Unlimited-OCR",
        role="long-horizon specialist",
        runtime_type="transformers",
        runtime_version="transformers==4.57.1",
        runtime_version_source="https://huggingface.co/baidu/Unlimited-OCR",
        weights=WeightsSpec(repo="baidu/Unlimited-OCR"),
        code=(CodeSpec(repo="baidu/Unlimited-OCR"),),
        container_image=None,
        container_image_source=None,
        cuda=None,
        torch="2.10.0",
        official_inference_config={
            "prompt": "<image>document parsing.",
            "image_mode": "gundam",
            "base_size": 1024,
            "image_size": 640,
            "crop_mode": True,
            "temperature": 0,
            "note": (
                "The card documents 'gundam' (base_size=1024, image_size=640, "
                "crop_mode=True) for single-page document parsing and reserves "
                "'<image>Multi page parsing.' with image_size=1024 for multi-page input. "
                "The arena is one page per request, so the gundam single-page path is the "
                "official setting."
            ),
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_A40, _RTX4090),
        gpu_pool_priority=(_A6000, _A40, _RTX4090),
        shard_size_hint=50,
        shard_size_hint_basis=(
            "masterplan section 19 historical 45.85 sec/page -> slow lane; section 15.6 "
            "slow band is 25-100 samples/shard"
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=(
            "https://github.com/baidu/Unlimited-OCR",
            "https://huggingface.co/baidu/Unlimited-OCR",
        ),
        license_status="approved",
        license_note="MIT on both the GitHub repository and the model card. " + FTO_CAVEAT,
        historical_evidence={
            "source": "masterplan section 19 historical-speed cost baseline",
            "seconds_per_page": 45.85,
            "scope_warning": (
                "section 19 speed row only; Unlimited-OCR is not in the section 5.1 "
                "18-page quality comparison, so no quality baseline exists"
            ),
        },
        previous_registry_revision=None,
        notes=(_MP_POOL_NOTE,),
    ),
    CandidateSpec(
        model_key="infinity_parser2_pro",
        display_name="Infinity-Parser2-Pro",
        role="maximum-accuracy open challenger",
        runtime_type="vllm",
        runtime_version="vllm==0.17.1 + flash-attn==2.8.3 + infinity_parser2",
        runtime_version_source="https://huggingface.co/infly/Infinity-Parser2-Pro",
        weights=WeightsSpec(repo="infly/Infinity-Parser2-Pro"),
        code=(),
        container_image=None,
        container_image_source=None,
        cuda="12.8",
        torch="2.10.0",
        official_inference_config={
            "serve_command": "vllm serve infly/Infinity-Parser2-Pro",
            "trust_remote_code": True,
            "reasoning_parser": "qwen3",
            "tensor_parallel_size": 2,
            "gpu_memory_utilization": 0.85,
            "max_model_len": 65536,
            "mm_encoder_tp_mode": "data",
            "mm_processor_cache_type": "shm",
            "enable_prefix_caching": True,
            "min_pixels": 2048,
            "max_pixels": 16777216,
            "max_new_tokens": 32768,
            "temperature": 0.0,
            "top_p": 1.0,
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_A100_PCIE, _H100_PCIE),
        gpu_pool_priority=(_A100_SXM, _A100_PCIE, _H100_PCIE, _H100_HBM3, _RTXPRO6000),
        shard_size_hint=25,
        shard_size_hint_basis=(
            "No historical sec/page exists for this model (masterplan section 19 lists it "
            "as new). 70.21 GB of weights across two GPUs puts it in the section 15.6 "
            "large/experimental band, 10-50 samples/shard; the canary replaces the hint."
        ),
        weights_strategy="volume_cache",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=("https://huggingface.co/infly/Infinity-Parser2-Pro",),
        license_status="verified",
        license_note=(
            "VERIFIED by founder decision 2026-09-03 "
            "(receipts/registry-updates/license-infinity_parser2_pro.json), and this was "
            "never about the weights. The checkpoint infly/Infinity-Parser2-Pro is "
            "apache-2.0 in its model card front matter (ARENA_CONTRACT.md section 11.5 "
            "D16 resolves this in runtime.json's favour); "
            "runtimes/infinity_parser2_pro/runtime.json records that the official runtime "
            "wrapper github.com/infly-ai/INF-MLLM STILL carries NO LICENSE file at its "
            "root or under Infinity-Parser2/ (checked 2026-09-03 via the GitHub contents "
            "API; the repo's `license` field is null). Readable is not reusable. The "
            "design-around is unchanged: use no INF-MLLM code and serve the checkpoint "
            "with the model card's own vllm command. " + FTO_CAVEAT
        ),
        historical_evidence=None,
        previous_registry_revision="b27d470100514329fc6439aada8f16ccea5f9e2a",
        gpu_min_vram_gb_value=160,
        gpu_min_vram_gb_basis=(
            "70.21 GB of fp16 safetensors across 15 shards; the official card starts vLLM "
            "with --tensor-parallel-size 2 and --max-model-len 65536, so the documented "
            "configuration is 2 x 80 GB. This is the total across both GPUs, not per-GPU."
        ),
        notes=(
            _MP_POOL_NOTE,
            "This is the only candidate whose official configuration needs two GPUs per "
            "worker. The controller must provision gpuCount=2 for this model or the "
            "documented configuration cannot be reproduced.",
            "runtime_mode_allowed omits 'bootstrap': a 70.21 GB boot download inside a "
            "canary pod is a stall risk that masterplan section 15.1 exists to prevent.",
        ),
    ),
    CandidateSpec(
        model_key="infinity_parser2_flash",
        display_name="Infinity-Parser2-Flash",
        role="low-latency open challenger (Infinity-Parser2 2B)",
        runtime_type="vllm",
        runtime_version="vllm==0.19.0 + transformers==5.4.0",
        runtime_version_source="https://huggingface.co/infly/Infinity-Parser2-Flash",
        weights=WeightsSpec(repo="infly/Infinity-Parser2-Flash"),
        code=(),
        container_image=None,
        container_image_source=None,
        cuda="12.9",
        torch="2.10.0",
        official_inference_config={
            "serve_command": "vllm serve infly/Infinity-Parser2-Flash",
            "trust_remote_code": True,
            "reasoning_parser": "qwen3",
            "tensor_parallel_size": 1,
            "gpu_memory_utilization": 0.85,
            "max_model_len": 32768,
            "mm_encoder_tp_mode": "data",
            "mm_processor_cache_type": "shm",
            "enable_prefix_caching": True,
            "gdn_prefill_backend": "triton",
            "min_pixels": 2048,
            "max_pixels": 16777216,
            "max_new_tokens": 32768,
            "temperature": 0.0,
            "top_p": 1.0,
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "Flash is the 2B sibling of Infinity-Parser2-Pro. Per-worker concurrency "
                "stays 1 until measured; scale by RTX 4090 replicas (founder cap ~4)."
            ),
        },
        recommended_gpu_pool=(_RTX4090,),
        gpu_pool_priority=(_RTX4090, _A40, _L40S),
        shard_size_hint=100,
        shard_size_hint_basis=(
            "No historical sec/page yet. ~4.4 GB weights on one 4090 puts Flash in the "
            "section 15.6 mid band; 100 samples/shard matches other 4090 lanes."
        ),
        weights_strategy="volume_cache",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=("https://huggingface.co/infly/Infinity-Parser2-Flash",),
        license_status="verified",
        license_note=(
            "Model card declares apache-2.0. Same design-around as Pro: do not vendor "
            "unlicensed INF-MLLM wrapper code; serve with vLLM. " + FTO_CAVEAT
        ),
        historical_evidence=None,
        previous_registry_revision="cfddc4106b0abc4706f05575a164f7dd35d09c46",
        gpu_min_vram_gb_value=24,
        gpu_min_vram_gb_basis=(
            "~4.43 GB BF16 safetensors (2.21B params). required_gb ~= 4.4*1.6+4 ~= 11; "
            "catalog tier 24 GB (RTX 4090)."
        ),
        notes=(
            _MP_POOL_NOTE,
            "FOUNDER 2026-09-05: full multi-pod full-page run on RTX 4090. "
            "infinity_parser2_pro remains FOUNDER_EXCLUDED (H100/A100 x2 cost).",
            "Do not launch H100 for this lane.",
        ),
    ),
    CandidateSpec(
        model_key="monkeyocrv2_b",
        display_name="MonkeyOCRv2-B-Parsing",
        role="compact multilingual/photo challenger",
        runtime_type="vllm",
        runtime_version="vllm==0.11.2 (no DFlash) or vllm 0.25.1 cu129 (DFlash)",
        runtime_version_source="https://huggingface.co/zenosai/MonkeyOCRv2-B-Parsing",
        weights=WeightsSpec(repo="zenosai/MonkeyOCRv2-B-Parsing"),
        code=(CodeSpec(repo="Yuliang-Liu/MonkeyOCR", role="official_parsing_toolkit"),),
        container_image=None,
        container_image_source=None,
        cuda="12.6",
        torch="2.6.0",
        official_inference_config={
            "serve": "parsing/serve.py -m <weights> -p 8888",
            "client": "parsing/parse.py -i <input> -o <output> -s http://127.0.0.1:8888",
            "dflash": False,
            "dflash_note": (
                "DFlash needs vLLM 0.25.1 and CUDA >= 12.9 plus a separate "
                "MonkeyOCRv2-B-Parsing-DFlash weight repository. The arena runs the "
                "documented no-DFlash path so the measured speed is the base model's."
            ),
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_RTX4090,),
        gpu_pool_priority=(_RTX4090, _A6000),
        shard_size_hint=100,
        shard_size_hint_basis=(
            "No historical sec/page exists (masterplan section 19 lists it as new). A "
            "0.7B-class parser is provisionally placed in the section 15.6 medium band "
            "at 100 samples/shard; the canary replaces the hint."
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=(
            "https://huggingface.co/zenosai/MonkeyOCRv2-B-Parsing",
            "https://github.com/Yuliang-Liu/MonkeyOCR",
        ),
        license_status="approved",
        license_note=(
            "apache-2.0 on the model card and on the Yuliang-Liu/MonkeyOCR toolkit. "
            + FTO_CAVEAT
        ),
        historical_evidence=None,
        previous_registry_revision="de7a993bd0f39a97b122dac767e82ae04935bce4",
        notes=(_MP_POOL_NOTE,),
    ),
    CandidateSpec(
        model_key="olmocr2",
        display_name="olmOCR-2-7B-1025-FP8",
        role="benchmark-family reference baseline",
        runtime_type="vllm",
        runtime_version="olmocr>=0.4.0 toolkit (vLLM server managed by the toolkit)",
        runtime_version_source="https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8",
        weights=WeightsSpec(repo="allenai/olmOCR-2-7B-1025-FP8"),
        code=(CodeSpec(repo="allenai/olmocr", role="official_toolkit"),),
        container_image=None,
        container_image_source=None,
        cuda=None,
        torch=None,
        official_inference_config={
            "prompt_builder": "olmocr.prompts.build_no_anchoring_v4_yaml_prompt",
            "target_longest_image_dim": 1288,
            "max_tokens": 8000,
            "temperature": 0.1,
            "max_model_len": 16384,
            "tensor_parallel_size": 1,
            "processor": "Qwen/Qwen2.5-VL-7B-Instruct",
            "note": (
                "Values come from olmocr/pipeline.py at the pinned toolkit revision "
                "(MAX_TOKENS = 8000, TEMPERATURE_BY_ATTEMPT[0] = 0.1, "
                "--target_longest_image_dim default 1288, --max_model_len default 16384). "
                "The model card's max_new_tokens=50 is a truncated demo, not the "
                "production setting."
            ),
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_RTX4090, _A40),
        gpu_pool_priority=(_RTX4090, _L40S, _RTXPRO6000),
        shard_size_hint=100,
        shard_size_hint_basis=(
            "No historical sec/page exists (masterplan section 19 lists it as new). A 7B "
            "FP8 model is provisionally placed in the section 15.6 medium band at 100 "
            "samples/shard; the canary replaces the hint."
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=(
            "https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8",
            "https://github.com/allenai/olmocr",
        ),
        license_status="approved",
        license_note=(
            "apache-2.0 on the model card and on the allenai/olmocr toolkit. Note that "
            "the olmOCR-Bench *dataset* licence is a separate question and is recorded "
            "as license-review-required in benchmark/benchmark-registry.lock.yaml. "
            + FTO_CAVEAT
        ),
        historical_evidence=None,
        previous_registry_revision="40bd7202494b8264ee17ada08b401b5aab7a9ce1",
        notes=(
            _MP_POOL_NOTE,
            "The checkpoint is FP8. gpu_pool_priority prefers Ada/Blackwell parts "
            "(RTX 4090, L40S, RTX PRO 6000) that have native FP8 tensor cores. "
            "masterplan section 13.3 also names the A40, which is Ampere and has no "
            "native FP8 path; the canary must confirm before an A40 is used.",
            "Scoring this model on olmOCR-Bench is a benchmark-family self-comparison. "
            "Report it as a reference baseline, never as an independent win.",
        ),
    ),
    CandidateSpec(
        model_key="hpd_parsing",
        display_name="HPD-Parsing",
        role="throughput specialist",
        runtime_type="custom",
        runtime_version="vllm-0.17.1+hpdparsing (customized build, official wheel)",
        runtime_version_source=(
            "https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/"
            "pipeline_usage/HPD-Parsing.en.md"
        ),
        weights=WeightsSpec(repo="PaddlePaddle/HPD-Parsing"),
        code=(CodeSpec(repo="PaddlePaddle/PaddleOCR", role="official_documentation"),),
        container_image=(
            "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/"
            "hpd-parsing-vllm:latest-nvidia-gpu"
        ),
        container_image_source=(
            "https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/"
            "pipeline_usage/HPD-Parsing.en.md"
        ),
        cuda="12.8",
        torch=None,
        official_inference_config={
            "prompt": "document parsing with fork.",
            "env": {"MAX_PATCHES_WITH_RESIZE": "true"},
            "served_model_name": "HPD-Parsing",
            "port": 8118,
            "trust_remote_code": True,
            "max_model_len": 16384,
            "limit_mm_per_prompt": {"image": 1},
            "gpu_memory_utilization": 0.9,
            "attention_backend": "FLASHINFER",
            "attention_config": {"use_prefill_query_quantization": True},
            "enable_chunked_prefill": True,
            "enable_prefix_caching": True,
            "speculative_config": {
                "method": "medusa",
                "model": "<MODEL_PATH>/P-MTP",
                "num_speculative_tokens": 6,
            },
            "temperature": 0,
            "max_tokens": 8000,
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "engine_batching",
            "reason": (
                "masterplan section 13.3 says HPD-Parsing scales through its own vLLM "
                "engine batching rather than by adding worker processes. The two-key "
                "policy has no vocabulary for that, so per_worker stays 1 and the "
                "engine-batching intent is recorded here for the controller."
            ),
        },
        recommended_gpu_pool=(_H100_PCIE, _A100_PCIE),
        gpu_pool_priority=(_H100_PCIE, _A100_SXM, _A100_PCIE, _H100_HBM3, _RTXPRO6000),
        shard_size_hint=100,
        shard_size_hint_basis=(
            "No historical sec/page exists (masterplan section 19 lists it as new). The "
            "official 4,752 tokens/s peak-throughput claim is a vendor number and is not "
            "used for planning; the model sits provisionally in the section 15.6 medium "
            "band at 100 samples/shard until the canary measures it."
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked",),
        official_source_urls=(
            "https://huggingface.co/PaddlePaddle/HPD-Parsing",
            "https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/"
            "pipeline_usage/HPD-Parsing.en.md",
        ),
        license_status="approved",
        license_note=(
            "apache-2.0 on the weight card; the PaddleOCR documentation repository is "
            "Apache-2.0. The official Docker image ships a customized vLLM build whose "
            "own distribution terms are NOT stated in the document and have not been "
            "reviewed. " + FTO_CAVEAT
        ),
        historical_evidence=None,
        previous_registry_revision=None,
        gpu_min_vram_gb_value=48,
        gpu_min_vram_gb_basis=(
            "Weights are only 2.79 GB (base 2.14 GB + P-MTP 0.64 GB), so VRAM is not the "
            "binding constraint. The official document lists verified hardware as "
            "H100/H800/H20/A100/A800/A30/L20/RTX Pro 6000 and requires a FLASHINFER "
            "attention backend with medusa speculative decoding, which pins the "
            "architecture rather than the capacity. 48 GB is the smallest catalog tier "
            "that also satisfies the architecture requirement."
        ),
        notes=(
            _MP_POOL_NOTE,
            "The RTX 4090 is NOT on the official verified-hardware list for the "
            "customized vLLM build, so it is excluded from the pool even though the "
            "weights would fit in 24 GB.",
            "container_digest stays null here: lane F resolves the immutable digest for "
            "'latest-nvidia-gpu'. A ':latest' tag is not an immutable image and must not "
            "be used for a full run without a resolved digest.",
        ),
    ),
    CandidateSpec(
        model_key="glm_ocr",
        display_name="GLM-OCR",
        role="compact challenger",
        runtime_type="vllm",
        runtime_version=None,
        runtime_version_source="https://huggingface.co/zai-org/GLM-OCR",
        weights=WeightsSpec(repo="zai-org/GLM-OCR"),
        code=(),
        container_image="vllm/vllm-openai:nightly",
        container_image_source="https://huggingface.co/zai-org/GLM-OCR",
        cuda=None,
        torch=None,
        official_inference_config={
            "serve_command": "vllm serve zai-org/GLM-OCR --allowed-local-media-path / --port 8080",
            "prompt": "Text Recognition:",
            "supported_prompts": {
                "text": "Text Recognition:",
                "formula": "Formula Recognition:",
                "table": "Table Recognition:",
            },
            "max_new_tokens": 8192,
            "note": (
                "The card restricts GLM-OCR to a fixed prompt vocabulary. Page-level "
                "document parsing uses 'Text Recognition:'. The official SDK "
                "(github.com/zai-org/GLM-OCR) adds PP-DocLayoutV3 layout analysis on top; "
                "the arena runs the model-only vLLM path so the measurement is the "
                "model's, not a pipeline's."
            ),
        },
        max_concurrency_per_worker=1,
        concurrency_policy={"per_worker": 1, "scale": "replicas_only"},
        concurrency_plan={
            "scale_after_canary": "replicas_and_concurrency",
            "reason": (
                "masterplan section 13.3 marks this lane canary-verified. Per-worker "
                "concurrency stays 1 and throughput scales by replicas until the canary "
                "measures a safe concurrency; raising it before that is how the 2026-08 "
                "MinerU VLM tensor-shape incident happened."
            ),
        },
        recommended_gpu_pool=(_RTX4090,),
        gpu_pool_priority=(_RTX4090, _A6000),
        shard_size_hint=100,
        shard_size_hint_basis=(
            "No historical sec/page exists (masterplan section 19 lists it as new). A "
            "0.9B-class model is provisionally placed in the section 15.6 medium band at "
            "100 samples/shard; the canary replaces the hint."
        ),
        weights_strategy="baked",
        runtime_mode_allowed=("baked", "bootstrap"),
        official_source_urls=("https://huggingface.co/zai-org/GLM-OCR",),
        license_status="approved",
        license_note="MIT declared in the model card front matter. " + FTO_CAVEAT,
        historical_evidence=None,
        previous_registry_revision="ca5d8b3e287e52589e37c28385d9655ee4372f9d",
        notes=(
            _MP_POOL_NOTE,
            "runtime_version is null on purpose: the official card pins nothing. It says "
            "'pip install -U vllm --extra-index-url https://wheels.vllm.ai/nightly' and "
            "'pip install git+https://github.com/huggingface/transformers.git'. A moving "
            "nightly is not a reproducible runtime, so lane C3 must resolve one exact "
            "nightly build and one transformers commit and record both in runtime.json.",
        ),
        extra={
            "runtime_version_unresolved_reason": (
                "Upstream recommends an unpinned vLLM nightly and a git-main transformers "
                "install; no exact version is documented on 2026-09-03."
            )
        },
    ),
    CandidateSpec(
        model_key="opus5_subscription",
        display_name="",  # filled from arena.constants.OPUS_DISPLAY_NAME
        role="frontier general multimodal ceiling",
        runtime_type="subscription",
        runtime_version="Claude Code 2.1.252 headless mode",
        runtime_version_source="https://code.claude.com/docs/en/headless",
        weights=None,
        code=(),
        container_image=None,
        container_image_source=None,
        cuda=None,
        torch=None,
        official_inference_config={
            "surface": "claude-code-subscription",
            "command": (
                "claude -p --model opus --output-format json --no-session-persistence "
                "--tools Read --allowedTools Read --permission-mode dontAsk --effort high "
                "--disable-slash-commands"
            ),
            "fresh_process_per_page": True,
            "bare_flag_forbidden": True,
            "note": (
                "ARENA_CONTRACT section 7. Lane D owns the runner and re-verifies the "
                "flags against the installed CLI; this record carries the contract value "
                "so the registry is complete, not so the runner reads it."
            ),
        },
        max_concurrency_per_worker=2,
        concurrency_policy={"per_worker": 2, "scale": "replicas_and_concurrency"},
        concurrency_plan={
            "scale_after_canary": "worker_ramp",
            "ramp": [2, 4, 6],
            "ramp_gate": "50-page canary between each step (masterplan section 21.7)",
            "reason": (
                "masterplan section 21.7 ramps local Claude Code workers 2 -> 4 -> 6 and "
                "never further. These are processes on the founder's machine, not GPU "
                "replicas, so the two-key policy is an approximation and the ramp above "
                "is the operative rule."
            ),
        },
        recommended_gpu_pool=(),
        gpu_pool_priority=(),
        shard_size_hint=50,
        shard_size_hint_basis=(
            "Not a GPU shard. The subscription lane checkpoints per page and pauses on a "
            "usage limit (masterplan section 21.8), so the shard is a resume unit only."
        ),
        weights_strategy="boot_download",
        runtime_mode_allowed=("subscription",),
        official_source_urls=(
            "https://www.anthropic.com/news/claude-opus-5",
            "https://www.anthropic.com/claude/opus",
            "https://code.claude.com/docs/en/headless",
            "https://code.claude.com/docs/en/cli-usage",
        ),
        license_status="review_required",
        license_note=(
            "Commercial hosted service under Anthropic's consumer/commercial terms, not "
            "an open-source licence. Subscription usage terms, API terms and any output "
            "redistribution right are separate questions from every model licence in this "
            "registry. " + FTO_CAVEAT
        ),
        historical_evidence=None,
        previous_registry_revision=None,
        gpu_min_vram_gb_value=None,
        gpu_min_vram_gb_basis="Not applicable: no GPU is provisioned for this lane.",
        extra={
            "license_id": "proprietary-anthropic-commercial-terms",
            "list_price_reference": {
                "input_usd_per_mtok": 5.0,
                "output_usd_per_mtok": 25.0,
                "source_url": "https://www.anthropic.com/news/claude-opus-5",
                "captured_at": "2026-09-03",
                "note": (
                    "masterplan section 4 records this as an API list-price reference. "
                    "This run uses the subscription surface, so the number is only used "
                    "for api_equivalent_list_price_usd. Never report the subscription "
                    "lane as $0/page (ARENA_CONTRACT section 7)."
                ),
            },
            "api_model_id": "claude-opus-5",
            "revision_unresolved_reason": (
                "The subscription surface does not expose a checkpoint revision. Lane D's "
                "probe reads the model id back out of the claude -p JSON payload and the "
                "contract requires the page to fail when it is not an Opus 5 model id."
            ),
        },
        notes=(
            "Not a RunPod candidate. masterplan section 3.1 marks it Full Run with an "
            "asterisk: subscription quota governs, and a quota pause never falls back to "
            "another model.",
        ),
    ),
)

CANDIDATES_BY_KEY: Final = {spec.model_key: spec for spec in CANDIDATES}

__all__ = [
    "CANDIDATES",
    "CANDIDATES_BY_KEY",
    "FTO_CAVEAT",
    "CandidateSpec",
    "CodeSpec",
    "LicenseStatus",
    "RuntimeType",
    "WeightsSpec",
    "WeightsStrategy",
]
