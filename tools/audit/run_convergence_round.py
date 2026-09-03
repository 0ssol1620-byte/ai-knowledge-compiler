#!/usr/bin/env python3
"""Execute one round of the frozen convergence protocol and record it.

`docs/audit/CONVERGENCE_PROTOCOL_2026-08-19.md` defines a round as one execution
of every pass, and fixes the stop rule in advance. This runs the automated passes,
collects each one's findings and — critically — each one's positive control, and
writes a round receipt.

**It does not declare convergence.** The stop rule needs two consecutive clean
rounds with every prior finding closed, and this tool reports the round number and
what is still outstanding. Deciding that a round "was probably enough" is the
retrospective-criterion defect the protocol exists to prevent, so the decision is
not delegated to the thing that runs the rounds.

**A pass whose control did not separate is recorded as NOT RUN, never as clean.**
A detector that cannot fire reports the same zero as a clean corpus, and this
programme has already voided one experiment and shipped three defective detectors
on exactly that confusion.

Pass A is a human read and cannot be automated; it is recorded as such, with the
round's human findings supplied by `--human-findings`.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROUNDS = ROOT / "docs" / "audit" / "convergence-rounds"
PROTOCOL = ROOT / "docs" / "audit" / "CONVERGENCE_PROTOCOL_2026-08-19.md"
BOUNDS = ROOT / "docs" / "audit" / "STANDING_BOUNDS.yaml"

#: Amendment 2. All six must be attested for a finding kind to be a declared
#: standing bound; anything undeclared, or declared with a condition missing, is
#: OPEN_ACTIONABLE and blocks convergence exactly as before.
REQUIRED_CONDITIONS = (
    "historically_unrecoverable_mechanically_established",
    "limitation_publicly_recorded",
    "hash_chain_prevents_recurrence",
    "no_current_claim_or_evidence_contradiction",
    "remains_visible_every_round",
    "never_counted_as_fixed",
)

#: pass id -> (label, script, receipt, findings key, control predicate path)
PASSES: dict[str, dict[str, Any]] = {
    "B": {
        "label": "numeric binding",
        "script": "tools/ip/audit_manuscript_numbers.py",
        "receipt": "docs/ip/receipts/manuscript-number-audit-2026-08-19.json",
        "findings_key": "findings",
        "control_key": None,
        "control_note": (
            "no synthetic control; its separating power is that it has fired on a stale "
            "count four times in live use, and it fails on a stale manifest"
        ),
    },
    "C": {
        "label": "register / inference",
        "script": "tools/ip/audit_inference_vs_measurement.py",
        "receipt": "docs/ip/receipts/inference-vs-measurement-audit-2026-08-19.json",
        "findings_key": "findings",
        "control_key": "detector_is_live",
    },
    "DE": {
        "label": "withdrawn terms + status vocabulary (shared tool, disclosed)",
        "script": "tools/ip/audit_cross_document_consistency.py",
        "receipt": "docs/ip/receipts/cross-document-consistency-2026-08-19.json",
        "findings_key": None,
        "findings_keys": [
            "forbidden_wording_leakage",
            "withdrawn_term_leakage",
            "status_vocabulary_conflicts",
            "missing_evidence_paths",
        ],
        "control_key": "withdrawn_term_detector_control.separates",
    },
    "G": {
        "label": "claim amendment direction",
        "script": "tools/ip/audit_claim_amendments.py",
        "receipt": "docs/ip/receipts/claim-amendment-direction-2026-08-19.json",
        "findings_key": "findings",
        "control_key": "detector_is_live",
    },
    "H": {
        "label": "figure and caption boundary",
        "script": "tools/ip/audit_figure_captions.py",
        "receipt": "docs/ip/receipts/figure-caption-audit-2026-08-19.json",
        "findings_key": "findings",
        "control_key": "detector_is_live",
    },
    "I": {
        "label": "assertion status vs surfaces (structural)",
        "script": "tools/ip/audit_assertion_registry.py",
        "receipt": "docs/ip/receipts/assertion-registry-audit-2026-08-19.json",
        "findings_key": "findings",
        "control_key": "detector_is_live",
        "note": (
            "added 2026-08-19 by protocol amendment 1. Distinct from pass DE: DE asks "
            "whether a withdrawn word survived, I asks whether a surface still asserts a "
            "narrowed or withdrawn proposition and whether an active assertion is still "
            "where it is relied on. DE was clean on all five surfaces while I found six "
            "leaks, which is the evidence that they are not the same detector."
        ),
    },
    "J": {
        "label": "amendment register completeness",
        "script": "tools/ip/audit_amendment_coverage.py",
        "receipt": "docs/ip/receipts/amendment-coverage-2026-08-19.json",
        "findings_key": "findings",
        "control_key": "detector_is_live",
        "note": (
            "added 2026-08-19 by protocol amendment 1, alongside pass I. Distinct from "
            "pass G: G checks that a registered amendment's direction matches its "
            "operation, J checks whether the register accounts for the claim inventory at "
            "all. G was clean over seven amendments while one of them named a claim that "
            "does not exist."
        ),
    },
    "K": {
        "label": "element-level evidence support",
        "script": "tools/ip/build_element_support_matrix.py",
        "receipt": "docs/ip/receipts/element-support-matrix-2026-08-19.json",
        "findings_key": "findings",
        "control_key": "detector_is_live",
        "note": (
            "added 2026-08-19 by protocol amendment 1, alongside I and J. Distinct from "
            "every other pass: they compare documents to each other or to a register, "
            "this one compares a claim's limitations to the evidence named for them."
        ),
    },
    "F": {
        "label": "test scope, interpreter and build status",
        "script": None,  # expensive; read the receipt the venv run produced
        "receipt": "docs/repro/TEST_SCOPE_STATUS.json",
        "findings_key": None,
        "control_key": "guard_is_live",
        "extra_gate": "repository_green",
        "note": (
            "not re-run here: the full scope takes ~12 minutes and must run under the "
            "project interpreter. The receipt records which interpreter produced it."
        ),
    },
}


def load_bounds() -> dict[str, dict[str, Any]]:
    """Finding kind -> the declaration that admits it, only if fully attested."""
    if not BOUNDS.exists():
        return {}
    doc = yaml.safe_load(BOUNDS.read_text(encoding="utf-8")) or {}
    admitted: dict[str, dict[str, Any]] = {}
    for entry in doc.get("standing_bounds") or []:
        conditions = entry.get("conditions") or {}
        missing = [c for c in REQUIRED_CONDITIONS
                   if not (conditions.get(c) or {}).get("attested_by")]
        if missing:
            # A declaration with a hole is not a bound. Reporting it as one would
            # let an unattested claim retire a blocking finding, which is the
            # abuse this whole mechanism has to be proof against.
            entry = {**entry, "admitted": False, "missing_conditions": missing}
        else:
            entry = {**entry, "admitted": True, "missing_conditions": []}
        admitted[entry.get("matches_finding_kind")] = entry
    return admitted


#: Amendment 3, 2026-08-20. A third outcome, narrower than a standing bound.
#:
#: A standing bound is a *permanently unrepairable* limitation. The four element
#: findings on reserved dependent claims are not that: each would close if
#: someone ran a measurement. Declaring them bounds would abuse the mechanism.
#: But they are also not work an agent left undone -- the claim set holds those
#: claims out of the filing core by a recorded decision, and the element matrix
#: stamps each finding `DISCLOSED_RESERVED_NOT_IN_FILING_CORE`.
#:
#: So they are deferred, and the deferral is checkable rather than asserted: the
#: finding must carry `reserved: true` AND that severity. A finding that carries
#: neither, or only one, stays open.
DEFERRED_SEVERITY = "DISCLOSED_RESERVED_NOT_IN_FILING_CORE"


def is_deferred(f: Any) -> bool:
    return (
        isinstance(f, dict)
        and f.get("severity") == DEFERRED_SEVERITY
        and f.get("reserved") is True
    )


def classify_findings(
    findings: list[Any], bounds: dict[str, dict[str, Any]]
) -> tuple[list[Any], list[Any], list[dict[str, Any]], list[Any]]:
    """Split findings into open-actionable, standing bounds and deferred.

    Default is OPEN_ACTIONABLE. A finding becomes a bound only by matching a
    declaration that carries all six attestations -- never by being old,
    familiar, or inconvenient. It becomes deferred only by carrying both the
    reserved flag and the reserved severity its generator stamps.
    """
    open_actionable, standing, rejected, deferred = [], [], [], []
    for f in findings:
        kind = f.get("kind") if isinstance(f, dict) else None
        entry = bounds.get(kind)
        if entry and entry.get("admitted"):
            standing.append(f)
        elif is_deferred(f):
            deferred.append(f)
        else:
            open_actionable.append(f)
            if entry and not entry.get("admitted"):
                rejected.append({"kind": kind, "id": entry.get("id"),
                                 "missing_conditions": entry.get("missing_conditions"),
                                 "why": "declared but not fully attested; treated as open"})
    return open_actionable, standing, rejected, deferred


def bounds_control(bounds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The mechanism must refuse an undeclared kind and an unattested declaration.

    Without this, "0 open actionable findings" reads the same whether the
    classifier is discriminating or waving everything through -- and the whole
    point of amendment 2 is that it must not become a way to retire findings.
    """
    undeclared = [{"kind": "SYNTHETIC_UNDECLARED_FINDING"}]
    open_a, standing_a, _, _ = classify_findings(undeclared, bounds)

    holed = dict(bounds)
    probe_kind = "SYNTHETIC_HOLED_DECLARATION"
    holed[probe_kind] = {
        "id": "SB-CONTROL-PROBE", "matches_finding_kind": probe_kind,
        "admitted": False, "missing_conditions": ["hash_chain_prevents_recurrence"],
    }
    open_b, standing_b, rejected_b, _ = classify_findings([{"kind": probe_kind}], holed)

    declared = [k for k, v in bounds.items() if v.get("admitted")]
    open_c, standing_c, _, _ = classify_findings(
        [{"kind": declared[0]}] if declared else [], bounds)

    # Amendment 3's own control: the deferral must refuse a finding carrying only
    # one of the two markers, in both directions, and admit only the pair.
    sev_only = [{"kind": "X", "severity": DEFERRED_SEVERITY}]
    flag_only = [{"kind": "X", "reserved": True}]
    both = [{"kind": "X", "severity": DEFERRED_SEVERITY, "reserved": True}]
    open_d, _, _, def_d = classify_findings(sev_only, bounds)
    open_e, _, _, def_e = classify_findings(flag_only, bounds)
    open_f, _, _, def_f = classify_findings(both, bounds)
    deferral = {
        "severity_without_reserved_flag_stays_open": len(open_d) == 1 and not def_d,
        "reserved_flag_without_severity_stays_open": len(open_e) == 1 and not def_e,
        "both_markers_defer": len(def_f) == 1 and not open_f,
    }
    deferral["separates"] = all(deferral.values())

    return {
        "separates": (
            len(open_a) == 1 and not standing_a
            and len(open_b) == 1 and not standing_b and len(rejected_b) == 1
            and (not declared or (len(standing_c) == 1 and not open_c))
            and deferral["separates"]
        ),
        "deferral_control": deferral,
        "undeclared_kind_stays_open": len(open_a) == 1 and not standing_a,
        "declaration_missing_a_condition_stays_open": (
            len(open_b) == 1 and not standing_b and len(rejected_b) == 1),
        "fully_attested_declaration_becomes_bound": (
            bool(declared) and len(standing_c) == 1 and not open_c),
        "admitted_declarations": declared,
        "what_it_proves": (
            "the classifier defaults to OPEN_ACTIONABLE, refuses a declaration missing any "
            "of the six attestations, and admits only a fully attested one"
        ),
        "what_it_does_not_prove": (
            "nothing about whether an attestation is true. Each is a written claim about "
            "the world, and condition 1 in particular rests on a command someone has to "
            "run -- the mechanism checks that it was asserted, not that it holds."
        ),
    }


def dig(doc: Any, dotted: str) -> Any:
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def run_pass(pid: str, spec: dict[str, Any], rerun: bool,
             bounds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ran = False
    if rerun and spec.get("script"):
        subprocess.run(  # noqa: S603
            [sys.executable, spec["script"]],
            cwd=ROOT, capture_output=True, text=True,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        ran = True
    receipt_path = ROOT / spec["receipt"]
    if not receipt_path.exists():
        return {"pass": pid, "label": spec["label"], "state": "NOT_RUN",
                "why": f"receipt missing: {spec['receipt']}"}
    doc = json.loads(receipt_path.read_text(encoding="utf-8"))

    if spec.get("findings_keys"):
        findings = []
        for key in spec["findings_keys"]:
            findings += doc.get(key) or []
    elif spec.get("findings_key"):
        findings = doc.get(spec["findings_key"]) or []
    else:
        findings = []

    control_key = spec.get("control_key")
    control = dig(doc, control_key) if control_key else None
    control_ok = bool(control) if control_key else None

    extra_gate = spec.get("extra_gate")
    extra_ok = doc.get(extra_gate) if extra_gate else None

    open_actionable, standing, rejected, deferred = classify_findings(findings, bounds)

    if control_key and not control_ok:
        state = "NOT_RUN"
        why = "positive control did not separate; a pass that cannot fire is not clean"
    elif extra_gate and not extra_ok:
        state = "FINDINGS"
        why = f"{extra_gate} is not true"
    elif open_actionable:
        state = "FINDINGS"
        why = f"{len(open_actionable)} open actionable finding(s)"
    elif standing or deferred:
        # Amendment 2: a pass carrying only declared standing bounds is clean for
        # the stop rule and still prints its bounds. Amendment 3 extends that to
        # findings deferred by a recorded decision. Neither is removed and neither
        # is counted as fixed.
        state = "CLEAN_WITH_STANDING_BOUNDS"
        parts = []
        if standing:
            parts.append(f"{len(standing)} declared standing bound(s)")
        if deferred:
            parts.append(f"{len(deferred)} finding(s) deferred by recorded decision")
        why = "0 open actionable; " + " and ".join(parts) + " remain"
    else:
        state = "CLEAN"
        why = "no findings, control separated" if control_key else "no findings"

    return {
        "pass": pid, "label": spec["label"], "state": state, "why": why,
        "rerun_this_round": ran, "receipt": spec["receipt"],
        "finding_count": len(findings),
        "open_actionable_count": len(open_actionable),
        "standing_bound_count": len(standing),
        "standing_bounds": standing[:20],
        "deferred_count": len(deferred),
        "deferred": deferred[:20],
        "declarations_rejected_as_unattested": rejected,
        "findings": open_actionable[:20],
        "control_key": control_key, "control_separated": control_ok,
        "control_note": spec.get("control_note"), "note": spec.get("note"),
        "extra_gate": extra_gate, "extra_gate_value": extra_ok,
    }


def prior_rounds() -> list[dict[str, Any]]:
    """Every recorded round, with invalidated ones marked rather than removed.

    A round whose inputs turn out to have been wrong is invalidated by an
    `INVALIDATION-round-NN.json` beside it. The round file itself is never edited
    or deleted -- the same rule that governs experiment receipts -- but an
    invalidated round does not count toward the consecutive-clean requirement.
    """
    if not ROUNDS.is_dir():
        return []
    out = []
    for path in sorted(ROUNDS.glob("round-*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        inval = path.with_name(f"INVALIDATION-{path.name}")
        if inval.exists():
            rec = dict(rec)
            rec["invalidated"] = True
            rec["clean_round"] = False
            with contextlib.suppress(json.JSONDecodeError):
                rec["invalidation"] = json.loads(inval.read_text(encoding="utf-8"))
        out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", action="store_true", help="re-execute each automated pass")
    ap.add_argument("--human-findings", type=int, default=None,
                    help="pass A: number of findings from the human read this round")
    ap.add_argument("--dry-run", action="store_true",
                    help="report without recording a round -- for verifying the runner "
                         "itself, which must never create a round record")
    args = ap.parse_args()

    prior = prior_rounds()
    number = len(prior) + 1

    bounds = load_bounds()
    control = bounds_control(bounds)
    results = [run_pass(pid, spec, args.rerun, bounds) for pid, spec in PASSES.items()]
    results.append({
        "pass": "A", "label": "registry <-> document semantics (human read)",
        "state": "CLEAN" if args.human_findings == 0 else (
            "FINDINGS" if args.human_findings else "NOT_RUN"),
        "why": ("human read recorded" if args.human_findings is not None
                else "no human read recorded for this round"),
        "finding_count": args.human_findings,
        "control_key": None, "control_separated": None,
        "note": "cannot be automated; the automated passes narrow the manual surface only",
    })

    not_run = [r for r in results if r["state"] == "NOT_RUN"]
    with_findings = [r for r in results if r["state"] == "FINDINGS"]
    standing_total = sum(r.get("standing_bound_count") or 0 for r in results)
    # Amendment 2 stop rule: open actionable findings block, declared standing
    # bounds do not -- and a control that cannot separate blocks either way, so a
    # broken bounds mechanism cannot quietly clear a round.
    clean_round = not not_run and not with_findings and control["separates"]

    # Amendment 3. Pass A is a human read and cannot be performed by this tool or
    # by any agent. Reporting the whole round as unconverged because a person has
    # not read it yet conflates two different states: work an agent still owes,
    # and work only a person can do. Both are reported, separately, and the
    # agent-side figure is never called convergence.
    agent_passes = [r for r in results if r["pass"] != "A"]
    agent_not_run = [r for r in agent_passes if r["state"] == "NOT_RUN"]
    agent_with_findings = [r for r in agent_passes if r["state"] == "FINDINGS"]
    agent_convergence_complete = (
        not agent_not_run and not agent_with_findings and control["separates"]
    )
    pass_a = next(r for r in results if r["pass"] == "A")
    pass_a_state = ("EXTERNAL_HUMAN_REVIEW_REQUIRED" if pass_a["state"] == "NOT_RUN"
                    else pass_a["state"])

    consecutive_clean = 0
    for rec in [*prior, {"clean_round": clean_round}][::-1]:
        if rec.get("clean_round"):
            consecutive_clean += 1
        else:
            break

    receipt: dict[str, Any] = {
        "schema": "tavonel.convergence-round.v1",
        "round": number,
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "docs/audit/CONVERGENCE_PROTOCOL_2026-08-19.md",
        "protocol_sha256": "sha256:" + hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "passes": results,
        "passes_not_run": [r["pass"] for r in not_run],
        "passes_with_findings": [r["pass"] for r in with_findings],
        "open_actionable_findings": sum(r.get("open_actionable_count") or 0 for r in results),
        "declared_standing_bounds": standing_total,
        "standing_bounds_registry": "docs/audit/STANDING_BOUNDS.yaml",
        "standing_bounds_control": control,
        "standing_bounds_note": (
            "A declared standing bound is a permanently unrepairable limitation. It is "
            "never deleted, never downgraded, never counted as fixed, and prints in every "
            "round. It does not block the stop rule; everything else does."
        ),
        "clean_round": clean_round,
        "agent_convergence_complete": agent_convergence_complete,
        "agent_passes_not_run": [r["pass"] for r in agent_not_run],
        "agent_passes_with_findings": [r["pass"] for r in agent_with_findings],
        "pass_a_state": pass_a_state,
        "agent_convergence_note": (
            "`agent_convergence_complete` covers passes B-K only. It is NOT convergence "
            "and must never be reported as 'human convergence complete' or as the protocol's "
            "stop rule being met. Pass A is a human read against the claim-evidence registry; "
            "while it reads EXTERNAL_HUMAN_REVIEW_REQUIRED, `clean_round` stays false and no "
            "round counts toward the two-consecutive-clean requirement."
        ),
        "consecutive_clean_rounds_including_this": consecutive_clean if clean_round else 0,
        "convergence_declared": False,
        "why_convergence_is_not_declared": (
            "The stop rule requires two consecutive clean rounds under this protocol, with "
            "every open actionable finding from the preceding round closed. Declared "
            "standing bounds remain outstanding and are printed rather than cleared. This "
            "tool reports rounds; it does not decide that a round was enough. Round "
            f"{number} of a minimum of 2, with {consecutive_clean if clean_round else 0} "
            "consecutive clean."
        ),
        "standing_prohibition": (
            "A pass whose control did not separate is NOT_RUN, never clean. Narrowing a "
            "pass, widening an exemption, or downgrading a finding after seeing it "
            "invalidates the round."
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()

    out = ROUNDS / f"round-{number:02d}.json"
    if not args.dry_run:
        ROUNDS.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"convergence round {number}")
    for r in results:
        ctl = "" if r["control_separated"] is None else f" control={r['control_separated']}"
        print(f"  {r['pass']:<3} {r['state']:<9} {r['label'][:48]:<50}{ctl}  -- {r['why']}")
    print(f"standing bounds control separates: {control['separates']}")
    if standing_total:
        print(f"declared standing bounds (do not block, never counted as fixed): "
              f"{standing_total}")
        for r in results:
            for b in r.get("standing_bounds") or []:
                print(f"    [{r['pass']}] {b.get('kind')}: {b.get('claim') or b.get('id') or ''}")
    print(f"clean round: {clean_round}")
    print(f"consecutive clean: {receipt['consecutive_clean_rounds_including_this']} of 2 required")
    print(f"convergence declared: {receipt['convergence_declared']}")
    print(f"wrote {out}" if not args.dry_run else "dry run -- no round recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
