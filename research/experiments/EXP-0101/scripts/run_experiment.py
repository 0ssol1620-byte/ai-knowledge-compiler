"""EXP-0101 driver — builds the fixture, runs every arm, writes every artifact.

Usage, from the repository root:

    .venv/Scripts/python.exe research/experiments/EXP-0101/scripts/run_experiment.py

Deterministic end to end. The fixture is derived from sha256 over seed strings,
the bootstrap uses a fixed-sequence generator, and no model or network call
happens anywhere in the run, so a second run on another machine must reproduce
`metrics/summary.json` byte for byte. `scripts/verify_receipts.py` is what
checks that claim rather than asserting it.

The `ABSORB_ALIGNMENT_DIFF` flag is passed explicitly rather than read from the
shell. The challenger is shadow-only; the harness is what may turn it on, and
making that visible in the source is the point.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "absorption" / "src"))

from akc_absorption.evolution_suite import (  # noqa: E402
    MutationClass,
    build_suite,
    suite_manifest_sha256,
)
from akc_absorption.flags import ABSORB_ALIGNMENT_DIFF  # noqa: E402
from akc_absorption.harness import ARMS, Arm, run_case  # noqa: E402
from akc_absorption.identity_bridge import (  # noqa: E402
    ALIGNMENT_SHARE,
    ALIGNMENT_SIGNAL_SHARES,
)
from akc_absorption.metrics import (  # noqa: E402
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CaseScore,
    holm_bonferroni,
    mcnemar_exact,
    score_case,
    summarise,
)
from akc_cir.identity import (  # noqa: E402
    IDENTITY_SIGNAL_WEIGHTS,
    MERGE_THRESHOLD,
    NEW_IDENTITY_THRESHOLD,
)

SEED_DOCUMENTS = 60
ENV = {ABSORB_ALIGNMENT_DIFF: "1"}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return result.stdout.strip()


def _config_sha256() -> str:
    """A digest over every knob that could move a number in this run."""
    payload = json.dumps(
        {
            "seed_documents": SEED_DOCUMENTS,
            "alignment_share": ALIGNMENT_SHARE,
            "alignment_signal_shares": ALIGNMENT_SIGNAL_SHARES,
            "identity_signal_weights": IDENTITY_SIGNAL_WEIGHTS,
            "merge_threshold": MERGE_THRESHOLD,
            "new_identity_threshold": NEW_IDENTITY_THRESHOLD,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "arms": [spec.arm.value for spec in ARMS],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    started = time.time()
    cases = build_suite(documents=SEED_DOCUMENTS)
    corpus_manifest_sha256 = suite_manifest_sha256(cases)

    _write_json(
        EXPERIMENT / "raw" / "knowledge-evolution-suite.json",
        {
            "suite_manifest_sha256": corpus_manifest_sha256,
            "cases": [case.as_record() for case in cases],
        },
    )
    sample = cases[3]
    _write_json(
        EXPERIMENT / "raw" / "sample-case.json",
        {
            "case_id": sample.case_id,
            "mutation": sample.mutation.value,
            "before": [
                {"anchor": unit.anchor, "logical_id": unit.logical_id, "text": unit.text}
                for unit in sample.before.units
            ],
            "after": [
                {"anchor": unit.anchor, "logical_id": unit.logical_id, "text": unit.text}
                for unit in sample.after.units
            ],
            "gold": sample.gold.as_record(),
        },
    )

    outcomes_path = EXPERIMENT / "raw" / "arm-outcomes.jsonl"
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    scores: dict[Arm, list[CaseScore]] = defaultdict(list)
    with outcomes_path.open("w", encoding="utf-8") as handle:
        for case in cases:
            for arm, outcome in run_case(case, env=ENV).items():
                handle.write(
                    json.dumps(outcome.as_record(), sort_keys=True, ensure_ascii=False) + "\n"
                )
                scores[arm].append(score_case(case, outcome))

    normalized = EXPERIMENT / "normalized" / "case-scores.jsonl"
    normalized.parent.mkdir(parents=True, exist_ok=True)
    with normalized.open("w", encoding="utf-8") as handle:
        for arm in scores:
            for item in scores[arm]:
                handle.write(
                    json.dumps(
                        {
                            "case_id": item.case_id,
                            "arm": item.arm.value,
                            "mutation": item.mutation.value,
                            "reported_semantic": item.reported_semantic,
                            "gold_semantic": item.gold_semantic,
                            "detected_gold_change": item.detected_gold_change,
                            "surfaced_gold_change": item.surfaced_gold_change,
                            "labelled_critical": item.labelled_critical,
                            "left_unresolved": item.left_unresolved,
                            "alignment_true_positives": item.alignment_true_positives,
                            "alignment_predicted": item.alignment_predicted,
                            "alignment_gold": item.alignment_gold,
                            "false_merges": item.false_merges,
                            "false_splits": item.false_splits,
                            "impact_recall_hit": item.impact_recall_hit,
                            "impact_recall_total": item.impact_recall_total,
                            "rebuild_equivalent": item.rebuild_equivalent,
                            "rebuild_fraction": item.rebuild_fraction,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

    summary = {arm.value: summarise(items) for arm, items in scores.items()}
    _write_json(EXPERIMENT / "metrics" / "summary.json", summary)

    per_class: dict[str, dict[str, object]] = {}
    for arm, items in scores.items():
        by_class: dict[str, object] = {}
        for mutation in MutationClass:
            subset = [item for item in items if item.mutation is mutation]
            by_class[mutation.value] = summarise(subset, with_ci=False)
        per_class[arm.value] = by_class
    _write_json(EXPERIMENT / "metrics" / "per-mutation-class.json", per_class)

    _write_json(EXPERIMENT / "metrics" / "statistics.json", _statistics(scores))

    _write_json(
        EXPERIMENT / "manifest.json",
        {
            "experiment": "EXP-0101",
            "contract": "docs/research/ABSORPTION_EXPERIMENT_CONTRACTS_BATCH1.md, Contract A",
            "disclosure": "NOT CLEARED FOR EXTERNAL DISCLOSURE",
            "result_status": "exploratory / internal - see receipts/clean-room-provenance.json",
            "canonical_finding": "receipts/canonical-finding.json",
            "successor_contract": "docs/research/ABSORPTION_EXPERIMENT_CONTRACT_A2.md",
            "registered_gap": "docs/research/DIAGNOSTIC_CONTRACT_DIAG_B_01.md",
            "claim_discipline": {
                "subject": "selective recompilation",
                "permitted_states": [
                    "IMPLEMENTED - the mechanism exists in code",
                    "DEMONSTRATED - a narrow recompilation benefit is proven",
                    "NOT YET DEMONSTRATED - neither shown end to end",
                ],
                "current_state": "NOT YET DEMONSTRATED",
                "note": (
                    "The machinery is IMPLEMENTED. This experiment measured mean "
                    "rebuild fraction 1.0000 for every arm routed through "
                    "akc_cir.semantic_diff. The cause is not settled and must not "
                    "be written down as settled before DIAG-B-01 runs."
                ),
                "gates": "Family B section 5; the IP track is holding for it",
            },
            "raw_evidence": (
                "raw/ is stored compressed; receipts/raw-evidence-manifest.json "
                "carries the raw and compressed digests and scripts/compress_raw.py "
                "--restore rebuilds the originals. Nothing was discarded."
            ),
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "git_commit": _git_commit(),
            "config_sha256": _config_sha256(),
            "seeds": {
                "fixture": "sha256 over seed strings; no PRNG",
                "bootstrap": BOOTSTRAP_SEED,
            },
            "split_definition": (
                "No train/test split. Every arm is deterministic and nothing is "
                "fitted, so there is nothing to hold out. No threshold or weight "
                "was chosen using this fixture; contract 0.9 is therefore not "
                "engaged and no holdout was spent."
            ),
            "model_registry_ids": [],
            "model_registry_note": (
                "None. No model is called anywhere in this experiment. The "
                "contract's Resources line allows an embedding provider for the "
                "semantic signal and this run does not use one: the content "
                "signals are lexical, numeric and structural. The consequence is "
                "recorded in the result block - the semantic ceiling here is "
                "lexical, and an embedding arm is unmeasured."
            ),
            "prompt_receipt_sha256": [],
            "flags": {ABSORB_ALIGNMENT_DIFF: "set to 1 by the harness only"},
            "seed_documents": SEED_DOCUMENTS,
            "cases": len(cases),
            "arms": [spec.arm.value for spec in ARMS],
            "runtime_seconds": round(time.time() - started, 1),
            "unpopulated_directories": {
                "figures": "written by scripts/make_figures.py",
                "tables": "written by scripts/make_tables.py",
            },
        },
    )

    # Deliberately no receipt index here. `compress_raw.py` runs next and
    # deletes the uncompressed originals, so an index written at this point
    # would name three artifacts that are about to stop existing. An index that
    # is merely absent is honest; one that lists files it cannot verify is the
    # kind of green tick this repository exists to distrust.
    # `verify_receipts.py` is the sole writer of `receipts/receipts.json`, and
    # it runs last precisely so it can cover the tables, figures and compressed
    # artifacts that this script never sees.
    print(f"EXP-0101 complete in {time.time() - started:.1f}s over {len(cases)} cases")
    print("run scripts/compress_raw.py, then scripts/verify_receipts.py --full")
    return 0


def _statistics(scores: dict[Arm, list[CaseScore]]) -> dict[str, object]:
    """McNemar of each arm against CURRENT, Holm-Bonferroni over the slices."""
    reference = {item.case_id: item for item in scores[Arm.CURRENT]}
    tests: dict[str, dict[str, object]] = {}
    raw_p: dict[str, float] = {}

    for arm, items in scores.items():
        if arm is Arm.CURRENT:
            continue
        for slice_name, predicate in (
            ("semantic_judgement", lambda item: item.correct_semantic_judgement),
            ("critical_detection", lambda item: item.detected_gold_change),
            ("layout_false_positive", lambda item: not item.reported_semantic),
            # The slice that decides cost. A false positive and an abstention
            # both end in a rebuild, so testing only the first lets an arm look
            # better by abstaining more.
            (
                "layout_false_invalidation",
                lambda item: not (item.reported_semantic or item.left_unresolved),
            ),
        ):
            arm_better = 0
            current_better = 0
            for item in items:
                other = reference[item.case_id]
                if slice_name == "critical_detection" and not item.mutation_is_critical:
                    continue
                if (
                    slice_name in {"layout_false_positive", "layout_false_invalidation"}
                    and not item.mutation_is_layout
                ):
                    continue
                mine = predicate(item)
                theirs = predicate(other)
                if mine and not theirs:
                    arm_better += 1
                elif theirs and not mine:
                    current_better += 1
            label = f"{arm.value}::{slice_name}"
            pvalue = mcnemar_exact(arm_better, current_better)
            raw_p[label] = pvalue
            tests[label] = {
                "arm_better": arm_better,
                "current_better": current_better,
                "discordant": arm_better + current_better,
                "p_exact": pvalue,
            }

    adjusted = holm_bonferroni(raw_p)
    for label, value in adjusted.items():
        tests[label]["p_holm_bonferroni"] = value
    return {
        "test": "exact two-sided McNemar, paired at document-pair level",
        "multiple_comparison": "Holm-Bonferroni over every arm x slice reported here",
        "reference_arm": Arm.CURRENT.value,
        "tests": tests,
    }


if __name__ == "__main__":
    raise SystemExit(main())
