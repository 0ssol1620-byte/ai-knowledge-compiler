"""Controls for the Protected Core conformance gate and the revision comparison.

The gate exists because ``79dd3b7`` satisfies every recoverability property --
clean, committed, byte-identical, fully closed under imports -- and is still not
a usable scientific baseline, because seven symbols the paper's claim chain
depends on do not exist in it. Recoverability and conformance are separate
questions and the study needs both answered.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for extra in (NS, NS / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import sfir4_core_conformance as conf  # noqa: E402
import sfir4_core_revision_comparison as cmp_  # noqa: E402

#: The revision the isolated-checkout attempt pinned. Kept as a literal because
#: this file records a finding about that exact revision.
PINNED = "79dd3b70460b6fc0a7deb44c6f29ecf99049f06e"


# ---------------------------------------------------------------------------
# The required set is the claim chain, not today's import list
# ---------------------------------------------------------------------------


def test_every_required_symbol_names_the_claim_it_carries() -> None:
    for (module, symbol), claim in conf.REQUIRED_SYMBOLS.items():
        assert module.startswith("akc_cir."), module
        assert symbol and isinstance(claim, str)
        assert len(claim) > 20, (symbol, claim)


def test_the_claim_chain_covers_the_paper_contribution() -> None:
    """Each element of the contribution must have at least one bound symbol."""
    claims = " ".join(conf.REQUIRED_SYMBOLS.values()).casefold()
    for element in (
        "identity",
        "change",
        "quarantine",
        "dependency",
        "selectiv",
        "fail-closed",
    ):
        assert element in claims, element


def test_every_core_module_is_covered_by_at_least_one_required_symbol() -> None:
    covered = {module for module, _ in conf.REQUIRED_SYMBOLS}
    assert covered == set(conf.CORE_MODULES)


# ---------------------------------------------------------------------------
# The gate against the core that is actually installed
# ---------------------------------------------------------------------------


def test_the_shared_core_satisfies_the_claim_chain() -> None:
    """The core this interpreter imports is the one SFIR4 was developed against.

    If this fails, the working tree lost a claim-bearing symbol and no SFIR4
    result taken after that point means what it says.
    """
    body = conf.conformance()
    assert body["verdict"] == "PASS", body["absent"]
    assert body["totals"]["absent"] == 0


def test_the_gate_reports_where_the_core_actually_resolved() -> None:
    """A receipt saying 'isolated checkout' must be checkable against reality.

    The shared virtualenv installs the repository editable and its ``.pth``
    hard-codes an absolute path into the shared working tree, so an isolated
    checkout imports the shared core unless something forces otherwise.
    """
    body = conf.conformance()
    assert body["resolved_from"]["package_root"]
    assert body["resolved_from"]["origin"].endswith("__init__.py")


def test_an_unexpected_core_root_is_refused() -> None:
    body = conf.conformance(expected_root=Path("/nowhere/that/exists"))
    assert body["verdict"] == "REFUSE"
    assert any("resolves from" in reason for reason in body["why"])


def test_require_conformant_fails_closed_on_the_wrong_root() -> None:
    with pytest.raises(conf.ConformanceRefused, match="Protected Core conformance"):
        conf.require_conformant(expected_root=Path("/nowhere/that/exists"))


def test_the_gate_reports_zero_cost_and_is_read_only() -> None:
    body = conf.conformance()
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
    assert body["read_only"] is True


# ---------------------------------------------------------------------------
# The finding about the pinned revision, executed
# ---------------------------------------------------------------------------


def test_the_pinned_revision_is_missing_claim_bearing_symbols() -> None:
    """The reason SFIR4 was not frozen at ``79dd3b7``.

    When the Protected Core work lands, this test fails and the correct response
    is to re-point it at the new revision -- never to drop symbols from
    ``REQUIRED_SYMBOLS`` so that an older core conforms.
    """
    body = cmp_.compare(PINNED)
    absent = body["claim_bearing_absent_from_left"]
    if not absent:
        pytest.fail(
            f"{PINNED} now carries every claim-bearing symbol; this control is "
            "stale and the baseline decision should be revisited"
        )
    symbols = {row["symbol"] for row in absent}
    assert "DependencyChannel" in symbols
    assert "ChangeChannel" in symbols
    assert "FacetVerdict" in symbols


def test_the_working_tree_core_is_a_strict_superset_of_the_pinned_one() -> None:
    """No API was removed, so this is not a divergence -- it is unlanded work."""
    body = cmp_.compare(PINNED)
    assert body["api_removals"] == [], body["api_removals"]


def test_the_comparison_never_imports_either_revision() -> None:
    """Importing the shared tree while describing a pinned one describes neither."""
    source = (NS / "tools" / "sfir4_core_revision_comparison.py").read_text(encoding="utf-8")
    assert "importlib" not in source
    assert "ast.parse" in source


def test_the_comparison_refuses_an_unknown_revision() -> None:
    with pytest.raises(cmp_.ComparisonRefused, match="unreadable at"):
        cmp_.compare("0" * 40)


def test_the_comparison_declines_to_guess_intent() -> None:
    body = cmp_.compare(PINNED)
    assert "does_not_classify_intent" in body
    assert "judgement is" in body["does_not_classify_intent"]


def test_a_comparison_of_a_revision_with_itself_is_empty() -> None:
    body = cmp_.compare(PINNED, PINNED)
    assert body["totals"]["claim_bearing_symbols_absent_from_left"] == 0
    assert body["totals"]["other_api_additions"] == 0
    assert body["totals"]["api_removals"] == 0
