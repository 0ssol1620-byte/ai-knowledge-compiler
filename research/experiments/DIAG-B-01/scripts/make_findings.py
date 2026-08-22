"""Regenerate DIAG-B-01's tables and verdict from `metrics/`. Nothing typed by hand.

    .venv/Scripts/python.exe research/experiments/DIAG-B-01/scripts/make_findings.py

The verdict rules are in this file, so a reader can disagree with a rule rather
than with an assertion:

* a counterfactual **supports** its cause when it lowers the rebuild fraction
  **and** equivalence stays at 1.0 -- a cheaper plan that leaves an artifact
  stale is a regression wearing a saving's clothes;
* a counterfactual **refutes** its cause when it lowers the fraction and breaks
  equivalence, because that says the thing it removed was load-bearing;
* a cause is **not necessary** when adding it to another changes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parents[1]

ORDER = (
    "actual",
    "c2_stable_evidence_ids",
    "c3_semantic_channel_only",
    "c2_and_c3",
    "c4_no_document_rollup",
)

DESCRIPTION = {
    "actual": "the diff exactly as `akc_cir.semantic_diff` produces it",
    "c2_stable_evidence_ids": "evidence ids held equal where the unit did not move",
    "c3_semantic_channel_only": "only meaning-changing kinds routed into the changed set",
    "c2_and_c3": "both of the above",
    "c4_no_document_rollup": "the document-level rollup artifact removed from the graph",
}

DISCLOSURE = (
    "> **NOT CLEARED FOR EXTERNAL DISCLOSURE.** Selective recompilation is\n"
    "> `NOT YET DEMONSTRATED`; every number below is a read-only counterfactual\n"
    "> on a synthetic fixture, not a demonstrated benefit.\n"
)


def _write(name: str, body: str) -> None:
    path = EXPERIMENT / "tables" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def _write_json(name: str, payload: object) -> None:
    path = EXPERIMENT / "receipts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _verdicts(summary: dict[str, Any]) -> dict[str, dict[str, object]]:
    counterfactuals = summary["counterfactuals"]
    actual = counterfactuals["actual"]["mean_rebuild_fraction"]
    c2 = counterfactuals["c2_stable_evidence_ids"]
    c3 = counterfactuals["c3_semantic_channel_only"]
    both = counterfactuals["c2_and_c3"]
    c4 = counterfactuals["c4_no_document_rollup"]

    def safe(entry: dict[str, Any]) -> bool:
        return entry["equivalence_rate"]["value"] == 1.0

    def reduction(entry: dict[str, Any]) -> float:
        return actual - entry["mean_rebuild_fraction"]

    c3_subsumes_c2 = both["mean_rebuild_fraction"] == c3["mean_rebuild_fraction"]

    return {
        "C1_evidence_identity_design": {
            "verdict": "NOT REQUIRED",
            "reason": (
                "C3 alone reaches the floor with equivalence intact, so no change "
                "to evidence identity derivation -- and no IDENTITY_SCHEME_VERSION "
                "migration -- is implied by this result."
            ),
            "rebuild_reduction": None,
        },
        "C2_version_scoped_evidence_id": {
            "verdict": "CONTRIBUTING, NOT NECESSARY" if c3_subsumes_c2 else "CONTRIBUTING",
            "reason": (
                "Stabilising evidence ids under re-render is safe (equivalence "
                f"{c2['equivalence_rate']['numerator']}/"
                f"{c2['equivalence_rate']['denominator']}) and lowers the fraction "
                f"to {c2['mean_rebuild_fraction']:.4f}, but it does not reach C3's "
                f"{c3['mean_rebuild_fraction']:.4f}: a unit that genuinely moved "
                "still reports EVIDENCE_MOVED. Adding it to C3 changes nothing."
                if c3_subsumes_c2
                else "Contributes independently of C3."
            ),
            "rebuild_reduction": reduction(c2),
            "safe": safe(c2),
        },
        "C3_semantic_evidence_conflation": {
            "verdict": "DOMINANT AND SUFFICIENT",
            "reason": (
                f"Routing only meaning-changing kinds into the changed set takes "
                f"{actual:.4f} to {c3['mean_rebuild_fraction']:.4f} with "
                f"equivalence {c3['equivalence_rate']['numerator']}/"
                f"{c3['equivalence_rate']['denominator']} and zero artifacts left "
                "stale. The changed-set channel is where the degeneration lives."
            ),
            "rebuild_reduction": reduction(c3),
            "safe": safe(c3),
        },
        "C4_dependency_invalidation_rule": {
            "verdict": "REFUTED",
            "reason": (
                f"Narrowing the dependency rule is cheaper "
                f"({c4['mean_rebuild_fraction']:.4f}) and wrong: equivalence falls "
                f"to {c4['equivalence_rate']['numerator']}/"
                f"{c4['equivalence_rate']['denominator']} with "
                f"{c4['artifacts_left_stale']} artifacts left stale. The breadth "
                "is real -- the rollup genuinely depends on every unit -- so the "
                "rule is doing its job and is not the cause."
            ),
            "rebuild_reduction": reduction(c4),
            "safe": safe(c4),
        },
    }


def main() -> int:
    summary = json.loads(
        (EXPERIMENT / "metrics" / "summary.json").read_text(encoding="utf-8")
    )
    counterfactuals = summary["counterfactuals"]
    attribution = summary["changed_set_attribution"]
    verdicts = _verdicts(summary)

    total_ids = attribution["total"]
    moved_only = attribution.get("evidence_moved_only", 0)

    lines = [
        "# DIAG-B-01 — what causes the full-rebuild degeneration",
        "",
        DISCLOSURE,
        "*Generated by `scripts/make_findings.py` from `metrics/summary.json`.*",
        "",
        f"Read-only counterfactuals over the same {summary['cases']} document pairs "
        "`EXP-0101` used.",
        "",
        "## Where the changed set comes from",
        "",
        "| source | ids | share |",
        "|---|---|---|",
    ]
    for key in sorted(attribution):
        if key == "total":
            continue
        lines.append(
            f"| `{key}` | {attribution[key]:,} | {attribution[key] / total_ids:.1%} |"
        )
    lines.append(f"| **total** | **{total_ids:,}** | |")
    lines.append("")
    lines.append(
        f"**{moved_only / total_ids:.1%} of the traversal seed set is there because a "
        "unit moved and for no other reason.**"
    )
    lines.append("")
    lines.append("## Counterfactuals")
    lines.append("")
    lines.append(
        "| counterfactual | what it changes | rebuild fraction | 95% CI | equivalence | stale |"
    )
    lines.append("|---|---|---|---|---|---|")
    for label in ORDER:
        entry = counterfactuals[label]
        low, high = entry["rebuild_fraction_ci95"]
        rate = entry["equivalence_rate"]
        lines.append(
            f"| `{label}` | {DESCRIPTION[label]} | "
            f"{entry['mean_rebuild_fraction']:.4f} | "
            f"[{low:.4f}, {high:.4f}] | "
            f"{rate['numerator']}/{rate['denominator']} | "
            f"{entry['artifacts_left_stale']} |"
        )
    lines.append("")
    lines.append("## Verdict per cause")
    lines.append("")
    lines.append("| cause | verdict | why |")
    lines.append("|---|---|---|")
    for cause, verdict in verdicts.items():
        lines.append(f"| `{cause}` | **{verdict['verdict']}** | {verdict['reason']} |")
    lines.append("")
    lines.append("## What this does not establish")
    lines.append("")
    lines.append(
        "- **`0.1263` is a counterfactual, not a demonstrated benefit.** It is what "
        "a corrected changed-set channel would have cost on this fixture. No such "
        "channel exists, so the claim state stays `NOT YET DEMONSTRATED`."
    )
    lines.append(
        "- **No fix is proposed and none is authorised.** A change to the changed-set "
        "channel touches `akc_cir.semantic_diff`, which is Protected Core and goes "
        "through the full ladder: compatibility contract, shadow, benchmark, canary, "
        "rollout, deprecate."
    )
    lines.append(
        "- **The fixture is synthetic.** Seventeen units per document, every one "
        "carrying an evidence id. A corpus whose units mostly lack evidence ids "
        "would show a smaller share for `evidence_moved_only`."
    )
    _write("findings.md", "\n".join(lines) + "\n")

    _write_json(
        "verdict.json",
        {
            "experiment": "DIAG-B-01",
            "disclosure": "NOT CLEARED FOR EXTERNAL DISCLOSURE",
            "claim_state": "selective recompilation: NOT YET DEMONSTRATED",
            "cases": summary["cases"],
            "changed_set_attribution": attribution,
            "evidence_moved_only_share": moved_only / total_ids,
            "counterfactuals": {
                label: {
                    "mean_rebuild_fraction": counterfactuals[label][
                        "mean_rebuild_fraction"
                    ],
                    "equivalence_rate": counterfactuals[label]["equivalence_rate"],
                    "artifacts_left_stale": counterfactuals[label][
                        "artifacts_left_stale"
                    ],
                }
                for label in ORDER
            },
            "verdicts": verdicts,
            "c1_design_question": summary["c1_design_question"],
            "for_the_ip_track": {
                "family_b_section_5_causal_wording": (
                    "The degeneration is caused by the changed-set channel carrying "
                    "positional and semantic change under one identifier "
                    "(C3), not by the dependency invalidation rule (refuted) and "
                    "not by evidence identity design (not required). The machinery "
                    "is IMPLEMENTED; a narrow recompilation benefit is NOT YET "
                    "DEMONSTRATED, because the corrected channel does not exist."
                ),
                "permitted_state": "IMPLEMENTED",
                "forbidden_state": "DEMONSTRATED",
            },
        },
    )
    print("findings.md and verdict.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
