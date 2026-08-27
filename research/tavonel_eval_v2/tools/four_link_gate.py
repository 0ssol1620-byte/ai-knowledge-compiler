#!/usr/bin/env python3
"""INC-V2-034 — the four-chain-link clause, made an executable hard gate.

`protocols/GPU_SUCCESSOR_STUDY_V1.yaml` section 4 states the requirement in
the founder's own words:

    Every represented source fact must have: source witness -> canonical
    representation -> fingerprint -> dependency/invalidation path. If any link
    in that chain is absent, the state cannot be declared source-faithful
    CURRENT.

and then names, in its own comment, exactly what this repository had not yet
built: `gpu_successor_preflight.cohort_feasibility` and
`tools/build_successor_cohort.py` both check kind, state and the
invisible-in-unit-text predicate; **neither verifies that a fingerprint and a
dependency path actually resolve, because a manifest does not carry them**.
The founder's ruling on that gap (2026-08-23): do not narrow the clause to
what is already checked — implement it.

This module is that implementation. It does not touch
`tools/gpu_successor_preflight.py` or `tools/build_successor_cohort.py` —
per the founder's routing, this session reads them to integrate against but
does not modify them. Where wiring is needed, it is reported, not made here.

What it checks, per candidate (one typed fact, already filtered to
`ELIGIBLE_KIND` + `REPRESENTED_IN_COMPILED_STATE` + invisible-in-text +
has-a-preceding-revision by `build_successor_cohort.eligibility_reason` —
this module does not repeat that filtering, it adds the missing layer on top
of it):

    link 1  source witness           — a followable locator: a real
                                        construct, a valid byte span, and a
                                        non-empty excerpt. A witness with no
                                        excerpt asserts a location with
                                        nothing a reader could check it
                                        against, which is not evidence.
    link 2  canonical representation — non-null, and hashed
                                        (`ir.digest`) so the claim is a
                                        digest, not an assertion.
    link 3  fingerprint              — computed for real, via
                                        `source_fact_ir.fingerprint.fingerprint`,
                                        the same pure function of
                                        (kind, representation) the compiler
                                        lane uses. Not reimplemented here.
    link 4  dependency path          — computed for real, via
                                        `source_fact_ir.fingerprint.dependency_keys`,
                                        the same function. An unanchored fact
                                        (no `witness.unit_path`) surfaces here,
                                        as `UnanchoredFact`, because a
                                        dependency edge cannot be named
                                        without an anchor.

A single boolean `eligible=true` is explicitly forbidden by the founder's
ruling. Every candidate is classified into exactly one of six states
(`ELIGIBILITY_STATES` below), and every `ELIGIBLE` classification carries a
`chain_digest` — the one digest a reader can recompute from the four link
digests beneath it to check the classification without re-running this tool.

Links 3 and 4 need no raw source bytes: `fingerprint()` and
`dependency_keys()` are both pure functions of the fact record already in the
manifest (kind, representation, witness.unit_path). This is why the gap could
be closed by enforcement rather than by narrowing the clause — the evidence
the clause asks for was already computable, nothing here required a network
fetch or a GPU second to produce it.

Link 1 is the one link this module cannot independently re-verify against
live source bytes: the acquisition artifacts this study reads
(`sfi1_worker._extract_pair`, `sfi2_worker._extract_pair`) do not retain a
digest of the raw payload a witness was drawn from — only its excerpt. That is
a real, reported limitation (see `WITNESS_LIMITATION` below), not a papered
gap: the excerpt itself is real, immutable, quoted source text captured at
extraction time, and this module requires it to be present and hashes it as
the witness's own followable reference. It does not claim to have re-read the
live source to confirm it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "source_fact_ir", "endpoint"):
    sys.path.insert(0, str(NS / _sub))
#: `source_fact_ir/fingerprint.py` imports itself as `from source_fact_ir import
#: ir`, a namespace-package import that needs the *parent* of `source_fact_ir/`
#: on the path too. Mirrors `tools/forensic_four_divergences_v2.py`'s own path
#: setup for the identical reason.
sys.path.insert(0, str(NS))

import gpu_successor_preflight as gsp  # noqa: E402
import ir  # noqa: E402
from common import now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from source_fact_ir import fingerprint as fp  # noqa: E402

SCHEMA = "tavonel.v2.four_link_gate.v1"

# ---------------------------------------------------------------------------
# the six states — a single boolean is forbidden by the founder's ruling
# ---------------------------------------------------------------------------

STATE_ELIGIBLE = "ELIGIBLE"
STATE_MISSING_SOURCE_WITNESS = "MISSING_SOURCE_WITNESS"
STATE_MISSING_CANONICAL_REPRESENTATION = "MISSING_CANONICAL_REPRESENTATION"
STATE_MISSING_FINGERPRINT = "MISSING_FINGERPRINT"
STATE_MISSING_DEPENDENCY_PATH = "MISSING_DEPENDENCY_PATH"
STATE_UNRESOLVED_CHAIN = "UNRESOLVED_CHAIN"

ELIGIBILITY_STATES: tuple[str, ...] = (
    STATE_ELIGIBLE,
    STATE_MISSING_SOURCE_WITNESS,
    STATE_MISSING_CANONICAL_REPRESENTATION,
    STATE_MISSING_FINGERPRINT,
    STATE_MISSING_DEPENDENCY_PATH,
    STATE_UNRESOLVED_CHAIN,
)

WITNESS_LIMITATION = (
    "link 1 (source witness) is checked against the recorded excerpt — real, "
    "immutable, quoted source text captured at extraction time — not against a "
    "fresh re-read of live source bytes. No acquisition artifact in this "
    "namespace retains a payload digest a witness could be re-verified against, "
    "so this module reports what it can check (a real, non-empty, hashed "
    "excerpt) rather than asserting a live re-verification it did not perform."
)

DEFAULT_MANIFEST = NS / "artifacts" / "development" / "typed_fact_cohort.json"


def _safe_rel(path: Path) -> str:
    """`common.rel` assumes a path under the repo root, which a test fixture
    or an ad hoc manifest need not be. Falls back to the plain string rather
    than raising, since this is a display field, not an identity check —
    mirrors `gpu_successor_preflight._safe_rel`."""
    try:
        return rel(path)
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# one candidate
# ---------------------------------------------------------------------------


def _fact_from_dict(candidate: dict[str, Any]) -> ir.SourceFact:
    """Reconstruct the real `ir.SourceFact` this candidate claims to be.

    Raises whatever `ir.Witness`/`ir.SourceFact`'s own invariants raise for a
    malformed record — the caller classifies that as `UNRESOLVED_CHAIN`,
    because a record that cannot even be reconstructed as the type the chain
    is defined over is not a link-specific failure, it is an unresolved one.
    """
    witness_raw = candidate.get("witness") or {}
    unit_path = witness_raw.get("unit_path")
    witness = ir.Witness(
        construct=str(witness_raw.get("construct", "")),
        byte_start=int(witness_raw.get("byte_start", 0)),
        byte_end=int(witness_raw.get("byte_end", 0)),
        excerpt=str(witness_raw.get("excerpt") or ""),
        unit_path=tuple(unit_path) if unit_path else None,
    )
    return ir.SourceFact(
        kind=candidate["kind"],
        witness=witness,
        state=candidate["state"],
        representation=candidate.get("representation"),
        policy_ref=candidate.get("policy_ref"),
        reason=candidate.get("reason"),
        extra=candidate.get("extra", {}) or {},
    )


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """One candidate's machine-readable eligibility state, evidence attached.

    Checked in chain order — witness, representation, fingerprint, dependency
    path — so a candidate that fails more than one link is still reported
    under a single, well-defined reason: the first link it cannot trace to a
    followable digest. `evidence` carries whichever digests were resolved
    before that point, never a digest for a link that was not actually
    computed.
    """
    fact_id = candidate.get("fact_id")
    kind = candidate.get("kind")
    state = candidate.get("state")
    record: dict[str, Any] = {
        "fact_id": fact_id,
        "kind": kind,
        "source_fact_ir_state": state,
        "evidence": {},
    }

    if state != ir.REPRESENTED:
        return {
            **record,
            "eligibility_state": STATE_UNRESOLVED_CHAIN,
            "reason": (
                f"source_fact_ir state is {state!r}, not {ir.REPRESENTED!r}. Only a "
                f"{ir.REPRESENTED} fact claims the chain (the same rule "
                "`ir.chain` applies) — the chain cannot be resolved for a fact "
                "that never asserted it, and this is not the same failure as any "
                "one link being absent."
            ),
        }

    # --- link 1: source witness --------------------------------------------
    witness_raw = candidate.get("witness") or {}
    construct = witness_raw.get("construct")
    byte_start = witness_raw.get("byte_start")
    byte_end = witness_raw.get("byte_end")
    excerpt = witness_raw.get("excerpt") or ""
    witness_ok = (
        isinstance(construct, str)
        and bool(construct)
        and isinstance(byte_start, int)
        and not isinstance(byte_start, bool)
        and isinstance(byte_end, int)
        and not isinstance(byte_end, bool)
        and byte_start >= 0
        and byte_end >= byte_start
        and bool(excerpt.strip())
    )
    if not witness_ok:
        return {
            **record,
            "eligibility_state": STATE_MISSING_SOURCE_WITNESS,
            "reason": (
                "witness is not a followable evidence reference: needs a "
                "non-empty construct, a valid byte span (byte_end >= byte_start "
                ">= 0), and a non-empty excerpt. " + WITNESS_LIMITATION
            ),
        }
    witness_digest = ir.digest(
        {
            "construct": construct,
            "byte_start": byte_start,
            "byte_end": byte_end,
            "excerpt": excerpt,
        }
    )
    record["evidence"]["witness_digest"] = witness_digest

    # --- link 2: canonical representation -----------------------------------
    representation = candidate.get("representation")
    if representation is None:
        return {
            **record,
            "eligibility_state": STATE_MISSING_CANONICAL_REPRESENTATION,
            "reason": (
                f"representation is null on a {ir.REPRESENTED} fact — the "
                "compiled state claims to carry this fact but carries no value "
                "for it"
            ),
        }
    representation_digest = ir.digest(representation)
    record["evidence"]["representation_digest"] = representation_digest

    # --- reconstruct the real SourceFact for links 3 and 4 -------------------
    try:
        fact = _fact_from_dict(candidate)
    except (ValueError, TypeError, KeyError) as error:
        return {
            **record,
            "eligibility_state": STATE_UNRESOLVED_CHAIN,
            "reason": (
                "candidate could not be reconstructed as a SourceFact despite "
                f"passing the witness and representation checks: "
                f"{type(error).__name__}: {error}"
            ),
        }

    # --- link 3: fingerprint --------------------------------------------------
    try:
        fingerprint_value = fp.fingerprint(fact)
    except Exception as error:  # any failure here is the link failing
        return {
            **record,
            "eligibility_state": STATE_MISSING_FINGERPRINT,
            "reason": f"fingerprint computation raised {type(error).__name__}: {error}",
        }
    if not fingerprint_value:
        return {
            **record,
            "eligibility_state": STATE_MISSING_FINGERPRINT,
            "reason": "fingerprint computation returned an empty value",
        }
    record["evidence"]["fingerprint"] = fingerprint_value

    # --- link 4: dependency path -----------------------------------------------
    try:
        dependency_keys = fp.dependency_keys(fact)
    except Exception as error:  # includes fp.UnanchoredFact
        return {
            **record,
            "eligibility_state": STATE_MISSING_DEPENDENCY_PATH,
            "reason": (f"dependency path resolution raised {type(error).__name__}: {error}"),
        }
    if not dependency_keys:
        return {
            **record,
            "eligibility_state": STATE_MISSING_DEPENDENCY_PATH,
            "reason": "dependency path resolution returned no artifact keys",
        }
    dependency_digest = ir.digest(list(dependency_keys))
    record["evidence"]["dependency_keys"] = list(dependency_keys)
    record["evidence"]["dependency_digest"] = dependency_digest

    chain_digest = ir.digest(
        {
            "witness_digest": witness_digest,
            "representation_digest": representation_digest,
            "fingerprint": fingerprint_value,
            "dependency_digest": dependency_digest,
        }
    )
    record["evidence"]["chain_digest"] = chain_digest

    return {**record, "eligibility_state": STATE_ELIGIBLE, "reason": None}


# ---------------------------------------------------------------------------
# a cohort of candidates
# ---------------------------------------------------------------------------


def classify_cohort(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Every candidate, classified. Counts and reasons, never summarised away."""
    records = [classify_candidate(candidate) for candidate in candidates]

    by_state: dict[str, int] = {state: 0 for state in ELIGIBILITY_STATES}
    by_kind: dict[str, dict[str, int]] = {}
    for rec in records:
        by_state[rec["eligibility_state"]] += 1
        kind = str(rec["kind"])
        row = by_kind.setdefault(kind, {state: 0 for state in ELIGIBILITY_STATES})
        row[rec["eligibility_state"]] += 1

    return {
        "candidates_considered": len(candidates),
        "by_state": by_state,
        "by_kind": dict(sorted(by_kind.items())),
        "eligible_count": by_state[STATE_ELIGIBLE],
        "records": records,
    }


def gate(candidates: list[dict[str, Any]], *, floor: int = gsp.COHORT_FLOOR) -> dict[str, Any]:
    """The hard gate: classify, then refuse below the floor.

    `feasible` and `verdict` are computed from `by_state[STATE_ELIGIBLE]`
    alone — the count AFTER the four-link check, never the pre-chain-check
    count `gpu_successor_preflight.cohort_feasibility` currently reports (see
    module docstring: that count does not verify links 3 and 4 at all).
    """
    cohort = classify_cohort(candidates)
    eligible_count = cohort["eligible_count"]
    feasible = eligible_count >= floor
    return {
        "schema": SCHEMA,
        "floor": floor,
        "feasible": feasible,
        "verdict": "READY" if feasible else "STOP",
        "rule": (
            "below the floor this gate STOPs. The floor is never relaxed to "
            "reach feasibility, and the exclusion counts and reasons in "
            "by_state/by_kind are recorded, not summarised away — a silently "
            "shrunk cohort reads as a clean one."
        ),
        "witness_limitation": WITNESS_LIMITATION,
        **cohort,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_candidates(manifest_path: Path, facts_key: str) -> list[dict[str, Any]]:
    body = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = body.get(facts_key, [])
    if not isinstance(candidates, list):
        raise ValueError(
            f"{_safe_rel(manifest_path)}[{facts_key!r}] is {type(candidates).__name__}, "
            "not a list of candidate facts"
        )
    return candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=(
            "a successor cohort manifest (tools/build_successor_cohort.py's "
            "output shape) or any JSON body carrying a list of SourceFact "
            "dicts under --facts-key"
        ),
    )
    parser.add_argument(
        "--facts-key",
        default="facts",
        help="the top-level key in --manifest holding the candidate list",
    )
    parser.add_argument("--floor", type=int, default=gsp.COHORT_FLOOR)
    parser.add_argument(
        "--no-receipt",
        action="store_true",
        help="print the gate result without writing an immutable receipt",
    )
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        result = {
            "schema": SCHEMA,
            "manifest": _safe_rel(args.manifest),
            "manifest_present": False,
            "candidates_considered": 0,
            "eligible_count": 0,
            "floor": args.floor,
            "feasible": False,
            "verdict": "STOP",
            "reason": "no manifest exists yet; reported infeasible, never estimated",
        }
        print(json.dumps(result, indent=2))
        return 2

    candidates = _load_candidates(args.manifest, args.facts_key)
    started = now()
    result = gate(candidates, floor=args.floor)
    result["started_at"] = started
    result["ended_at"] = now()
    result["manifest"] = _safe_rel(args.manifest)
    result["manifest_sha256"] = sha_file(args.manifest)

    if args.no_receipt:
        summary = {k: v for k, v in result.items() if k != "records"}
        print(json.dumps(summary, indent=2))
        return 0 if result["verdict"] == "READY" else 2

    written = write_immutable(
        "four-link-gate",
        result,
        tool=Path(__file__).resolve(),
        protocol=None,
    )
    summary = {
        **written,
        "verdict": result["verdict"],
        "eligible_count": result["eligible_count"],
        "candidates_considered": result["candidates_considered"],
        "by_state": result["by_state"],
    }
    print(json.dumps(summary, indent=2))
    return 0 if result["verdict"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
