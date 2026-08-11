"""Gate 4 evidence — rerun the frozen manifest and check it reproduces.

    .venv/Scripts/python.exe research/experiments/EXP-0101/scripts/verify_receipts.py
    .venv/Scripts/python.exe research/experiments/EXP-0101/scripts/verify_receipts.py --full

Without `--full` this rebuilds the fixture and checks the corpus manifest digest
against `manifest.json`, then rewrites `receipts/receipts.json` over the whole
experiment tree including the tables and figures the run itself could not cover.

With `--full` it also re-runs every arm over every case and compares the metrics
it computes against the ones on disk. That is the only version of this check
that is worth calling reproducibility: a matching file digest proves the file
has not been edited, and proves nothing about whether the pipeline would produce
it again.

Reproducibility is written as a verdict with a reason, never as a bare `true`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "absorption" / "src"))

from akc_absorption.evolution_suite import build_suite, suite_manifest_sha256  # noqa: E402
from akc_absorption.flags import ABSORB_ALIGNMENT_DIFF  # noqa: E402
from akc_absorption.harness import Arm, run_case  # noqa: E402
from akc_absorption.metrics import CaseScore, score_case, summarise  # noqa: E402


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _reindex() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(EXPERIMENT.rglob("*")):
        if not path.is_file() or path.name in {"receipts.json", "reproducibility.json"}:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(
            {
                "path": path.relative_to(EXPERIMENT).as_posix(),
                "sha256": f"sha256:{digest}",
                "bytes": str(path.stat().st_size),
            }
        )
    _write_json(
        EXPERIMENT / "receipts" / "receipts.json",
        {
            "experiment": "EXP-0101",
            "note": (
                "A number not bound to a receipt does not exist. Written by "
                "scripts/verify_receipts.py, which runs after the tables and "
                "figures and therefore covers them."
            ),
            "artifacts": entries,
        },
    )
    return entries


def main(argv: list[str]) -> int:
    full = "--full" in argv
    manifest: dict[str, Any] = json.loads(
        (EXPERIMENT / "manifest.json").read_text(encoding="utf-8")
    )

    cases = build_suite(documents=int(manifest["seed_documents"]))
    corpus_digest = suite_manifest_sha256(cases)
    corpus_ok = corpus_digest == manifest["corpus_manifest_sha256"]

    metrics_match: bool | None = None
    mismatches: list[str] = []
    if full:
        scores: dict[Arm, list[CaseScore]] = defaultdict(list)
        for case in cases:
            for arm, outcome in run_case(case, env={ABSORB_ALIGNMENT_DIFF: "1"}).items():
                scores[arm].append(score_case(case, outcome))
        recomputed = {arm.value: summarise(items) for arm, items in scores.items()}
        on_disk = json.loads(
            (EXPERIMENT / "metrics" / "summary.json").read_text(encoding="utf-8")
        )
        canonical_new = json.dumps(recomputed, sort_keys=True)
        canonical_old = json.dumps(on_disk, sort_keys=True)
        metrics_match = canonical_new == canonical_old
        if not metrics_match:
            for arm in sorted(set(recomputed) | set(on_disk)):
                if json.dumps(recomputed.get(arm), sort_keys=True) != json.dumps(
                    on_disk.get(arm), sort_keys=True
                ):
                    mismatches.append(arm)

    entries = _reindex()
    # A run that did not recompute the metrics has not tested reproducibility,
    # so it does not get to say PASS. The earlier version of this script did,
    # and a later `verify_receipts.py` with no flag would then quietly overwrite
    # a real PASS with an empty one -- the weaker check erasing the stronger
    # evidence, which is the failure this whole receipt exists to prevent.
    if not corpus_ok or metrics_match is False:
        verdict = "FAIL"
    elif metrics_match is None:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"

    reason = []
    if not corpus_ok:
        reason.append(
            f"corpus manifest digest {corpus_digest} does not match the frozen "
            f"{manifest['corpus_manifest_sha256']}"
        )
    if metrics_match is None:
        reason.append(
            "metrics were NOT recomputed: this run re-indexed the artifacts and "
            "checked the corpus digest only. Run with --full before citing this "
            "as reproducibility evidence"
        )
    elif metrics_match:
        reason.append("every arm's summary recomputed identically from the frozen inputs")
    else:
        reason.append(f"recomputed summary differs for: {', '.join(mismatches)}")

    _write_json(
        EXPERIMENT / "receipts" / "reproducibility.json",
        {
            "experiment": "EXP-0101",
            "gate": "4 reproducibility",
            "verdict": verdict,
            "recomputed_metrics": bool(full),
            "corpus_manifest_sha256": corpus_digest,
            "corpus_manifest_matches_frozen": corpus_ok,
            "artifacts_indexed": len(entries),
            "reason": reason,
        },
    )
    print(f"reproducibility: {verdict} ({'; '.join(reason)})")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
