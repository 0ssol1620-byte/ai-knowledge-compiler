"""`source_fact_ir/change_facets.py` -- the identity/change separation shadow.

Four kinds of test here, deliberately kept apart, in this order:

1. **Partition** -- every call returns exactly the nine declared facet keys,
   never more, never fewer, and the two data-source-free facets never report
   anything but `UNRESOLVED`.
2. **Reachability** -- every declared facet can actually produce more than one
   verdict; a facet frozen to a single value regardless of input would be
   declared but dead, and this is what would have caught that.
3. **Identity-regression control** -- pairs that are genuinely the same unit
   still resolve `UNCHANGED`, and a pure Unicode-encoding difference (no
   information content changed, just which codepoints spell the same
   character) is *not* reported as a CONTENT change. This is the check that
   this shadow does not just flip the bug from false-negative to false-positive.
4. **Real-data differential** -- replays the 14 SFI2 confirmed selective stale
   escapes (`receipts/sfi2-native-provenance--20260823T085006Z-e53cc8aaeb7d
   .json`, `rebuild.E5_confirmed_selective_stale_escape.confirmed`) through
   this module and asserts the property INC-V2-037 requires: every one of the
   14 cases, which `akc_cir.semantic_diff`'s `identity_text` gate reports as
   *no change* (`MODIFIED_CLAIM` never emitted), resolves CONTENT=CHANGED
   here. Skipped, not failed, when the frozen receipt, lineage frame or
   payload cache is not present in this checkout -- their absence is an
   environment fact, not a defect in this module. No network is ever touched;
   every payload comes from `artifacts/development/sfi2_cache/`.

This file does not modify `tools/forensic_sfi2_execution.py`. It imports
`load_cases`, `load_lineages`, `fetch_payload`, `build_document` and
`CACHE_ROOT`/`LINEAGES` from it (the same payload/cache mechanics
`test_forensic_sfi2_execution.py` already uses) and `snapshots` from
`compiler/selective_build.py`, purely to reconstruct the real `UnitSnapshot`
pairs to hand to `change_facets()`. Nothing here calls `diff_documents` for
any purpose other than reporting, in the differential, what the *old*
predicate said -- `change_facets()` itself is never given `semantic_diff`'s
answer to check its own.
"""

from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import forensic_sfi2_execution as forensic  # noqa: E402
import selective_build as engine  # noqa: E402
from payload_cache import PayloadCache  # noqa: E402
from source_fact_ir import change_facets as cf  # noqa: E402

REAL_DATA_MISSING = not (
    forensic.LINEAGES.exists()
    and forensic.CACHE_ROOT.exists()
    and any(NS.glob("receipts/sfi2-native-provenance--*.json"))
)
skip_without_real_data = pytest.mark.skipif(
    REAL_DATA_MISSING,
    reason="frozen sfi2-native-provenance receipt, lineage frame or payload cache not present",
)


# ---------------------------------------------------------------------------
# a minimal UnitLike fixture -- deliberately not `akc_cir.semantic_diff
# .UnitSnapshot`, to prove `change_facets()` needs nothing from that module
# to run at all.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str = "same text, filler enough to not matter for this shadow."
    document_path: tuple[str, ...] = ("src", "h1", "h2")
    anchor: str = "h2"
    explicit_identifier: str = "h1/h2"
    evidence_id: str | None = "e:u1"
    page_number1: int | None = 3
    temporal_fingerprint: str = ""
    metadata_fingerprint: str = ""
    visual_fingerprint: str = ""
    authority: str | None = None


def _pair(**after_overrides: Any) -> tuple[_Unit, _Unit]:
    before = _Unit()
    after = replace(before, **after_overrides)
    return before, after


# --- 1. partition -----------------------------------------------------------


@pytest.mark.parametrize(
    "before,after",
    [
        _pair(),
        _pair(text="a wholly different sentence, still filler enough to count."),
        _pair(
            document_path=("src", "h1", "h9"),
            anchor="h9",
            explicit_identifier="h1/h9",
            temporal_fingerprint="t2",
            metadata_fingerprint="m2",
            visual_fingerprint="v2",
            authority="jurisdiction-b",
            evidence_id=None,
        ),
    ],
)
def test_every_call_returns_exactly_the_declared_facet_keys(
    before: _Unit, after: _Unit
) -> None:
    verdicts = cf.change_facets(before, after)
    assert set(verdicts) == set(cf.FACETS)
    assert all(v in cf.VERDICTS for v in verdicts.values())


def test_data_source_free_facets_are_always_unresolved_never_silently_ignored() -> None:
    before, after = _pair(text="content moved, and every optional field is populated too.")
    before = replace(
        before,
        temporal_fingerprint="t1",
        metadata_fingerprint="m1",
        visual_fingerprint="v1",
        authority="jurisdiction-a",
    )
    after = replace(
        after,
        temporal_fingerprint="t1",
        metadata_fingerprint="m1",
        visual_fingerprint="v1",
        authority="jurisdiction-a",
    )
    verdicts = cf.change_facets(before, after)
    assert verdicts[cf.ACCESSIBILITY] == cf.UNRESOLVED
    assert verdicts[cf.EXTERNAL_DEPENDENCY_EXECUTION] == cf.UNRESOLVED
    # every other facet in this fixture *did* resolve, so the two above are
    # not unresolved because nothing else could be either.
    assert verdicts[cf.CONTENT] == cf.CHANGED


def test_ignoring_an_unknown_facet_name_raises_rather_than_silently_accepting_it() -> None:
    before, after = _pair()
    with pytest.raises(ValueError, match="not a declared facet"):
        cf.change_facets(before, after, ignored_facets=frozenset({"NOT_A_FACET"}))


def test_facets_with_verdict_rejects_an_undeclared_verdict() -> None:
    before, after = _pair()
    verdicts = cf.change_facets(before, after)
    with pytest.raises(ValueError, match="not a declared verdict"):
        cf.facets_with_verdict(verdicts, "sort-of-changed")


# --- 2. reachability: every declared facet can produce more than one verdict


def test_content_facet_reaches_changed_and_unchanged() -> None:
    same_before, same_after = _pair()
    assert cf.change_facets(same_before, same_after)[cf.CONTENT] == cf.UNCHANGED

    before, after = _pair(text="a materially different sentence, filler included too.")
    assert cf.change_facets(before, after)[cf.CONTENT] == cf.CHANGED


def test_structural_facet_reaches_changed_and_unchanged_and_ignores_source_id() -> None:
    same_before, same_after = _pair()
    assert cf.change_facets(same_before, same_after)[cf.STRUCTURAL] == cf.UNCHANGED

    # the source-id component of document_path differs but nothing about the
    # unit's own position does -- STRUCTURAL must not fire on that alone.
    before = _Unit(document_path=("src-one", "h1", "h2"))
    after = _Unit(document_path=("src-two", "h1", "h2"))
    assert cf.change_facets(before, after)[cf.STRUCTURAL] == cf.UNCHANGED

    moved_before, moved_after = _pair(
        document_path=("src", "h1", "h9"), anchor="h9", explicit_identifier="h1/h9"
    )
    assert cf.change_facets(moved_before, moved_after)[cf.STRUCTURAL] == cf.CHANGED


def test_reference_locator_facet_reaches_all_three_data_driven_verdicts() -> None:
    same_before, same_after = _pair()
    assert cf.change_facets(same_before, same_after)[cf.REFERENCE_LOCATOR] == cf.UNCHANGED

    moved_before, moved_after = _pair(evidence_id="e:u2")
    assert cf.change_facets(moved_before, moved_after)[cf.REFERENCE_LOCATOR] == cf.CHANGED

    unset_before, unset_after = _pair(evidence_id=None)
    assert cf.change_facets(unset_before, unset_after)[cf.REFERENCE_LOCATOR] == cf.UNRESOLVED


@pytest.mark.parametrize(
    "facet,field",
    [
        (cf.TEMPORAL, "temporal_fingerprint"),
        (cf.METADATA, "metadata_fingerprint"),
        (cf.VISUAL, "visual_fingerprint"),
    ],
)
def test_optional_fingerprint_facets_reach_all_three_data_driven_verdicts(
    facet: str, field: str
) -> None:
    # neither side ever populated this fingerprint -- unresolved, not "no change"
    unset_before, unset_after = _pair()
    assert cf.change_facets(unset_before, unset_after)[facet] == cf.UNRESOLVED

    same_before = replace(_Unit(), **{field: "fp-1"})
    same_after = replace(_Unit(), **{field: "fp-1"})
    assert cf.change_facets(same_before, same_after)[facet] == cf.UNCHANGED

    before = replace(_Unit(), **{field: "fp-1"})
    after = replace(_Unit(), **{field: "fp-2"})
    assert cf.change_facets(before, after)[facet] == cf.CHANGED


def test_authority_facet_reaches_all_four_verdicts() -> None:
    unset_before, unset_after = _pair()
    assert cf.change_facets(unset_before, unset_after)[cf.AUTHORITY_APPLICABILITY] == (
        cf.UNRESOLVED
    )

    same_before = _Unit(authority="jurisdiction-a")
    same_after = _Unit(authority="jurisdiction-a")
    assert cf.change_facets(same_before, same_after)[cf.AUTHORITY_APPLICABILITY] == (
        cf.UNCHANGED
    )

    before = _Unit(authority="jurisdiction-a")
    after = _Unit(authority="jurisdiction-b")
    assert cf.change_facets(before, after)[cf.AUTHORITY_APPLICABILITY] == cf.CHANGED

    # a family with no jurisdiction concept declares this out of scope in
    # advance, rather than letting two absent values read as a false UNCHANGED.
    ignored = cf.change_facets(
        before, after, ignored_facets=frozenset({cf.AUTHORITY_APPLICABILITY})
    )
    assert ignored[cf.AUTHORITY_APPLICABILITY] == cf.IGNORED_BY_PREDECLARED_POLICY


@pytest.mark.parametrize("facet", sorted(cf.FACETS_WITHOUT_DATA_SOURCE))
def test_no_data_source_facets_reach_unresolved_and_ignored_but_never_changed(
    facet: str,
) -> None:
    before, after = _pair(text="a materially different sentence, filler included too.")
    assert cf.change_facets(before, after)[facet] == cf.UNRESOLVED
    ignored = cf.change_facets(before, after, ignored_facets=frozenset({facet}))
    assert ignored[facet] == cf.IGNORED_BY_PREDECLARED_POLICY


def test_every_declared_facet_is_reached_by_this_suite() -> None:
    """The partition-completeness check the plan requires: nothing declared
    in `FACETS` is untested, and nothing tested is undeclared."""
    exercised = {
        cf.CONTENT,
        cf.STRUCTURAL,
        cf.REFERENCE_LOCATOR,
        cf.TEMPORAL,
        cf.AUTHORITY_APPLICABILITY,
        cf.METADATA,
        cf.VISUAL,
        cf.ACCESSIBILITY,
        cf.EXTERNAL_DEPENDENCY_EXECUTION,
    }
    assert exercised == set(cf.FACETS)


# --- 3. identity-regression control -----------------------------------------


def test_identical_text_is_unchanged_the_same_unit_still_matches() -> None:
    before, after = _pair()
    verdicts = cf.change_facets(before, after)
    assert verdicts[cf.CONTENT] == cf.UNCHANGED
    assert verdicts[cf.STRUCTURAL] == cf.UNCHANGED


def test_pure_unicode_encoding_difference_is_not_reported_as_a_content_change() -> None:
    """`café` (e + combining acute) and `café` (precomposed e-acute)
    are the same visible text spelled with two different codepoint sequences.
    No information changed -- this is exactly the "formatting-only change
    lands as CONTENT unchanged" case the compatibility contract names, and it
    is the control against the differential below: a shadow whose CONTENT
    facet fired on *this* too would not be bounding the SFI2 over-fire risk,
    it would just be a raw byte-equality check wearing a facet name.
    """
    decomposed = "café is on the menu, filler included to pass the length floor."
    composed = "café is on the menu, filler included to pass the length floor."
    assert decomposed != composed  # genuinely different codepoint sequences
    assert unicodedata.normalize("NFC", decomposed) == unicodedata.normalize("NFC", composed)
    before = _Unit(text=decomposed)
    after = _Unit(text=composed)
    assert cf.change_facets(before, after)[cf.CONTENT] == cf.UNCHANGED


def test_a_real_content_change_that_identity_folds_away_is_still_caught() -> None:
    """The shape of all 14 SFI2 cases, without the production pipeline: a
    registered-trademark sign is inserted. `normalize_text_for_identity`
    folds punctuation to a space, so an identity-text comparison would call
    this unchanged -- `change_facets()` imports no identity fold at all and
    catches it anyway."""
    before = _Unit(text="Apache Druid is a database, filler included to pass the floor.")
    after = _Unit(text="Apache® Druid is a database, filler included to pass the floor.")
    assert cf.change_facets(before, after)[cf.CONTENT] == cf.CHANGED


# --- 4. real-data differential: the 14 confirmed SFI2 cases ------------------


def _matched_units_for(
    lineage: dict[str, Any], case: dict[str, Any], cache: PayloadCache
) -> list[tuple[str, Any, Any]]:
    """`(artifact_key, before_unit, after_unit)` for each artifact the case
    names, built the same way `forensic.trace_case` builds its own snapshots
    -- `provenance_document` + `selective_build.snapshots`, nothing patched.
    """
    before_raw = forensic.fetch_payload(cache, lineage, case["before_version"])
    after_raw = forensic.fetch_payload(cache, lineage, case["after_version"])
    before_doc = forensic.build_document(lineage, case["before_version"], before_raw)
    after_doc = forensic.build_document(lineage, case["after_version"], after_raw)
    before_units, _ = engine.snapshots(before_doc)
    after_units, _ = engine.snapshots(after_doc)
    by_before = {u.logical_id: u for u in before_units}
    by_after = {u.logical_id: u for u in after_units}

    rows: list[tuple[str, Any, Any]] = []
    for artifact in case.get("artifacts") or case.get("keys") or []:
        logical = artifact.split("section:", 1)[-1] if artifact.startswith("section:") else None
        before_unit = by_before.get(logical)
        after_unit = by_after.get(logical)
        if before_unit is not None and after_unit is not None:
            rows.append((artifact, before_unit, after_unit))
    return rows


@skip_without_real_data
def test_differential_all_fourteen_confirmed_cases_are_caught_by_content_facet() -> None:
    """The differential the plan requires: for every one of the 14 E5-confirmed
    cases, report what the old identity-fold predicate said and what this
    shadow's CONTENT facet says, then assert the property INC-V2-037 exists to
    restore -- the old predicate said *no change* on all 14 (that is the
    frozen finding this whole lane traces back to), and CONTENT must say
    CHANGED on all 14, independently, without ever having been told the old
    predicate's answer.
    """
    cases, meta = forensic.load_cases()
    assert meta["e5_confirmed_count"] == 14
    lineages = forensic.load_lineages()
    cache = PayloadCache(forensic.CACHE_ROOT, "cache-only-forensic-replay")

    report: list[dict[str, Any]] = []
    for case in cases:
        lineage = lineages[case["lineage_id"]]
        old_predicate = forensic.trace_case(lineage, case, cache)
        assert old_predicate["resolved"], old_predicate.get("unresolved_reason")

        for artifact, before_unit, after_unit in _matched_units_for(lineage, case, cache):
            old_row = next(
                row for row in old_predicate["artifacts"] if row["artifact"] == artifact
            )
            new_verdicts = cf.change_facets(before_unit, after_unit)
            report.append(
                {
                    "lineage_id": case["lineage_id"],
                    "artifact": artifact,
                    "old_identity_text_equal": old_row["identity_text_equal"],
                    "old_modified_claim_emitted": old_row["modified_claim_emitted"],
                    "new_content_verdict": new_verdicts[cf.CONTENT],
                    "new_structural_verdict": new_verdicts[cf.STRUCTURAL],
                }
            )

    assert len(report) == 14
    for row in report:
        print(
            f"{row['lineage_id']}: old identity_text_equal="
            f"{row['old_identity_text_equal']} modified_claim_emitted="
            f"{row['old_modified_claim_emitted']} -> new CONTENT="
            f"{row['new_content_verdict']} STRUCTURAL={row['new_structural_verdict']}"
        )
        # Identity continuity, which the migration was required to preserve:
        # the identity fold still agrees on both sides of all 14 edits. That is
        # not the defect -- it is the feature. `normalize_text_for_identity` was
        # never made content-sensitive, so these units are still the same units.
        assert row["old_identity_text_equal"] is True
        # SFI2 froze `modified_claim_emitted=False` on all 14: identity equality
        # was being used as the change predicate, so a fold-equal edit emitted no
        # modification and the artifact went stale (INC-V2-037). `trace_case`
        # calls live production, so once the change predicate moved off the
        # identity fold this same replay began reporting True -- the frozen FAIL
        # is the historical measurement, and this assertion is now the guard that
        # the repair is still in place. Both readings are true of their own time;
        # neither is edited into the other.
        assert row["old_modified_claim_emitted"] is True
        # the property this shadow exists to prove: independently derived,
        # CONTENT still sees the difference the old gate folded away.
        assert row["new_content_verdict"] == cf.CHANGED
        # none of the 14 cases move the unit's position -- pure text edits --
        # so STRUCTURAL agreeing UNCHANGED is the expected, not incidental,
        # shape of a facet decomposition that does not over-fire.
        assert row["new_structural_verdict"] == cf.UNCHANGED
