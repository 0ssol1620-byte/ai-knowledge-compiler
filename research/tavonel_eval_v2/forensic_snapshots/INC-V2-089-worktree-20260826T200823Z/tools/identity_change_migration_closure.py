#!/usr/bin/env python3
"""Run IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 once, against its frozen universe.

The closure of the INC-V2-037 predicate migration. Eight threshold-free
structural invariants, graded over a development cohort proven disjoint from the
538-pair retrospective safety regression, plus a fixture battery frozen with the
protocol that supplies the gate power the cohort's unit representation cannot.

**Ordering is a precondition, not a convention.** This tool refuses (exit 4)
unless the protocol freeze receipt exists and pins the protocol file's current
sha256, and unless the universe freeze receipt exists. INC-V2-042 is what
happens when a ladder's rungs are climbed in the wrong order and the receipts
are written afterwards by the party who already knows the answer; a refusal is
the only form of that rule that cannot be walked past.

**Legacy disagreement is not ground truth here.** The legacy predicate is the
defect under repair. It is run — `legacy_identity_change_predicate=True` is the
pinned reference path and this tool is one of the reasons it must stay — but
only to show that identity decisions did not move. Nothing is graded against
what it called unchanged, and the word "false positive" appears nowhere for an
over-fire, because establishing one would need an oracle neither predicate
provides.

**The expectation comes from `source_fact_ir/expected_change_status.py`**, which
imports neither predicate. INVARIANT_3 walks its AST to check that, every run.

**A closure over zero pairs FAILS as vacuous.** So does an invariant with zero
exercising observations, which reports UNPROVEN and can never contribute to a
PASS. That is this study's most-repeated defect — a check reporting clean
because it is watching nothing — written into the grading rule.

Usage::

    python tools/identity_change_migration_closure.py            # the closure
    python tools/identity_change_migration_closure.py --fixtures-only
    python tools/identity_change_migration_closure.py --write-receipt
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import change_facets as facets  # noqa: E402
import expected_change_status as oracle  # noqa: E402
import selective_build as engine  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
    normalize_text_for_identity,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeKind,
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    content_facet_verdict,
    diff_documents,
)
from common import rel  # noqa: E402
from evidence import runs_of, write_immutable  # noqa: E402
from freeze_migration_closure import (  # noqa: E402
    PROTOCOL,
    UNIVERSE_STEM,
    FreezeRefused,
    load_protocol,
    require_frozen_protocol,
)

SCHEMA = "tavonel.v2.identity_change_migration_closure.v1"
STEM = "identity-change-migration-closure"
ORACLE_MODULE = NS / "source_fact_ir" / "expected_change_status.py"

MET = "MET"
VIOLATED = "VIOLATED"
UNPROVEN = "UNPROVEN"

#: Change kinds whose presence or absence is a statement about *matching* rather
#: than about an already-matched pair's content. `evidence_moved` belongs here
#: because it is emitted per matched pair: if a unit stopped matching, its
#: locator record disappears with it.
IDENTITY_SENSITIVE_KINDS = frozenset(
    {
        ChangeKind.UNIT_ADDED,
        ChangeKind.UNIT_REMOVED,
        ChangeKind.IDENTITY_UNRESOLVED,
        ChangeKind.EVIDENCE_MOVED,
    }
)

#: Kinds that assert a settled continuity decision about a unit. An
#: `identity_unresolved` unit may carry none of them — that is INVARIANT_6.
CONTINUITY_ASSERTING_KINDS = frozenset(
    {ChangeKind.MODIFIED_CLAIM, ChangeKind.UNIT_ADDED, ChangeKind.UNIT_REMOVED}
)


class ClosureRefused(RuntimeError):
    """A precondition of the closure is not met. Never worked around here."""


# --------------------------------------------------------------------------
# INVARIANT_2 — the identity fold's declared classes
#
# Each perturbation produces a variant the fold MUST equate with the original.
# They are written as functions of arbitrary real text so that the invariant can
# be exercised on the cohort's own units rather than only on hand-built strings:
# a fold that stopped folding would be caught on synthetic input too, but a fold
# that stopped folding *only on real input* would not.
# --------------------------------------------------------------------------

#: U+FB01 LATIN SMALL LIGATURE FI. NFKC decomposes it to "fi", and both forms are
#: word characters, so the punctuation and whitespace stages cannot explain the
#: equality. This class therefore tests NFKC specifically.
_LIGATURE_FI = "ﬁ"


FOLD_CLASSES: dict[str, Callable[[str], str]] = {
    # NFKC only: "ﬁ" vs "fi" are equal after compatibility decomposition and
    # by no other stage of the fold.
    "nfkc_compatibility": lambda text: text + _LIGATURE_FI,
    # ASCII-only case flip. `str.upper()` would be wrong here: `casefold` is not
    # the inverse of `upper` outside ASCII. U+0131 LATIN SMALL LETTER DOTLESS I
    # upper-cases to "I", whose fold is "i", while its own fold is itself -- so
    # an upper-cased perturbation would report the fold as broken on real
    # Turkish text when the fold is fine and the perturbation is not.
    "case_only": lambda text: "".join(
        character.swapcase() if character.isascii() and character.isalpha() else character
        for character in text
    ),
    # The Apache -> Apache(R) shape from INC-V2-037, generalised: a registered
    # trademark sign is not a word character, folds to a space, and the space is
    # then collapsed and stripped.
    "punctuation_to_space": lambda text: text + "®",
    "whitespace_collapse": lambda text: text.replace(" ", "  "),
}

#: The original side of the `nfkc_compatibility` pair. Every other class
#: perturbs the text and compares against the text itself; this one has to
#: compare two perturbations, because "fi" appended to arbitrary text is the
#: thing NFKC turns the ligature into.
_NFKC_ORIGINAL: Callable[[str], str] = lambda text: text + "fi"  # noqa: E731


def fold_class_pair(name: str, text: str) -> tuple[str, str]:
    """The (a, b) the named class relates, for one real or synthetic text."""
    if name == "nfkc_compatibility":
        return _NFKC_ORIGINAL(text), FOLD_CLASSES[name](text)
    return text, FOLD_CLASSES[name](text)


def measure_identity_fold(
    texts: list[str],
    *,
    classes: tuple[str, ...],
    fold: Callable[[str], str] = normalize_text_for_identity,
) -> dict[str, Any]:
    """INVARIANT_2. The fold must still fold, and must still be lossy.

    `fold` is an injection seam for the test battery only: it substitutes a
    content-sensitive fold and asserts this comes back red. Production callers
    never pass it.
    """
    violations: list[dict[str, str]] = []
    lossiness_witnesses = 0
    per_class: dict[str, dict[str, int]] = {name: {"pairs": 0, "witnesses": 0} for name in classes}

    for text in texts:
        for name in classes:
            before, after = fold_class_pair(name, text)
            per_class[name]["pairs"] += 1
            if fold(before) != fold(after):
                violations.append(
                    {
                        "class": name,
                        "why": "the identity fold no longer folds this class",
                        "before": before[:160],
                        "after": after[:160],
                    }
                )
                continue
            if before != after:
                lossiness_witnesses += 1
                per_class[name]["witnesses"] += 1

    return {
        "texts": len(texts),
        "classes": list(classes),
        "per_class": per_class,
        "observations": sum(row["pairs"] for row in per_class.values()),
        "lossiness_witnesses": lossiness_witnesses,
        "violations": violations,
    }


# --------------------------------------------------------------------------
# INVARIANT_3 — the expectation oracle is independent, checked structurally
# --------------------------------------------------------------------------


def _module_paths(entry: Path) -> list[Path]:
    """`entry` plus every sibling module it imports from its own package dir.

    Shallow on purpose and stated as such: the oracle imports `change_facets`
    and nothing else, and a transitive walk that silently stopped somewhere
    would be a check whose depth nobody could state. If the oracle grows an
    import outside its own directory, `forbidden_imports` catches the ones that
    matter and the module list below records exactly what was inspected.
    """
    tree = ast.parse(entry.read_text(encoding="utf-8"))
    found = [entry]
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            sibling = entry.parent / (name.split(".")[0] + ".py")
            if sibling.is_file() and sibling not in found:
                found.append(sibling)
    return found


def audit_oracle_independence(
    *,
    entry: Path = ORACLE_MODULE,
    forbidden_imports: tuple[str, ...],
    forbidden_attributes: tuple[str, ...],
    module: ModuleType | None = None,
) -> dict[str, Any]:
    """INVARIANT_3. AST, signature and runtime binding, not a text search.

    A grep would pass on `from akc_cir import semantic_diff as sd`. The AST walk
    resolves the alias to its real name, and reads `ast.Attribute.attr` and
    `ast.Name.id` so that an attribute access on a forbidden symbol is caught
    even where the import that supplied it is not.
    """
    banned = set(forbidden_imports)
    banned_attrs = set(forbidden_attributes)
    violations: list[dict[str, str]] = []
    inspected: list[str] = []

    for path in _module_paths(entry):
        inspected.append(rel(path))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in banned or alias.name.split(".")[0] in banned:
                        violations.append(
                            {"module": rel(path), "kind": "import", "name": alias.name}
                        )
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ""
                if name in banned or name.split(".")[0] in banned:
                    violations.append({"module": rel(path), "kind": "import_from", "name": name})
            elif isinstance(node, ast.Attribute) and node.attr in banned_attrs:
                violations.append({"module": rel(path), "kind": "attribute", "name": node.attr})
            elif isinstance(node, ast.Name) and node.id in banned_attrs:
                violations.append({"module": rel(path), "kind": "name", "name": node.id})

    target = module if module is not None else oracle
    signature = inspect.signature(target.facet_obligations)
    parameters = tuple(signature.parameters)
    if parameters != ("before", "after", "channels", "ignored"):
        violations.append(
            {
                "module": rel(entry),
                "kind": "signature",
                "name": "facet_obligations" + str(signature),
            }
        )

    bound_forbidden = sorted(
        name
        for name, value in vars(target).items()
        if isinstance(value, ModuleType)
        and (
            getattr(value, "__name__", "") in banned
            or getattr(value, "__name__", "").split(".")[0] in banned
        )
    )
    for name in bound_forbidden:
        violations.append({"module": rel(entry), "kind": "runtime_binding", "name": name})

    return {
        "modules_inspected": inspected,
        "signature": str(signature),
        "observations": len(inspected),
        "violations": violations,
    }


# --------------------------------------------------------------------------
# INVARIANT_5 (a)-(c) — the oracle's mapping, over its whole input domain
# --------------------------------------------------------------------------


def audit_obligation_mapping(
    *,
    obligation_for: Callable[..., str] = oracle.obligation_for,
    permissive: frozenset[str] = oracle.OBLIGATIONS_SATISFIED_BY_SILENCE,
) -> dict[str, Any]:
    """INVARIANT_5(a)(b)(c). Exhaustive over 9 facets x 4 verdicts x 2 channels.

    This is a property of the oracle evaluated over its entire input domain, not
    a summary of what it returned on the cohort. A summary would be downstream of
    the data and could report clean on a mapping the cohort never reached — the
    shape INC-V2-037's typed cross-check had.
    """
    violations: list[dict[str, str]] = []
    combinations = 0

    for facet in facets.FACETS:
        for verdict in facets.VERDICTS:
            for has_channel in (True, False):
                combinations += 1
                obligation = obligation_for(facet, verdict, has_production_channel=has_channel)
                if obligation not in oracle.OBLIGATIONS:
                    violations.append(
                        {
                            "facet": facet,
                            "verdict": verdict,
                            "why": f"obligation outside the declared set: {obligation!r}",
                        }
                    )
                    continue
                if verdict not in (facets.CHANGED, facets.UNRESOLVED):
                    continue
                if has_channel:
                    if obligation in permissive:
                        violations.append(
                            {
                                "facet": facet,
                                "verdict": verdict,
                                "why": (
                                    f"{verdict!r} on a facet with a production channel "
                                    f"was discharged by silence: {obligation!r}"
                                ),
                            }
                        )
                elif obligation != oracle.UNRESOLVED_NO_PRODUCTION_CHANNEL:
                    violations.append(
                        {
                            "facet": facet,
                            "verdict": verdict,
                            "why": (
                                "a facet with no production channel must resolve "
                                "unresolved_no_production_channel, never "
                                f"{obligation!r}"
                            ),
                        }
                    )

    # (b) vocabulary closure -- an unknown must raise, not resolve.
    for label, args in (
        ("unknown_facet", ("NOT_A_FACET", facets.CHANGED)),
        ("unknown_verdict", (facets.CONTENT, "not_a_verdict")),
    ):
        try:
            obligation_for(args[0], args[1], has_production_channel=True)
        except oracle.ContractBroken:
            pass
        except Exception as error:
            violations.append({"why": f"{label} raised {type(error).__name__}, not ContractBroken"})
        else:
            violations.append(
                {"why": f"{label} returned a value instead of raising ContractBroken"}
            )

    # (c) permissive set closure.
    for obligation in (oracle.REQUIRE_TYPED_CHANGE, oracle.REQUIRE_FAIL_CLOSED):
        if obligation in permissive:
            violations.append({"why": f"{obligation!r} must not be dischargeable by silence"})

    return {
        "combinations_evaluated": combinations,
        "vocabulary_probes": 2,
        "observations": combinations + 2,
        "violations": violations,
    }


# --------------------------------------------------------------------------
# reading production's answer
# --------------------------------------------------------------------------


def _records_by_unit(diff: Any) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for change in diff.changes:
        if change.logical_id:
            index.setdefault(change.logical_id, set()).add(change.kind.value)
    return index


def _document_kinds(diff: Any) -> set[str]:
    return {change.kind.value for change in diff.changes}


def _identity_records(diff: Any) -> list[dict[str, object]]:
    return [
        change.as_record() for change in diff.changes if change.kind in IDENTITY_SENSITIVE_KINDS
    ]


def matched_pairs(
    before_units: list[UnitSnapshot], after_units: list[UnitSnapshot], source: str
) -> tuple[list[tuple[UnitSnapshot, UnitSnapshot]], int]:
    """`diff_documents`' matching, reproduced, with AMBIGUOUS and NEW excluded.

    Reproduced rather than read off the change records because a
    `MODIFIED_CLAIM` names the *before*-side logical id and the resolver may
    have matched it to an incoming unit whose own id differs; looking the
    incoming unit up by the reported id misses exactly those pairs. Same
    `assign_one_to_one`, same fingerprints, same lineage, so a divergence would
    be a bug here rather than a difference of policy.

    Excluding AMBIGUOUS is INVARIANT_6(c): an unsettled identity must never
    reach the facet oracle as though it were a matched pair.
    """
    by_logical = {unit.logical_id: unit for unit in before_units}
    decisions = assign_one_to_one(
        [unit.fingerprint(source_lineage=source) for unit in after_units],
        [unit.fingerprint(source_lineage=source) for unit in before_units],
        resolver=LogicalIdentityResolver(),
    )
    pairs: list[tuple[UnitSnapshot, UnitSnapshot]] = []
    ambiguous = 0
    for incoming, decision in zip(after_units, decisions, strict=True):
        if decision.match is LogicalMatch.AMBIGUOUS:
            ambiguous += 1
            continue
        if decision.match is LogicalMatch.NEW:
            continue
        counterpart = by_logical.get(decision.logical_id or "")
        if counterpart is not None:
            pairs.append((counterpart, incoming))
    return pairs, ambiguous


def check_ambiguity(diff: Any) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(a)(b) over one diff's own records."""
    index = _records_by_unit(diff)
    removed = {
        change.logical_id
        for change in diff.changes
        if change.kind is ChangeKind.UNIT_REMOVED and change.logical_id
    }
    violations: list[dict[str, Any]] = []
    observations = 0
    for change in diff.changes:
        if change.kind is not ChangeKind.IDENTITY_UNRESOLVED:
            continue
        observations += 1
        asserted = {kind.value for kind in CONTINUITY_ASSERTING_KINDS} & index.get(
            change.logical_id or "", set()
        )
        if asserted:
            violations.append(
                {
                    "logical_id": change.logical_id,
                    "why": "an unsettled identity also carries a continuity assertion",
                    "kinds": sorted(asserted),
                }
            )
        forced = sorted(set(change.candidates or ()) & removed)
        if forced:
            violations.append(
                {
                    "logical_id": change.logical_id,
                    "why": "a candidate of an unsettled identity was reported removed",
                    "candidates": forced,
                }
            )
    return violations, observations


# --------------------------------------------------------------------------
# one pair
# --------------------------------------------------------------------------


def _shape_of(units: list[UnitSnapshot]) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset(unit.document_path for unit in units),
        block_count=len(units),
        unit_order=tuple(unit.logical_id for unit in units),
    )


def measure_pair(
    before_document: dict[str, Any],
    after_document: dict[str, Any],
    *,
    channels: dict[str, bool],
    records: dict[str, str | None],
    unresolved_records: dict[str, str | None],
    scopes: dict[str, str],
    ignored: frozenset[str],
    level: DiffLevel = DiffLevel.GRAPH,
    obligations: Callable[..., dict[str, dict[str, str]]] = oracle.facet_obligations,
    diff_fn: Callable[..., Any] = diff_documents,
) -> dict[str, Any]:
    """One frozen revision pair, graded against the facet contract.

    `obligations` and `diff_fn` are injection seams for the test battery only.
    Production calls pass neither; the tests substitute a broken oracle or a
    doctored diff and assert the closure comes back red, which is the only way
    to know these checks are watching anything.
    """
    before_units, before_shape = engine.snapshots(before_document)
    after_units, after_shape = engine.snapshots(after_document)
    source = after_document["source_id"]

    def _diff(legacy: bool) -> Any:
        return diff_fn(
            before_sha256=before_document["source_digest"],
            after_sha256=after_document["source_digest"],
            level=level,
            before_shape=before_shape,
            after_shape=after_shape,
            before_units=before_units,
            after_units=after_units,
            source=source,
            legacy_identity_change_predicate=legacy,
        )

    legacy_diff = _diff(True)
    new_diff = _diff(False)

    pairs, ambiguous_excluded = matched_pairs(before_units, after_units, source)
    matched_counterparts = {counterpart.logical_id for counterpart, _ in pairs}

    # ---------------- INVARIANT_1 ----------------
    i1: list[dict[str, Any]] = []
    if _identity_records(legacy_diff) != _identity_records(new_diff):
        i1.append({"why": "identity-sensitive change records moved with the predicate"})
    if tuple(legacy_diff.unresolved) != tuple(new_diff.unresolved):
        i1.append({"why": "the unresolved tuple moved with the predicate"})
    for label, diff in (("legacy", legacy_diff), ("new", new_diff)):
        claimed = {
            change.logical_id
            for change in diff.changes
            if change.kind is ChangeKind.MODIFIED_CLAIM and change.logical_id
        }
        invented = sorted(claimed - matched_counterparts)
        if invented:
            i1.append(
                {
                    "why": f"the {label} predicate named a modified_claim the resolver "
                    "did not match",
                    "logical_ids": invented[:10],
                }
            )

    # ---------------- INVARIANT_6 ----------------
    i6: list[dict[str, Any]] = []
    ambiguity_observations = 0
    for label, diff in (("legacy", legacy_diff), ("new", new_diff)):
        found, count = check_ambiguity(diff)
        for row in found:
            i6.append({"predicate": label, **row})
        if label == "new":
            ambiguity_observations = count

    # ---------------- INVARIANTS 4, 5(d), 7 ----------------
    unit_index = _records_by_unit(new_diff)
    document_kinds = _document_kinds(new_diff)

    i4: list[dict[str, Any]] = []
    i5: list[dict[str, Any]] = []
    i7: list[dict[str, Any]] = []
    changed_observations = 0
    unresolved_observations = 0
    unresolved_without_failclosed = 0
    change_equivalent_observations = 0
    facet_verdict_counts: dict[str, dict[str, int]] = {
        facet: {verdict: 0 for verdict in facets.VERDICTS} for facet in facets.FACETS
    }

    for counterpart, incoming in pairs:
        resolved = obligations(counterpart, incoming, channels=channels, ignored=ignored)
        # Records about THIS matched pair. Production spells the owner of a
        # record differently per kind -- `modified_claim` and `evidence_moved`
        # name the before-side id, the temporal/metadata/visual/authority
        # records name the incoming one -- so the pair's record set is the union
        # of its two ids. When they are equal, which is the common case, the
        # union is the same set; it is never a union across different pairs.
        pair_kinds = unit_index.get(counterpart.logical_id, set()) | unit_index.get(
            incoming.logical_id, set()
        )
        for facet, row in resolved.items():
            verdict, obligation = row["verdict"], row["obligation"]
            facet_verdict_counts[facet][verdict] += 1
            if verdict == facets.UNRESOLVED:
                unresolved_observations += 1
            if verdict == facets.IGNORED_BY_PREDECLARED_POLICY and facet not in ignored:
                i7.append(
                    {
                        "logical_id": counterpart.logical_id,
                        "facet": facet,
                        "why": "an ignore that the frozen declaration does not name",
                    }
                )
            if obligation not in (oracle.REQUIRE_TYPED_CHANGE, oracle.REQUIRE_FAIL_CLOSED):
                if verdict == facets.CHANGED and obligation in (
                    oracle.NO_OBLIGATION,
                    oracle.IGNORED_BY_PREDECLARED_POLICY,
                ):
                    change_equivalent_observations += 1
                    if facet not in ignored:
                        i7.append(
                            {
                                "logical_id": counterpart.logical_id,
                                "facet": facet,
                                "why": "a changed facet treated as change-equivalent "
                                "without a predeclared ignore",
                            }
                        )
                continue

            if obligation == oracle.REQUIRE_FAIL_CLOSED:
                required = unresolved_records.get(facet)
                if required is None:
                    # A declared gap, counted rather than discharged. Production
                    # has no fail-closed behaviour for an absent value on this
                    # facet -- see the frozen protocol's `unresolved_fail_closed`
                    # -- so there is no record to demand. It is recorded as
                    # unresolved and never as unchanged, which is the half of
                    # INVARIANT_5 that applies here.
                    unresolved_without_failclosed += 1
                    continue
            else:
                required = records.get(facet)
                if required is None:  # pragma: no cover -- channels/records agree
                    i4.append(
                        {
                            "logical_id": counterpart.logical_id,
                            "facet": facet,
                            "why": "a production channel is declared with no record name",
                        }
                    )
                    continue
            if verdict == facets.CHANGED:
                changed_observations += 1
            present = (
                required in document_kinds
                if scopes.get(facet) == "document"
                else required in pair_kinds
            )
            if present:
                continue
            entry = {
                "logical_id": counterpart.logical_id,
                "facet": facet,
                "verdict": verdict,
                "required_record": required,
                "scope": scopes.get(facet, "unit"),
                "why": "a facet that moved produced no typed change",
            }
            i4.append(entry)
            if facet == facets.CONTENT:
                i5.append({**entry, "why": "CONTENT did not fail closed"})

    return {
        "lineage_id": after_document["source_id"],
        "before_unit_count": len(before_units),
        "after_unit_count": len(after_units),
        "matched_pair_count": len(pairs),
        "ambiguous_decisions_excluded": ambiguous_excluded,
        "ambiguity_observations": ambiguity_observations,
        "changed_facet_observations": changed_observations,
        "unresolved_facet_observations": unresolved_observations,
        "unresolved_without_a_production_fail_closed_behaviour": unresolved_without_failclosed,
        "change_equivalent_observations": change_equivalent_observations,
        "facet_verdicts": facet_verdict_counts,
        "legacy_modified_count": sum(
            1 for c in legacy_diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM
        ),
        "new_modified_count": sum(
            1 for c in new_diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM
        ),
        "violations": {
            "INVARIANT_1": i1,
            "INVARIANT_4": i4,
            "INVARIANT_5": i5,
            "INVARIANT_6": i6,
            "INVARIANT_7": i7,
        },
    }


# --------------------------------------------------------------------------
# the fixture battery
# --------------------------------------------------------------------------

_FIXTURE_TEXT = "The permit holder shall retain records for three years after closure."

_FIXTURE_BASE = {
    "logical_id": "u:fixture",
    "text": _FIXTURE_TEXT,
    "document_path": ("fixture", "Chapter", "Records"),
    "anchor": "Records",
    "neighbour_anchors": ("", ""),
    "explicit_identifier": "Chapter/Records",
    "evidence_id": "e:u:fixture",
}


def _facet_fixture(
    before_kw: dict[str, Any], after_kw: dict[str, Any], expect: str
) -> dict[str, Any]:
    before = [UnitSnapshot(**{**_FIXTURE_BASE, **before_kw})]
    after = [UnitSnapshot(**{**_FIXTURE_BASE, **after_kw})]
    diff = diff_documents(
        before_sha256="sha256:fixture-before",
        after_sha256="sha256:fixture-after",
        level=DiffLevel.GRAPH,
        before_shape=_shape_of(before),
        after_shape=_shape_of(after),
        before_units=before,
        after_units=after,
        source="fixture",
        legacy_identity_change_predicate=False,
    )
    kinds = _document_kinds(diff)
    return {
        "expected_record": expect,
        "records": sorted(kinds),
        "held": expect in kinds,
    }


def _fold_fixture(name: str) -> dict[str, Any]:
    before, after = fold_class_pair(name, _FIXTURE_TEXT)
    folded_equal = normalize_text_for_identity(before) == normalize_text_for_identity(after)
    return {
        "raw_differ": before != after,
        "folds_equal": folded_equal,
        "held": folded_equal and before != after,
    }


def _ambiguity_fixture() -> dict[str, Any]:
    """A unit whose incoming side carries no text: the resolver abstains.

    The reordered-document route INC-V2-038 describes does not reach AMBIGUOUS
    on this unit representation — the explicit identifier survives a reorder and
    carries the score over the bar — so the fixture uses the review-band route
    instead. Which route it takes is recorded here rather than left implied.
    """
    before = [UnitSnapshot(**_FIXTURE_BASE)]
    after = [UnitSnapshot(**{**_FIXTURE_BASE, "text": ""})]
    diff = diff_documents(
        before_sha256="sha256:fixture-before",
        after_sha256="sha256:fixture-after",
        level=DiffLevel.GRAPH,
        before_shape=_shape_of(before),
        after_shape=_shape_of(after),
        before_units=before,
        after_units=after,
        source="fixture",
        legacy_identity_change_predicate=False,
    )
    violations, observations = check_ambiguity(diff)
    pairs, ambiguous = matched_pairs(before, after, "fixture")
    return {
        "route": "review band",
        "identity_unresolved_records": observations,
        "ambiguous_decisions_excluded_from_matching": ambiguous,
        "matched_pairs": len(pairs),
        "violations": violations,
        "held": observations > 0 and ambiguous > 0 and not pairs and not violations,
    }


def _content_unresolved_fixture() -> dict[str, Any]:
    """Production's own projection must answer `unresolved`, never `unchanged`.

    Called directly, not through `diff_documents`: the fingerprint normalizes
    `text` before the predicate runs and raises on a non-str, so the fail-closed
    branch cannot be reached end to end on this unit representation. The
    protocol declares that limitation; this fixture records that the projection
    itself is correct, and does not pretend to have exercised the branch.
    """
    before = UnitSnapshot(**_FIXTURE_BASE)
    after = UnitSnapshot(**{**_FIXTURE_BASE, "text": None})  # type: ignore[arg-type]
    production = content_facet_verdict(before, after)
    try:
        independent: str = facets.change_facets(before, after)[facets.CONTENT]
    except Exception as error:
        # `change_facets._content_projection` has no non-str guard where
        # `semantic_diff._content_facet_projection` does, so the independent
        # module raises where production answers `unresolved`. Raising is still
        # fail-closed -- it is not `unchanged` -- so this is a divergence to
        # report, not a violation, and it is NOT repaired here: editing the
        # facet contract to make a fixture hold is fitting the contract to the
        # check.
        independent = f"raised:{type(error).__name__}"
    reachable_end_to_end = True
    try:
        after.fingerprint(source_lineage="fixture")
    except TypeError:
        reachable_end_to_end = False
    return {
        "production_verdict": str(production),
        "independent_module_behaviour": independent,
        "independent_module_agrees": independent == facets.UNRESOLVED,
        "reachable_through_diff_documents": reachable_end_to_end,
        "held": str(production) == facets.UNRESOLVED,
    }


FIXTURE_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "fold_nfkc_compatibility": lambda: _fold_fixture("nfkc_compatibility"),
    "fold_case_only": lambda: _fold_fixture("case_only"),
    "fold_punctuation_to_space": lambda: _fold_fixture("punctuation_to_space"),
    "fold_whitespace_collapse": lambda: _fold_fixture("whitespace_collapse"),
    "facet_temporal_changed": lambda: _facet_fixture(
        {"temporal_fingerprint": "t1"}, {"temporal_fingerprint": "t2"}, "temporal_changed"
    ),
    "facet_metadata_changed": lambda: _facet_fixture(
        {"metadata_fingerprint": "m1"}, {"metadata_fingerprint": "m2"}, "metadata_changed"
    ),
    "facet_visual_changed": lambda: _facet_fixture(
        {"visual_fingerprint": "v1"}, {"visual_fingerprint": "v2"}, "visual_changed"
    ),
    "facet_authority_changed": lambda: _facet_fixture(
        {"authority": "EPA"}, {"authority": "OSHA"}, "authority_changed"
    ),
    "facet_locator_changed": lambda: _facet_fixture(
        {"evidence_id": "e:1", "page_number1": 1},
        {"evidence_id": "e:2", "page_number1": 2},
        "evidence_moved",
    ),
    "content_unresolved_projection_fails_closed": _content_unresolved_fixture,
    "ambiguous_identity_stays_unresolved": _ambiguity_fixture,
}


def run_fixture_battery(declared: dict[str, Any]) -> dict[str, Any]:
    """Development gate power, declared before execution and never summed in.

    The declaration and the builders must name the same set. A builder with no
    declaration is power nobody agreed to count; a declaration with no builder
    is a fixture that silently never ran, which is this study's oldest defect.
    """
    declared_ids = set(declared)
    built_ids = set(FIXTURE_BUILDERS)
    drift = {
        "declared_without_a_builder": sorted(declared_ids - built_ids),
        "built_without_a_declaration": sorted(built_ids - declared_ids),
    }
    results = {name: FIXTURE_BUILDERS[name]() for name in sorted(declared_ids & built_ids)}
    failed = sorted(name for name, row in results.items() if not row["held"])
    return {
        "declared": sorted(declared_ids),
        "drift": drift,
        "results": results,
        "failed": failed,
        "held": not failed
        and not drift["declared_without_a_builder"]
        and not drift["built_without_a_declaration"],
    }


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------


def _verdict(violations: list[Any], observations: int) -> str:
    if violations:
        return VIOLATED
    return MET if observations > 0 else UNPROVEN


def grade(
    *,
    pairs: list[dict[str, Any]],
    fold: dict[str, Any],
    independence: dict[str, Any],
    mapping: dict[str, Any],
    fixtures: dict[str, Any],
    disjointness: dict[str, Any],
) -> dict[str, Any]:
    """The eight invariants, each with its own population and its own power.

    A zero-observation invariant is UNPROVEN, never MET, and an UNPROVEN
    invariant can never contribute to a PASS. A closure over zero pairs is
    VACUOUS_FAIL before any invariant is read.
    """

    def collected(key: str) -> list[Any]:
        rows: list[Any] = []
        for pair in pairs:
            for row in pair["violations"][key]:
                rows.append({"lineage_id": pair["lineage_id"], **row})
        return rows

    resolved_pairs = len(pairs)
    matched_total = sum(pair["matched_pair_count"] for pair in pairs)
    changed_total = sum(pair["changed_facet_observations"] for pair in pairs)
    unresolved_total = sum(pair["unresolved_facet_observations"] for pair in pairs)
    facet_total = sum(pair["matched_pair_count"] * len(facets.FACETS) for pair in pairs)
    unresolved_gap_total = sum(
        pair["unresolved_without_a_production_fail_closed_behaviour"] for pair in pairs
    )
    ambiguity_cohort = sum(pair["ambiguity_observations"] for pair in pairs)
    ambiguity_fixture = (
        fixtures["results"]
        .get("ambiguous_identity_stays_unresolved", {})
        .get("identity_unresolved_records", 0)
    )

    fixture_violations = (
        [{"why": "a declared fixture did not hold", "fixtures": fixtures["failed"]}]
        if fixtures["failed"]
        else []
    ) + (
        [{"why": "the fixture battery drifted from its declaration", **fixtures["drift"]}]
        if fixtures["drift"]["declared_without_a_builder"]
        or fixtures["drift"]["built_without_a_declaration"]
        else []
    )

    i2_violations = list(fold["violations"]) + [
        row for row in fixture_violations if "fold" in json.dumps(row)
    ]
    if fold["lossiness_witnesses"] == 0:
        i2_violations.append(
            {"why": "no real text witnessed the fold being lossy; the check has no power"}
        )

    i6_violations = collected("INVARIANT_6") + [
        row
        for row in fixture_violations
        if "ambiguous_identity_stays_unresolved" in json.dumps(row)
    ]

    invariants = {
        "INVARIANT_1_identity_decisions_unchanged": {
            "verdict": _verdict(collected("INVARIANT_1"), resolved_pairs),
            "population": "resolved pairs",
            "exercising_observations": resolved_pairs,
            "violations": collected("INVARIANT_1"),
        },
        "INVARIANT_2_identity_fold_remains_identity_only": {
            "verdict": _verdict(i2_violations, fold["observations"]),
            "population": "fold classes x cohort texts, plus the fold fixtures",
            "exercising_observations": fold["observations"],
            "lossiness_witnesses": fold["lossiness_witnesses"],
            "per_class": fold["per_class"],
            "violations": i2_violations,
        },
        "INVARIANT_3_expectation_is_independent": {
            "verdict": _verdict(
                independence["violations"], independence["observations"] and resolved_pairs
            ),
            "population": "the oracle module set, exercised over every resolved pair",
            "exercising_observations": resolved_pairs,
            "modules_inspected": independence["modules_inspected"],
            "signature": independence["signature"],
            "violations": independence["violations"],
        },
        "INVARIANT_4_changed_facet_resolves_typed_or_failclosed": {
            "verdict": _verdict(collected("INVARIANT_4"), changed_total),
            "population": "changed, non-ignored facet observations",
            "exercising_observations": changed_total,
            "violations": collected("INVARIANT_4"),
        },
        "INVARIANT_5_never_silently_unchanged": {
            "verdict": _verdict(
                list(mapping["violations"]) + collected("INVARIANT_5"),
                mapping["observations"] and unresolved_total,
            ),
            "population": "the oracle's 72-combination domain, plus every facet observation",
            "mapping_combinations_evaluated": mapping["combinations_evaluated"],
            "exercising_observations": unresolved_total,
            "unresolved_observations": unresolved_total,
            "unresolved_without_a_production_fail_closed_behaviour": unresolved_gap_total,
            "declared_gap": (
                "production has no fail-closed behaviour for an absent fingerprint "
                "on the non-CONTENT facets; those observations are counted here, "
                "never recorded as unchanged, and never counted as evidence that "
                "the channel works. See the frozen protocol's unresolved_fail_closed."
            ),
            "violations": list(mapping["violations"]) + collected("INVARIANT_5"),
        },
        "INVARIANT_6_ambiguous_identity_stays_unresolved": {
            "verdict": _verdict(i6_violations, ambiguity_cohort + ambiguity_fixture),
            "population": "identity_unresolved records; cohort and fixture counted apart",
            "cohort_observations": ambiguity_cohort,
            "fixture_observations": ambiguity_fixture,
            "cohort_gate_power": "present" if ambiguity_cohort else "none",
            "violations": i6_violations,
        },
        "INVARIANT_7_only_predeclared_ignores": {
            "verdict": _verdict(collected("INVARIANT_7"), facet_total),
            "population": "every (matched pair, facet) observation",
            "exercising_observations": facet_total,
            "change_equivalent_observations": sum(
                pair["change_equivalent_observations"] for pair in pairs
            ),
            "violations": collected("INVARIANT_7"),
        },
        "INVARIANT_8_sfi2_cases_cannot_certify": {
            "verdict": _verdict(disjointness["violations"], resolved_pairs),
            "population": "the frozen universe",
            "exercising_observations": resolved_pairs,
            "sfi2_pairs_in_any_denominator": 0,
            "retrospective_receipts_read_for_grading": [],
            "violations": disjointness["violations"],
        },
    }

    if resolved_pairs == 0:
        overall = "VACUOUS_FAIL"
    elif any(row["verdict"] == VIOLATED for row in invariants.values()):
        overall = "FAIL"
    elif any(row["verdict"] == UNPROVEN for row in invariants.values()):
        overall = "UNPROVEN"
    else:
        overall = "PASS"

    return {
        "overall": overall,
        "pairs_resolved": resolved_pairs,
        "matched_pairs_total": matched_total,
        "facet_observations_total": facet_total,
        "invariants": invariants,
        "fixture_battery": {
            "standing": "DEVELOPMENT_GATE_POWER_ONLY",
            "never_summed_into_a_cohort_denominator": True,
            "held": fixtures["held"],
            "failed": fixtures["failed"],
            "drift": fixtures["drift"],
            "results": fixtures["results"],
        },
    }


# --------------------------------------------------------------------------
# preconditions and the run
# --------------------------------------------------------------------------


def universe_receipt() -> dict[str, Any]:
    runs = runs_of(UNIVERSE_STEM)
    if not runs:
        raise ClosureRefused(
            "the cohort universe has not been frozen. Run "
            "`freeze_migration_closure.py universe` first -- measuring against "
            "an unfrozen universe is how a cohort gets chosen by its result."
        )
    body = json.loads((ROOT / runs[-1]).read_text(encoding="utf-8"))
    body["_receipt_path"] = runs[-1]
    return body


def _channel_tables(
    protocol: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, str | None], dict[str, str | None], dict[str, str]]:
    declared = protocol["facet_channels"]
    missing = set(facets.FACETS) - set(declared)
    if missing:
        raise ClosureRefused(f"the frozen protocol declares no channel for {sorted(missing)}")
    channels = {facet: bool(declared[facet]["has_production_channel"]) for facet in facets.FACETS}
    records = {facet: declared[facet]["production_record"] for facet in facets.FACETS}
    unresolved_records = {
        facet: declared[facet]["unresolved_production_record"] for facet in facets.FACETS
    }
    scopes = {facet: declared[facet]["scope"] for facet in facets.FACETS}
    return channels, records, unresolved_records, scopes


def _sample_texts(document: dict[str, Any], per_document: int = 4) -> list[str]:
    """Deterministic text sample: fixed indices, never a random draw."""
    units = [unit["text"] for unit in document["units"] if isinstance(unit.get("text"), str)]
    if not units:
        return []
    if len(units) <= per_document:
        return units
    span = len(units) - 1
    indices = sorted({0, span // 3, (2 * span) // 3, span})
    return [units[index] for index in indices]


def run(limit: int | None = None) -> dict[str, Any]:
    started = time.time()
    protocol_receipt = require_frozen_protocol()
    protocol = load_protocol()
    universe = universe_receipt()

    if universe.get("protocol_sha256") != protocol_receipt["protocol_sha256"]:
        raise ClosureRefused("the frozen universe was built against a different protocol digest")

    channels, records, unresolved_records, scopes = _channel_tables(protocol)
    ignore_declaration = protocol["predeclared_ignored_facets"]["by_family"]
    forbidden_imports = tuple(protocol["expectation_oracle"]["forbidden_imports"])
    forbidden_attrs = tuple(protocol["expectation_oracle"]["forbidden_attribute_reads"])

    rows = universe["pairs"] if limit is None else universe["pairs"][:limit]
    pair_results: list[dict[str, Any]] = []
    texts: list[str] = []
    for row in rows:
        before_document = json.loads(
            (ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8")
        )
        after_document = json.loads(
            (ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8")
        )
        declared_ignores = ignore_declaration.get(row["family"])
        if declared_ignores is None:
            raise ClosureRefused(
                f"the frozen protocol declares no ignore policy for family {row['family']!r}"
            )
        unknown = set(declared_ignores) - set(facets.FACETS)
        if unknown:
            raise ClosureRefused(
                f"the frozen ignore declaration names a non-facet: {sorted(unknown)}"
            )
        result = measure_pair(
            before_document,
            after_document,
            channels=channels,
            records=records,
            unresolved_records=unresolved_records,
            scopes=scopes,
            ignored=frozenset(declared_ignores),
        )
        result["lineage_id"] = row["lineage_id"]
        result["family"] = row["family"]
        pair_results.append(result)
        texts.extend(_sample_texts(before_document))

    fold = measure_identity_fold(texts, classes=tuple(FOLD_CLASSES))
    independence = audit_oracle_independence(
        forbidden_imports=forbidden_imports, forbidden_attributes=forbidden_attrs
    )
    mapping = audit_obligation_mapping()
    fixtures = run_fixture_battery(protocol["fixture_battery"]["classes"])

    disjointness = {
        "from_the_538_pair_retrospective_cohort": universe["disjointness"][
            "from_the_538_pair_retrospective_cohort"
        ]["holds"],
        "from_the_14_sfi2_forensic_cases": universe["disjointness"][
            "from_the_14_sfi2_forensic_cases"
        ]["holds"],
        "violations": [],
    }
    for key in (
        "from_the_538_pair_retrospective_cohort",
        "from_the_14_sfi2_forensic_cases",
    ):
        overlap = universe["disjointness"][key]["overlap"]
        if overlap or not universe["disjointness"][key]["holds"]:
            disjointness["violations"].append({"why": f"{key} does not hold", "overlap": overlap})

    graded = grade(
        pairs=pair_results,
        fold=fold,
        independence=independence,
        mapping=mapping,
        fixtures=fixtures,
        disjointness=disjointness,
    )

    return {
        "schema": SCHEMA,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": protocol_receipt["protocol_sha256"],
        "protocol_freeze_receipt": protocol_receipt["_receipt_path"],
        "protocol_freeze_run_id": protocol_receipt["provenance"]["run_id"],
        "universe_freeze_receipt": universe["_receipt_path"],
        "universe_freeze_run_id": universe["provenance"]["run_id"],
        "universe_sha256": universe["universe_sha256"],
        "freeze_precedes_measurement": {
            "protocol_freeze_run_id": protocol_receipt["provenance"]["run_id"],
            "universe_freeze_run_id": universe["provenance"]["run_id"],
            "enforced_by": (
                "this tool refuses to run without both receipts and without a "
                "protocol digest match; the run ids carry the wall-clock stamps "
                "as corroboration"
            ),
        },
        "path_taken": universe["path_taken"],
        "cohort_pairs_declared": universe["pair_count"],
        "limit": limit,
        "legacy_reference_path": {
            "preserved": True,
            "flag": "legacy_identity_change_predicate=True",
            "used_for": "identity-continuity comparison only",
            "never_used_as": "ground truth; the legacy predicate is the defect under repair",
        },
        "over_fire_reading": {
            "legacy_modified_total": sum(row["legacy_modified_count"] for row in pair_results),
            "new_modified_total": sum(row["new_modified_count"] for row in pair_results),
            "note": (
                "reported descriptively and graded by nothing. No acceptance "
                "criterion in this closure reads a disagreement count, and no "
                "over-fire is called a false positive."
            ),
        },
        **graded,
        "oracle_independence": independence,
        "obligation_mapping": mapping,
        "identity_fold": fold,
        "wall_seconds": round(time.time() - started, 1),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "pairs": pair_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument(
        "--fixtures-only",
        action="store_true",
        help="run the pre-freeze fixture smoke and nothing else; reads no cohort pair",
    )
    args = parser.parse_args()

    if args.fixtures_only:
        declared = load_protocol()["fixture_battery"]["classes"]
        report = run_fixture_battery(declared)
        print(json.dumps(report, indent=1, default=str))
        return 0 if report["held"] else 1

    try:
        report = run(args.limit)
    except (ClosureRefused, FreezeRefused) as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4

    summary = {key: value for key, value in report.items() if key != "pairs"}
    print(json.dumps(summary, indent=1, default=str))

    if args.write_receipt:
        pinned = {key: value for key, value in report.items() if key != "pairs"}
        pinned["pair_count_measured"] = len(report["pairs"])
        pinned.update(
            write_immutable(STEM, pinned, tool=Path(__file__).resolve(), protocol=PROTOCOL)
        )
        print("receipt:", pinned.get("receipt"))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
