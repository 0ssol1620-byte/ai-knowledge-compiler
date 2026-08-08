"""Create ground-truth-free, deterministic public-core shard manifests.

The generated manifests are the only benchmark input metadata copied to GPU
workers.  Evaluator labels remain on the controller.  Pages that originate
from the same document are assigned to one primary worker, while a retry owner
is always a different worker when more than one worker is available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from benchmark.v6.contracts import canonical_sha256
from benchmark.v6.sharding import PageManifestEntry, plan_document_shards

_PAGE_SUFFIXES = (
    re.compile(r"(?i)(?:[_-]page[_-]?\d+)$"),
    re.compile(r"(?i)(?:[_-]p(?:age)?\d+)$"),
    re.compile(r"(?i)(?:[_-]pg\d+(?:[_-]pg\d+)*)$"),
)


def _document_id(benchmark_id: str, source_relative_path: str) -> str:
    source = Path(source_relative_path.replace("\\", "/"))
    stem = source.stem
    # OmniDocBench ships page images from multi-page source documents.  The
    # other public suites stage independent one-page benchmark cases whose
    # filenames may coincidentally share a source-looking prefix, so collapsing
    # those names would create duplicate page coordinates and false context.
    if benchmark_id == "omnidocbench":
        for pattern in _PAGE_SUFFIXES:
            updated = pattern.sub("", stem)
            if updated != stem:
                stem = updated
                break
    normalized = f"{source.parent.as_posix()}/{stem}".lstrip("./")
    return f"{benchmark_id}:{normalized}"


def _retry_owner(*, page_id: str, primary_owner: int, worker_count: int) -> int:
    if worker_count < 1:
        raise ValueError("worker_count must be positive")
    if not 0 <= primary_owner < worker_count:
        raise ValueError("primary_owner is outside worker_count")
    if worker_count == 1:
        return primary_owner
    digest = hashlib.sha256(f"retry\0{page_id}".encode()).digest()
    offset = 1 + int.from_bytes(digest[:8], "big") % (worker_count - 1)
    return (primary_owner + offset) % worker_count


def build_campaign_plan(
    *,
    manifests: tuple[Path, ...],
    worker_count: int,
    estimated_seconds_per_page: float,
) -> dict[str, Any]:
    if worker_count < 2:
        raise ValueError("at least two workers are required for cross-worker retry")
    if estimated_seconds_per_page <= 0:
        raise ValueError("estimated_seconds_per_page must be positive")

    suites: list[dict[str, Any]] = []
    total_pages = 0
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        benchmark_id = str(manifest["benchmark_id"])
        revision = str(manifest["dataset_revision"])
        inputs = manifest["inputs"]
        pages = tuple(
            PageManifestEntry(
                document_id=_document_id(benchmark_id, str(item["source_relative_path"])),
                page_number=int(item.get("page_index", 0)) + 1,
                page_id=str(item["case_id"]),
                source_sha256=str(item["input_sha256"]),
                estimated_seconds=estimated_seconds_per_page,
                page_class=benchmark_id,
            )
            for item in inputs
        )
        namespace = f"{benchmark_id}@{revision}"
        shards = plan_document_shards(pages, shard_count=worker_count, namespace=namespace)
        input_by_case = {str(item["case_id"]): item for item in inputs}
        serialized_shards: list[dict[str, Any]] = []
        for shard in shards:
            shard_inputs: list[dict[str, Any]] = []
            for page in shard.pages:
                source = input_by_case[page.page_id]
                shard_inputs.append(
                    {
                        "case_id": page.page_id,
                        "document_id": page.document_id,
                        "page_number": page.page_number,
                        "input_relative_path": str(source["input_relative_path"]),
                        "input_sha256": page.source_sha256,
                        "primary_worker_index": shard.shard_index,
                        "retry_worker_index": _retry_owner(
                            page_id=page.page_id,
                            primary_owner=shard.shard_index,
                            worker_count=worker_count,
                        ),
                    }
                )
            serialized_shards.append(
                {
                    "shard_id": shard.shard_id,
                    "worker_index": shard.shard_index,
                    "manifest_sha256": shard.manifest_sha256,
                    "estimated_seconds": shard.estimated_seconds,
                    "input_count": len(shard_inputs),
                    "inputs": shard_inputs,
                }
            )
        total_pages += len(pages)
        suites.append(
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": revision,
                "source_manifest_sha256": manifest["source_manifest_sha256"],
                "ground_truth_mounted": False,
                "input_count": len(pages),
                "shards": serialized_shards,
            }
        )

    plan: dict[str, Any] = {
        "schema": "folynta.public-core-shard-campaign.v1",
        "worker_count": worker_count,
        "total_input_count": total_pages,
        "ground_truth_mounted_on_workers": False,
        "retry_excludes_primary_worker": True,
        "suites": suites,
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", action="append", type=Path, required=True)
    parser.add_argument("--worker-count", type=int, default=4)
    parser.add_argument("--estimated-seconds-per-page", type=float, default=34.7077806417882)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_campaign_plan(
        manifests=tuple(args.manifest),
        worker_count=args.worker_count,
        estimated_seconds_per_page=args.estimated_seconds_per_page,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "plan_sha256": plan["plan_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
