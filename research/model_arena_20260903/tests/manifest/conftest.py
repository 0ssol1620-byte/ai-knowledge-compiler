"""Synthetic staged-public-core tree + fake lock file for lane A2 tests.

Deliberately tiny (3 fake PNGs per benchmark by default) and fully synthetic:
no real benchmark data, no GT, no network. Mirrors the real staged-manifest
shape produced by ``benchmark/runpod_eval/public_core_sources.py`` closely
enough that ``arena.manifest.build`` cannot tell the difference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.manifest.build import BenchmarkSource, BuildConfig
from arena.manifest.hashing import canonical_json, sha256_file, sha256_text
from PIL import Image

BENCHMARKS: tuple[str, ...] = ("parsebench", "omnidoc", "olmocr")
STAGED_IDS: dict[str, str] = {
    "parsebench": "parsebench",
    "omnidoc": "omnidocbench",
    "olmocr": "olmocr-bench",
}


def make_png(path: Path, *, fill: int = 128, size: tuple[int, int] = (16, 16)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", size, color=fill).save(path, format="PNG")


def default_items(benchmark: str, count: int = 3) -> list[dict[str, Any]]:
    staged_id = STAGED_IDS[benchmark]
    media_type = "pdf" if benchmark == "parsebench" else "image"
    items = []
    for i in range(count):
        source_path = f"docs/fake_{i}.pdf" if media_type == "pdf" else f"images/fake_{i}.png"
        items.append(
            {
                "case_id": f"{staged_id}-case{i:03d}",
                "source_relative_path": source_path,
                "media_type": media_type,
                "page_index": 0,
                "fill": 250 if i == 0 else min(255, 40 * i),
            }
        )
    return items


def build_staged_tree(
    stage_root: Path,
    *,
    items_by_benchmark: dict[str, list[dict[str, Any]]],
    revisions: dict[str, str],
    extra_files: dict[str, list[str]] | None = None,
) -> None:
    """Write ``<stage_root>/<staged_id>/{inference-input-manifest.json,inputs/*.png}``.

    ``extra_files`` (benchmark key -> list of relative paths under that
    benchmark's staged root) lets a test plant an extra, non-whitelisted file
    to exercise the GT-isolation "planted file" failure path.
    """
    extra_files = extra_files or {}
    for benchmark, items in items_by_benchmark.items():
        staged_id = STAGED_IDS[benchmark]
        bench_root = stage_root / staged_id
        inputs_dir = bench_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        manifest_items = []
        for item in items:
            case_id = item["case_id"]
            png_path = inputs_dir / f"{case_id}.png"
            make_png(png_path, fill=item.get("fill", 128))
            manifest_items.append(
                {
                    "case_id": case_id,
                    "source_relative_path": item["source_relative_path"],
                    "source_sha256": item.get("source_sha256", "sha256:" + "0" * 64),
                    "media_type": item["media_type"],
                    "page_index": item.get("page_index", 0),
                    "input_relative_path": f"inputs/{case_id}.png",
                    "input_sha256": sha256_file(png_path),
                }
            )

        manifest: dict[str, Any] = {
            "schema": "folynta.public-core-inference-inputs.v1",
            "benchmark_id": staged_id,
            "dataset_revision": revisions[benchmark],
            "source_manifest_sha256": "sha256:" + "1" * 64,
            "ground_truth_mounted": False,
            "renderer": {"pdf_backend": "test", "dpi": 72, "output_format": "png"},
            "source_count": len(manifest_items),
            "input_count": len(manifest_items),
            "complete_source_coverage": True,
            "complete_input_coverage": True,
            "inputs": manifest_items,
        }
        content = {k: v for k, v in manifest.items() if k != "content_sha256"}
        manifest["content_sha256"] = sha256_text(canonical_json(content))
        (bench_root / "inference-input-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        for relative in extra_files.get(benchmark, []):
            planted = bench_root / relative
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text("not a png", encoding="utf-8")


def write_fake_lock(path: Path, revisions: dict[str, str]) -> None:
    entries = []
    for benchmark in BENCHMARKS:
        staged_id = STAGED_IDS[benchmark]
        entries.append(
            {
                "id": staged_id,
                "dataset": {
                    "repository": f"fake/{staged_id}",
                    "revision": revisions[benchmark],
                    "manifest_sha256": "sha256:" + "a" * 64,
                },
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"benchmarks": entries}), encoding="utf-8")


def make_config(
    tmp_path: Path,
    *,
    per_benchmark: int = 3,
    revisions: dict[str, str] | None = None,
    items_by_benchmark: dict[str, list[dict[str, Any]]] | None = None,
    expected_counts: dict[str, int] | None = None,
    extra_files: dict[str, list[str]] | None = None,
) -> BuildConfig:
    revisions = revisions or {b: f"rev-{b}" for b in BENCHMARKS}
    items_by_benchmark = items_by_benchmark or {
        b: default_items(b, per_benchmark) for b in BENCHMARKS
    }
    expected_counts = expected_counts or {b: len(items_by_benchmark[b]) for b in BENCHMARKS}

    stage_root = tmp_path / "staged-public-core"
    build_staged_tree(
        stage_root,
        items_by_benchmark=items_by_benchmark,
        revisions=revisions,
        extra_files=extra_files,
    )
    lock_path = tmp_path / "benchmark-registry.lock.yaml"
    write_fake_lock(lock_path, revisions)

    constants_path = tmp_path / "fake_constants.py"
    constants_path.write_text("FAKE = True\n", encoding="utf-8")

    acquired_root = tmp_path / "acquired-public-core"
    acquired_root.mkdir(parents=True, exist_ok=True)
    evaluator_cache_root = tmp_path / "evaluator-cache"
    evaluator_cache_root.mkdir(parents=True, exist_ok=True)

    benchmarks = tuple(
        BenchmarkSource(
            key=b,
            staged_id=STAGED_IDS[b],
            inputs_root=stage_root / STAGED_IDS[b],
            expected_count=expected_counts[b],
            dataset_repository=f"fake/{STAGED_IDS[b]}",
            dataset_revision=revisions[b],
            dataset_manifest_sha256="sha256:" + "a" * 64,
        )
        for b in BENCHMARKS
        if b in items_by_benchmark
    )

    out_dir = tmp_path / "out"
    return BuildConfig(
        campaign_id="TEST-CAMPAIGN-V1",
        benchmarks=benchmarks,
        acquired_root=acquired_root,
        evaluator_cache_root=evaluator_cache_root,
        output_source_manifest=out_dir / "source_manifest.jsonl",
        output_campaign_manifest=out_dir / "campaign_manifest.json",
        output_canary_selection=out_dir / "canary_selection.json",
        cache_path=out_dir / "receipts" / "manifest-hash-cache.json",
        receipts_dir=out_dir / "receipts",
        constants_path=constants_path,
        canary_salt="TEST-SALT",
        canary_pages_per_benchmark=2,
        opus_canary_counts={"parsebench": 2, "omnidoc": 2, "olmocr": 1},
        budget={"target_usd": 1.0, "soft_cap_usd": 2.0, "hard_cap_usd": 3.0},
        historical_evaluator_pins={b: f"pin-{b}" for b in BENCHMARKS},
    )


@pytest.fixture
def build_config(tmp_path: Path) -> BuildConfig:
    return make_config(tmp_path)


# Fixture-based access to the module-level helpers above. Test modules in this
# directory consume these instead of importing this conftest module directly
# (pytest's own conftest-loading machinery already claims the "conftest" module
# name; a second `import conftest` from a sibling test file is fragile).


@pytest.fixture
def config_factory(tmp_path: Path):
    def _factory(**kwargs: Any) -> BuildConfig:
        return make_config(tmp_path, **kwargs)

    return _factory


@pytest.fixture
def staged_tree_builder():
    return build_staged_tree


@pytest.fixture
def fake_lock_writer():
    return write_fake_lock


@pytest.fixture
def default_items_factory():
    return default_items


@pytest.fixture
def staged_ids() -> dict[str, str]:
    return dict(STAGED_IDS)
