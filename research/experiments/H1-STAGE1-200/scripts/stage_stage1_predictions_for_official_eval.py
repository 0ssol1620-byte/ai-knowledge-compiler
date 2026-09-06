#!/usr/bin/env python3
"""Restore OmniDocBench page identity to Stage-1 predictions before scoring.

Stage-1 hands the GPU Pod inputs named by `case_id` -- `omnidocbench-<hex>.png`
-- and never the OmniDocBench filename. That is deliberate: the Pod must not be
able to learn which benchmark page it is looking at, and every Stage-1 receipt
asserts `ground_truth_mounted: False`. The map from `case_id` back to
`source_relative_path` lives only in the local inference input manifest.

The official evaluator matches predictions to ground truth *by page name*. Given
the Pod's own output directory it therefore finds nothing: measured 2026-08-18,
184 of 200 pages came back as `!!!WARNING: No prediction for <page>, evaluate as
empty page`, and an empty page scores as a total miss. The run produced a number,
and the number was meaningless -- the worst kind of failure, because nothing in
it looks broken.

So this stages a copy named the way the evaluator expects. It renames; it never
edits a prediction's bytes, and it refuses rather than guesses:

  * a prediction whose `case_id` is not in the manifest is an error
  * a manifest entry with no prediction is an error
  * two cases resolving to one page name is an error

The receipt records the sha256 of every staged file so the scored artifact can
be tied back to the archive the Pod produced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def case_to_page_name(manifest: Path) -> dict[str, str]:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    pages: dict[str, str] = {}
    for item in payload["inputs"]:
        case_id = str(item["case_id"])
        page = Path(str(item["source_relative_path"])).stem
        if case_id in mapping:
            raise ValueError(f"duplicate case_id in manifest: {case_id}")
        if page in pages:
            raise ValueError(
                f"two cases resolve to page {page}: {pages[page]} and {case_id}"
            )
        mapping[case_id] = page
        pages[page] = case_id
    expected = int(payload["input_count"])
    if len(mapping) != expected:
        raise ValueError(f"manifest declares {expected} inputs but carries {len(mapping)}")
    return mapping


def stage_repeat(source: Path, destination: Path, mapping: dict[str, str]) -> list[dict[str, str]]:
    predictions = sorted(source.glob("*.md"))
    if not predictions:
        raise RuntimeError(f"{source} holds no predictions")
    destination.mkdir(parents=True, exist_ok=False)
    staged: list[dict[str, str]] = []
    seen: set[str] = set()
    for prediction in predictions:
        case_id = prediction.stem
        page = mapping.get(case_id)
        if page is None:
            raise RuntimeError(
                f"{prediction.name} has no manifest entry; the predictions and the "
                "manifest describe different runs"
            )
        target = destination / f"{page}.md"
        shutil.copy2(prediction, target)
        seen.add(case_id)
        staged.append(
            {
                "case_id": case_id,
                "page_name": page,
                "sha256": sha256_file(target),
            }
        )
    missing = sorted(set(mapping) - seen)
    if missing:
        raise RuntimeError(
            f"{len(missing)} manifest cases have no prediction, first: {missing[0]}. "
            "Scoring these as empty pages would understate the result silently."
        )
    return staged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()

    mapping = case_to_page_name(args.source_manifest.resolve())
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    records = []
    for index in range(1, args.repeats + 1):
        name = f"markdown-repeat-{index}"
        staged = stage_repeat(
            args.predictions_root.resolve() / name, output_root / name, mapping
        )
        print(f"[stage] {name}: {len(staged)} predictions renamed to page identity", flush=True)
        records.append({"repeat_index": index, "staged_count": len(staged), "files": staged})

    receipt = {
        "schema": "tavonel.stage1-official-eval-staging.v1",
        "note": (
            "Stage-1 anonymises inputs to case_id so the GPU Pod cannot identify the "
            "benchmark page. The official evaluator matches on page name. This staging "
            "renames only -- prediction bytes are unchanged."
        ),
        "source_manifest_sha256": sha256_file(args.source_manifest.resolve()),
        "predictions_root": str(args.predictions_root.resolve()),
        "repeats": records,
    }
    (output_root / "staging-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[stage] receipt written to {output_root / 'staging-receipt.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
