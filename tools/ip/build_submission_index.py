#!/usr/bin/env python3
"""Generate the submission package index with current hashes.

The index is a hand-over inventory: every deliverable, its role, and its hash at
index time. It is regenerated rather than edited, because a hand-maintained hash
table drifts silently and a drifted hash table is worse than none.

A missing file is a finding, not a skipped row. If a deliverable named here is
absent, either the package is incomplete or the index is stale, and both need a
human to look.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

GROUPS: dict[str, list[tuple[str, str]]] = {
    "PATENT": [
        ("filing README", "docs/ip/FILING_README_2026-08-20.md"),
        ("filing review draft (built PDF)", "docs/ip/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf"),
        ("drawing sheets, combined (built PDF)", "docs/ip/drawings/TAVONEL_PATENT_DRAWINGS.pdf"),
        ("claim set", "docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md"),
        ("abstract and drawings", "docs/ip/PATENT_ABSTRACT_AND_DRAWINGS_2026-08-20.md"),
        ("specification", "docs/ip/PATENT_SPECIFICATION_v1_2026-08-19.md"),
        ("claim-evidence matrix (generated)", "docs/ip/CLAIM_EVIDENCE_MATRIX.md"),
        ("claim-evidence registry (source)", "docs/ip/claim-evidence-matrix.yaml"),
        ("prior-art and narrowing memo", "docs/ip/PRIOR_ART_AND_NARROWING_MEMO_2026-08-19.md"),
        ("examiner red team", "docs/ip/EXAMINER_RED_TEAM_2026-08-19.md"),
        (
            "examiner red team, statutory (101/102/103/112)",
            "docs/ip/EXAMINER_RED_TEAM_STATUTORY_2026-08-20.md",
        ),
        ("examiner red team, W6 disposition", "docs/ip/W6_V8_EXAMINER_RED_TEAM_2026-08-20.md"),
        ("claim amendment register", "docs/ip/CLAIM_AMENDMENTS.yaml"),
        ("element-level support bindings", "docs/ip/ELEMENT_SUPPORT_BINDINGS.yaml"),
        (
            "element support matrix (receipt)",
            "docs/ip/receipts/element-support-matrix-2026-08-19.json",
        ),
        ("assertion registry", "docs/ip/ASSERTION_REGISTRY.yaml"),
        ("withdrawn-term registry", "docs/ip/WITHDRAWN_TERMS.yaml"),
        ("counsel flags (generated)", "docs/ip/COUNSEL_FLAGS_2026-08-20.md"),
        (
            "unsupported-breadth ledger (generated)",
            "docs/ip/UNSUPPORTED_BREADTH_LEDGER_2026-08-20.md",
        ),
        ("technology intake register (FTO)", "docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml"),
        ("disclosure registry", "docs/ip/V4_DISCLOSURE_REGISTRY.yaml"),
    ],
    "PAPER": [
        ("manuscript", "docs/paper/MANUSCRIPT_v1_2026-08-19.md"),
        ("manuscript, generic build (built PDF)", "docs/paper/TAVONEL_MANUSCRIPT_GENERIC.pdf"),
        ("figures", "docs/paper/FIGURES_2026-08-19.md"),
        ("rendered figure registry", "docs/paper/figures/FIGURE_REGISTRY.json"),
        ("tables", "docs/paper/TABLES_2026-08-19.md"),
        ("reviewer red team", "docs/audit/REVIEWER_RED_TEAM_2026-08-19.md"),
        ("reviewer red team, W6 disposition", "docs/audit/W6_V8_REVIEWER_RED_TEAM_2026-08-20.md"),
    ],
    "AUDIT": [
        ("hostile review", "docs/audit/HOSTILE_REVIEW_2026-08-19.md"),
        ("ablation coverage", "docs/audit/ABLATION_COVERAGE_2026-08-19.md"),
        ("failed and superseded ledger", "docs/evidence/FAILED_AND_SUPERSEDED_LEDGER.md"),
        (
            "receipt-overwrite incident",
            "research/experiments/H1-A12-01/INCIDENT_RECEIPT_OVERWRITE_2026-08-19.md",
        ),
        ("submission readiness checklist", "docs/SUBMISSION_READINESS_CHECKLIST_2026-08-19.md"),
        ("convergence protocol (frozen)", "docs/audit/CONVERGENCE_PROTOCOL_2026-08-19.md"),
        ("convergence round 2 (not clean)", "docs/audit/convergence-rounds/round-02.json"),
        (
            "W6 final state",
            "research/experiments/H1-W6-SAME-INTELLIGENCE-01/W6_V8_FINAL_STATE_2026-08-20.md",
        ),
        ("standing bounds registry", "docs/audit/STANDING_BOUNDS.yaml"),
    ],
    "REPRO": [
        ("experiment manifest", "docs/repro/EXPERIMENT_MANIFEST.json"),
        ("execution index", "docs/repro/EXECUTION_INDEX_2026-08-19.json"),
        ("historical drift register", "docs/repro/HISTORICAL_DRIFT_REGISTER.yaml"),
        ("exclusion rules", "docs/repro/EXCLUSION_RULES_2026-08-19.md"),
        ("session execution log", "docs/repro/SESSION_EXECUTION_LOG_2026-08-19.md"),
        ("test scope and interpreter status", "docs/repro/TEST_SCOPE_STATUS.json"),
        ("full-suite failure triage", "docs/repro/FULL_SUITE_TRIAGE.json"),
    ],
    "HUMAN_REVIEW": [
        ("pass A packet (human read)", "docs/submission/HUMAN_PASS_A_PACKET.md"),
        ("inventor / founder review checklist", "docs/ip/INVENTOR_REVIEW_CHECKLIST_2026-08-20.md"),
        ("final external actions", "docs/submission/FINAL_EXTERNAL_ACTIONS.md"),
    ],
    "STATUS": [("program status", "research/PROGRAM_STATUS_2026-08-19.md")],
}

NOT_IN_PACKAGE = [
    (
        "W6 same-intelligence comparative result",
        "the confirmatory run executed on 2026-08-20 and stopped at its pre-arm baseline "
        "validity gate. No arm ran; the comparative endpoint is NOT_MEASURED. The cohort is "
        "spent and is development data from this point forward",
    ),
    (
        "A12 cause-conditioned recovery",
        "blocked external — no container runtime on this host, so no image digest",
    ),
    (
        "cross-source equivalence",
        "no second source family with explicit amendment relationships exists offline",
    ),
    (
        "rendered figure assets",
        "figures are specified as mermaid and tables, not exported to images",
    ),
    (
        "a convergence claim",
        "pass A is a human read and has not been performed. Rounds record "
        "`agent_convergence_complete` for passes B-K separately, and that field is not "
        "convergence and may not be reported as one",
    ),
    (
        "four claim recitals supported only by implementation",
        "A4, A5, B7 and B9 are RESERVED continuation material, held out of the filing core "
        "by a recorded decision rather than measured",
    ),
]

HEADER = """# Submission package index — 2026-08-19

Every deliverable, its role, and its hash at index time. **`PATENT_FILING = NOT
FILED` and no paper is submitted.** This is an inventory of what is ready to hand
over, not a record of a handover.

Regenerate with `python tools/ip/build_submission_index.py`. Hashes change
whenever a document is edited; a stale hash here means the index was not rebuilt,
not that a document was tampered with.
"""


def main() -> int:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    lines = [HEADER]

    for group, items in GROUPS.items():
        present = []
        for role, rel in items:
            path = ROOT / rel
            if not path.exists():
                missing.append(rel)
                continue
            data = path.read_bytes()
            row = {
                "group": group,
                "role": role,
                "path": rel,
                "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
            rows.append(row)
            present.append(row)
        if not present:
            continue
        lines += [f"## {group}", "", "| role | path | sha256 | bytes |", "|---|---|---|---|"]
        lines += [
            f"| {r['role']} | `{r['path']}` | `{r['sha256'][7:19]}…` | {r['bytes']:,} |"
            for r in present
        ]
        lines.append("")

    lines += ["## Not in this package", ""]
    lines += [f"- **{name}** — {why}." for name, why in NOT_IN_PACKAGE]
    lines += ["", "Each is listed so its absence is a stated state rather than an omission.", ""]

    if missing:
        lines += [
            "## MISSING deliverables",
            "",
            "These are named in the index and were not found on disk:",
            "",
        ]
        lines += [f"- `{m}`" for m in missing]
        lines.append("")

    (ROOT / "docs" / "SUBMISSION_PACKAGE_INDEX_2026-08-19.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    receipt = {
        "schema": "tavonel.submission-package-index.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "files": rows,
        "file_count": len(rows),
        "missing": missing,
        "missing_count": len(missing),
        "patent_filing_state": "NOT_FILED",
        "paper_submission_state": "NOT_SUBMITTED",
        "excluded_workstreams": [name for name, _ in NOT_IN_PACKAGE],
        "clean": not missing,
    }
    receipt["receipt_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
    )
    (ROOT / "docs" / "ip" / "receipts" / "submission-package-index-2026-08-19.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"indexed {len(rows)} deliverables across {len(GROUPS)} groups")
    for m in missing:
        print(f"  MISSING: {m}")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
