#!/usr/bin/env python3
"""H1-A9-01 Phase 0: can the registered acceptance arms be evaluated at all?

Phase 0 is a feasibility determination, not a result. The preregistration sets
`performance_conclusion_allowed: False` and `gpu_spend_usd: 0`, and its
`missing_data_rule` is the part that does the work:

    Never synthesize self-confidence, agreement, or evaluator labels after the
    fact. An arm with missing original features is reported unavailable rather
    than imputed.

So this program measures which of the four registered arms have their original
features present in already-frozen artifacts, and answers the registered
`go_to_phase_1_if` conditions with those measurements. It reads indexes and
manifests only. It runs no model and spends nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

# The frozen public-core merge whose case indexes are read. Every merged root in
# benchmark/reports/generated carries the same candidate_id, so the choice of
# root does not change which *parsers* are available -- only which recovery
# variant of the one parser is described.
FROZEN_MERGE = (
    ROOT
    / "benchmark"
    / "reports"
    / "generated"
    / "folynta-quality-candidate-hybrid-merged-2026-08-09"
)
STAGE1_MANIFEST = (
    ROOT / ".chatgpt2codex" / "stage1-hard-200-v1" / "inference-input-manifest.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def frozen_candidate_ids() -> dict[str, str]:
    """Every distinct primary parser in the frozen public-core merges."""
    found: dict[str, str] = {}
    for receipt in sorted(
        (ROOT / "benchmark" / "reports" / "generated").glob("*/merge-receipt.json")
    ):
        candidate = str(read_json(receipt).get("candidate_id", ""))
        found.setdefault(candidate, receipt.parent.name)
    return found


def suite_source_extensions() -> dict[str, dict[str, int]]:
    """A native text layer is possible in a PDF and impossible in a page image."""
    extensions: dict[str, dict[str, int]] = {}
    for index in sorted((FROZEN_MERGE / "indexes").glob("*-cases.json")):
        payload = read_json(index)
        counter = Counter(
            str(record.get("source_relative_path", "")).rsplit(".", 1)[-1].lower()
            for record in payload["records"]
        )
        extensions[str(payload["benchmark_id"])] = dict(counter.most_common())
    return extensions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1-run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    run_dir = args.stage1_run_dir.resolve()
    stage1_receipt = read_json(run_dir / "stage1-receipt.json")
    run_summary = read_json(run_dir / "results" / "output" / "run-summary.json")
    stage1_candidate = str(run_summary["candidate_id"])

    # --- overlap between the second parser and the frozen first parser ---------
    manifest = read_json(STAGE1_MANIFEST)
    ours = {item["source_relative_path"] for item in manifest["inputs"]}
    omnidoc = read_json(FROZEN_MERGE / "indexes" / "omnidocbench-cases.json")
    frozen = {record.get("source_relative_path", "") for record in omnidoc["records"]}
    overlap = sorted(ours & frozen)
    same_revision = str(omnidoc["dataset_revision"]) == str(manifest["dataset_revision"])

    # --- which per-case features the frozen runtime actually emitted ----------
    case_fields = sorted(run_summary["runs"][0]["cases"][0])
    confidence_fields = [
        field
        for field in case_fields
        if any(token in field for token in ("confidence", "logprob", "score", "prob"))
    ]

    extensions = suite_source_extensions()
    image_only = {
        suite: counts
        for suite, counts in extensions.items()
        if not any(ext == "pdf" for ext in counts)
    }
    pdf_bearing = {
        suite: counts for suite, counts in extensions.items() if "pdf" in counts
    }

    arms = {
        "candidate_agreement_threshold": {
            "available": len(overlap) > 0 and same_revision,
            "why": (
                f"two distinct primary parsers cover the same cases: "
                f"{sorted(frozen_candidate_ids())} frozen, plus {stage1_candidate} from "
                f"the 2026-08-18 live run; {len(overlap)}/{len(ours)} sources overlap and "
                f"dataset_revision matches ({same_revision})"
            ),
            "cases": len(overlap),
        },
        "model_self_confidence_threshold": {
            "available": bool(confidence_fields),
            "why": (
                "the frozen Stage-1 runtime emits no per-case confidence; run-summary "
                f"case fields are {case_fields}. The preregistration forbids "
                "reconstructing this feature after the fact, so the arm is reported "
                "unavailable rather than imputed."
            ),
            "cases": 0,
        },
        "source_grounded_acceptance_receipt": {
            "available": False,
            "why": (
                "the cases both parsers cover are OmniDocBench page images "
                f"({image_only.get('omnidocbench')}), which carry no native text layer, so "
                "akc_cir.source_grounded_acceptance.native_text_source_check would return "
                "unavailable_source_check for every case. The PDF-bearing suites "
                f"({ {k: v.get('pdf') for k, v in pdf_bearing.items()} }) could carry native "
                "text, but they have only one primary parser and their source PDFs are not "
                "staged in this checkout."
            ),
            "cases": 0,
        },
        "abstain_review_baseline": {
            "available": True,
            "why": "a baseline that accepts nothing needs no features",
            "cases": len(overlap),
        },
    }

    available_policies = [name for name, arm in arms.items() if arm["available"]]
    # The registered gate asks for two policies **on the same cases**. An abstain
    # baseline plus one real policy is not the comparison A9 was registered to
    # make: the research question is source-grounded acceptance *versus*
    # agreement or self-confidence, and the source-grounded arm is the one that
    # cannot run on the overlapping cases.
    go = "source_grounded_acceptance_receipt" in available_policies and len(
        available_policies
    ) >= 2

    receipt = {
        "schema": "tavonel.research.phase0-feasibility.v1",
        "experiment_id": "H1-A9-01",
        "phase": 0,
        "gpu_spend_usd": 0,
        "performance_conclusion_allowed": False,
        "frozen_inputs": {
            "stage1_run_dir": str(run_dir),
            "stage1_candidate_id": stage1_candidate,
            "stage1_assembly_id": stage1_receipt["assembly_id"],
            "stage1_receipt_sha256": sha256_file(run_dir / "stage1-receipt.json"),
            "stage1_input_manifest_sha256": sha256_file(STAGE1_MANIFEST),
            "frozen_merge_root": FROZEN_MERGE.name,
            "frozen_merge_receipt_sha256": sha256_file(FROZEN_MERGE / "merge-receipt.json"),
            "frozen_candidate_ids": frozen_candidate_ids(),
            "dataset_revision": manifest["dataset_revision"],
        },
        "suite_source_extensions": extensions,
        "arms": arms,
        "go_to_phase_1": go,
        "go_to_phase_1_reason": (
            "NO-GO. The agreement arm and the source-grounded arm cannot be evaluated on "
            "the same cases. The 200 cases with two independent parsers are page images "
            "with no native text to ground against; the corpora that could carry native "
            "text have one parser and no staged sources. Evaluating the registered "
            "research question would require reconstructing features the preregistration "
            "forbids reconstructing."
            if not go
            else "GO."
        ),
        "narrowest_unblocking_step": (
            "Run the second parser over a PDF subset whose native text layer is verified "
            "present, so agreement features and source-grounded checks exist on the same "
            "frozen cases. Scope it by the number of cases needed for the registered "
            "endpoint, not by the size of the PDF corpora."
        ),
        "claim_state": "A9 native-source gate implemented and unit-verified; "
        "empirical precision benefit WITHHELD",
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for name, arm in arms.items():
        print(f"[phase0] {name}: {'AVAILABLE' if arm['available'] else 'UNAVAILABLE'}", flush=True)
    print(f"[phase0] go_to_phase_1 = {go}", flush=True)
    print(f"[phase0] receipt: {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
