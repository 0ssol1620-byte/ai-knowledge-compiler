"""ACCEPTANCE DOMAIN == EXECUTABLE GRADING DOMAIN, checked as set equality.

THE DEFECT THIS EXISTS TO MAKE UNREPEATABLE. V2R3R1 froze a pass rule requiring
all eight invariants MET and none UNPROVEN, and shipped an instrument that
aggregates one. The instrument could never produce the PASS its own frozen rule
required. Nothing compared the two domains, so the mismatch survived a full
freeze chain, eight rungs of attestation, and the irreversible execution of a
300-pair corpus that is now spent. INC-V2-067.

The SFI3 freezer had the same shape in miniature: it checked
`len(body["endpoints"])`. **A count is not a correspondence.** Two lists of nine
can disagree on every member, and eight wrong names pass any check that counts.

So this module compares SETS OF IDENTIFIERS, three ways:

    declared  -- the ids the protocol's `invariants:` block names
    graded    -- the ids the scorer's aggregation ACTUALLY emits, obtained by
                 running it, not by reading a list beside it
    schema    -- the ids the result schema requires a receipt to carry

All three must equal each other AND equal `CANONICAL_INVARIANTS`. A rename in
any one of them is a refusal, not a warning.

`graded` is EXECUTED rather than declared, and that is the load-bearing choice.
A module can carry a tuple naming eight invariants and aggregate one -- that is
precisely what happened -- and any check reading the tuple would have agreed
with the protocol and reported clean. The only honest question is *what does the
grading function put in its output*, and the only way to ask it is to call it.

WHAT THIS DOES NOT DO. It says nothing about whether an invariant is correctly
implemented, whether it has power, or what its verdict should be. It answers one
question: does the thing that accepts and the thing that grades talk about the
same eight objects? Coverage is not correctness.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]

SCHEMA = "tavonel.v2.invariant_domain_equality.v1"

#: The eight invariant identifiers, in full, pinned once.
#:
#: Full ids, not the `INVARIANT_<n>` ordinals. The founder's ruling requires that
#: "eight wrong names must fail", and a comparison on ordinals alone would accept
#: eight invariants numbered 1-8 that assert entirely different things. The
#: ordinal is a position; the full id is the claim.
#:
#: These are V1's ids, carried unchanged through V2R1, V2R2, V2R3 and V2R3R1.
#: The set has never moved across a version boundary -- only the semantics behind
#: INVARIANT_6 and INVARIANT_8 have -- so an id that changes here is a new
#: scientific object and must be declared as one.
CANONICAL_INVARIANTS: tuple[str, ...] = (
    "INVARIANT_1_identity_decisions_unchanged",
    "INVARIANT_2_identity_fold_remains_identity_only",
    "INVARIANT_3_expectation_is_independent",
    "INVARIANT_4_changed_facet_resolves_typed_or_failclosed",
    "INVARIANT_5_never_silently_unchanged",
    "INVARIANT_6_ambiguous_identity_stays_unresolved",
    "INVARIANT_7_only_predeclared_ignores",
    "INVARIANT_8_sfi2_cases_cannot_certify",
)

ORDINAL = re.compile(r"^INVARIANT_(\d+)_[a-z0-9_]+$")

MET = "MET"
VIOLATED = "VIOLATED"
UNPROVEN = "UNPROVEN"
PASS = "PASS"  # noqa: S105 - a verdict label, not a credential
FAIL = "FAIL"
VACUOUS_FAIL = "VACUOUS_FAIL"

#: The verdict vocabulary a full closure result may use. Pinned so a scorer
#: cannot invent a ninth outcome that no acceptance rule knows how to read.
INVARIANT_VERDICTS = (MET, VIOLATED, UNPROVEN)
OVERALL_VERDICTS = (PASS, FAIL, UNPROVEN, VACUOUS_FAIL)


class DomainRefused(RuntimeError):
    """The acceptance domain and the grading domain are not the same set.

    Raised BEFORE anything is executed. A protocol carrying this mismatch may
    not be frozen and a cohort may not be acquired against it.
    """


class ContractBroken(RuntimeError):
    """A produced receipt does not carry exactly the declared invariant set.

    Raised at emission. Distinct from `DomainRefused` because the two happen at
    different times and mean different things: one says the study was
    mis-specified, the other says the study ran and reported something its own
    specification cannot read.
    """


# ---------------------------------------------------------------------------
# the anchor checks itself


def _require_canonical_is_well_formed() -> None:
    """The anchor is eight distinct ids covering ordinals 1..8 exactly.

    An anchor nobody checks is a ninth place for the defect to live. If this
    tuple were silently edited to seven entries, every comparison below would
    still agree with itself and report a clean domain.
    """
    if len(set(CANONICAL_INVARIANTS)) != len(CANONICAL_INVARIANTS):
        raise DomainRefused(f"CANONICAL_INVARIANTS repeats an id: {CANONICAL_INVARIANTS}")
    ordinals = []
    for name in CANONICAL_INVARIANTS:
        match = ORDINAL.match(name)
        if match is None:
            raise DomainRefused(
                f"{name!r} is not shaped INVARIANT_<n>_<slug>; the anchor cannot be "
                "read as an ordered set of invariants"
            )
        ordinals.append(int(match.group(1)))
    if sorted(ordinals) != list(range(1, 9)):
        raise DomainRefused(f"CANONICAL_INVARIANTS covers ordinals {sorted(ordinals)}, not 1..8")


_require_canonical_is_well_formed()


def ordinals(names: object) -> tuple[int, ...]:
    """The ordinal of each id, for reporting. Never used as the comparison."""
    out = []
    for name in names if isinstance(names, (list, tuple, set, frozenset)) else ():
        match = ORDINAL.match(str(name))
        if match is not None:
            out.append(int(match.group(1)))
    return tuple(sorted(out))


# ---------------------------------------------------------------------------
# the three domains


def declared_invariants(protocol: Path) -> tuple[str, ...]:
    """The ids the protocol's own `invariants:` block names."""
    import yaml

    if not protocol.is_file():
        raise DomainRefused(f"{protocol} does not exist; nothing declares an acceptance domain")
    body = yaml.safe_load(protocol.read_text(encoding="utf-8")) or {}
    block = body.get("invariants")
    if not isinstance(block, dict) or not block:
        raise DomainRefused(
            f"{protocol.name} has no `invariants:` mapping. A pass rule that says "
            "'all eight invariants MET' over a protocol that names none is a "
            "sentence, not a rule."
        )
    return tuple(sorted(block))


def graded_invariants(grade: Callable[..., dict[str, Any]], **null_inputs: Any) -> tuple[str, ...]:
    """The ids the aggregation ACTUALLY emits, obtained by running it.

    Not read from a constant beside the function. V2R3R1's scorer could have
    carried a tuple of eight names and still aggregated one; the tuple would
    have matched the protocol and the check would have passed. The output is the
    only witness to what is graded.

    `null_inputs` are whatever the callable needs to produce an empty-population
    result. The verdicts that come back are meaningless here and are discarded
    -- only the KEYS are read.
    """
    try:
        result = grade(**null_inputs)
    except Exception as error:
        raise DomainRefused(
            f"the grading function could not be executed on a null population, so "
            f"its grading domain cannot be observed: {type(error).__name__}: {error}"
        ) from error
    block = (result or {}).get("invariants")
    if not isinstance(block, dict) or not block:
        raise DomainRefused(
            "the grading function returned no `invariants` block. Whatever it "
            "computes, it does not report per-invariant verdicts, and a pass rule "
            "over invariants cannot be evaluated from its output."
        )
    return tuple(sorted(block))


def schema_invariants(required: object) -> tuple[str, ...]:
    """The ids the result schema requires a receipt to carry."""
    if not isinstance(required, (list, tuple, set, frozenset)) or not required:
        raise DomainRefused(
            "the result schema requires no invariant keys, so a receipt missing "
            "seven of eight would satisfy it"
        )
    return tuple(sorted(str(name) for name in required))


# ---------------------------------------------------------------------------
# the gate


def _difference(label: str, actual: tuple[str, ...]) -> list[str]:
    anchor = set(CANONICAL_INVARIANTS)
    found = set(actual)
    problems = []
    missing = sorted(anchor - found)
    extra = sorted(found - anchor)
    if missing:
        problems.append(f"{label} omits {missing}")
    if extra:
        problems.append(f"{label} names {extra}, which no invariant set declares")
    return problems


def require_domain_equality(
    *,
    declared: tuple[str, ...],
    graded: tuple[str, ...],
    schema: tuple[str, ...],
) -> dict[str, Any]:
    """All three domains are the same set, and that set is the anchor.

    Raises `DomainRefused` on any difference. Returns the evidence on success --
    a caller that wants to record WHAT it checked gets the three sets back
    rather than a bare `True`.
    """
    problems: list[str] = []
    problems += _difference("the protocol's declared set", declared)
    problems += _difference("the scorer's graded set", graded)
    problems += _difference("the result schema's required set", schema)

    #: Checked separately from the anchor comparison above. Three sets can each
    #: differ from the anchor and still differ from each other, and a reader
    #: needs to know which relationship broke.
    if set(declared) != set(graded):
        problems.append(
            f"declared and graded disagree: declared-not-graded="
            f"{sorted(set(declared) - set(graded))}, "
            f"graded-not-declared={sorted(set(graded) - set(declared))}"
        )
    if set(declared) != set(schema):
        problems.append(
            f"declared and the result schema disagree: "
            f"declared-not-required={sorted(set(declared) - set(schema))}, "
            f"required-not-declared={sorted(set(schema) - set(declared))}"
        )

    if problems:
        raise DomainRefused(
            "ACCEPTANCE DOMAIN != EXECUTABLE GRADING DOMAIN.\n  "
            + "\n  ".join(problems)
            + "\nA count of eight is not sufficient and eight wrong names must "
            "fail; this is set equality on full identifiers. See INC-V2-067."
        )
    return {
        "schema": SCHEMA,
        "held": True,
        "canonical": list(CANONICAL_INVARIANTS),
        "declared": list(declared),
        "graded": list(graded),
        "schema_required": list(schema),
        "ordinals": list(ordinals(CANONICAL_INVARIANTS)),
        "compared": "set equality on full identifiers, never on a count",
        "graded_domain_obtained_by": (
            "executing the grading function on a null population and reading the "
            "keys it emitted -- not by reading a constant declared beside it"
        ),
    }


def require_receipt_domain(receipt: dict[str, Any]) -> dict[str, Any]:
    """A produced result carries exactly the eight invariant blocks, each graded.

    Raises `ContractBroken`. Separate from `require_domain_equality` because a
    receipt is produced AFTER execution: at that point the study has already
    spent whatever it spent, and the correct report is that the result cannot be
    read against its own rule -- not that the study should be re-specified.
    """
    block = receipt.get("invariants")
    if not isinstance(block, dict):
        raise ContractBroken(
            "the result carries no `invariants` mapping, so its overall verdict "
            "rests on nothing a reader can check"
        )
    problems = _difference("the result receipt", tuple(sorted(block)))
    for name in sorted(set(block) & set(CANONICAL_INVARIANTS)):
        row = block[name]
        if not isinstance(row, dict) or "verdict" not in row:
            problems.append(f"{name} carries no verdict")
            continue
        if row["verdict"] not in INVARIANT_VERDICTS:
            problems.append(
                f"{name} reports {row['verdict']!r}, which is not one of {list(INVARIANT_VERDICTS)}"
            )
    overall = receipt.get("overall")
    if overall not in OVERALL_VERDICTS:
        problems.append(
            f"`overall` is {overall!r}, not one of {list(OVERALL_VERDICTS)}. A "
            "result with no overall verdict forces a reader to aggregate the "
            "invariants themselves, which is an interpretation step after the "
            "outcome is known."
        )
    if problems:
        raise ContractBroken(
            "the result does not carry the declared invariant set:\n  " + "\n  ".join(problems)
        )
    return {
        "schema": SCHEMA,
        "held": True,
        "overall": overall,
        "invariants_present": list(sorted(block)),
        "verdicts": {name: block[name]["verdict"] for name in sorted(block)},
    }


def overall_from(invariants: dict[str, Any], *, pairs_resolved: int) -> str:
    """The frozen pass rule, evaluated by the scorer rather than by a reader.

    Ordering matters and is the rule's own: a closure over zero pairs is
    `VACUOUS_FAIL` before any invariant is read, a single violation is `FAIL`,
    and an unexercised invariant can never contribute to a `PASS`.
    """
    if pairs_resolved <= 0:
        return VACUOUS_FAIL
    verdicts = [row.get("verdict") for row in invariants.values()]
    if any(verdict == VIOLATED for verdict in verdicts):
        return FAIL
    if any(verdict == UNPROVEN for verdict in verdicts):
        return UNPROVEN
    return PASS


def main(argv: list[str] | None = None) -> int:
    """Report the anchor. There is nothing to check without a protocol and a scorer."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=None)
    args = parser.parse_args(argv)
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "canonical": list(CANONICAL_INVARIANTS),
        "ordinals": list(ordinals(CANONICAL_INVARIANTS)),
    }
    if args.protocol is not None:
        try:
            body["declared"] = list(declared_invariants(args.protocol))
            body["declared_equals_canonical"] = set(body["declared"]) == set(CANONICAL_INVARIANTS)
        except DomainRefused as error:
            body["declared"] = None
            body["why"] = str(error)
    print(json.dumps(body, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
