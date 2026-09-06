"""Rung 5 of the INC-V2-047 ladder: the production switch, receipted.

The switch is a one-line edit. This tool exists because a one-line edit is
exactly the kind of act that leaves no trace of the reasoning behind it, and
INC-V2-042 is the record of what this programme costs when a Protected Core
default moves ahead of the evidence that was supposed to authorise it.

So this does not *perform* the flip -- it OBSERVES it, checks that every rung
below it actually landed, and refuses to write a receipt if any of them did
not. A receipt that can only say PASS would be a check that can only return one
answer, which is not a measurement (INC-V2-044).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import akc_cir.semantic_diff as sd  # noqa: E402
from evidence import RECEIPTS, write_immutable  # noqa: E402


def latest_receipt(stem: str) -> Path | None:
    """The newest immutable receipt with this stem, or None.

    Receipt names carry a UTC timestamp, so lexical order is chronological.
    Same helper as `freeze_sfi3_protocol._latest_receipt`; not imported from
    there because that module is a gate and importing it to read a filename
    would couple this tool to the gate's own preconditions.
    """
    found = sorted(RECEIPTS.glob(stem + "--*.json"))
    return found[-1] if found else None


def read_json(path: Path) -> dict[str, Any]:
    import json

    return dict(json.loads(path.read_text(encoding="utf-8")))


STEM = "identity-quarantine-switch"
CONTRACT = NS / "docs" / "COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md"
SUBJECT = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "semantic_diff.py"
QUARANTINE = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity_quarantine.py"


def _digest(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rung(stem: str, name: str) -> dict[str, Any]:
    """One lower rung, read from its own receipt rather than from a claim."""
    try:
        path = latest_receipt(stem)
    except Exception as exc:
        return {"rung": name, "state": "MISSING", "detail": str(exc)}
    if path is None:
        return {"rung": name, "state": "MISSING", "detail": f"no {stem} receipt exists"}
    body = read_json(path)
    verdict = body.get("verdict")
    return {
        "rung": name,
        "state": "PASS" if verdict == "PASS" else "FAIL",
        "verdict": verdict,
        "receipt": path.name,
        "run_id": body.get("run_id"),
    }


def _suite(target: str, label: str) -> dict[str, Any]:
    """Run a suite now. A suite someone remembers passing is not evidence."""
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", target, "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return {
        "suite": label,
        "target": target,
        "state": "PASS" if proc.returncode == 0 else "FAIL",
        "summary": tail,
    }


def observe() -> dict[str, Any]:
    rungs = [
        {
            "rung": "1 compatibility contract",
            "state": "PASS" if CONTRACT.exists() else "MISSING",
            "document": CONTRACT.name,
            "digest": _digest(CONTRACT) if CONTRACT.exists() else None,
        },
        _rung("identity-quarantine-differential", "2 shadow / differential"),
        _rung("identity-quarantine-canary", "4 canary"),
    ]
    suites = [
        _suite("tests/unit", "Protected Core consumers"),
        _suite("research/tavonel_eval_v2/tests/test_identity_quarantine.py", "3 property battery"),
    ]

    observed_default = bool(sd.QUARANTINE_UNSETTLED_IDENTITY_DEFAULT)
    blocking = [r for r in rungs if r["state"] != "PASS"]
    blocking += [s for s in suites if s["state"] != "PASS"]

    if observed_default and blocking:
        state = "SWITCHED_WITHOUT_A_COMPLETE_LADDER"
    elif observed_default:
        state = "SWITCHED"
    elif blocking:
        state = "NOT_SWITCHED_AND_NOT_READY"
    else:
        state = "READY_BUT_NOT_SWITCHED"

    return {
        "rung": 5,
        "incident": "INC-V2-047",
        "state": state,
        "verdict": "PASS" if state == "SWITCHED" else "FAIL",
        "observed_production_default": observed_default,
        "subject_digest": _digest(SUBJECT),
        "quarantine_digest": _digest(QUARANTINE),
        "lower_rungs": rungs,
        "suites_run_now": suites,
        "blocking": [b.get("rung") or b.get("suite") for b in blocking],
        "what_this_does_not_claim": [
            "not prospective certification -- the 514-pair universe is V1's and "
            "the nine cases were seen before the repair was written",
            "two of the contract's four clauses have no members anywhere and "
            "selected_candidate is unreachable as wired (INC-V2-052); they ship "
            "inert and stay declared rather than being quietly deleted",
            "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 remains FAIL, permanently, and "
            "is never repaired, rescored or reused as a positive denominator",
        ],
    }


def main() -> int:
    body = observe()
    if "--write-receipt" in sys.argv:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))
    import json

    print(json.dumps(body, indent=2, sort_keys=True))
    return 0 if body["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
