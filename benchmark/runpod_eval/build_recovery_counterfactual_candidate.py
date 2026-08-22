#!/usr/bin/env python3
"""Build the candidate set the campaign would have produced without recovery.

Published leaderboard numbers are not comparable to ours: different evaluator
revisions, an excluded metric, and a deliberately conservative watchdog policy
all move the score independently of anything we built. The comparison that does
isolate our contribution holds everything constant except whether the recovery
lane ran.

Recovery's contribution to accuracy is not subtle: a case it rescued produced no
output at all in the primary run, and a document with no output fails every rule
the official evaluator applies to it. So the counterfactual candidate set is the
real one with the rescued documents emptied, and the score difference between
the two is attributable to recovery alone.

The rescued documents are emptied rather than deleted because an absent file is
a candidate-validation error in some evaluators, which would abort the run
instead of scoring it. An empty document is what the pipeline actually would
have delivered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def long_path(path: Path) -> str:
    """Return a form of the path that survives the Windows 260-character limit.

    olmOCR-Bench candidate filenames embed a document hash and a page number, so
    a nested output root pushes ordinary paths past MAX_PATH and the copy fails
    partway through. The extended-length prefix lifts the limit; on other
    platforms the path is returned unchanged.
    """
    if os.name != "nt":
        return str(path)
    resolved = os.path.abspath(str(path))
    if resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved.lstrip("\\")
    return "\\\\?\\" + resolved


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


CATEGORY_LAYOUT = "category"
FLAT_LAYOUT = "flat"
PARSEBENCH_RESULT_LAYOUT = "parsebench_result"


def empty_parsebench_result(path: str) -> None:
    """Rewrite a ParseBench result so it carries no extraction.

    ParseBench candidates are JSON envelopes rather than markdown files, so
    truncating the file would make it unreadable rather than empty. A worker that
    died produced no text and detected no regions, so the envelope is preserved
    and the extraction inside it is cleared: that is what the evaluator would
    have been handed.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    output = payload.get("output")
    if not isinstance(output, dict):
        raise ValueError(f"ParseBench result has no output object: {path}")
    output["markdown"] = ""
    for key in ("layout_pages", "pages"):
        if key in output:
            output[key] = []
    payload["raw_output"] = None
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def candidate_relative_path(
    source_relative_path: str, suffix: str, layout: str = CATEGORY_LAYOUT
) -> str:
    """Map a source document path to the evaluator's candidate markdown path.

    The two evaluators lay their candidates out differently. olmOCR-Bench mirrors
    the dataset's category folders, so ``bench_data/pdfs/<category>/<stem>.pdf``
    is answered by ``<category>/<stem><suffix>.md``. OmniDocBench keeps every
    prediction in one directory keyed only by the source stem.
    """
    parts = Path(source_relative_path).parts
    stem = Path(parts[-1]).stem
    if layout == FLAT_LAYOUT:
        return f"markdown-repeat-1/{stem}{suffix}.md"
    if layout not in (CATEGORY_LAYOUT, PARSEBENCH_RESULT_LAYOUT):
        raise ValueError(f"unknown candidate layout: {layout}")
    if len(parts) < 2:
        raise ValueError(f"cannot derive category from source path: {source_relative_path}")
    if layout == PARSEBENCH_RESULT_LAYOUT:
        return f"{parts[-2]}/{stem}.result.json"
    return f"{parts[-2]}/{stem}{suffix}.md"


def build_counterfactual(
    *,
    candidate_root: Path,
    output_root: Path,
    case_index: dict[str, Any],
    emptied_case_ids: set[str],
    candidate_suffix: str,
    layout: str = CATEGORY_LAYOUT,
) -> dict[str, Any]:
    if os.path.exists(long_path(output_root)):
        raise FileExistsError(f"counterfactual candidate set already exists: {output_root}")

    records = {str(record["case_id"]): record for record in case_index["records"]}
    unknown = sorted(emptied_case_ids - set(records))
    if unknown:
        raise ValueError(
            f"{len(unknown)} cases to empty are absent from the case index, "
            f"first: {unknown[0]}"
        )

    shutil.copytree(long_path(candidate_root), long_path(output_root))

    emptied: list[str] = []
    absent: list[str] = []
    for case_id in sorted(emptied_case_ids):
        record = records[case_id]
        relative = candidate_relative_path(
            str(record["source_relative_path"]), candidate_suffix, layout
        )
        target = long_path(output_root / relative)
        if not os.path.exists(target):
            # A case with no candidate file was already missing from the real
            # run, so recovery did not supply it and nothing is attributable.
            absent.append(case_id)
            continue
        if layout == PARSEBENCH_RESULT_LAYOUT:
            empty_parsebench_result(target)
        else:
            with open(target, "w", encoding="utf-8"):
                pass
        emptied.append(case_id)

    if not emptied:
        raise ValueError("no candidate files were emptied; the mapping is wrong")

    pattern = "*.result.json" if layout == PARSEBENCH_RESULT_LAYOUT else "*.md"
    return {
        "candidate_root": str(candidate_root),
        "output_root": str(output_root),
        "cases_requested_to_empty": len(emptied_case_ids),
        "cases_emptied": len(emptied),
        "cases_without_a_candidate_file": len(absent),
        "candidate_files_total": sum(1 for _ in output_root.rglob(pattern)),
        "emptied_case_ids": emptied,
        "cases_without_a_candidate_file_ids": absent,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--case-index", required=True, type=Path)
    parser.add_argument(
        "--rescued-case-ids",
        required=True,
        type=Path,
        help="JSON array of case ids the recovery lane delivered",
    )
    parser.add_argument("--candidate-suffix", default="_pg1_repeat1")
    parser.add_argument(
        "--layout",
        default=CATEGORY_LAYOUT,
        choices=(CATEGORY_LAYOUT, FLAT_LAYOUT, PARSEBENCH_RESULT_LAYOUT),
        help="how the evaluator lays out candidate files",
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case_index = json.loads(args.case_index.read_text(encoding="utf-8-sig"))
    rescued = set(json.loads(args.rescued_case_ids.read_text(encoding="utf-8-sig")))
    result = build_counterfactual(
        candidate_root=args.candidate_root,
        output_root=args.output_root,
        case_index=case_index,
        emptied_case_ids=rescued,
        candidate_suffix=args.candidate_suffix,
        layout=args.layout,
    )
    receipt = {
        "schema": "folynta.recovery-counterfactual-candidate.v1",
        "question": (
            "What would the official score have been if the recovery lane had not run?"
        ),
        "method": (
            "Copy the evaluated candidate set and empty every document the recovery "
            "lane delivered, holding model, evaluator revision, corpus and settings "
            "constant so the score difference is attributable to recovery alone."
        ),
        "score_inflation_allowed": False,
        "candidate_layout": args.layout,
        **result,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {k: v for k, v in receipt.items() if not k.endswith("_ids")},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
