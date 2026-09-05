"""A synthetic frozen campaign tree, small enough to reason about by hand.

Six pages - two per benchmark - with real bytes on disk and real sha256
values, so the QA gate, the layout writers and the provenance walk are
exercised against files rather than against mocks. Every helper that breaks
something breaks exactly one thing, which is what lets a failing test name the
check it broke.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from arena.constants import CAMPAIGN_ID
from arena.scoring import jsonio
from arena.scoring.paths import ScoringPaths

MODEL_KEY = "paddleocr_vl_1_6"
MODEL_REVISION = "a" * 40
IMAGE_DIGEST = "ghcr.io/example/paddleocr@sha256:" + "b" * 64
PROMPT_ID = "paddleocr_official_v1"
PROMPT_SHA = "sha256:" + "c" * 64
CONFIG_SHA = "sha256:" + "d" * 64


@dataclass(frozen=True, slots=True)
class CaseSpec:
    benchmark: str
    case_key: str
    source_relative_path: str
    media_type: str
    page_index: int
    markdown: str
    status: str = "SUCCESS"
    is_probably_blank: bool = False


DEFAULT_CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        benchmark="omnidoc",
        case_key="omnidocbench-0000000000000000000000a1",
        source_relative_path="images/PPT_alpha_page_001.png",
        media_type="image",
        page_index=1,
        markdown="# Alpha\n\nfirst page\n",
    ),
    CaseSpec(
        benchmark="omnidoc",
        case_key="omnidocbench-0000000000000000000000a2",
        source_relative_path="images/PPT_beta_page_002.png",
        media_type="image",
        page_index=2,
        markdown="# Beta\n\n| a | b |\n",
    ),
    CaseSpec(
        benchmark="parsebench",
        case_key="parsebench-0000000000000000000000b1",
        source_relative_path="docs/chart/quarterly_chart.pdf",
        media_type="pdf",
        page_index=0,
        markdown="## Quarterly\n\nrevenue rose\n",
    ),
    CaseSpec(
        benchmark="parsebench",
        case_key="parsebench-0000000000000000000000b2",
        source_relative_path="docs/text/policy_letter.pdf",
        media_type="pdf",
        page_index=0,
        markdown="Dear reader\n",
    ),
    CaseSpec(
        benchmark="olmocr",
        case_key="olmocr-bench-0000000000000000000000c1",
        source_relative_path="bench_data/pdfs/arxiv_math/2502.15977_pg21.pdf",
        media_type="pdf",
        page_index=0,
        markdown="$x^2$\n",
    ),
    CaseSpec(
        benchmark="olmocr",
        case_key="olmocr-bench-0000000000000000000000c2",
        source_relative_path="bench_data/pdfs/tables/table_two.pdf",
        media_type="pdf",
        page_index=0,
        markdown="| h | i |\n| - | - |\n",
    ),
)


@dataclass
class Campaign:
    root: Path
    paths: ScoringPaths
    model_key: str
    specs: tuple[CaseSpec, ...]
    manifest_rows: list[dict[str, Any]] = field(default_factory=list)

    # ---------------------------------------------------------------- helpers
    def spec(self, case_key: str) -> CaseSpec:
        for spec in self.specs:
            if spec.case_key == case_key:
                return spec
        raise KeyError(case_key)

    def canonical(self, case_key: str) -> Path:
        return self.paths.canonical_path(self.model_key, case_key)

    def raw(self, case_key: str) -> Path:
        return self.paths.raw_path(self.model_key, case_key)

    def receipt(self, case_key: str) -> Path:
        return self.paths.receipt_path(self.model_key, case_key)

    def rewrite_manifest(self) -> None:
        jsonio.write_jsonl_atomic(
            self.paths.frozen_manifest(self.model_key), self.manifest_rows
        )

    def edit_receipt(self, case_key: str, **changes: Any) -> None:
        path = self.receipt(case_key)
        document = jsonio.read_json(path)
        document.update(changes)
        jsonio.write_json_atomic(path, document)

    def corrupt_canonical(self, case_key: str, text: str = "tampered\n") -> None:
        """Change the bytes without changing the hash the manifest recorded."""

        jsonio.write_text_atomic(self.canonical(case_key), text)

    def empty_canonical(self, case_key: str) -> None:
        """Truncate an output and keep the manifest hash honest about it."""

        digest = jsonio.write_bytes_atomic(self.canonical(case_key), b"")
        for row in self.manifest_rows:
            if row["case_key"] == case_key:
                row["canonical_sha256"] = digest
        self.rewrite_manifest()

    def write_invalid_utf8(self, case_key: str) -> None:
        digest = jsonio.write_bytes_atomic(self.canonical(case_key), b"\xff\xfe not utf8")
        for row in self.manifest_rows:
            if row["case_key"] == case_key:
                row["canonical_sha256"] = digest
        self.rewrite_manifest()

    def duplicate_row(self, case_key: str) -> None:
        for row in list(self.manifest_rows):
            if row["case_key"] == case_key:
                self.manifest_rows.append(dict(row))
        self.rewrite_manifest()

    def drop_row(self, case_key: str) -> None:
        self.manifest_rows = [
            row for row in self.manifest_rows if row["case_key"] != case_key
        ]
        self.rewrite_manifest()

    def set_campaign_manifest_count(self, benchmark: str, count: int) -> None:
        document = jsonio.read_json(self.paths.campaign_manifest)
        document["benchmarks"][benchmark]["sample_count"] = count
        jsonio.write_json_atomic(self.paths.campaign_manifest, document)

    def remove_campaign_manifest(self) -> None:
        jsonio.io_path(self.paths.campaign_manifest).unlink()


def build_campaign(
    root: Path,
    *,
    model_key: str = MODEL_KEY,
    specs: Sequence[CaseSpec] = DEFAULT_CASES,
) -> Campaign:
    paths = ScoringPaths(root=root, repo_root=root / "repo")
    specs = tuple(specs)
    source_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for spec in specs:
        counts[spec.benchmark] = counts.get(spec.benchmark, 0) + 1
        official = spec.source_relative_path.rsplit(".", 1)[0]
        sample_id = (
            f"{spec.benchmark}:{official}"
            if spec.media_type != "pdf"
            else f"{spec.benchmark}:{official}#p{spec.page_index}"
        )
        png_bytes = f"PNG-{spec.case_key}".encode()
        input_sha = jsonio.sha256_bytes(png_bytes)
        source_rows.append(
            {
                "schema": "tavonel.arena.source-row.v1",
                "campaign_id": CAMPAIGN_ID,
                "benchmark": spec.benchmark,
                "staged_benchmark_id": spec.case_key.rsplit("-", 1)[0],
                "dataset_revision": "e" * 40,
                "sample_id": sample_id,
                "case_key": spec.case_key,
                "original_source_relative_path": spec.source_relative_path,
                "original_source_sha256": jsonio.sha256_bytes(spec.source_relative_path),
                "media_type": spec.media_type,
                "page_index": spec.page_index,
                "input_relative_path": f"inputs/{spec.case_key}.png",
                "input_png_sha256": input_sha,
                "width": 1654,
                "height": 2339,
                "bytes": len(png_bytes),
                "preflight": {
                    "near_white_ratio": 0.99 if spec.is_probably_blank else 0.42,
                    "is_probably_blank": spec.is_probably_blank,
                },
            }
        )

        canonical_path = paths.canonical_path(model_key, spec.case_key)
        raw_path = paths.raw_path(model_key, spec.case_key)
        receipt_path = paths.receipt_path(model_key, spec.case_key)
        canonical_sha = jsonio.write_text_atomic(canonical_path, spec.markdown)
        raw_sha = jsonio.write_text_atomic(raw_path, spec.markdown)
        receipt = {
            "schema": "tavonel.arena.page-receipt.v1",
            "campaign_id": CAMPAIGN_ID,
            "case_key": spec.case_key,
            "sample_id": sample_id,
            "benchmark": spec.benchmark,
            "status": spec.status,
            "error_class": None if spec.status == "SUCCESS" else "UNKNOWN",
            "model_key": model_key,
            "model_revision": MODEL_REVISION,
            "runtime_image_digest": IMAGE_DIGEST,
            "runtime_mode": "baked",
            "prompt_id": PROMPT_ID,
            "prompt_sha256": PROMPT_SHA,
            "inference_config_sha256": CONFIG_SHA,
            "source_sha256": input_sha,
            "raw_output_sha256": raw_sha,
            "canonical_output_sha256": canonical_sha,
        }
        receipt_sha = jsonio.write_json_atomic(receipt_path, receipt)
        manifest_rows.append(
            {
                "schema": "tavonel.arena.frozen_manifest_entry.v1",
                "case_key": spec.case_key,
                "sample_id": sample_id,
                "benchmark": spec.benchmark,
                "status": spec.status,
                "raw_sha256": raw_sha,
                "canonical_sha256": canonical_sha,
                "receipt_sha256": receipt_sha,
                "raw_path": str(raw_path.relative_to(root)).replace("\\", "/"),
                "canonical_path": str(canonical_path.relative_to(root)).replace("\\", "/"),
            }
        )

    jsonio.write_jsonl_atomic(paths.source_manifest, source_rows)
    jsonio.write_jsonl_atomic(paths.frozen_manifest(model_key), manifest_rows)
    jsonio.write_json_atomic(
        paths.frozen_marker(model_key),
        {
            "schema": "tavonel.arena.frozen_marker.v1",
            "campaign_id": CAMPAIGN_ID,
            "frozen_at": "2026-09-03T00:00:00Z",
            "manifest_sha256": jsonio.sha256_file(paths.frozen_manifest(model_key)),
            "sample_count": len(specs),
            "success_count": sum(1 for spec in specs if spec.status == "SUCCESS"),
            "failed_count": sum(1 for spec in specs if spec.status != "SUCCESS"),
            "model_revision": MODEL_REVISION,
            "runtime_image_digest": IMAGE_DIGEST,
        },
    )
    jsonio.write_json_atomic(
        paths.campaign_manifest,
        {
            "schema": "tavonel.arena.campaign-manifest.v1",
            "campaign_id": CAMPAIGN_ID,
            "benchmarks": {
                benchmark: {"sample_count": count} for benchmark, count in counts.items()
            },
            "total_samples": len(specs),
        },
    )
    return Campaign(
        root=root,
        paths=paths,
        model_key=model_key,
        specs=specs,
        manifest_rows=manifest_rows,
    )


def add_composite(
    campaign: Campaign,
    variant: str = "c_adaptive",
    *,
    unresolved: Sequence[str] = (),
) -> str:
    """Write a TAVONEL replay manifest that reuses the model's frozen pages."""

    rows: list[dict[str, Any]] = []
    for spec in campaign.specs:
        row: dict[str, Any] = {
            "schema": "tavonel.arena.replay-row.v1",
            "campaign_id": CAMPAIGN_ID,
            "variant": variant,
            "case_key": spec.case_key,
            "sample_id": next(
                item["sample_id"]
                for item in campaign.manifest_rows
                if item["case_key"] == spec.case_key
            ),
            "benchmark": spec.benchmark,
            "chosen_model_key": campaign.model_key,
            "final_model": campaign.model_key,
        }
        if spec.case_key in unresolved:
            row.update(
                {
                    "unresolved": True,
                    "unresolved_reason": "no frozen output for the chosen model",
                    "composite_canonical_path": None,
                    "composite_canonical_sha256": None,
                }
            )
        else:
            destination = campaign.paths.composite_canonical(variant, spec.case_key)
            digest = jsonio.write_text_atomic(destination, spec.markdown)
            row.update(
                {
                    "unresolved": False,
                    "unresolved_reason": None,
                    "composite_canonical_path": str(
                        destination.relative_to(campaign.root)
                    ).replace("\\", "/"),
                    "composite_canonical_sha256": digest,
                    "chosen_raw_path": str(
                        campaign.raw(spec.case_key).relative_to(campaign.root)
                    ).replace("\\", "/"),
                    "chosen_raw_sha256": jsonio.sha256_file(campaign.raw(spec.case_key)),
                }
            )
        rows.append(row)
    jsonio.write_jsonl_atomic(campaign.paths.composite_manifest(variant), rows)
    return variant


@pytest.fixture
def campaign(tmp_path: Path) -> Campaign:
    return build_campaign(tmp_path / "arena")
