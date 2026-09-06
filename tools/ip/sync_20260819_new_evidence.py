#!/usr/bin/env python3
"""Synchronize the 2026-08-19 H1-E2, H1-F and A12 readiness evidence.

This is intentionally claim-id based: it preserves unrelated YAML rows and all
existing receipt paths rather than rewriting the registry wholesale.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs" / "ip" / "claim-evidence-matrix.yaml"


def block_bounds(text: str, claim_id: str) -> tuple[int, int]:
    marker = f"  - id: {claim_id}\n"
    start = text.index(marker)
    next_start = text.find("\n  - id: ", start + len(marker))
    end = len(text) if next_start < 0 else next_start + 1
    return start, end


def dump_claim(claim: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(
        [claim],
        sort_keys=False,
        allow_unicode=True,
        width=100,
        default_flow_style=False,
    ).rstrip()
    return "\n".join("  " + line for line in dumped.splitlines()) + "\n"


def replace_claim(text: str, claim: dict[str, Any]) -> str:
    start, end = block_bounds(text, str(claim["id"]))
    return text[:start] + dump_claim(claim) + text[end:]


def main() -> int:
    text = REGISTRY.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    claims = {str(claim["id"]): claim for claim in document["claims"]}

    a12 = claims["A12-CAUSE-CONDITIONED-RECOVERY"]
    a12["status"] = "BLOCKED_INTERNAL"
    audit_path = (
        "research/experiments/H1-A12-01/receipts/"
        "runtime-readiness-audit-2026-08-19.json"
    )
    a12["evidence"] = [item for item in a12["evidence"] if item["path"] != audit_path]
    a12["evidence"].append(
        {
            "path": audit_path,
            "asserts": [
                {"pointer": "/overall_state", "equals": "BLOCKED_RUNTIME_AND_RECIPE"},
                {"pointer": "/gates/licence_ready", "equals": True},
                {"pointer": "/gates/source_only_ready", "equals": True},
                {"pointer": "/gates/formal_immutable_runtime_ready", "equals": False},
                {"pointer": "/gates/exact_same_family_recipe_ready", "equals": False},
                {"pointer": "/gpu_spend_authorized", "equals": False},
                {"pointer": "/incremental_gpu_spend_usd", "equals": 0.0},
            ],
        }
    )
    a12["limitations"] = [
        (
            "Licence is NOT the blocker. benchmark/v6/candidate-registry.yaml records "
            "paddleocr-vl-1.6 and deepseek-ocr-2 as Apache-2.0, status approved, "
            "commercial_use allowed. Both remain promotion_eligible false for production."
        ),
        (
            "The source-only 48-case bundle is READY and hash-verified. The two internal "
            "research blockers are (1) no qualified immutable runtime image is READY and "
            "(2) no exact machine-readable same-family ablation recipe was frozen."
        ),
        (
            "The preregistered stop-before-spend rule therefore forbids provider "
            "provisioning. Provider preflight was deliberately not run and incremental GPU "
            "spend remains $0. This is infrastructure/recipe state, not a legal or source-data "
            "blocker."
        ),
        (
            "promotion_eligible false continues to govern production traffic and is "
            "unaffected by any research-readiness finding."
        ),
    ]

    identity = claims["B-IDENTITY-BLOCKED-EQUIVALENCE"]
    identity["title"] = (
        "Candidate-indexed block matching eliminates measured fail-open merges, but its "
        "residual tied split assignments are path-dependent across revisions"
    )
    identity["status"] = "PARTIALLY_SUPPORTED"
    h1e2_path = (
        "research/experiments/H1-E2-TIE-PATH-DEPENDENCE-01/receipts/"
        "path-dependence-amend1-2026-08-19.json"
    )
    identity["evidence"] = [item for item in identity["evidence"] if item["path"] != h1e2_path]
    identity["evidence"].append(
        {
            "path": h1e2_path,
            "asserts": [
                {"pointer": "/current_row_divergences", "equals": 8},
                {"pointer": "/future_row_divergences", "equals": 8},
                {"pointer": "/negative_control_divergences", "equals": 0},
                {"pointer": "/positive_falsification/separates", "equals": True},
                {"pointer": "/controls_valid", "equals": True},
                {
                    "pointer": "/promotion_disposition",
                    "equals": "PROMOTION_VETO_PATH_DEPENDENT",
                },
                {"pointer": "/promotion_safe_under_this_protocol", "equals": False},
            ],
        }
    )
    identity["permitted_wording"] = (
        "Across 33,600 compared identity decisions on seven controlled topologies, "
        "candidate-indexed block matching never converted an abstention or a new identity "
        "into a continuation, and never merged onto a different prior unit. However, the "
        "eight residual tied split-assignment divergences all produced a different "
        "next-revision decision in the frozen H1-E2 path-dependence probe; valid negative "
        "and positive controls separated as required. The current BLOCKED implementation "
        "is therefore retained as a performance shadow and vetoed from default "
        "Protected-Core promotion."
    )
    identity["forbidden_wording"] = [
        "block matching is provably equivalent to the full matcher",
        "the candidate index is lossless",
        "the residual permutations are harmless because their outcome multiset matches",
        "BLOCKED is equivalent to LEGACY",
        "BLOCKED is safe to promote as the default identity policy",
    ]
    identity["limitations"] = [
        (
            "The per-row bound is analytic; whole-assignment equivalence is measured, not "
            "proved. Dropping an edge can free a column another row then takes; H1-E found "
            "eight such residual assignment differences."
        ),
        (
            "MatchingPolicy.BLOCKED remains a SHADOW policy and LEGACY remains the default. "
            "H1-E2 supplied the missing follow-on protocol and found 8/8 next-revision path "
            "divergences, so the current implementation is explicitly promotion-vetoed."
        ),
        (
            "Exactly-equal candidate tie-breaking is a pre-existing ambiguity class in the "
            "global assignment too, but H1-E2 shows that changing which source row receives "
            "the abstention/new decision is not semantically ignorable across revisions."
        ),
        (
            "Controlled generated corpus. H1-F adds real-corpus selective-recompilation "
            "equivalence evidence, but no real-corpus BLOCKED-vs-LEGACY identity-matching "
            "arm exists."
        ),
    ]

    governance = claims["D-GOVERNANCE-LINEAGE-CONTROLLED"]
    governance["scope"] = (
        "22 constructed mechanism cells x 500 deterministic repetitions = 11,000 executions"
    )
    governance["permitted_wording"] = (
        "Across 22 constructed mechanism cells, each repeated 500 times (11,000 "
        "executions), the resolver selected the correct authority, abstained where an "
        "override lacked evidence, marked exactly-equal conflicts CONFLICTED, never "
        "revealed a permission-hidden claim id, reproduced as-of answers on both temporal "
        "axes, and reconstructed consumption lineage to depth 64 at precision and recall 1.0."
    )

    real_claim = {
        "id": "B-EQUIV-REAL-CORPUS-RETROSPECTIVE",
        "title": (
            "The live selective-recompilation implementation matches its full-rebuild oracle "
            "on every previously acquired natural Wikipedia revision pair"
        ),
        "status": "EMPIRICALLY_VALIDATED_REAL",
        "scope": (
            "retrospective all-stored regression over 28 English-Wikipedia revision pairs / "
            "56 sealed source files; 11 pairs contain semantic changed logical ids under the "
            "evaluation adapter"
        ),
        "evidence": [
            {
                "path": (
                    "research/experiments/H1-F-REAL-CORPUS-EQUIV-01/receipts/"
                    "all-stored-real-corpus-2026-08-19.json"
                ),
                "asserts": [
                    {"pointer": "/pair_count", "equals": 28},
                    {"pointer": "/changed_pair_count", "equals": 11},
                    {"pointer": "/equivalent_pair_count", "equals": 28},
                    {"pointer": "/all_pairs_equivalent", "equals": True},
                    {"pointer": "/stale_left_behind_total", "equals": 0},
                    {
                        "pointer": "/success_for_retrospective_regression_statement",
                        "equals": True,
                    },
                    {"pointer": "/fresh_holdout", "equals": False},
                    {"pointer": "/confirmatory", "equals": False},
                ],
            }
        ],
        "permitted_wording": (
            "On all 28 previously acquired natural English-Wikipedia revision pairs stored "
            "across the Family B development, confirmatory-corpus and extension corpora, the "
            "live pinned implementation's selective result matched its full-rebuild oracle "
            "with no stale artifact left behind. Eleven of those pairs contained semantic "
            "changed logical ids under the evaluation adapter."
        ),
        "forbidden_wording": [
            "Family B is generally equivalent to full rebuild",
            "external validity is proven",
            "this was a fresh holdout or confirmatory endpoint",
            "28 independent domains were validated",
        ],
        "limitations": [
            (
                "Retrospective evidence: all source pairs pre-date this protocol and were used "
                "by earlier Family B work. H1-F removes outcome selection by including every "
                "stored pair, but it is not a fresh holdout."
            ),
            (
                "English Wikipedia is one source family. Cross-source generalization to SEC, "
                "DART, contracts, scans, and arbitrary production dependency graphs remains open."
            ),
            (
                "Seventeen of the 28 raw revision pairs normalize to no semantic changed "
                "logical ids under the evaluation adapter; they exercise the no-stale path "
                "but are not 17 additional positive change events."
            ),
            (
                "The artifact graph is the sealed evaluation adapter, not an unconstrained "
                "production graph. The H1-F seal pins current identity, diff, dependency and "
                "recompilation code plus all 56 source files."
            ),
        ],
        "paper_section": "C. Living Knowledge — real-corpus regression",
        "patent": "Family B — corroborating real-corpus support, not a generality limitation",
    }

    text = text.replace(
        "#   BLOCKED_EXTERNAL               needs a human/legal/account/credential input\n",
        "#   BLOCKED_EXTERNAL               needs a human/legal/account/credential input\n"
        "#   BLOCKED_INTERNAL               blocked by an unresolved internal "
        "runtime/implementation gate\n",
    )
    for claim in (a12, identity, governance):
        text = replace_claim(text, claim)

    if "  - id: B-EQUIV-REAL-CORPUS-RETROSPECTIVE\n" in text:
        start, end = block_bounds(text, "B-EQUIV-REAL-CORPUS-RETROSPECTIVE")
        text = text[:start] + text[end:]
    insertion, _ = block_bounds(text, "B-STRUCTURE-ONLY-STALE-DEFECT")
    text = text[:insertion] + dump_claim(real_claim) + "\n" + text[insertion:]

    yaml.safe_load(text)  # syntax guard before writing
    REGISTRY.write_text(text, encoding="utf-8")
    print("synchronized A12, H1-E2, H1-F and D evidence rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
