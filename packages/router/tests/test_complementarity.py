"""The rescue table must keep saying what the artifact says, and fail closed.

Two kinds of test live here. The first re-reads the frozen artifacts and checks
that no digit in `complementarity.py` has drifted from them -- the module is
generated, and a generated file that nobody re-checks is a transcription waiting
to be wrong. The second is the part that matters in production: what the router
does when the measurement it wants does not exist or cannot be served.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from akc_router.complementarity import (
    ARENA_MODEL_ROUTES,
    COMPLEMENTARITY_ARTIFACT,
    COMPLEMENTARITY_SHA256,
    MEASURED_RESCUES,
    ORACLE_ARTIFACT,
    ORACLE_SHA256,
    WRONG_EDIT_THRESHOLD,
    ParseElement,
    dominant_element,
    rescues_for,
    select_cross_check_peer,
)
from akc_router.engine import select_first_route
from akc_router.models import ProcessingMode, Route, RouteDecision, RouterContext
from akc_router.preflight import PageMetrics, RiskTier

REPO_ROOT = Path(__file__).resolve().parents[3]

ALL_READY = frozenset({Route.PADDLE_VL, Route.OVIS_VL, Route.INFINITY_FLASH})


def _digest(relative: str) -> str:
    return hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()


def _page(**overrides: object) -> PageMetrics:
    """A scanned page that needs a visual parse, with no formula or table by default."""
    base: dict[str, object] = {
        "page_index0": 0,
        "width": 1700,
        "height": 2200,
        "native_text_chars": 0,
        "native_word_count": 0,
        "native_block_count": 0,
        "native_text_coverage": 0.0,
        "image_coverage": 0.95,
        "invalid_unicode_ratio": 0.0,
        "replacement_char_ratio": 0.0,
        "whitespace_anomaly_score": 0.0,
        "native_reading_order_score": 0.0,
        "estimated_columns": 1,
        "table_density": 0.0,
        "formula_density": 0.0,
        "chart_probability": 0.0,
        "handwriting_probability": 0.0,
        "rotation_degrees": 0,
        "skew_degrees": 0.0,
        "blur_score": 0.1,
        "contrast_score": 0.8,
        "small_text_score": 0.1,
        "script_distribution": {"latin": 1.0},
        "suspected_prompt_injection": False,
    }
    base.update(overrides)
    return PageMetrics(**base)  # type: ignore[arg-type]


def _context(ready: frozenset[Route]) -> RouterContext:
    return RouterContext(
        mode=ProcessingMode.PRECISION,
        risk_tier=RiskTier.HIGH,
        ready_routes=ready,
    )


class TestArtifactBinding:
    def test_the_cited_artifacts_still_hash_to_what_the_module_claims(self) -> None:
        assert _digest(COMPLEMENTARITY_ARTIFACT) == COMPLEMENTARITY_SHA256
        assert _digest(ORACLE_ARTIFACT) == ORACLE_SHA256

    def test_every_row_matches_the_artifact_it_was_generated_from(self) -> None:
        raw = json.loads((REPO_ROOT / COMPLEMENTARITY_ARTIFACT).read_text(encoding="utf-8"))
        assert raw["methodology"]["tau"] == WRONG_EDIT_THRESHOLD
        checked = 0
        for row in MEASURED_RESCUES:
            pairs = raw["pairwise"][row.element.value]
            forward = f"{row.baseline}__{row.peer}"
            reverse = f"{row.peer}__{row.baseline}"
            if forward in pairs:
                pair = pairs[forward]
                rate = pair["P_B_correct_given_A_wrong"]
                wrong = pair["n_A_wrong"]
            else:
                pair = pairs[reverse]
                rate = pair["P_A_correct_given_B_wrong"]
                wrong = pair["n_B_wrong"]
            assert row.rescue_rate == pytest.approx(rate, abs=5e-7), row
            assert row.baseline_wrong_pages == wrong, row
            assert row.scored_pages == pair["n_pages"], row
            assert row.both_wrong_rate == pytest.approx(pair["P_both_wrong"], abs=5e-7), row
            checked += 1
        assert checked == len(MEASURED_RESCUES)

    def test_no_rate_is_published_without_its_denominator(self) -> None:
        for row in MEASURED_RESCUES:
            assert row.baseline_wrong_pages > 0, row
            assert row.scored_pages >= row.baseline_wrong_pages, row
            assert str(row.baseline_wrong_pages) in row.denominator


class TestSelection:
    @pytest.mark.parametrize(
        ("element", "expected_peer", "expected_rate"),
        [
            (ParseElement.TEXT, "ovis", 0.439873),
            (ParseElement.FORMULA, "flash", 0.151899),
            (ParseElement.TABLE, "ovis", 0.222222),
            (ParseElement.READING_ORDER, "ovis", 0.188889),
        ],
    )
    def test_picks_the_measured_winner_for_each_element(
        self,
        element: ParseElement,
        expected_peer: str,
        expected_rate: float,
    ) -> None:
        """Formula is the row that makes the table worth having: it is not ovis."""
        measurement = select_cross_check_peer(
            baseline=Route.PADDLE_VL,
            element=element,
            ready_routes=ALL_READY,
        )
        assert measurement is not None
        assert measurement.peer == expected_peer
        assert measurement.rescue_rate == pytest.approx(expected_rate, abs=5e-7)

    def test_rows_are_ordered_so_the_first_match_is_the_strongest(self) -> None:
        for element in ParseElement:
            rates = [row.rescue_rate for row in rescues_for(Route.PADDLE_VL, element)]
            assert rates == sorted(rates, reverse=True)

    def test_returns_nothing_when_no_measured_peer_can_be_served(self) -> None:
        assert (
            select_cross_check_peer(
                baseline=Route.PADDLE_VL,
                element=ParseElement.TEXT,
                ready_routes=frozenset({Route.PADDLE_VL, Route.NATIVE}),
            )
            is None
        )

    def test_returns_nothing_for_a_baseline_the_campaign_never_measured(self) -> None:
        for route in (Route.NATIVE, Route.HPD_FAST, Route.UNLIMITED_LONG):
            assert (
                select_cross_check_peer(
                    baseline=route,
                    element=ParseElement.TEXT,
                    ready_routes=ALL_READY,
                )
                is None
            )

    def test_never_offers_a_route_as_its_own_second_reader(self) -> None:
        for baseline in ARENA_MODEL_ROUTES.values():
            for element in ParseElement:
                measurement = select_cross_check_peer(
                    baseline=baseline,
                    element=element,
                    ready_routes=ALL_READY,
                )
                if measurement is not None:
                    assert ARENA_MODEL_ROUTES[measurement.peer] != baseline

    def test_a_zero_rescue_rate_is_not_a_second_reader(self) -> None:
        """paddle -> opus on tables measured 0.0. A peer that never rescues is no peer."""
        zero_rows = [row for row in MEASURED_RESCUES if row.rescue_rate == 0.0]
        assert zero_rows, "the guard is pointless if the artifact has no zero rows"
        for row in zero_rows:
            measurement = select_cross_check_peer(
                baseline=ARENA_MODEL_ROUTES.get(row.baseline, Route.NATIVE),
                element=row.element,
                ready_routes=ALL_READY,
            )
            assert measurement is None or measurement.rescue_rate > 0.0


class TestDominantElement:
    def test_a_page_with_neither_is_a_text_page(self) -> None:
        assert dominant_element(_page()) is ParseElement.TEXT

    def test_the_denser_of_the_two_decides(self) -> None:
        assert dominant_element(_page(formula_density=0.4, table_density=0.1)) is (
            ParseElement.FORMULA
        )
        assert dominant_element(_page(formula_density=0.1, table_density=0.4)) is (
            ParseElement.TABLE
        )

    def test_a_tie_goes_to_the_table(self) -> None:
        assert dominant_element(_page(formula_density=0.3, table_density=0.3)) is (
            ParseElement.TABLE
        )


class TestDecisionContract:
    def test_a_named_peer_must_say_which_element_named_it(self) -> None:
        with pytest.raises(ValueError, match="which element"):
            RouteDecision(
                route=Route.PADDLE_VL,
                route_profile="parse_precision_v1",
                reason_codes=(),
                expected_credits=1.0,
                requires_visual_parse=True,
                require_cross_check=True,
                max_attempts=2,
                policy_version="test",
                cross_check_route=Route.OVIS_VL,
            )

    def test_a_route_cannot_check_itself(self) -> None:
        with pytest.raises(ValueError, match="cross-check itself"):
            RouteDecision(
                route=Route.PADDLE_VL,
                route_profile="parse_precision_v1",
                reason_codes=(),
                expected_credits=1.0,
                requires_visual_parse=True,
                require_cross_check=True,
                max_attempts=2,
                policy_version="test",
                cross_check_route=Route.PADDLE_VL,
                cross_check_element="text",
            )

    def test_a_peer_without_a_cross_check_is_refused(self) -> None:
        with pytest.raises(ValueError, match="requires require_cross_check"):
            RouteDecision(
                route=Route.PADDLE_VL,
                route_profile="parse_precision_v1",
                reason_codes=(),
                expected_credits=1.0,
                requires_visual_parse=True,
                require_cross_check=False,
                max_attempts=2,
                policy_version="test",
                cross_check_route=Route.OVIS_VL,
                cross_check_element="text",
            )


class TestEngine:
    def test_names_the_peer_when_one_is_servable(self) -> None:
        decision = select_first_route(_context(ALL_READY), _page())
        assert decision.route is Route.PADDLE_VL
        assert decision.require_cross_check is True
        assert decision.cross_check_route is Route.OVIS_VL
        assert decision.cross_check_element == "text"
        assert "cross_check_measured:text:ovis" in decision.reason_codes

    def test_a_formula_page_gets_the_formula_winner_not_the_text_one(self) -> None:
        decision = select_first_route(
            _context(ALL_READY),
            _page(formula_density=0.6, table_density=0.05),
        )
        assert decision.cross_check_route is Route.INFINITY_FLASH
        assert decision.cross_check_element == "formula"

    def test_says_the_peer_is_unavailable_rather_than_substituting_one(self) -> None:
        decision = select_first_route(_context(frozenset({Route.PADDLE_VL})), _page())
        assert decision.route is Route.PADDLE_VL
        assert decision.require_cross_check is True
        assert decision.cross_check_route is None
        assert "cross_check_peer_unavailable" in decision.reason_codes

    def test_names_no_peer_when_no_cross_check_was_asked_for(self) -> None:
        context = RouterContext(
            mode=ProcessingMode.BALANCED,
            risk_tier=RiskTier.NORMAL,
            ready_routes=ALL_READY,
        )
        decision = select_first_route(context, _page())
        assert decision.require_cross_check is False
        assert decision.cross_check_route is None
        assert not any(code.startswith("cross_check") for code in decision.reason_codes)

    def test_an_unready_first_route_still_fails_closed(self) -> None:
        decision = select_first_route(_context(frozenset({Route.NATIVE})), _page())
        assert decision.route is Route.UNRESOLVED
        assert decision.cross_check_route is None
        assert "fail_closed_unresolved" in decision.reason_codes
