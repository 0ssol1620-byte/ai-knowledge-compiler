"""A dependency cycle cannot be recompiled in any order: the candidate goes to review."""

from __future__ import annotations

import dataclasses

import akc_product_core.compiler as compiler_module
import pytest
from akc_product_core import ProductCoreCompiler

from tests.unit.test_product_core_bridge import RELEASE, _document, _request, _sha


def test_a_reported_cycle_makes_the_candidate_review_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = compiler_module.DependencyGraph.impact_of

    def with_cycle(self, changed, **kw):  # type: ignore[no-untyped-def]
        return dataclasses.replace(
            original(self, changed, **kw), cycles_detected=(("ku_a", "ku_b", "ku_a"),)
        )

    monkeypatch.setattr(compiler_module.DependencyGraph, "impact_of", with_cycle)
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _request((_document("filing-a", "Revenue is 100 million won."),), request_id="c1"),
        input_sha256=_sha("c1"),
    )

    assert response.status == "review_required"
    assert "DEPENDENCY_CYCLE:ku_a->ku_b->ku_a" in response.candidate.review_reasons


def test_without_a_cycle_the_initial_compile_is_not_held_for_one() -> None:
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _request((_document("filing-a", "Revenue is 100 million won."),), request_id="c2"),
        input_sha256=_sha("c2"),
    )

    assert not any(r.startswith("DEPENDENCY_CYCLE") for r in response.candidate.review_reasons)
