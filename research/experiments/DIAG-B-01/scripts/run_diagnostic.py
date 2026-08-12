"""DIAG-B-01 driver — attribute the full-rebuild degeneration across C1-C4.

    .venv/Scripts/python.exe research/experiments/DIAG-B-01/scripts/run_diagnostic.py

Read-only. Every counterfactual constructs its inputs outside Protected Core and
hands them to `diff_documents`, `plan_recompilation` and `verify_equivalence`.
No `akc_cir` module is modified, and no fix is proposed here: which cause is
real decides what a fix would be, and that decision is not this contract's.

Same manifest as `EXP-0101` -- same generator, same seed, same 660 cases -- so
the numbers are directly comparable to the 1.0000 this exists to explain.
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
    build_suite,
    suite_manifest_sha256,
)
from akc_absorption.metrics import bootstrap_ci  # noqa: E402
from akc_absorption.recompilation_diagnostic import (  # noqa: E402
    COUNTERFACTUALS,
    attribute_changed_set,
    diff_for,
    evidence_id_is_version_scoped,
    run_counterfactuals,
)

SEED_DOCUMENTS = 60


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        # LF explicitly -- a receipt over CRLF bytes describes a file no
        # checkout of this repository produces.
        newline="\n",
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


def main() -> int:
    started = time.time()
    cases = build_suite(documents=SEED_DOCUMENTS)
    corpus = suite_manifest_sha256(cases)

    fractions: dict[str, list[float]] = defaultdict(list)
    equivalent: dict[str, int] = defaultdict(int)
    stale: dict[str, int] = defaultdict(int)
    changed_ids: dict[str, int] = defaultdict(int)
    attribution: dict[str, int] = defaultdict(int)
    per_class: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    rows = EXPERIMENT / "raw" / "counterfactuals.jsonl"
    rows.parent.mkdir(parents=True, exist_ok=True)
    with rows.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            outcomes = run_counterfactuals(case)
            for key, value in attribute_changed_set(diff_for(case)).items():
                attribution[key] += value
            for label, outcome in outcomes.items():
                fractions[label].append(outcome.rebuild_fraction)
                equivalent[label] += int(outcome.equivalent)
                stale[label] += outcome.stale_left_behind
                changed_ids[label] += outcome.changed_ids
                per_class[case.mutation.value][label].append(outcome.rebuild_fraction)
            handle.write(
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "mutation": case.mutation.value,
                        "outcomes": {
                            label: outcome.as_record()
                            for label, outcome in outcomes.items()
                        },
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    total = len(cases)
    summary: dict[str, object] = {
        "cases": total,
        "counterfactuals": {
            label: {
                "causes": [cause.value for cause in COUNTERFACTUALS[label]],
                "mean_rebuild_fraction": sum(values) / len(values),
                "rebuild_fraction_ci95": bootstrap_ci(values),
                "equivalence_rate": {
                    "value": equivalent[label] / total,
                    "numerator": equivalent[label],
                    "denominator": total,
                    "population": "all cases",
                },
                "artifacts_left_stale": stale[label],
                "changed_ids_total": changed_ids[label],
            }
            for label, values in fractions.items()
        },
        "changed_set_attribution": dict(attribution),
        "c1_design_question": evidence_id_is_version_scoped(),
    }
    _write_json(EXPERIMENT / "metrics" / "summary.json", summary)

    _write_json(
        EXPERIMENT / "metrics" / "per-mutation-class.json",
        {
            mutation: {
                label: sum(values) / len(values) for label, values in labels.items()
            }
            for mutation, labels in sorted(per_class.items())
        },
    )

    _write_json(
        EXPERIMENT / "manifest.json",
        {
            "experiment": "DIAG-B-01",
            "contract": "docs/research/DIAGNOSTIC_CONTRACT_DIAG_B_01.md",
            "explains": "EXP-0101 mean_rebuild_fraction = 1.0000",
            "disclosure": "NOT CLEARED FOR EXTERNAL DISCLOSURE",
            "read_only": (
                "No akc_cir module is modified. Every counterfactual constructs "
                "inputs outside Protected Core and calls its public entry points."
            ),
            "claim_state": "selective recompilation: NOT YET DEMONSTRATED",
            "corpus_manifest_sha256": corpus,
            "git_commit": _git_commit(),
            "seed_documents": SEED_DOCUMENTS,
            "cases": total,
            "model_registry_ids": [],
            "runtime_seconds": round(time.time() - started, 1),
        },
    )

    entries = []
    for path in sorted(EXPERIMENT.rglob("*")):
        if not path.is_file() or path.name == "receipts.json":
            continue
        entries.append(
            {
                "path": path.relative_to(EXPERIMENT).as_posix(),
                "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": str(path.stat().st_size),
            }
        )
    _write_json(
        EXPERIMENT / "receipts" / "receipts.json",
        {"experiment": "DIAG-B-01", "artifacts": entries},
    )

    print(f"DIAG-B-01 complete in {time.time() - started:.1f}s over {total} cases")
    for label, values in fractions.items():
        print(
            f"  {label:26s} rebuild {sum(values) / len(values):.4f}  "
            f"equivalent {equivalent[label]}/{total}  stale {stale[label]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
