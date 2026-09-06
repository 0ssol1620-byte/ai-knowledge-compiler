#!/usr/bin/env python3
"""H1-J -- per-filter governance ablation.

Protocol: ../PROTOCOL_2026-08-19.md, frozen before this ran (sha256 pinned in
the receipt).

`akc_cir.authority` is Protected Core and is **not modified**. The resolver is
reimplemented here with one toggle per filter, guarded by the same fidelity gate
H1-I used: with every filter enabled the harness must reproduce the real
`resolve_authority` -- status, winning claim id and required_review -- on every
frozen state, or no ablation result is reported at all.

The design point that makes this more than a pass/fail count is in protocol §3.
R1/R2/R3 restate F1/F2/F3, so disabling an admissibility filter usually changes
nothing: the offending claim is admitted but ranks below any compliant claim.
That null means "redundant here", not "unnecessary". Every filter is therefore
run against a `paired` state (a compliant alternative exists, redundancy can
mask) and a `solitary` state (it does not, the mask is broken).
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
AUTH = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "authority.py"
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.authority import (  # noqa: E402
    AuthorityClass,
    ClaimContext,
    ResolutionRule,
    ResolutionStatus,
    RuleOutcome,
    ScopedClaim,
    SourceStatus,
    resolve_authority,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = T0 + timedelta(days=180)

#: Every toggle this harness understands. Disabling one must change exactly one
#: mechanism; §7's no-op control is what tests that claim.
FILTERS = ("F1", "F2", "F3", "F4", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "G1")


def claim(
    cid: str,
    value: str,
    authority: AuthorityClass = AuthorityClass.OFFICIAL,
    *,
    scope: dict[str, str] | None = None,
    permission: str | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    status: SourceStatus = SourceStatus.ACTIVE,
    recorded: datetime | None = None,
    evidence: str | None = "ev-1",
) -> ScopedClaim:
    return ScopedClaim(
        claim_id=cid,
        subject="warranty_term",
        value=value,
        authority=authority,
        source_status=status,
        scope=scope or {},
        valid_from=valid_from,
        valid_to=valid_to,
        recorded_at=recorded or T0,
        required_permission=permission,
        evidence_id=evidence,
    )


def context(**kw) -> ClaimContext:
    base = dict(subject="warranty_term", as_of=NOW, customer_id="cust_a")
    base.update(kw)
    return ClaimContext(**base)


# --- the ablatable resolver -------------------------------------------------


def rank_claims_ablated(claims, ctx, rules, off: frozenset[str]):
    applicable = []
    for c in claims:
        if "F1" not in off and not c.visible_to(ctx):
            continue
        if "F2" not in off and not c.temporally_valid(ctx.as_of):
            continue
        if "F3" not in off and c.scope_match(ctx) < 0:
            continue
        applicable.append(c)

    rule_list = list(rules)
    scored = []
    for c in applicable:
        override = 0
        for rule in rule_list:
            if not rule.applies_to(c, ctx):
                continue
            if rule.outcome is RuleOutcome.EXCLUDE:
                override = -1
                break
            override = max(override, rule.precedence)
        if override < 0 and "F4" not in off:
            continue
        if override < 0:
            override = 0
        scored.append((rank_tuple_ablated(c, ctx, override, off), c))

    scored.sort(key=lambda pair: (pair[0], pair[1].claim_id), reverse=True)
    return scored


def rank_tuple_ablated(c, ctx, override: int, off: frozenset[str]) -> tuple[int, ...]:
    """Same eight positions; a disabled element is pinned to a constant.

    Pinning to a constant rather than dropping the position keeps the tuple
    length fixed, so a disabled element cannot silently promote every later
    element one place -- which would ablate two things at once.
    """
    return (
        0 if "R1" in off else (1 if c.visible_to(ctx) else 0),
        0 if "R2" in off else (1 if c.temporally_valid(ctx.as_of) else 0),
        0 if "R3" in off else c.scope_match(ctx),
        0 if "R4" in off else override,
        0 if "R5" in off else int(c.authority),
        0 if "R6" in off else c.specificity,
        0 if "R7" in off else int(c.source_status),
        0
        if "R8" in off
        else (int(c.recorded_at.timestamp()) if c.recorded_at else 0),
    )


def resolve_ablated(claims, ctx, rules=(), off: frozenset[str] = frozenset()):
    hidden = sum(1 for c in claims if not c.visible_to(ctx))
    ranked = rank_claims_ablated(claims, ctx, rules, off)
    if not ranked:
        return {
            "status": ResolutionStatus.NO_CANDIDATE.value,
            "claim_id": None,
            "value": None,
            "required_review": False,
            "permission_filtered": hidden,
        }
    best_tuple, best = ranked[0]
    tied = [c for tup, c in ranked if tup == best_tuple]
    if "G1" not in off and len({c.value for c in tied}) > 1:
        return {
            "status": ResolutionStatus.CONFLICTED.value,
            "claim_id": None,
            "value": None,
            "required_review": True,
            "permission_filtered": hidden,
        }
    return {
        "status": ResolutionStatus.RESOLVED.value,
        "claim_id": best.claim_id,
        "value": best.value,
        "required_review": False,
        "permission_filtered": hidden,
    }


def real(claims, ctx, rules=()) -> dict[str, Any]:
    r = resolve_authority(claims, ctx, rules=rules)
    return {
        "status": r.status.value,
        "claim_id": r.claim.claim_id if r.claim else None,
        "value": r.claim.value if r.claim else None,
        "required_review": r.required_review,
        "permission_filtered": r.permission_filtered,
    }


# --- frozen states (protocol §3, §4, §7) ------------------------------------

EXCLUDE_RULE = ResolutionRule(
    rule_id="rule-exclude-legacy",
    subject_type="warranty_term",
    when=lambda c, ctx: c.claim_id == "violating",
    outcome=RuleOutcome.EXCLUDE,
)
PREFER_RULE = ResolutionRule(
    rule_id="rule-prefer-marked",
    subject_type="warranty_term",
    when=lambda c, ctx: c.claim_id == "compliant",
    precedence=5,
    outcome=RuleOutcome.PREFER,
)

COMPLIANT = claim("compliant", "24 months", AuthorityClass.OFFICIAL)


def states() -> list[dict[str, Any]]:
    """Each filter gets a paired and a solitary state (protocol §3)."""
    out: list[dict[str, Any]] = []

    def add(fid, kind, violating, ctx, rules=(), expect=""):
        claims = [violating] if kind == "solitary" else [violating, COMPLIANT]
        out.append(
            {
                "filter": fid,
                "kind": kind,
                "claims": claims,
                "context": ctx,
                "rules": rules,
                "violation": expect,
            }
        )

    leak = claim("violating", "6 months", AuthorityClass.REGULATORY, permission="hr:read")
    for kind in ("paired", "solitary"):
        add("F1", kind, leak, context(), (), "cross-permission leak")
        add("R1", kind, leak, context(), (), "cross-permission leak")

    expired = claim(
        "violating", "6 months", AuthorityClass.REGULATORY,
        valid_from=T0 - timedelta(days=400), valid_to=T0 - timedelta(days=10),
    )
    for kind in ("paired", "solitary"):
        add("F2", kind, expired, context(), (), "temporally invalid claim answers as-of")
        add("R2", kind, expired, context(), (), "temporally invalid claim answers as-of")

    wrong_scope = claim(
        "violating", "6 months", AuthorityClass.REGULATORY, scope={"customer_id": "cust_b"}
    )
    for kind in ("paired", "solitary"):
        add("F3", kind, wrong_scope, context(), (), "wrong-scope answer")
        add("R3", kind, wrong_scope, context(), (), "wrong-scope answer")

    excluded = claim("violating", "6 months", AuthorityClass.REGULATORY)
    for kind in ("paired", "solitary"):
        add("F4", kind, excluded, context(), (EXCLUDE_RULE,), "excluded claim used")

    # R4: the override element must lift a lower-authority preferred claim.
    out.append(
        {
            "filter": "R4",
            "kind": "paired",
            "claims": [
                claim("violating", "6 months", AuthorityClass.REGULATORY),
                claim("compliant", "24 months", AuthorityClass.INFORMAL),
            ],
            "context": context(),
            "rules": (PREFER_RULE,),
            "violation": "explicit override ignored",
        }
    )
    out.append(
        {
            "filter": "R5", "kind": "paired",
            "claims": [
                claim("violating", "6 months", AuthorityClass.DRAFT),
                claim("compliant", "24 months", AuthorityClass.REGULATORY),
            ],
            "context": context(), "rules": (),
            "violation": "lower authority outranks higher",
        }
    )
    out.append(
        {
            "filter": "R6", "kind": "paired",
            "claims": [
                claim("violating", "6 months", AuthorityClass.OFFICIAL),
                claim("compliant", "24 months", AuthorityClass.OFFICIAL,
                      scope={"customer_id": "cust_a"}),
            ],
            "context": context(), "rules": (),
            "violation": "less specific beats more specific",
        }
    )
    out.append(
        {
            "filter": "R7", "kind": "paired",
            "claims": [
                claim("violating", "6 months", AuthorityClass.OFFICIAL,
                      status=SourceStatus.WITHDRAWN),
                claim("compliant", "24 months", AuthorityClass.OFFICIAL,
                      status=SourceStatus.ACTIVE),
            ],
            "context": context(), "rules": (),
            "violation": "withdrawn source beats active",
        }
    )
    out.append(
        {
            "filter": "R8", "kind": "paired",
            "claims": [
                claim("violating", "6 months", AuthorityClass.OFFICIAL,
                      recorded=T0 - timedelta(days=300)),
                claim("compliant", "24 months", AuthorityClass.OFFICIAL,
                      recorded=T0),
            ],
            "context": context(), "rules": (),
            "violation": "staler claim beats newer",
        }
    )
    out.append(
        {
            "filter": "G1", "kind": "paired",
            "claims": [
                claim("tie_a", "6 months", AuthorityClass.OFFICIAL),
                claim("tie_b", "24 months", AuthorityClass.OFFICIAL),
            ],
            "context": context(), "rules": (),
            "violation": "unresolvable conflict silently resolved",
        }
    )
    return out


#: Protocol §7. No filter should change this: one claim, compliant on every
#: dimension, nothing to filter and nothing to rank against.
NOOP_STATE = {
    "claims": [COMPLIANT],
    "context": context(),
    "rules": (),
}


def sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def classify(baseline: dict, ablated: dict, kind: str, all_states) -> tuple[str, str]:
    """Protocol §5. Returns (class, rationale)."""
    verdict_changed = (
        baseline["status"] != ablated["status"]
        or baseline["claim_id"] != ablated["claim_id"]
    )
    diagnostic_changed = (
        baseline["required_review"] != ablated["required_review"]
        or baseline["permission_filtered"] != ablated["permission_filtered"]
    )
    if verdict_changed:
        return "A", "removal changed the resolved answer; the violation is admitted"
    if diagnostic_changed:
        return "C", "verdict unchanged but the resolution's diagnosis changed"
    if kind == "solitary":
        return (
            "U",
            "no change even with no compliant alternative present, so no other "
            "filter can be the blocker; this is not class B and is reported as U",
        )
    return (
        "B_pending_blocker",
        "no change in the paired state; the redundant blocker must be named by "
        "the solitary run before this may be called B",
    )


def structural_analysis() -> dict[str, Any]:
    """AMENDMENT 1 -- why four ranking elements could not be ablated alone.

    R1/R2/R3 and R6 returned no separation. Protocol §6 says an unseparating
    control makes that filter's null uncitable, so the honest options are to
    report them as unmeasured or to explain the non-separation structurally.
    Both are done: the verdicts stay UNRESOLVED, and the reason is recorded with
    a mechanical proof where one exists.
    """
    ctx = context(region="r1", contract_id="c1", object_id="o1")
    rows = []
    for n, scope in enumerate(
        [{}, {"customer_id": "cust_a"},
         {"customer_id": "cust_a", "region": "r1"},
         {"customer_id": "cust_a", "region": "r1", "contract_id": "c1"}]
    ):
        c = claim(f"probe{n}", "v", scope=dict(scope))
        rows.append(
            {
                "scope_dimensions": len(scope),
                "scope_match": c.scope_match(ctx),
                "specificity": c.specificity,
                "equal": c.scope_match(ctx) == c.specificity,
            }
        )
    mismatched = claim("probe_bad", "v", scope={"customer_id": "cust_b"})
    return {
        "R1_R2_R3_non_separation": (
            "Ranking elements 1-3 restate admissibility filters F1-F3. With F1-F3 "
            "enabled the offending claim is already removed, so there is nothing "
            "for the ranking element to order and disabling it changes nothing. "
            "Ablating R1 meaningfully would require disabling F1 at the same "
            "time, which ablates two mechanisms at once and measures neither. "
            "These three are therefore UNMEASURED by this instrument, not shown "
            "to be inert."
        ),
        "R6_is_provably_redundant_with_R3": {
            "proof": (
                "scope_match returns -1 on any dimension mismatch, otherwise it "
                "returns the count of matched dimensions, which is len(scope). "
                "specificity is defined as len(scope). Therefore for every claim "
                "admissible under F3 (scope_match >= 0), ranking element 3 and "
                "ranking element 6 carry the SAME VALUE. They can differ only "
                "when scope_match is -1, which F3 already disqualifies."
            ),
            "probes": rows,
            "all_equal_for_admissible_claims": all(r["equal"] for r in rows),
            "differ_only_when_disqualified": {
                "scope_match": mismatched.scope_match(ctx),
                "specificity": mismatched.specificity,
                "admissible": mismatched.scope_match(ctx) >= 0,
            },
            "claim_consequence": (
                "The claim may not recite specificity as an independent ranking "
                "element contributing information beyond scope match. It is dead "
                "weight in the tuple for every claim that reaches it."
            ),
        },
    }


def main() -> int:
    exp = Path(__file__).resolve().parents[1]
    out = exp / "receipts" / "governance-filter-ablation-2026-08-19.json"
    all_states = states()

    # --- fidelity gate ---
    fidelity_rows = []
    for st in [*all_states, dict(NOOP_STATE, filter="NOOP", kind="control")]:
        r = real(st["claims"], st["context"], st.get("rules", ()))
        h = resolve_ablated(st["claims"], st["context"], st.get("rules", ()), frozenset())
        agrees = (
            r["status"] == h["status"]
            and r["claim_id"] == h["claim_id"]
            and r["required_review"] == h["required_review"]
        )
        fidelity_rows.append(
            {
                "filter": st.get("filter"), "kind": st.get("kind"),
                "real": r, "harness_all_enabled": h, "agrees": agrees,
            }
        )
    fidelity = {"rows": fidelity_rows, "all_agree": all(r["agrees"] for r in fidelity_rows)}

    receipt: dict[str, Any] = {
        "schema": "tavonel.governance-filter-ablation.v1",
        "experiment": "H1-J-GOVERNANCE-FILTER-ABLATION-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": sha256_file(exp / "PROTOCOL_2026-08-19.md"),
        "authority_module_sha256": sha256_file(AUTH),
        "fidelity_gate": fidelity,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    out.parent.mkdir(parents=True, exist_ok=True)

    if not fidelity["all_agree"]:
        receipt["result"] = "VOID_FIDELITY_GATE_FAILED"
        receipt["ablation_result_reported"] = False
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("VOID: fidelity gate failed")
        for row in fidelity_rows:
            if not row["agrees"]:
                print("  ", row)
        return 1

    # --- no-op control, per ablation (protocol §7) ---
    noop_base = resolve_ablated(NOOP_STATE["claims"], NOOP_STATE["context"], (), frozenset())
    noop = {}
    for fid in FILTERS:
        got = resolve_ablated(
            NOOP_STATE["claims"], NOOP_STATE["context"], (), frozenset({fid})
        )
        noop[fid] = {
            "unchanged": got == noop_base,
            "baseline": noop_base,
            "ablated": got,
        }
    noop_clean = all(v["unchanged"] for v in noop.values())

    # --- per-filter ablation ---
    results = []
    for st in all_states:
        fid = st["filter"]
        base = real(st["claims"], st["context"], st.get("rules", ()))
        abl = resolve_ablated(
            st["claims"], st["context"], st.get("rules", ()), frozenset({fid})
        )
        klass, why = classify(base, abl, st["kind"], all_states)
        results.append(
            {
                "filter": fid,
                "kind": st["kind"],
                "violation_class": st["violation"],
                "baseline": base,
                "ablated": abl,
                "separated": base != abl,
                "class": klass,
                "rationale": why,
            }
        )

    # --- reconcile paired/solitary into a per-filter verdict (protocol §3, §5) ---
    per_filter: dict[str, Any] = {}
    for fid in sorted({r["filter"] for r in results}):
        rows = [r for r in results if r["filter"] == fid]
        paired = next((r for r in rows if r["kind"] == "paired"), None)
        solitary = next((r for r in rows if r["kind"] == "solitary"), None)
        if paired and solitary:
            if solitary["separated"] and not paired["separated"]:
                verdict = "REDUNDANT_BUT_LOAD_BEARING"
                note = (
                    "masked in the paired state by a ranking element that "
                    "restates it; the mask breaks when no compliant alternative "
                    "exists, and then this filter is the only refusal"
                )
            elif solitary["separated"] and paired["separated"]:
                verdict, note = "ESSENTIAL", "admits the violation in both states"
            elif not solitary["separated"] and not paired["separated"]:
                verdict = "UNRESOLVED"
                note = (
                    "no change even with no alternative present; no blocker was "
                    "identified, so this is class U, not class B"
                )
            else:
                verdict, note = "UNRESOLVED", "paired separated but solitary did not"
        else:
            row = rows[0]
            verdict = "ESSENTIAL" if row["separated"] else "UNRESOLVED"
            note = (
                "single-state filter; " +
                ("removal admits the violation" if row["separated"]
                 else "no change and no blocker identified")
            )
        per_filter[fid] = {
            "verdict": verdict,
            "note": note,
            "positive_control_separated": any(r["separated"] for r in rows),
            "citable": any(r["separated"] for r in rows),
            "rows": [
                {"kind": r["kind"], "separated": r["separated"], "class": r["class"]}
                for r in rows
            ],
        }

    non_separating = [f for f, v in per_filter.items() if not v["positive_control_separated"]]

    receipt.update(
        {
            "result": (
                "ABLATION_COMPLETE" if noop_clean else "VOID_NOOP_CONTROL_CHANGED"
            ),
            "ablation_result_reported": noop_clean,
            "noop_control": {"clean": noop_clean, "per_filter": noop},
            "filters_evaluated": sorted(per_filter),
            "per_filter_verdict": per_filter,
            "filters_whose_control_did_not_separate": non_separating,
            "uncitable_filters": non_separating,
            "raw_results": results,
            "structural_analysis": structural_analysis(),
            "amendment_1": (
                "R1/R2/R3 and R6 produced no separation. Their verdicts remain "
                "UNRESOLVED and their nulls are uncitable per protocol §6. The "
                "structural reason is recorded in structural_analysis, including "
                "a mechanical proof that ranking element 6 duplicates element 3 "
                "for every admissible claim. See AMENDMENT_1_2026-08-19.md."
            ),
            "supersedes": "receipts/governance-filter-ablation-attempt1-2026-08-19.json",
            "redundancy_note": (
                "R1/R2/R3 restate F1/F2/F3. A null in the paired state alone is "
                "class B_pending_blocker and is never reported as B without the "
                "solitary run naming the blocker."
            ),
        }
    )
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"fidelity gate: {'PASS' if fidelity['all_agree'] else 'FAIL'}")
    print(f"no-op control clean: {noop_clean}")
    print(f"result: {receipt['result']}")
    for fid in sorted(per_filter):
        v = per_filter[fid]
        print(f"  {fid:<3} {v['verdict']:<26} control_separates={v['positive_control_separated']}")
    if non_separating:
        print(f"UNCITABLE (control did not separate): {non_separating}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
