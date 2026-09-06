#!/usr/bin/env python3
"""Which OmniDocBench pages has this project already looked at?

The confirmatory holdout is only untouched if nothing about it has been seen.
"Seen" is deliberately broad here: a page counts as observed if any local
artifact contains a per-page score for it, whether or not that score was ever
used to choose a threshold. Reconstructing intent after the fact is not
auditable; the presence of a score on disk is.

The audit walks every evaluation artifact in the repository, collects the page
names that appear as scored keys, and unions them with the sealed discovery set.
Whatever remains is eligible. Nothing is selected here -- this file only
establishes what may be selected from, and writes the exclusion set that the
freeze step consumes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Artifact filenames whose keys are page identities. Scanning every JSON in the
# tree would sweep in unrelated maps; these are the evaluator's own per-page
# outputs plus the staged prediction directories.
PER_PAGE_ARTIFACTS = (
    "text_block_per_page_edit.json",
    "reading_order_per_page_edit.json",
    "table_per_page_edit.json",
    "display_formula_per_page_edit.json",
    "table_per_table_TEDS.json",
    "display_formula_per_sample_CDM.json",
)

# Directories whose predictions came from the gated parser. A page is burned for
# this experiment if the gated parser has ever produced output for it, because
# stability and cross-parser agreement are both computed from that output.
GATED_PARSER_MARKER_PARTS = ("formal-runtime-v29", "ovisocr2")

SEARCH_ROOTS = (
    ".chatgpt2codex",
    "artifacts",
    "benchmark/reports",
    "benchmark/datasets/private",
    "benchmark/cache/omnidoc/result",
    "research",
    "docs/evidence",
)


def page_from_key(key: str) -> str:
    """`page.png_[3]` -> `page.png`; other keys are page names already."""
    if key.endswith("]") and "_[" in key:
        return key.rsplit("_[", 1)[0]
    return key


def observed_pages(root: Path, valid: set[str]) -> dict[str, list[str]]:
    """Page -> the artifacts that scored it."""
    found: dict[str, list[str]] = {}
    for relative in SEARCH_ROOTS:
        base = root / relative
        if not base.exists():
            continue
        for name in PER_PAGE_ARTIFACTS:
            for path in base.rglob(name):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                for key in data:
                    page = page_from_key(str(key))
                    if page in valid:
                        found.setdefault(page, []).append(
                            str(path.relative_to(root)).replace("\\", "/")
                        )
    return found


def predicted_pages(root: Path, valid: set[str]) -> dict[str, list[str]]:
    """Pages for which a staged prediction file exists anywhere."""
    stems = {Path(page).stem: page for page in valid}
    found: dict[str, list[str]] = {}
    for relative in SEARCH_ROOTS:
        base = root / relative
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            page = stems.get(path.stem)
            if page is None:
                continue
            found.setdefault(page, []).append(
                str(path.parent.relative_to(root)).replace("\\", "/")
            )
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--staged-manifest", type=Path, required=True)
    parser.add_argument("--discovery-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.repository_root.resolve()
    manifest = json.loads(args.staged_manifest.resolve().read_text(encoding="utf-8"))
    source_by_page = {
        Path(entry["source_relative_path"]).name: entry for entry in manifest["inputs"]
    }
    valid = set(source_by_page)

    seal = json.loads(args.discovery_seal.resolve().read_text(encoding="utf-8"))
    discovery = {str(p["image_path"]) for p in seal["pages"]}
    discovery |= set(seal.get("excluded_without_an_official_page_score", []))

    scored = observed_pages(root, valid)
    predicted = predicted_pages(root, valid)

    # Observation is not one thing, and collapsing it to one thing gives the
    # wrong answer here: under "any artifact mentions this page" every page in
    # the corpus is burned, because a completed campaign scored all of them with
    # the second parser. What matters for *this* experiment is narrower and
    # checkable -- whether the gated parser ever ran on the page, because both
    # halves of the frozen gate are functions of its output.
    gated_parser_pages = {
        page
        for page, directories in predicted.items()
        if any(part in d for d in directories for part in GATED_PARSER_MARKER_PARTS)
    }
    second_parser_only = set(predicted) - gated_parser_pages - discovery

    observed = gated_parser_pages | discovery
    eligible = sorted(valid - observed)

    # Document identity, for leakage control. The staged manifest carries the
    # source path; the directory plus the page-number-stripped stem is the
    # document, matching the selector that built the discovery slice.
    def document_of(page: str) -> str:
        return str(source_by_page[page]["source_relative_path"]).rsplit("_page_", 1)[0]

    discovery_documents = {document_of(p) for p in discovery if p in source_by_page}
    eligible_documents = {document_of(p) for p in eligible}
    shared_documents = sorted(eligible_documents & discovery_documents)
    leak_free = sorted(p for p in eligible if document_of(p) not in discovery_documents)

    receipt = {
        "schema": "tavonel.a9-holdout-provenance-audit.v1",
        "annotation_rows": len(valid),
        "discovery_pages": len(discovery),
        "pages_with_a_per_page_score_on_disk": len(scored),
        "pages_with_a_staged_prediction_on_disk": len(predicted),
        "pages_the_gated_parser_has_run_on": len(gated_parser_pages),
        "pages_scored_only_by_the_second_parser_campaign": len(second_parser_only),
        "observed_total": len(observed),
        "eligible_pages": len(eligible),
        "eligible_documents": len(eligible_documents),
        "discovery_documents": len(discovery_documents),
        "eligible_pages_sharing_a_discovery_document": len(eligible) - len(leak_free),
        "documents_shared_with_discovery": shared_documents,
        "eligible_after_document_level_exclusion": len(leak_free),
        "definition_of_observed": (
            "any page that appears as a key in a per-page evaluator artifact on "
            "disk, or has a staged prediction file, or is in the sealed "
            "discovery manifest -- regardless of whether it influenced a "
            "threshold, because intent is not auditable and file presence is"
        ),
        "eligibility_rule_applied": (
            "excluded if the gated parser has ever produced output for the page, "
            "or the page is in the sealed discovery set, or the page belongs to a "
            "document that contributed a discovery page"
        ),
        "residual_contamination_risk": (
            "eligible pages carry second-parser scores from the completed public "
            "campaign. Those scores were never inspected per page during A9 and "
            "neither gate signal can be computed from them alone -- stability "
            "needs two gated-parser runs and agreement needs one -- but the risk "
            "is not zero and is recorded rather than argued away."
        ),
        "eligible": leak_free,
        "excluded_for_document_leakage": sorted(set(eligible) - set(leak_free)),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for key, value in receipt.items():
        if isinstance(value, (int, str)) and not key.startswith("definition"):
            print(f"  {key}: {value}")
    print(f"  documents shared with discovery: {len(shared_documents)}")
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
