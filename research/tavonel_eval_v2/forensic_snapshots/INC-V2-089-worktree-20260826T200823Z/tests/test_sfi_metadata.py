"""Lane 3 -- LANGUAGE, ACCESSIBILITY, APPLICABILITY, EFFECTIVE_TIME, AUTHORITY.

Pytest, no network, inline byte strings standing in for the corpus families
named in the task: git markdown repos (YAML front matter), eCFR regulations
and SEC EDGAR filings (labelled prose / a constrained HTML subset), and
Wikipedia (plain HTML fragments).
"""

from __future__ import annotations

import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
# Bare sys.path + bare import, matching tests/test_sfi_core.py and
# tests/test_sfi_adversarial.py: the sibling-extractor loader in
# test_sfi_adversarial.py imports every source_fact_ir/*.py module under its
# bare stem name ("metadata", "ir", ...), so this file uses that same bare
# identity rather than the package-qualified one (`source_fact_ir.metadata`).
# `metadata.py` itself now resolves `ir` correctly either way (see its
# try/except import), and `ir.register` compares producers by module basename
# + class name rather than object identity, so a dual import no longer raises
# -- but staying on the bare convention here keeps this test file's module
# identity consistent with the sibling loader's, which is what the other
# lane's tests already assume.
sys.path.insert(0, str(NS / "source_fact_ir"))

import ir  # noqa: E402
import metadata as metadata_module  # noqa: E402
from metadata import MetadataExtractor  # noqa: E402

EXTRACTOR = MetadataExtractor()
DOCUMENT: dict = {
    "source_id": "lineage:test-doc",
    "source_family": "git_markdown",
    "license": "CC-BY-4.0",
}


def extract(raw: bytes) -> list[ir.SourceFact]:
    return EXTRACTOR.extract(raw=raw, document=DOCUMENT)


def only(facts: list[ir.SourceFact], kind: str) -> list[ir.SourceFact]:
    return [fact for fact in facts if fact.kind == kind]


# ---------------------------------------------------------------------------
# 1. a language metadata change is extracted and its representation moves


def test_language_front_matter_change_moves_the_representation():
    before = b"---\nlang: en\ntitle: doc\n---\n\n# Heading\n\nBody text here.\n"
    after = b"---\nlang: fr\ntitle: doc\n---\n\n# Heading\n\nBody text here.\n"

    before_langs = only(extract(before), ir.LANGUAGE)
    after_langs = only(extract(after), ir.LANGUAGE)

    assert len(before_langs) == 1
    assert len(after_langs) == 1
    assert before_langs[0].state == ir.REPRESENTED
    assert before_langs[0].representation["tag"] == "en"
    assert after_langs[0].representation["tag"] == "fr"
    assert before_langs[0].representation != after_langs[0].representation
    # same construct/witness locator shape -> same fact identity family, only the value moved
    assert before_langs[0].kind == after_langs[0].kind == ir.LANGUAGE


def test_language_html_lang_attribute_and_hreflang_are_scoped_correctly():
    raw = (
        b'<html lang="en-US"><body>'
        b'<p lang="fr">bonjour</p>'
        b'<a href="/fr/page" hreflang="fr-CA">lien</a>'
        b"</body></html>"
    )
    facts = only(extract(raw), ir.LANGUAGE)
    scopes = {fact.representation["scope"] for fact in facts}
    assert scopes == {"document", "element", "link"}
    doc_fact = next(f for f in facts if f.representation["scope"] == "document")
    assert doc_fact.representation["tag"] == "en-us"
    link_fact = next(f for f in facts if f.representation["scope"] == "link")
    assert link_fact.representation["tag"] == "fr-ca"


# ---------------------------------------------------------------------------
# 2. an accessibility metadata change (alt text) is extracted while body
#    prose is unchanged


def test_accessibility_alt_text_change_is_extracted_with_unchanged_prose():
    before = (
        b"# Report\n\nSame unchanged prose paragraph that stays identical between versions "
        b'so the body carries no delta on its own account here at all.\n\n'
        b'<img src="chart.png" alt="quarterly revenue chart">\n'
    )
    after = (
        b"# Report\n\nSame unchanged prose paragraph that stays identical between versions "
        b'so the body carries no delta on its own account here at all.\n\n'
        b'<img src="chart.png" alt="quarterly revenue chart, revised">\n'
    )
    before_facts = only(extract(before), ir.ACCESSIBILITY)
    after_facts = only(extract(after), ir.ACCESSIBILITY)
    assert len(before_facts) == 1
    assert before_facts[0].representation["construct"] == "img-alt"
    assert before_facts[0].representation["text"] == "quarterly revenue chart"
    assert after_facts[0].representation["text"] == "quarterly revenue chart, revised"
    assert before_facts[0].representation != after_facts[0].representation


def test_accessibility_empty_alt_is_declined_by_policy_not_represented():
    raw = b'<img src="deco.png" alt="">'
    facts = only(extract(raw), ir.ACCESSIBILITY)
    assert len(facts) == 1
    assert facts[0].state == ir.IGNORED
    assert facts[0].policy_ref == "POLICY-META-002"
    assert facts[0].policy_ref in metadata_module.POLICY


def test_accessibility_covers_figcaption_caption_and_cell_scope():
    raw = (
        b"<table><caption>Revenue by quarter</caption>"
        b'<tr><th id="q1" scope="col">Q1</th></tr>'
        b'<tr><td headers="q1">100</td></tr></table>'
        b"<figure><img src='x.png'><figcaption>A chart of revenue</figcaption></figure>"
    )
    facts = only(extract(raw), ir.ACCESSIBILITY)
    constructs = {
        fact.representation["construct"] for fact in facts if fact.state == ir.REPRESENTED
    }
    assert constructs == {"table-caption", "cell-scope", "cell-headers", "figcaption"}


def test_accessibility_title_on_div_is_declined_by_predeclared_policy():
    raw = b'<div title="a decorative duplicate title">content</div>'
    facts = only(extract(raw), ir.ACCESSIBILITY)
    assert len(facts) == 1
    assert facts[0].state == ir.IGNORED
    assert facts[0].policy_ref == "POLICY-META-001"


# ---------------------------------------------------------------------------
# 3. an applicability/scope metadata change is extracted


def test_applicability_front_matter_change_is_extracted():
    before = b"---\napplies_to: internal-only\n---\n\nBody.\n"
    after = b"---\napplies_to: public\n---\n\nBody.\n"
    before_facts = only(extract(before), ir.APPLICABILITY)
    after_facts = only(extract(after), ir.APPLICABILITY)
    assert before_facts[0].representation["value"] == "internal-only"
    assert after_facts[0].representation["value"] == "public"


def test_applicability_ecfr_style_prose_is_extracted():
    raw = (
        b"Sec. 1.1 Applicability. This part applies to persons who operate "
        b"a facility subject to this subchapter.\n\n"
        b"Except as provided in Sec. 1.2, no exemption is available.\n"
    )
    facts = only(extract(raw), ir.APPLICABILITY)
    labels = {fact.representation["label"] for fact in facts}
    assert labels == {"Applicability", "exception"}
    applicability = next(f for f in facts if f.representation["label"] == "Applicability")
    assert "persons who operate" in applicability.representation["statement"]


# ---------------------------------------------------------------------------
# 4. an effective-date change is extracted and ISO-normalised


def test_effective_time_named_date_is_iso_normalised_and_changes():
    before = b"---\neffective: March 4, 2026\n---\n\nBody.\n"
    after = b"---\neffective: March 11, 2026\n---\n\nBody.\n"
    before_fact = only(extract(before), ir.EFFECTIVE_TIME)[0]
    after_fact = only(extract(after), ir.EFFECTIVE_TIME)[0]
    assert before_fact.state == ir.REPRESENTED
    assert before_fact.representation["iso"] == "2026-03-04"
    assert after_fact.representation["iso"] == "2026-03-11"


def test_effective_time_html_time_element_and_meta_date_are_extracted():
    raw = (
        b'<time datetime="2026-01-15">Jan 15, 2026</time>'
        b'<meta name="date" content="2026-02-01">'
    )
    facts = only(extract(raw), ir.EFFECTIVE_TIME)
    isos = {fact.representation["iso"] for fact in facts}
    assert isos == {"2026-01-15", "2026-02-01"}


def test_effective_time_sec_period_of_report_is_extracted():
    raw = b"Period of Report: 2026-06-30\n"
    facts = only(extract(raw), ir.EFFECTIVE_TIME)
    assert len(facts) == 1
    assert facts[0].representation == {
        "role": "period_of_report", "iso": "2026-06-30", "raw": "2026-06-30",
    }


# ---------------------------------------------------------------------------
# 5. an ambiguous date fails closed as UNRESOLVED with a reason, never guessed


def test_ambiguous_numeric_date_is_unresolved_not_guessed():
    raw = b"---\neffective: 03/04/2026\n---\n\nBody.\n"
    facts = only(extract(raw), ir.EFFECTIVE_TIME)
    assert len(facts) == 1
    fact = facts[0]
    assert fact.state == ir.UNRESOLVED
    assert fact.representation is None  # the hard rule: never store an inferred date as fact
    assert "ambiguous" in fact.reason
    assert "03/04/2026" in fact.reason


def test_datetime_with_time_of_day_and_no_timezone_is_unresolved():
    raw = b'<time datetime="2026-03-04T10:00:00">a meeting</time>'
    facts = only(extract(raw), ir.EFFECTIVE_TIME)
    assert len(facts) == 1
    assert facts[0].state == ir.UNRESOLVED
    assert "timezone" in facts[0].reason


# ---------------------------------------------------------------------------
# 6. a source with no stated author emits no authority fact -- absence, not
#    fabrication


def test_no_stated_author_emits_no_authority_fact():
    raw = (
        b"---\ntitle: An ordinary document\ndate: 2026-01-01\n---\n\n"
        b"# Heading\n\nSome prose that never says who wrote it.\n"
    )
    facts = only(extract(raw), ir.AUTHORITY)
    assert facts == []


def test_stated_author_in_meta_and_front_matter_and_ecfr_prose_is_extracted():
    meta = b'<meta name="author" content="Jane Doe">'
    front_matter = b"---\nauthor: Jane Doe\n---\n\nBody.\n"
    ecfr = b"Authority: 5 U.S.C. 301; 44 U.S.C. 3101.\nAgency: General Services Administration.\n"

    meta_facts = only(extract(meta), ir.AUTHORITY)
    fm_facts = only(extract(front_matter), ir.AUTHORITY)
    ecfr_facts = only(extract(ecfr), ir.AUTHORITY)

    assert meta_facts[0].representation == {"source": "meta", "role": "author", "name": "Jane Doe"}
    assert fm_facts[0].representation == {
        "source": "front_matter", "role": "author", "name": "Jane Doe",
    }
    roles = {fact.representation["role"] for fact in ecfr_facts}
    assert roles == {"citation", "agency"}


# ---------------------------------------------------------------------------
# 7. every fact's witness verifies against the raw bytes


def test_every_extracted_witness_verifies_against_raw():
    raw = (
        b"---\nlang: en\napplies_to: public\neffective: 2026-01-01\nauthor: Jane Doe\n---\n\n"
        b"# Title\n\n"
        b'<html lang="en"><img src="a.png" alt="a chart">'
        b'<a href="/x" hreflang="fr" title="link title">x</a>'
        b'<div title="dup">y</div>'
        b'<table><caption>Cap</caption><tr><th id="c1" scope="col">C1</th></tr>'
        b'<tr><td headers="c1">1</td></tr></table>'
        b'<figure><figcaption>fig text</figcaption></figure>'
        b'<time datetime="2026-05-01">May</time>'
        b'<meta name="date" content="2026-05-02">'
        b'<meta name="author" content="Jane Doe">'
        b'<span aria-label="star rating">*****</span>'
        b'<span aria-describedby="missing-id">z</span>'
        b"Applicability. This applies to everyone.\n"
        b"Authority: 5 U.S.C. 301.\n"
        b"Agency: GSA.\n"
        b"Effective Date: March 4, 2026.\n"
        b"Period of Report: 2026-06-30\n"
        b"</html>"
    )
    facts = extract(raw)
    assert len(facts) > 15  # sanity: the fixture actually exercises the extractor
    for fact in facts:
        assert fact.witness.verify(raw), (fact.kind, fact.witness.construct, fact.state)


def test_extract_all_registers_and_runs_the_metadata_extractor():
    # importing the module is what performs `ir.register(...)`; extract_all
    # must therefore surface our kinds without any extra wiring here.
    assert set(EXTRACTOR.kinds) <= set(ir.registered_kinds())
    raw = b"---\nlang: en\n---\n\nBody text that is long enough to be a unit on its own merits.\n"
    facts = ir.extract_all(raw=raw, document=DOCUMENT)
    assert any(fact.kind == ir.LANGUAGE for fact in facts)


# ---------------------------------------------------------------------------
# 8. a recognised-but-uncanonicalisable construct lands in
#    RECOGNIZED_BUT_UNREPRESENTED, not IGNORED


def test_dangling_aria_describedby_is_recognized_but_unrepresented():
    raw = b'<span aria-describedby="missing-id">z</span>'
    facts = only(extract(raw), ir.ACCESSIBILITY)
    assert len(facts) == 1
    fact = facts[0]
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None
    assert "missing-id" in fact.reason
    assert fact.policy_ref is None  # UNREPRESENTED is not a policy decision


def test_resolved_aria_describedby_is_represented():
    raw = b'<p id="hint">extra detail here</p><span aria-describedby="hint">z</span>'
    facts = only(extract(raw), ir.ACCESSIBILITY)
    described = [
        f for f in facts
        if f.representation and f.representation.get("construct") == "aria-describedby"
    ]
    assert len(described) == 1
    assert described[0].state == ir.REPRESENTED
    assert described[0].representation["text"]["hint"] == "extra detail here"


# ---------------------------------------------------------------------------
# chain completeness sanity: a REPRESENTED fact from this lane satisfies the
# witness+representation half of the chain unconditionally (fingerprint and
# dependency resolution belong to lane 4 and are not exercised here).


def test_represented_facts_have_a_non_null_representation_and_no_reason_or_policy():
    raw = b"---\nlang: en\n---\n\nBody.\n"
    facts = extract(raw)
    for fact in facts:
        if fact.state == ir.REPRESENTED:
            assert fact.representation is not None
            assert fact.reason is None
            assert fact.policy_ref is None
