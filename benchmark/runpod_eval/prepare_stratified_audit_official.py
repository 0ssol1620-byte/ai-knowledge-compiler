#!/usr/bin/env python3
"""Prepare official evaluator inputs for all three stratified audit repeats."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from long_paths import long_path, safe_link_or_copy, safe_makedirs
from public_core_merge import build_parsebench_result, canonical_json, sha256_file

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError(f"expected a list of pages: {path}")
    return payload


def _link(source: Path, target: Path) -> None:
    # Audit inputs keep the corpora's original filenames, which push these paths
    # past the Windows limit once they are nested under an evaluation root.
    safe_link_or_copy(source, target)


def _filter_jsonl(source: Path, target: Path, selected_pdfs: set[str]) -> int:
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("pdf")) in selected_pdfs:
            rows.append(line)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return len(rows)


def prepare_audit_official(
    *,
    results_root: Path,
    staging_root: Path,
    acquired_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"audit official preparation exists: {output_root}")
    campaign = _load(results_root / "terminal-receipt.json")
    if (
        campaign.get("schema") != "folynta.public-core-stratified-audit-campaign.v1"
        or int(campaign.get("inference_count", -1)) != 1152
    ):
        raise ValueError("stratified audit campaign identity is invalid")
    worker_by_suite = {
        str(item["benchmark_id"]): int(item["worker_index"])
        for item in campaign["collections"]
    }
    if set(worker_by_suite) != set(SUITES):
        raise ValueError("stratified audit campaign suite coverage is invalid")
    output_root.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    manifests: dict[str, dict[str, Any]] = {}
    for suite in SUITES:
        manifest_path = staging_root / suite / "stratified-audit.json"
        manifest = _load(manifest_path)
        if (
            manifest.get("schema") != "folynta.public-core-stratified-audit.v1"
            or manifest.get("benchmark_id") != suite
            or int(manifest.get("input_count", -1)) != 128
        ):
            raise ValueError(f"stratified audit manifest identity mismatch: {suite}")
        manifests[suite] = manifest
        manifest_target = output_root / "manifests" / f"{suite}.json"
        manifest_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_path, manifest_target)

    parse_manifest = manifests["parsebench"]
    parse_selected = {str(item["source_relative_path"]) for item in parse_manifest["inputs"]}
    parse_source = acquired_root / "parsebench"
    parse_dataset = output_root / "datasets" / "parsebench"
    rule_counts: dict[str, int] = {}
    for jsonl in (
        "chart.jsonl",
        "layout.jsonl",
        "table.jsonl",
        "text_content.jsonl",
        "text_formatting.jsonl",
    ):
        rule_counts[jsonl] = _filter_jsonl(
            parse_source / jsonl,
            parse_dataset / jsonl,
            parse_selected,
        )
    for relative in sorted(parse_selected):
        _link(parse_source / relative, parse_dataset / relative)
    groups = ("chart", "layout", "table", "text")
    if not all(
        any(relative.startswith(f"docs/{group}/") for relative in parse_selected)
        for group in groups
    ):
        raise ValueError("ParseBench audit does not cover every benchmark group")

    olm_manifest = manifests["olmocr-bench"]
    olm_selected = {
        Path(str(item["source_relative_path"])).relative_to("bench_data/pdfs").as_posix()
        for item in olm_manifest["inputs"]
    }
    olm_source = acquired_root / "olmocr-bench" / "bench_data"
    olm_dataset = output_root / "datasets" / "olmocr-bench" / "pdfs"
    olm_rule_counts: dict[str, int] = {}
    for jsonl in sorted(olm_source.glob("*.jsonl")):
        olm_rule_counts[jsonl.name] = _filter_jsonl(
            jsonl,
            output_root / "datasets" / "olmocr-bench" / jsonl.name,
            olm_selected,
        )
    for relative in sorted(olm_selected):
        _link(olm_source / "pdfs" / relative, olm_dataset / relative)
    if sum(olm_rule_counts.values()) < 1:
        raise ValueError("olmOCR audit subset has no official rules")

    # OmniDocBench scores against a ground-truth file, so the audit needs one
    # narrowed to the sampled pages; handing it the full 1,651-page file makes
    # the evaluator refuse a 128-page prediction set.
    omnidoc_pages: set[str] = set()

    for suite in SUITES:
        summary_path = results_root / suite / "run-summary.json"
        summary = _load(summary_path)
        runs = summary.get("runs", [])
        if (
            summary.get("candidate_id") != "mineru-3.4.4-vlm"
            or summary.get("evidence_class") != "stratified-audit"
            or [int(run["repeat_index"]) for run in runs] != [1, 2, 3]
        ):
            raise ValueError(f"stratified audit run summary mismatch: {suite}")
        manifest = manifests[suite]
        cases = {str(item["case_id"]): item for item in manifest["inputs"]}
        if len(cases) != 128:
            raise ValueError(f"stratified audit case coverage mismatch: {suite}")
        for repeat_index, run in enumerate(runs, 1):
            observed = {str(item["case_id"]): item for item in run["cases"]}
            if set(observed) != set(cases):
                raise ValueError(
                    f"stratified audit repeat coverage mismatch: {suite}/{repeat_index}"
                )
            completed = 0
            for case_id, case in cases.items():
                runtime = observed[case_id]
                markdown = (
                    results_root
                    / suite
                    / f"markdown-repeat-{repeat_index}"
                    / f"{case_id}.md"
                )
                if sha256_file(markdown) != str(runtime["markdown_sha256"]):
                    raise ValueError(f"stratified audit Markdown binding mismatch: {case_id}")
                source = Path(str(case["source_relative_path"]))
                if runtime.get("status") != "completed":
                    # A case that produced nothing still has to reach the
                    # evaluator. olmOCR refuses a candidate set with a document
                    # missing entirely, so the absence is expressed as an empty
                    # answer, which is what the pipeline actually delivered and
                    # what the evaluator should score as a failure.
                    if suite == "olmocr-bench":
                        relative = source.relative_to("bench_data/pdfs")
                        empty = (
                            output_root
                            / "predictions"
                            / suite
                            / f"repeat-{repeat_index}"
                            / relative.parent
                            / f"{relative.stem}_pg1_repeat1.md"
                        )
                        safe_makedirs(empty.parent)
                        with open(long_path(empty), "w", encoding="utf-8"):
                            pass
                    continue
                completed += 1
                if suite == "parsebench":
                    model_path = (
                        results_root
                        / suite
                        / f"repeat-{repeat_index}"
                        / case_id
                        / "vlm"
                        / f"{case_id}_model.json"
                    )
                    result = build_parsebench_result(
                        case=case,
                        markdown=markdown.read_text(encoding="utf-8"),
                        model_payload=json.loads(model_path.read_text(encoding="utf-8")),
                        input_path=staging_root
                        / suite
                        / str(case["input_relative_path"]),
                        worker_index=worker_by_suite[suite],
                        run_summary_sha256=sha256_file(summary_path),
                    )
                    destination = (
                        output_root
                        / "predictions"
                        / suite
                        / f"repeat-{repeat_index}"
                        / source.parent.name
                        / f"{source.stem}.result.json"
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(canonical_json(result))
                elif suite == "omnidocbench":
                    _link(
                        markdown,
                        output_root
                        / "predictions"
                        / suite
                        / f"markdown-repeat-{repeat_index}"
                        / f"{source.stem}.md",
                    )
                    omnidoc_pages.add(source.name)
                else:
                    relative = source.relative_to("bench_data/pdfs")
                    _link(
                        markdown,
                        output_root
                        / "predictions"
                        / suite
                        / f"repeat-{repeat_index}"
                        / relative.parent
                        / f"{relative.stem}_pg1_repeat1.md",
                    )
            records.append(
                {
                    "benchmark_id": suite,
                    "repeat_index": repeat_index,
                    "completed": completed,
                    "failed": 128 - completed,
                }
            )
    # OmniDocBench compares against a ground-truth file page by page and refuses
    # to score when the counts differ, so the audit gets a copy narrowed to the
    # pages it actually sampled.
    omnidoc_ground_truth = _load_list(acquired_root / "omnidocbench" / "OmniDocBench.json")
    omnidoc_subset = [
        page
        for page in omnidoc_ground_truth
        if str(page.get("page_info", {}).get("image_path")) in omnidoc_pages
    ]
    if len(omnidoc_subset) != len(omnidoc_pages):
        raise ValueError(
            f"OmniDocBench audit ground truth covers {len(omnidoc_subset)} of "
            f"{len(omnidoc_pages)} sampled pages"
        )
    omnidoc_target = output_root / "datasets" / "omnidocbench" / "OmniDocBench.json"
    omnidoc_target.parent.mkdir(parents=True, exist_ok=True)
    omnidoc_target.write_text(
        json.dumps(omnidoc_subset, ensure_ascii=False), encoding="utf-8"
    )

    receipt: dict[str, Any] = {
        "schema": "folynta.stratified-audit-official-preparation.v1",
        "suite_count": 3,
        "repeat_count": 3,
        "input_count_per_suite": 128,
        "records": records,
        "parsebench_rule_counts": rule_counts,
        "olmocr_rule_counts": olm_rule_counts,
        "omnidocbench_ground_truth_pages": len(omnidoc_subset),
        "paths": {
            "manifests": str(output_root / "manifests"),
            "datasets": str(output_root / "datasets"),
            "predictions": str(output_root / "predictions"),
        },
    }
    receipt_path = output_root / "preparation-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return {**receipt, "receipt_sha256": sha256_file(receipt_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--acquired-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = prepare_audit_official(
        results_root=args.results_root.resolve(),
        staging_root=args.staging_root.resolve(),
        acquired_root=args.acquired_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["prepare_audit_official"]
