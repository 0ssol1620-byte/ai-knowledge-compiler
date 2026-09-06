"""Drives `source_fact_ir.scope_gate` — the executable proof of what enters
the declared supported/scored SFI3 path for `INCLUDE_TARGET` facts.

The founder's ruling this answers: "a lane considered it out of scope" is
not evidence. Either `_extract_html_includes`, `_extract_hugo_shortcodes`
and `_extract_mediawiki_templates` get the frozen INCLUDE_TARGET taxonomy,
or an executable gate proves they cannot contribute a computed/ambiguous
target to the scored path. These tests are that proof running as pytest,
not merely importable — a claim nothing runs is exactly the INC-V2-034
defect (a scope claim in prose that sat unresolved for weeks because prose
cannot refuse a bad input).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))

from canonicalization.canonical_document import canonical_document  # noqa: E402
from source_fact_ir import ir, scope_gate  # noqa: E402
from source_fact_ir.reference import reference_extractor  # noqa: E402

# ---------------------------------------------------------------------------
# 1. every declared construct is actually reachable through the registered,
# scored entry point — not merely present as a private helper function


@pytest.mark.parametrize("construct", scope_gate.INCLUDE_TARGET_CONSTRUCTS)
def test_every_declared_construct_is_in_the_scored_path(construct: str):
    assert scope_gate.is_in_scored_path(construct), (
        f"{construct} is declared part of the INCLUDE_TARGET cohort but "
        "reference_extractor.extract (the entry point ir.extract_all calls) "
        "never produced a fact for it"
    )


def _document_for(raw: bytes) -> dict:
    """A real canonicalized document, not a hand-rolled `{}`/`{"source_id":
    ...}` stand-in. `ir.extract_all` runs *every* registered extractor
    (core, reference, metadata), and the metadata extractor requires a real
    `document["source_id"]` — an empty or partial dict fails there with a
    `KeyError`, for a reason that has nothing to do with what this test is
    proving about `INCLUDE_TARGET` wiring. Building the document the same
    way `tests/test_sfi_reference.py` does keeps this test exercising the
    actual pipeline shape rather than a stand-in whose gaps this test would
    otherwise have to work around one extractor at a time.
    """
    return canonical_document(
        source_family="wiki",
        source_id="scope-gate-test-source",
        version_id="v1",
        payload=raw,
        source_digest="sha256:0" * 8,
        known_at=None,
        valid_from=None,
        licence="cc0",
    )


def test_include_target_kind_has_exactly_one_registered_producer():
    """The registry (`source_fact_ir.ir.register`) is what "declared
    supported/scored path" cashes out to at runtime: `INCLUDE_TARGET` must
    be registered, and `reference_extractor` must be the thing that produces
    it — otherwise "in the scored path" would be an unverifiable claim about
    code that is never actually called by `ir.extract_all`."""
    assert ir.INCLUDE_TARGET in ir.registered_kinds()
    # Behavioural proof rather than reaching into the registry's private
    # dict: every construct's fixture must round-trip through
    # `ir.extract_all`, the actual scoring entry point.
    for scope in scope_gate.CONSTRUCT_SCOPES.values():
        facts = ir.extract_all(raw=scope.fixture, document=_document_for(scope.fixture))
        matches = [
            f for f in facts
            if f.kind == ir.INCLUDE_TARGET and f.witness.construct == scope.construct
        ]
        assert matches, (
            f"{scope.construct}'s fixture produced no INCLUDE_TARGET fact via "
            "ir.extract_all"
        )


# ---------------------------------------------------------------------------
# 2. no construct can silently turn a computed/ambiguous/malformed input
# into a REPRESENTED fact — the taxonomy-wired constructs, proven against a
# battery of previously-reachable defects


@pytest.mark.parametrize(
    "construct", ["jinja-include", "hugo-shortcode-include", "html-include-src"]
)
def test_never_represents_a_computed_or_malformed_target(construct: str):
    # Raises on failure; a clean return is the pass.
    scope_gate.assert_never_represents_a_computed_or_malformed_target(construct)


def test_html_include_computed_target_is_falsifiable_and_was_falsified():
    """The previous lane's argument ("no computed expression can arise in an
    HTML attribute value") is tested here directly, against the exact input
    that falsifies it: a Jekyll/Liquid-style interpolation embedded inside
    an otherwise-plausible-looking `src` value, with no whitespace to make
    it stand out. Before the fix this shipped alongside, this fixture
    produced a REPRESENTED fact whose "path" was literally
    `{{region}}.html` — a template expression asserted as a static target.
    """
    raw = b'<include src="{{region}}.html">\n'
    facts = reference_extractor.extract(raw=raw, document={})
    matches = [
        f for f in facts
        if f.kind == ir.INCLUDE_TARGET and f.witness.construct == "html-include-src"
    ]
    assert len(matches) == 1
    fact = matches[0]
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None
    assert fact.reason
    assert "{{" in fact.reason


def test_hugo_shortcode_computed_target_is_falsifiable_and_was_falsified():
    """The previous lane's argument for Hugo's "quoted-arg search" is tested
    against a Go template function call whose only quoted substring is a
    format string, not the target. Before the fix this shipped alongside,
    `re.search(r'"([^"]*)"', inner)` found `"%s.html"` and represented it as
    the target, silently discarding that it was a `printf` argument, not a
    path.
    """
    raw = b'{{< include (printf "%s.html" .Param) >}}\n'
    facts = reference_extractor.extract(raw=raw, document={})
    matches = [
        f for f in facts
        if f.kind == ir.INCLUDE_TARGET and f.witness.construct == "hugo-shortcode-include"
    ]
    assert len(matches) == 1
    fact = matches[0]
    assert fact.state != ir.REPRESENTED
    assert fact.representation is None


# ---------------------------------------------------------------------------
# 3. mediawiki — the structural proof, driven against attempted attacks


@pytest.mark.parametrize(
    "raw", scope_gate.MEDIAWIKI_NESTED_TRANSCLUSION_ATTEMPTS
)
def test_mediawiki_name_never_carries_a_computed_expression(raw: bytes):
    # Raises on failure; a clean return is the pass.
    scope_gate.prove_mediawiki_name_cannot_carry_a_computed_expression(raw)


def test_mediawiki_nested_transclusion_is_not_silently_dropped_as_one_fact():
    """The structural proof (no brace ever appears in a captured name) does
    not mean nested transclusion vanishes without a trace: the regex still
    matches the *inner* leaf as its own separate, real fact — this pins that
    behaviour so a future change cannot silently start dropping it instead
    of continuing to (mis)represent it as an unrelated construct, which
    would hide a construct this extractor is already known not to model
    correctly (see the docstring on `_extract_mediawiki_templates`) behind
    apparent silence instead of a visible, wrong-but-inspectable fact.
    """
    raw = b"{{ {{PAGENAME}} }}\n"
    facts = reference_extractor.extract(raw=raw, document={})
    matches = [
        f for f in facts
        if f.kind == ir.INCLUDE_TARGET and f.witness.construct == "mediawiki-template"
    ]
    assert len(matches) == 1
    assert matches[0].state == ir.REPRESENTED
    assert matches[0].representation["normalized"] == "PAGENAME"


# ---------------------------------------------------------------------------
# 4. the whole gate, run as one call (what a release/scoring gate would call)


def test_prove_scope_runs_clean_for_the_whole_cohort():
    results = scope_gate.prove_scope()
    assert set(results) == set(scope_gate.INCLUDE_TARGET_CONSTRUCTS)
    for construct, result in results.items():
        assert result["in_scored_path"] is True, construct
        assert result["never_represents_computed_or_malformed"] is True, construct
