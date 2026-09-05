"""A synthetic frozen campaign: 3 models x 6 pages, built entirely on disk.

The pages are chosen to exercise each named trigger exactly once — empty,
truncated, repeating, broken table, formula-heavy and clean — so a routing
change shows up as a specific page moving, not as a count drifting.

Nothing here reads the real campaign tree, the staged corpus, an evaluator or
any answer key. The fixtures write their own receipts, outputs, manifests and
pod ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from arena.constants import CAMPAIGN_ID
from arena.tavonel import jsonio
from arena.tavonel.paths import ArenaPaths

PRIMARY = "paddleocr_vl_1_6"
TEXT_SPECIALIST = "deepseek_ocr2"
TABLE_SPECIALIST = "mineru_vlm"
ESCALATION = "opus5_subscription"

CASES = (
    "case-clean",
    "case-empty",
    "case-truncated",
    "case-repetition",
    "case-table",
    "case-formula",
)

CLEAN = "# Quarterly Report\n\nRevenue rose twelve percent in the third quarter of the year.\n"
TRUNCATED = (
    "# Findings\n\nThe measurement was repeated three times and the result\n\n"
    "```python\nprint(1)\n"
)
REPETITION = "The same row repeats again and again in this printed document.\n\n" * 8
TABLE_BROKEN = "| Region | Revenue | Share |\n| North | 12 | 4 |\n| South | 18 |\n"
TABLE_GOOD = "| Region | Revenue |\n| --- | --- |\n| North | 12 |\n| South | 18 |\n| East | 4 |\n"
FORMULA = (
    "# Method\n\nConsider $E = mc^2$ and $$\\int_0^1 x dx$$ together with "
    "\\(a + b\\) and \\[c + d\\].\n"
)
PLAIN_ALTERNATIVE = "# Quarterly Report\n\nRevenue increased by twelve percent last quarter.\n"

# model_key -> case_key -> canonical markdown ("" means an empty output)
OUTPUTS: dict[str, dict[str, str]] = {
    PRIMARY: {
        "case-clean": CLEAN,
        "case-empty": "",
        "case-truncated": TRUNCATED,
        "case-repetition": REPETITION,
        "case-table": TABLE_BROKEN,
        "case-formula": FORMULA,
    },
    TEXT_SPECIALIST: {
        "case-clean": PLAIN_ALTERNATIVE,
        "case-empty": CLEAN,
        "case-truncated": CLEAN,
        "case-repetition": PLAIN_ALTERNATIVE,
        "case-table": TABLE_GOOD,
        "case-formula": FORMULA,
    },
    TABLE_SPECIALIST: {
        "case-clean": CLEAN,
        "case-empty": PLAIN_ALTERNATIVE,
        "case-truncated": CLEAN,
        "case-repetition": CLEAN,
        "case-table": TABLE_GOOD,
        "case-formula": FORMULA,
    },
}

_FAILED_CASES = {"case-empty"}
# Different rates per model, so a variant that routes pages away from the
# primary cannot come out at the same cost by arithmetic coincidence.
_POD_RATES = {PRIMARY: 0.34, TEXT_SPECIALIST: 1.19, TABLE_SPECIALIST: 0.79}
_MAX_TOKENS = 4096
_PAGE_WIDTH = 400
_PAGE_HEIGHT = 400


@dataclass(frozen=True, slots=True)
class Campaign:
    """Handle on one synthetic campaign tree."""

    paths: ArenaPaths
    models: tuple[str, ...]
    cases: tuple[str, ...]

    @property
    def root(self) -> Path:
        return self.paths.root


def _preflight(case_key: str) -> dict[str, Any]:
    return {
        "near_white_ratio": 0.60,
        "render_entropy": 4.2,
        "mean_intensity": 200.0,
        # A page that came back empty still has ink on it: that is what makes a
        # higher-DPI rerender a sensible recovery rather than a guess.
        "edge_density": 0.09 if case_key == "case-empty" else 0.02,
        "is_probably_blank": False,
    }


def write_source_manifest(paths: ArenaPaths, cases: tuple[str, ...]) -> None:
    rows = [
        {
            "schema": "tavonel.arena.source-row.v1",
            "campaign_id": CAMPAIGN_ID,
            "benchmark": "omnidoc",
            "staged_benchmark_id": "omnidocbench",
            "dataset_revision": "aa1ee96d",
            "sample_id": f"omnidoc:images/{case_key}",
            "case_key": case_key,
            "original_source_relative_path": f"images/{case_key}.png",
            "original_source_sha256": jsonio.prefixed(jsonio.sha256_hex(case_key)),
            "media_type": "image",
            "page_index": 0,
            "input_relative_path": f"inputs/{case_key}.png",
            "input_png_sha256": jsonio.prefixed(jsonio.sha256_hex(case_key + "png")),
            "width": _PAGE_WIDTH,
            "height": _PAGE_HEIGHT,
            "bytes": 1024,
            "preflight": _preflight(case_key),
        }
        for case_key in cases
    ]
    jsonio.write_jsonl_atomic(paths.source_manifest, rows)


def write_model_registry(paths: ArenaPaths, models: tuple[str, ...]) -> None:
    jsonio.write_json_atomic(
        paths.model_registry,
        {
            "models": {
                model: {
                    "model_key": model,
                    "official_inference_config": {"max_new_tokens": _MAX_TOKENS},
                }
                for model in models
            }
        },
    )


def write_pod_ledger(paths: ArenaPaths, models: tuple[str, ...]) -> None:
    rows = [
        {
            "schema": "tavonel.arena.pod-ledger.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": model,
            "pod_id": f"pod-{model}",
            "gpu_type": "RTX4090",
            "listed_rate_usd_per_hour": _POD_RATES.get(model, 0.34),
            "data_center_id": "EU-RO-1",
            "price_snapshot_sha256": jsonio.prefixed(jsonio.sha256_hex("catalog")),
            "runtime_mode": "baked",
            "provisioned_at": "2026-09-03T09:00:00+00:00",
            "model_ready_at": "2026-09-03T09:05:00+00:00",
            "last_job_finished_at": "2026-09-03T10:00:00+00:00",
            "terminated_at": "2026-09-03T10:01:00+00:00",
            "billed_seconds": 3600,
            "model_loading_seconds": 300,
            "useful_inference_seconds": 3000,
            "retry_seconds": 0,
            "idle_seconds": 300,
            "estimated_provider_cost_usd": 0.34,
            "useful_cost_usd": 0.283,
            "wasted_cost_usd": 0.057,
        }
        for model in models
        if model != ESCALATION
    ]
    jsonio.write_jsonl_atomic(paths.cost_ledger, rows)


def write_model_outputs(paths: ArenaPaths, model: str, texts: dict[str, str]) -> None:
    manifest_rows: list[dict[str, Any]] = []
    for case_key in sorted(texts):
        text = texts[case_key]
        raw_sha = jsonio.write_text_atomic(paths.raw_text_path(model, case_key), text)
        canonical_sha = jsonio.write_text_atomic(paths.canonical_path(model, case_key), text)
        failed = model == PRIMARY and case_key in _FAILED_CASES
        receipt = {
            "schema": "tavonel.arena.page-receipt.v1",
            "campaign_id": CAMPAIGN_ID,
            "inference_job_id": jsonio.json_sha256_hex({"case": case_key, "model": model}),
            "benchmark": "omnidoc",
            "sample_id": f"omnidoc:images/{case_key}",
            "case_key": case_key,
            "source_sha256": jsonio.prefixed(jsonio.sha256_hex(case_key + "png")),
            "model_key": model,
            "model_revision": "rev-000",
            "runtime_image_digest": "image@sha256:" + "0" * 64,
            "runtime_mode": "subscription" if model == ESCALATION else "baked",
            "gpu_type": "RTX4090",
            "gpu_id": "0",
            "pod_id": f"pod-{model}",
            "worker_id": f"{model}-w0-pod",
            "shard_id": f"{model}-omnidoc-000",
            "job_kind": "inference",
            "queued_at": "2026-09-03T09:10:00+00:00",
            "worker_ready_at": "2026-09-03T09:10:05+00:00",
            "started_at": "2026-09-03T09:10:06+00:00",
            "first_token_at": None,
            "finished_at": "2026-09-03T09:10:07+00:00",
            "queue_ms": 10,
            "load_ms": 0,
            "preprocess_ms": 5,
            "inference_ms": 900,
            "postprocess_ms": 5,
            "total_ms": 920,
            "peak_vram_mb": 8000,
            "input_bytes": 1024,
            "output_bytes": len(text.encode("utf-8")),
            "output_chars": len(text),
            "input_tokens": None,
            # Only the primary hit its cap, and only on the page built to be cut off.
            "output_tokens": (
                _MAX_TOKENS if (model == PRIMARY and case_key == "case-truncated") else 40
            ),
            "attempt": 1,
            "retry_count": 0,
            "retry_reason": None,
            "status": "FAILED" if failed else "SUCCESS",
            "error_class": "OUTPUT_EMPTY" if failed else None,
            "error_message": None,
            "wasted_gpu_seconds": 0,
            "image_width": _PAGE_WIDTH,
            "image_height": _PAGE_HEIGHT,
            "raw_output_path": f"runs/{model}/raw/{case_key}.raw.txt",
            "raw_output_sha256": raw_sha,
            "canonical_output_path": f"runs/{model}/canonical/{case_key}.md",
            "canonical_output_sha256": canonical_sha,
        }
        if model == ESCALATION:
            receipt["api_equivalent_list_price_usd"] = 0.021
            receipt["subscription_included_usage"] = True
            receipt["actual_marginal_api_cost"] = "N/A"
        jsonio.write_json_atomic(paths.receipt_path(model, case_key), receipt)
        manifest_rows.append(
            {
                "case_key": case_key,
                "sample_id": f"omnidoc:images/{case_key}",
                "benchmark": "omnidoc",
                "status": receipt["status"],
                "raw_sha256": raw_sha,
                "canonical_sha256": canonical_sha,
                "receipt_sha256": jsonio.prefixed(
                    jsonio.sha256_hex(paths.receipt_path(model, case_key).read_bytes())
                ),
                "raw_path": f"runs/{model}/raw/{case_key}.raw.txt",
                "canonical_path": f"runs/{model}/canonical/{case_key}.md",
            }
        )
    jsonio.write_jsonl_atomic(paths.frozen_manifest(model), manifest_rows)
    jsonio.write_json_atomic(
        paths.frozen_outputs / model / "FROZEN.json",
        {
            "frozen_at": "2026-09-03T11:00:00+00:00",
            "manifest_sha256": jsonio.prefixed(
                jsonio.sha256_hex(paths.frozen_manifest(model).read_bytes())
            ),
            "sample_count": len(manifest_rows),
            "success_count": sum(1 for row in manifest_rows if row["status"] == "SUCCESS"),
            "failed_count": sum(1 for row in manifest_rows if row["status"] != "SUCCESS"),
            "model_revision": "rev-000",
            "runtime_image_digest": "image@sha256:" + "0" * 64,
        },
    )


def build_campaign(root: Path, *, with_escalation: bool = False) -> Campaign:
    """Write a complete synthetic campaign tree under ``root``."""
    paths = ArenaPaths(root=root)
    outputs = dict(OUTPUTS)
    if with_escalation:
        outputs[ESCALATION] = {case_key: CLEAN for case_key in CASES}
    models = tuple(sorted(outputs))
    write_source_manifest(paths, CASES)
    write_model_registry(paths, models)
    write_pod_ledger(paths, models)
    for model, texts in outputs.items():
        write_model_outputs(paths, model, texts)
    return Campaign(paths=paths, models=models, cases=CASES)


@pytest.fixture
def campaign(tmp_path: Path) -> Campaign:
    return build_campaign(tmp_path / "c")


@pytest.fixture
def campaign_with_opus(tmp_path: Path) -> Campaign:
    return build_campaign(tmp_path / "c", with_escalation=True)
