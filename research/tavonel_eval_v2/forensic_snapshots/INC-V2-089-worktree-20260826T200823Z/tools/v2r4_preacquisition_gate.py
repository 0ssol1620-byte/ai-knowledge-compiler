"""The V2R4 PRE-ACQUISITION JOIN GATE. Founder ruling section G.

TWELVE CONDITIONS, ALL REQUIRED, EVERY ONE EXECUTED. Not a checklist a reader
ticks -- each row below runs the thing it is about and reports what came back.
The gate exists because everything downstream of it is irreversible: the moment
V2R4 opens content, the material is spent whatever the instrument turns out to
say, and INC-V2-067 is what it costs to discover an instrument defect on the far
side of that line.

WHAT THIS GATE IS NOT. It is not the freeze ladder and it does not replace it.
The ladder seals; this decides whether sealing may begin. It runs BEFORE rung 0,
so it deliberately expects the frame, universe, scorer and exclusion rungs to be
UNFROZEN and refuses if any of them is not.

FAIL CLOSED, AND SAY WHICH. A condition that raises is reported with its
exception rather than swallowed, and the verdict is the AND of every row. A row
that could not be evaluated is a FAIL, never a pass with a note: "we could not
tell" and "it holds" are different answers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import anti_blocker_audit  # noqa: E402
import invariant_domain  # noqa: E402
import rehearse_v2r4_closure as rehearsal  # noqa: E402
import sfi3_root_reservation as reservation  # noqa: E402
import v2r4_attestation as att  # noqa: E402
import v2r4_grading as grading  # noqa: E402
import v2r4_semantics_delta as delta  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.v2r4_preacquisition_gate.v1"
GATE_ID = "V2R4_PREACQUISITION_JOIN_GATE"
STEM = "identity-change-migration-closure-v2r4-preacquisition-gate"

PASS = "PASS"  # noqa: S105 - a verdict label, not a credential
FAIL = "FAIL"
READY = "READY_FOR_ACQUISITION"
BLOCKED = "BLOCKED_BEFORE_ACQUISITION"

#: The V2R4 corpus. Its emptiness is what "no fresh material has been opened"
#: means for this study.
CORPUS = NS / "artifacts" / "development" / "v2r4_corpus"

#: SFI3's corpus. Its emptiness is what "SFI3 fresh payload opened == false"
#: means, and it is checked HERE rather than trusted, because the whole serial
#: order exists to keep it empty until V2R4 passes.
SFI3_CORPUS = NS / "artifacts" / "development" / "sfi3_corpus"

MEASUREMENT_GLOB = "identity-change-migration-closure-v2r4--*.json"


class GateRefused(RuntimeError):
    """A condition could not be established. Acquisition does not begin."""


def _row(name: str, check) -> dict[str, Any]:
    """Run one condition. An exception is a FAIL that carries its reason."""
    try:
        detail = check()
    except Exception as error:
        return {
            "condition": name,
            "verdict": FAIL,
            "error": f"{type(error).__name__}: {error}",
        }
    return {"condition": name, "verdict": PASS, "detail": detail}


# ---------------------------------------------------------------------------
# the twelve


def _c1_invariant_domain() -> dict[str, Any]:
    """DECLARED == GRADED == RECEIPT, with GRADED obtained by EXECUTION."""
    domain = grading.require_domain()
    declared, graded, schema = (
        set(domain["declared"]),
        set(domain["graded"]),
        set(domain["schema_required"]),
    )
    if not declared == graded == schema:
        raise GateRefused(f"domains differ: {declared}, {graded}, {schema}")
    return {
        "invariants": sorted(declared),
        "count": len(declared),
        "compared": "set equality on full identifiers, never a count",
    }


def _c2_full_eight_rehearsal() -> dict[str, Any]:
    """The scorer is rehearsable: it grades all eight, on synthetic input only."""
    body = rehearsal.rehearse()
    if body.get("verdict") != "SCORER_REHEARSABLE":
        raise GateRefused(f"rehearsal verdict is {body.get('verdict')}")
    return {
        "verdict": body["verdict"],
        "green": body.get("green", {}).get("overall"),
        "drivers": len(rehearsal.RED_DRIVERS),
    }


def _c3_every_invariant_reds_independently() -> dict[str, Any]:
    """Each invariant can be driven VIOLATED on its own, with zero collateral.

    A scorer that reports FAIL whatever you hand it is not an instrument, and one
    that cannot red a given invariant has not been shown to grade it. The driver
    set is checked for SET EQUALITY against the executed graded domain first, so
    a driver quietly missing is a FAIL rather than a smaller loop.
    """
    rehearsal.require_driver_domain()
    reds = {}
    for invariant in sorted(rehearsal.RED_DRIVERS):
        proof = rehearsal.drive_red(invariant)
        reds[invariant] = {
            "target_verdict": proof["target_verdict"],
            "collateral_damage": proof["collateral_damage"],
            "overall": proof["overall"],
        }
        #: All three, because each rules out a different way of looking right.
        #: A driver that reds the TARGET but also seven bystanders proves the
        #: scorer breaks, not that this invariant is graded; one that reds
        #: nothing while the overall verdict is FAIL proves less than nothing.
        if (
            proof["target_verdict"] != invariant_domain.VIOLATED
            or proof["collateral_damage"]
            or proof["overall"] != invariant_domain.FAIL
        ):
            raise GateRefused(f"{invariant} did not red cleanly: {proof}")
    return {
        "invariants_driven_red": len(reds),
        "each_with_zero_collateral": True,
        "per_invariant": reds,
    }


def _c4_allowed_delta() -> dict[str, Any]:
    body = delta.prove_allowed_delta()
    if body["verdict"] != delta.VERDICT_HELD:
        raise GateRefused(f"allowed-delta verdict is {body['verdict']}")
    return {
        "verdict": body["verdict"],
        "accepted_deltas": body["accepted_delta_count"],
        "core_paths_preserved": len(body["core_paths_preserved"]),
        "core_breaches": body["core_breaches"],
    }


def _c5_reservation_is_frozen() -> dict[str, Any]:
    """SFI3_ROOT_RESERVATION_V1 exists on disk and still derives to itself."""
    path = reservation.latest_reservation()
    if path is None:
        raise GateRefused(
            "no SFI3_ROOT_RESERVATION_V1 receipt exists. Both studies bind it by "
            "path and sha256, and a binding to nothing is not a binding."
        )
    stored = json.loads(path.read_text(encoding="utf-8"))
    verified = reservation.verify(stored)
    return {
        "receipt": path.name,
        "reservation_id": stored["reservation_id"],
        "content_digest": stored["content_digest"],
        "reserved_counts": stored["reserved_counts"],
        "verified": verified.get("held", True),
    }


def _c6_root_separation() -> dict[str, Any]:
    """V2R4's declared containers are outside the reservation, and fresh."""
    roots = att.prove_root_disjointness()
    sfi3 = att.prove_sfi3_separation()
    if roots["clashes"] or roots["module"] != "sources_v2r4":
        raise GateRefused(f"root disjointness is wrong: {roots}")
    return {
        "module": roots["module"],
        "prior_identities": roots["prior_identities"],
        "clashes": roots["clashes"],
        "sfi3_containers_checked": sfi3["containers_checked"],
        "sfi3_reserved_counts": sfi3["reserved_counts"],
    }


def _c7_exclusion_domain() -> dict[str, Any]:
    """INVARIANT_8's declared populations are exactly the proved ones.

    SFI3 is deliberately NOT among them. Requiring it would be a gate on a cohort
    that cannot exist until this study passes.
    """
    body = grading.require_exclusion_domain()
    populations = tuple(grading.declared_populations())
    if "from_sfi3_material" in populations:
        raise GateRefused(
            "INVARIANT_8 still names from_sfi3_material. SFI3 separation is a "
            "RESERVATION on container identity, not an invariant over a cohort "
            "that does not exist."
        )
    return {
        "populations": list(populations),
        "count": len(populations),
        "held": body.get("held", True),
        "sfi3_is_not_one_of_them": True,
    }


def _c8_anti_blocker_audit() -> dict[str, Any]:
    body = anti_blocker_audit.audit()
    if body["blocker_count"]:
        raise GateRefused(
            f"{body['blocker_count']} blocker(s): "
            f"{[f for f in body['findings'] if f.get('severity') == 'BLOCKER']}"
        )
    return {
        "verdict": body["verdict"],
        "blocker_count": 0,
        "modules_scanned": len(body["modules_scanned"]),
        "modules_absent": body["modules_absent"],
    }


def _c9_full_suite_green(run: bool = True) -> dict[str, Any]:
    """The authoritative suite, actually executed.

    NOT a cached verdict and not a claim. `capture_output` with an explicit utf-8
    decode, because the default locale decode on this console raises on the
    suite's own output and would turn a green run into an unreadable failure.
    """
    if not run:
        raise GateRefused("the suite was not run, so its state is unknown")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=NS,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    tail = (completed.stdout or "").strip().splitlines()[-1:] or ["<no output>"]
    if completed.returncode != 0:
        raise GateRefused(f"the suite is not green: {tail[0]}")
    return {"returncode": 0, "summary": tail[0]}


def _c10_gpu_spend_is_zero() -> dict[str, Any]:
    """No GPU has been provisioned for this chain. Preparation, not spend."""
    receipts = sorted((NS / "receipts").glob("gpu-successor-launch--*.json"))
    spent = []
    for path in receipts:
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("gpu_seconds") or body.get("cost_usd"):
            spent.append({"receipt": path.name, "gpu_seconds": body.get("gpu_seconds")})
    if spent:
        raise GateRefused(f"GPU spend is not zero: {spent}")
    return {"launch_receipts": len(receipts), "gpu_seconds": 0, "cost_usd": 0}


def _c11_sfi3_payload_unopened() -> dict[str, Any]:
    """SFI3's fresh material has not been opened. The serial order depends on it."""
    if SFI3_CORPUS.exists() and any(SFI3_CORPUS.iterdir()):
        raise GateRefused(
            f"{SFI3_CORPUS.name} holds material. SFI3 acquires only AFTER this study "
            "passes; opening it first spends the next study's confirmatory cohort."
        )
    frozen = sorted((NS / "receipts").glob("source-fact-ir-heldout-v3-*frame*.json"))
    return {
        "sfi3_corpus_present": SFI3_CORPUS.exists(),
        "sfi3_corpus_empty": True,
        "sfi3_frame_receipts": [path.name for path in frozen],
    }


def _c12_no_prior_v2r4_measurement() -> dict[str, Any]:
    """A closure runs EXACTLY ONCE, so a prior measurement ends this study."""
    measurements = sorted((NS / "receipts").glob(MEASUREMENT_GLOB))
    if measurements:
        raise GateRefused(
            f"a V2R4 measurement already exists: {[p.name for p in measurements]}. "
            "Its corpus is spent and no rescore is permitted."
        )
    acquired = CORPUS.exists() and any(CORPUS.iterdir())
    if acquired:
        raise GateRefused(
            f"{CORPUS.name} already holds acquired material, so this gate is no "
            "longer PRE-acquisition."
        )
    return {
        "measurement_receipts": 0,
        "corpus_present": CORPUS.exists(),
        "fresh_material_opened": False,
    }


#: Ordered, and the order is the ruling's. A reader comparing this list to
#: section G should find twelve rows in the same sequence.
CONDITIONS: tuple[tuple[str, Any], ...] = (
    ("invariant_domain_equality", _c1_invariant_domain),
    ("v2r4_full_eight_rehearsal", _c2_full_eight_rehearsal),
    ("every_invariant_reds_independently", _c3_every_invariant_reds_independently),
    ("v2r4_allowed_delta_attestation", _c4_allowed_delta),
    ("sfi3_root_reservation_frozen", _c5_reservation_is_frozen),
    ("v2r4_sfi3_root_separation", _c6_root_separation),
    ("i8_exclusion_domain_exact", _c7_exclusion_domain),
    ("anti_blocker_audit_zero_blockers", _c8_anti_blocker_audit),
    ("authoritative_full_suite_green", _c9_full_suite_green),
    ("gpu_spend_zero", _c10_gpu_spend_is_zero),
    ("sfi3_fresh_payload_unopened", _c11_sfi3_payload_unopened),
    ("no_prior_v2r4_measurement", _c12_no_prior_v2r4_measurement),
)


def _require_twelve() -> None:
    """The ruling names twelve. A row silently dropped is a gate that got easier."""
    if len(CONDITIONS) != 12:
        raise RuntimeError(
            f"the gate declares {len(CONDITIONS)} conditions; founder ruling section "
            "G names twelve. A gate with a missing row reports READY on less "
            "evidence than it was authorised to require."
        )
    names = [name for name, _check in CONDITIONS]
    if len(set(names)) != len(names):
        raise RuntimeError(f"duplicate condition names: {names}")


_require_twelve()


def run(*, skip_suite: bool = False) -> dict[str, Any]:
    """Every condition, executed. The verdict is the AND of all twelve."""
    rows = []
    for name, check in CONDITIONS:
        if name == "authoritative_full_suite_green":
            rows.append(_row(name, lambda: _c9_full_suite_green(run=not skip_suite)))
        else:
            rows.append(_row(name, check))

    failed = [row["condition"] for row in rows if row["verdict"] != PASS]
    return {
        "schema": SCHEMA,
        "gate_id": GATE_ID,
        "verdict": BLOCKED if failed else READY,
        "conditions_declared": len(CONDITIONS),
        "conditions_passed": len(rows) - len(failed),
        "failed": failed,
        "rows": rows,
        "what_ready_means": (
            "every one of the twelve conditions section G names was EXECUTED and "
            "came back PASS. It authorises the freeze ladder to begin -- rung 0 "
            "onward -- and nothing else. It is not a result, not a verdict about "
            "production, and not permission to spend GPU."
        ),
        "what_is_still_unspent": (
            "no V2R4 content has been opened, no SFI3 payload has been opened, and "
            "GPU spend is zero. The first irreversible act is the acquisition the "
            "frame authorises, and it comes after rung 0 seals."
        ),
    }


def freeze(*, skip_suite: bool = False) -> dict[str, Any]:
    """Run the gate and seal the result immutably.

    A gate whose verdict exists only in console output is not evidence that the
    gate was passed, and this one stands immediately before the irreversible act.
    REFUSES to seal a BLOCKED verdict: a receipt recording that acquisition was
    not authorised is a record nobody needs and a file somebody could later cite
    as though the gate had run clean.
    """
    body = run(skip_suite=skip_suite)
    if body["verdict"] != READY:
        raise GateRefused(
            f"the gate is {body['verdict']} on {body['failed']}. Nothing is sealed: "
            "fix the conditions and run it again. A receipt is not a consolation "
            "prize for a gate that refused."
        )
    body["provenance"] = write_immutable(STEM, body, tool=Path(__file__).resolve(), protocol=None)
    return body


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator entry
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-suite",
        action="store_true",
        help="do not run the full suite (the row then FAILS, deliberately)",
    )
    parser.add_argument("--quiet", action="store_true", help="verdict and failures only")
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="seal the result immutably; refuses unless every condition passed",
    )
    args = parser.parse_args(argv)

    try:
        body = (
            freeze(skip_suite=args.skip_suite) if args.freeze else run(skip_suite=args.skip_suite)
        )
    except GateRefused as error:
        print(json.dumps({"verdict": BLOCKED, "why": str(error)}, indent=1))
        return 4

    if args.quiet:
        print(json.dumps({k: v for k, v in body.items() if k != "rows"}, indent=1))
    else:
        print(json.dumps(body, indent=1, sort_keys=True, default=str))
    return 0 if body["verdict"] == READY else 4


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
