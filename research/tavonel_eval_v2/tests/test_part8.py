"""The source-map contract that reads MARKUP_SEMANTICS_V1 — INC-V2-013.

The defect these tests exist to prevent is not a wrong number. It is a
*plausible* one: a policy that is frozen, sealed, controlled and read by
nothing, while the report says the workstream is done. So the checks here are
mostly about wiring — that the scoring path really does consult the policy, that
the old grammar is gone from it, and that the legacy instrument is untouched so
the result it produced stays reproducible.
"""

from __future__ import annotations

import html as _html
import json
import re
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "canonicalization"))
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS / "retrieval"))

from coverage_witness_v2 import UNRESOLVED_IN_CLOSURE, witness_status  # noqa: E402
from markup_controls import CONTROLS  # noqa: E402
from markup_policy import IGNORED, MODELED, UNMODELED, UNRESOLVED  # noqa: E402
from source_map import LOCATION_UNVERIFIABLE  # noqa: E402
from source_map_v2 import html_located, located_spans, normalise  # noqa: E402

_TAG = re.compile(r"<[^>]+>")


def visible(raw: str) -> str:
    return _html.unescape(_TAG.sub(" ", raw))


def states(raw: str, canonical: str | None = None) -> dict[str, str]:
    canonical = visible(raw) if canonical is None else canonical
    return {span.kind: span.classification for span in html_located(raw, canonical)}


# --- the policy is actually in the scoring path ------------------------------


@pytest.mark.parametrize("control", CONTROLS, ids=lambda c: c["name"])
def test_each_control_classifies_the_same_way_through_the_map(control: dict) -> None:
    kind = control["kind"]
    wanted = (
        "attr:" + control["construct"].lower()
        if kind == "attribute"
        else "start_tag:" + control["construct"].lower()
        if kind == "tag"
        else "charref"
    )
    raw = control["after"]
    span = next((s for s in html_located(raw, visible(raw)) if s.kind == wanted), None)
    assert span is not None, (control["name"], wanted)
    assert span.classification == control["expect_state"], control["guards"]
    assert (span.fact or {}).get("facet") == control["expect_facet"]


@pytest.mark.parametrize(
    "attribute,expected",
    [
        ("colspan", MODELED),
        ("rowspan", MODELED),
        ("scope", MODELED),
        ("role", MODELED),
        ("alt", MODELED),
        ("lang", MODELED),
        ("rel", MODELED),
        ("class", UNRESOLVED),
        ("style", UNRESOLVED),
        ("cellpadding", IGNORED),
    ],
)
def test_the_old_ignored_list_is_not_inherited_by_the_map(attribute: str, expected: str) -> None:
    raw = '<td %s="x">text</td>' % attribute
    assert states(raw).get("attr:" + attribute) == expected


def test_structural_tags_reach_the_map_as_modelled() -> None:
    got = states("<table><tr><td>a</td></tr></table>")
    for kind in ("start_tag:table", "start_tag:tr", "start_tag:td"):
        assert got[kind] == MODELED, kind


def test_an_undeclared_element_is_unmodeled_in_the_map() -> None:
    assert states("<policyref>a</policyref>").get("start_tag:policyref") == UNMODELED


# --- content is granted by traceability, never by assertion ------------------


def test_text_present_in_the_canonical_text_is_modelled() -> None:
    raw = "<p>Quarterly revenue rose to 4.2 billion euros.</p>"
    assert states(raw)["data"] == MODELED


def test_text_absent_from_the_canonical_text_is_unmodeled() -> None:
    raw = "<p>Quarterly revenue rose to 4.2 billion euros.</p>"
    assert states(raw, "something else entirely")["data"] == UNMODELED


def test_an_empty_canonical_text_grants_nothing() -> None:
    """Otherwise a document the canonicaliser dropped entirely would look complete."""
    raw = "<p>Quarterly revenue rose to 4.2 billion euros.</p>"
    assert states(raw, "")["data"] == UNMODELED


def test_a_character_reference_is_traced_through_the_character_it_produces() -> None:
    """The non-breaking space must be found as itself, not as any whitespace.

    A canonicaliser that folded it to an ordinary space did not carry the
    character through, and saying otherwise would be a grant by assertion.
    """
    raw = "<p>a&#160;b</p>"
    assert states(raw, "a" + chr(160) + "b")["charref"] == MODELED
    assert states(raw, "a b")["charref"] == UNMODELED
    assert states(raw, "zzz")["charref"] == UNMODELED


def test_whitespace_between_elements_stays_ignorable() -> None:
    got = html_located("<ul>\n  <li>a</li>\n</ul>", "a")
    whitespace = [s for s in got if s.kind == "data" and not s.text.strip()]
    assert whitespace, "no inter-element whitespace event was produced"
    assert all(s.classification == IGNORED for s in whitespace)


def test_normalise_does_not_fold_the_non_breaking_space() -> None:
    """Folding it on both sides would make every reference to it pass for free."""
    assert normalise("a  b") == "a b"
    assert normalise("a" + chr(160) + "b") == "a" + chr(160) + "b"


# --- fail closed --------------------------------------------------------------


def _witness(elements: list[dict]) -> dict:
    return {"elements": elements, "element_count": len(elements), "by_role": {}}


def _element(classification: str, role: str = "direct_atom_span") -> dict:
    return {
        "start": 0,
        "end": 1,
        "kind": "attr:test",
        "classification": classification,
        "location_state": "LOCATION_VERIFIED",
        "role": role,
        "sample": "x",
    }


def test_unresolved_blocks_completeness_and_is_counted_separately() -> None:
    status = witness_status(_witness([_element(MODELED), _element(UNRESOLVED)]), [])
    assert status["status"] == "QUESTION_LOCAL_COVERAGE_INCOMPLETE"
    assert UNRESOLVED_IN_CLOSURE in status["reasons"]
    assert status["unresolved_in_closure"] == 1
    assert status["unmodeled_in_closure"] == 0


def test_unmodeled_and_unresolved_are_never_collapsed_into_one_count() -> None:
    status = witness_status(
        _witness([_element(UNMODELED), _element(UNRESOLVED), _element(IGNORED)]), []
    )
    assert status["unmodeled_in_closure"] == 1
    assert status["unresolved_in_closure"] == 1
    assert status["ignored_in_closure"] == 1
    assert set(status["reasons"]) >= {"UNMODELED_SOURCE_FACT_IN_CLOSURE", UNRESOLVED_IN_CLOSURE}


def test_a_closure_of_modelled_and_ignored_elements_can_still_complete() -> None:
    """The instrument has to be able to say yes, or it measures nothing."""
    status = witness_status(_witness([_element(MODELED), _element(IGNORED)]), [])
    assert status["status"] == "QUESTION_LOCAL_COVERAGE_COMPLETE"
    assert status["reasons"] == []


def test_an_unlocatable_span_anywhere_blocks() -> None:
    class _Span:
        location_state = LOCATION_UNVERIFIABLE

    status = witness_status(_witness([_element(MODELED)]), [_Span()])
    assert status["status"] == "QUESTION_LOCAL_COVERAGE_INCOMPLETE"


def test_a_malformed_document_yields_no_position_rather_than_a_guess() -> None:
    spans = html_located("<p>unterminated", "unterminated")
    assert all(s.start is None or s.start >= 0 for s in spans)


# --- the legacy instrument is untouched ---------------------------------------


def test_markdown_keeps_its_own_grammar() -> None:
    spans, grammar = located_spans("# Heading\n\ntext\n", ".md")
    assert grammar == "markdown"
    assert spans


def test_markup_dispatch_names_the_policy_it_used() -> None:
    _, grammar = located_spans("<p>a</p>", ".html", "a")
    assert grammar == "markup:MARKUP_SEMANTICS_V1"


@pytest.mark.parametrize(
    "name", ["source_map.py", "coverage_witness.py", "source_spans.py"]
)
def test_the_sealed_locality_v2_modules_still_carry_their_sealed_digest(name: str) -> None:
    """SOURCE_LOCALITY_V2's eligible Q1 = 5 is only reproducible if these do not move."""
    import hashlib  # noqa: PLC0415

    current = "sha256:" + hashlib.sha256((NS / "canonicalization" / name).read_bytes()).hexdigest()
    receipts = sorted((NS / "receipts").glob("locality-v2--*.json"))
    assert receipts, "no locality v2 receipt to compare against"
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    instrument = body["instrument"]
    sealed = {
        "source_map.py": instrument.get("source_map_sha256"),
        "coverage_witness.py": instrument.get("witness_sha256"),
    }.get(name)
    if sealed is None:
        pytest.skip("source_spans is sealed by P0d, not by this receipt")
    assert current == sealed, name


def test_the_contract_seal_passed_and_spent_nothing() -> None:
    receipts = sorted((NS / "receipts").glob("source-map-contract--*.json"))
    assert receipts
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert body["verdict"] == "PASS"
    assert body["incident"] == "INC-V2-013"
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
    assert body["instrument_identity"]["composite"].startswith("sha256:")


def test_the_composite_moved_and_the_move_is_explained() -> None:
    from run_p4g import COMPOSITE_AT_P4G_FREEZE, composite_identity  # noqa: PLC0415

    identity = composite_identity()
    assert identity["composite"] != COMPOSITE_AT_P4G_FREEZE
    assert identity["explained_by"] == "INC-V2-013"
    assert identity["frozen_in_P4g"] == COMPOSITE_AT_P4G_FREEZE


def test_the_floor_is_not_lowered_anywhere_in_the_scorer() -> None:
    from run_p4g import HARD_MINIMUM_ELIGIBLE_Q1  # noqa: PLC0415

    assert HARD_MINIMUM_ELIGIBLE_Q1 == 190


# --- the acquisition declaration ---------------------------------------------


def test_the_extension_rules_are_labelled_as_extensions() -> None:
    sys.path.insert(0, str(NS / "acquisition"))
    import sources_p4g  # noqa: PLC0415

    spacing = sources_p4g.REVISION_SPACING
    assert spacing["git_docs"]["provenance"].startswith("EXTENSION")
    assert spacing["sec_edgar"]["provenance"].startswith("EXTENSION")
    assert spacing["encyclopedia_wikipedia"]["provenance"] == "verbatim from P4e"
    assert spacing["regulation_ecfr"]["provenance"] == "verbatim from P4e"
    assert spacing["frozen_before_any_fetch"] is True


def test_the_selection_rule_cannot_see_an_outcome() -> None:
    sys.path.insert(0, str(NS / "acquisition"))
    import sources_p4g  # noqa: PLC0415

    for clause in sources_p4g.REVISION_SPACING.values():
        if not isinstance(clause, dict):
            continue
        text = " ".join(str(v) for k, v in clause.items() if k in {"rule", "decidable_from"})
        assert "score" not in text.lower()
        assert "eligib" not in text.lower()


def test_no_family_dominates_the_declared_quota() -> None:
    sys.path.insert(0, str(NS / "acquisition"))
    import sources_p4g  # noqa: PLC0415

    quota = sources_p4g.FAMILY_QUOTA
    families = {k: v for k, v in quota.items() if isinstance(v, int) and k.endswith(("docs", "ecfr", "wikipedia", "edgar"))}
    assert len(families) >= 4
    assert max(families.values()) / sum(families.values()) <= 0.31


# --- the closure has to look at the markup, not only at the text -------------


def _markup_witness(raw: str, atom: str, canonical: str | None = None):
    from coverage_witness_v2 import (  # noqa: PLC0415
        MARKUP_GRAMMAR,
        build_witness,
        witness_status,
    )
    from source_map_v2 import located_spans  # noqa: PLC0415

    canonical = atom if canonical is None else canonical
    spans, grammar = located_spans(raw, ".html", canonical)
    assert grammar == MARKUP_GRAMMAR
    witness = build_witness(
        spans, atom, [], [], raw=raw, canonical_text=canonical, grammar=grammar
    )
    return witness, witness_status(witness, spans)


OVER_GRANT_SOURCE = (
    "<html><body>"
    "<p>Filler paragraph one, unrelated to the atom.</p>"
    '<div class="mw-parser-output"><p>The permitted exposure limit is fifty '
    "parts per million averaged over eight hours.</p></div>"
    "<p>Filler paragraph two, also unrelated.</p>"
    "</body></html>"
)
ATOM_TEXT = (
    "The permitted exposure limit is fifty parts per million averaged over eight hours."
)


def test_markup_inside_the_atom_region_is_examined() -> None:
    """The over-grant control. Text alone would say complete; markup says no."""
    witness, status = _markup_witness(OVER_GRANT_SOURCE, ATOM_TEXT)
    assert witness["atom_source_region"] is not None
    kinds = {element["kind"] for element in witness["elements"]}
    assert any(kind.startswith("attr:") or kind.startswith("start_tag:") for kind in kinds), (
        "the closure admitted no markup at all, so it examined nothing"
    )
    assert status["status"] == "QUESTION_LOCAL_COVERAGE_INCOMPLETE"
    assert UNRESOLVED_IN_CLOSURE in status["reasons"]


def test_the_region_is_not_the_whole_document() -> None:
    """A region stretched to the file is the document-level rule under a new name."""
    witness, _ = _markup_witness(OVER_GRANT_SOURCE, ATOM_TEXT)
    low, high = witness["atom_source_region"]
    assert high - low < len(OVER_GRANT_SOURCE) * 0.8


def test_an_unlocatable_atom_refuses_rather_than_guesses() -> None:
    from coverage_witness_v2 import REGION_NOT_LOCALISABLE  # noqa: PLC0415

    _, status = _markup_witness("<p>a b</p><p>a b</p>", "nothing like this in the source")
    assert REGION_NOT_LOCALISABLE in status["reasons"]
    assert status["status"] == "QUESTION_LOCAL_COVERAGE_INCOMPLETE"


def test_markdown_does_not_acquire_a_region_requirement() -> None:
    from coverage_witness_v2 import build_witness  # noqa: PLC0415
    from source_map_v2 import located_spans  # noqa: PLC0415

    raw = "# Title\n\nA paragraph with enough words to be found.\n"
    spans, grammar = located_spans(raw, ".md")
    witness = build_witness(
        spans,
        "A paragraph with enough words to be found.",
        [],
        [],
        raw=raw,
        grammar=grammar,
    )
    assert witness["region_required"] is False
