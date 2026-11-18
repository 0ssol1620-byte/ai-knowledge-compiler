"""WO-D22-3: creative-works and team-workspace reachable through the Core V2 contract.

The class guarded here: every request the live contract already accepted (no
``requested_blueprint`` or one of the seven built-in ids) compiles to the same bytes it did
when the compiler planned against the built-in registry; the two new ids compile to their own
plan; any other id is refused by the contract. Both plan call sites are exercised: the
single compile and ``corpus_reduce``.
"""

from __future__ import annotations

import json
from typing import Any, get_args

import akc_product_core.compiler as compiler_module
import akc_product_core.corpus_reduce as reduce_module
import pytest
from akc_cir.base import canonical_json
from akc_domain_packs import builtin_blueprints
from akc_domain_packs.horizontal import horizontal_blueprints
from akc_product_core.compiler import ProductCoreCompiler
from akc_product_core.contracts import BlueprintId, ProductCoreCompileRequest
from akc_product_core.corpus_reduce import corpus_reduce
from pydantic import ValidationError

from benchmark.product_core_corpus_reduce import (
    RELEASE,
    T0,
    compile_parts,
    compile_wire,
    synthetic_corpora,
)

BUILTIN_IDS: tuple[BlueprintId, ...] = (
    "corporate-filings",
    "course-materials",
    "generic-mixed-corpus",
    "legal-contracts",
    "personal-knowledge",
    "research-library",
    "technical-documentation",
)
NEW_IDS: tuple[BlueprintId, ...] = ("creative-works", "team-workspace")
LIVE_ACCEPTED: tuple[BlueprintId | None, ...] = (None, *BUILTIN_IDS)
CORPORA = synthetic_corpora()
CORPUS_NAMES = ("synthetic-00", "synthetic-05", "seam-contradictions", "no-claims")


def _compile(documents: Any, blueprint: BlueprintId | None) -> dict[str, Any]:
    _, _, payload = compile_wire(
        ProductCoreCompiler(core_release_digest=RELEASE),
        documents,
        request_id="horizontal-selection",
        requested_at=T0,
        blueprint=blueprint,
    )
    return payload


def _plan(payload: dict[str, Any]) -> dict[str, Any]:
    files = payload["candidate"]["package"]["files"]
    (plan_file,) = [row for row in files if row["path"] == "ontology/architecture-plan.json"]
    plan: dict[str, Any] = json.loads(plan_file["content"])
    return plan


def _as_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 6b3a27bf behaviour: plan_architecture against the built-in registry only."""
    monkeypatch.setattr(compiler_module, "horizontal_blueprints", builtin_blueprints)
    monkeypatch.setattr(reduce_module, "horizontal_blueprints", builtin_blueprints)


def test_contract_accepts_exactly_the_nine_registry_ids() -> None:
    assert set(get_args(BlueprintId)) == {b.id for b in horizontal_blueprints().blueprints}
    assert set(get_args(BlueprintId)) == {*BUILTIN_IDS, *NEW_IDS}
    assert {b.id for b in builtin_blueprints().blueprints} == set(BUILTIN_IDS)


@pytest.mark.parametrize("blueprint", ["generic", "Creative-Works", "creative_works", "missing"])
def test_contract_still_refuses_an_unknown_id(blueprint: str) -> None:
    request, _, _ = compile_wire(
        ProductCoreCompiler(core_release_digest=RELEASE),
        CORPORA["synthetic-00"],
        request_id="horizontal-unknown",
        requested_at=T0,
        blueprint="team-workspace",
    )
    wire = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert ProductCoreCompileRequest.model_validate(wire).requested_blueprint == "team-workspace"
    with pytest.raises(ValidationError):
        ProductCoreCompileRequest.model_validate({**wire, "requestedBlueprint": blueprint})


@pytest.mark.parametrize("blueprint", [*BUILTIN_IDS, *NEW_IDS])
def test_all_nine_ids_compile_and_name_their_blueprint(blueprint: BlueprintId) -> None:
    payload = _compile(CORPORA["synthetic-00"], blueprint)
    assert payload["status"] != "rejected"
    plan = _plan(payload)
    assert plan["blueprint"] == blueprint
    assert plan["module_sha256"] == horizontal_blueprints().module_sha256[blueprint]


@pytest.mark.parametrize("name", CORPUS_NAMES)
def test_requests_the_live_contract_accepted_compile_to_the_same_bytes(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    after = {bp: canonical_json(_compile(CORPORA[name], bp)) for bp in LIVE_ACCEPTED}
    _as_live(monkeypatch)
    before = {bp: canonical_json(_compile(CORPORA[name], bp)) for bp in LIVE_ACCEPTED}
    assert after == before


@pytest.mark.parametrize("blueprint", [None, "legal-contracts", *NEW_IDS])
def test_corpus_reduce_plans_against_the_same_registry(
    blueprint: BlueprintId | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents = CORPORA["synthetic-09"]
    split = [list(range(0, len(documents), 2)), list(range(1, len(documents), 2))]

    def reduced() -> dict[str, Any]:
        parts = compile_parts(
            ProductCoreCompiler(core_release_digest=RELEASE),
            documents,
            split,
            corpus_id="corpus-horizontal",
            blueprint=blueprint,
        )
        world, _ = corpus_reduce(parts)
        return world

    world = reduced()
    if blueprint is not None:
        assert world["architecture"]["blueprint"] == blueprint
    if blueprint in NEW_IDS:
        _as_live(monkeypatch)
        with pytest.raises(LookupError):
            reduced()
    else:
        _as_live(monkeypatch)
        assert canonical_json(reduced()) == canonical_json(world)
