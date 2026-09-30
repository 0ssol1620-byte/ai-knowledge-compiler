"""The Core's integrity checks are computed from the package it built, and fail closed."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from akc_cir.knowledge_model import CanonicalKnowledgeModel
from akc_cir.models import CanonicalDocument
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.compiler import VALIDATION_CHECK_REVIEW_REASON
from akc_product_core.contracts import (
    CandidatePackage,
    CandidatePackageFile,
    PreviousUnit,
    ProductCoreCompileResponse,
    ProductCoreDocument,
)

from .test_product_core_bridge import RELEASE, _document, _request

CHECKS = set(VALIDATION_CHECK_REVIEW_REASON)
ENGLISH = "Revenue for fiscal 2025 was 120 million dollars according to the annual report."
KOREAN = "2025년 매출액은 1200억원이며 영업이익은 150억원으로 증가하였다."


Mutation = Callable[[dict[str, str], list[CanonicalDocument], list[PreviousUnit]], None]


def _compile(
    *documents: ProductCoreDocument,
) -> tuple[ProductCoreCompileRequest, ProductCoreCompileResponse]:
    request = _request(tuple(documents), request_id="validation-checks")
    return request, ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request, input_sha256="sha256:" + "b" * 64
    )


@pytest.mark.parametrize("text", [ENGLISH, KOREAN])
def test_healthy_compile_reports_all_four_checks_computed_true(text: str) -> None:
    _, response = _compile(_document("doc-a", text))
    validation = response.candidate.validation

    assert {name: validation[name] for name in CHECKS} == dict.fromkeys(CHECKS, True)
    assert not set(VALIDATION_CHECK_REVIEW_REASON.values()) & set(response.candidate.review_reasons)
    report = json.loads(
        next(
            f.content
            for f in response.candidate.package.files
            if f.path == "validation/report.json"
        )
    )
    assert report["checks"] == {name: True for name in CHECKS}
    assert response.receipt.candidate_promotion is False


def test_mixed_english_and_korean_collection_completes_as_candidate() -> None:
    _, response = _compile(_document("doc-en", ENGLISH), _document("doc-ko", KOREAN))

    assert response.status == "completed"
    assert response.candidate.lifecycle == "candidate"
    assert all(response.candidate.validation[name] is True for name in CHECKS)


def test_input_key_that_is_not_content_addressed_forces_review() -> None:
    document = _document("doc-a", ENGLISH)
    document = document.model_copy(update={"immutable_object_key": "uploads/doc-a/latest.pdf"})
    _, response = _compile(document)

    assert response.candidate.validation["immutableInputsOnly"] is False
    assert response.status == "review_required"
    assert response.candidate.lifecycle == "review_required"
    assert "IMMUTABLE_INPUTS_ONLY_UNPROVEN" in response.candidate.review_reasons
    assert response.receipt.candidate_promotion is False


def test_ocr_key_from_another_version_forces_review() -> None:
    document = _document("doc-a", ENGLISH)
    document = document.model_copy(
        update={"ocr_object_key": "immutable/t/w/doc-a/" + "c" * 64 + "/ocr.json"}
    )
    _, response = _compile(document)

    assert response.candidate.validation["immutableInputsOnly"] is False
    assert "IMMUTABLE_INPUTS_ONLY_UNPROVEN" in response.candidate.review_reasons


def _recheck(mutate: Mutation, *, text: str | None = None) -> dict[str, bool]:
    """Recompute the checks over a package one mutation away from a healthy one."""
    documents_in = (
        (_document("doc-a", text),)
        if text
        else (_document("doc-en", ENGLISH), _document("doc-ko", KOREAN))
    )
    request, response = _compile(*documents_in)
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    documents = [
        CanonicalDocument.model_validate(item) for item in response.candidate.canonical_documents
    ]
    model = CanonicalKnowledgeModel.model_validate(response.candidate.canonical_knowledge_model)
    files = {file.path: file.content for file in response.candidate.package.files}
    units = list(response.candidate.units)
    mutate(files, documents, units)
    package = CandidatePackage(
        roots=response.candidate.package.roots,
        files=tuple(
            CandidatePackageFile(
                path=path,
                media_type="application/octet-stream",
                size_bytes=len(content.encode("utf-8")),
                sha256=next(
                    (f.sha256 for f in response.candidate.package.files if f.path == path),
                    "sha256:" + "0" * 64,
                ),
                content=content,
            )
            for path, content in files.items()
        ),
    )
    return compiler._validation_checks(
        request=request,
        canonical_documents=documents,
        knowledge_model=model,
        units=units,
        package=package,
    )


def test_recheck_of_untouched_package_passes() -> None:
    assert _recheck(lambda files, documents, units: None) == dict.fromkeys(CHECKS, True)


def test_tampered_file_content_fails_deterministic_materialization() -> None:
    def mutate(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        files["semantics/claims.jsonl"] += "\n"

    assert _recheck(mutate)["deterministicMaterialization"] is False


def test_graph_serialisations_that_disagree_fail_deterministic_materialization() -> None:
    def drop_ttl_edge(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        lines = files["ontology/knowledge.ttl"].splitlines()
        edge = next(i for i, line in enumerate(lines) if " tav:supported_by " in line)
        files["ontology/knowledge.ttl"] = "\n".join(lines[:edge] + lines[edge + 1 :]) + "\n"

    def drop_csv_node(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        lines = files["graph/nodes.csv"].splitlines()
        files["graph/nodes.csv"] = "\n".join(lines[:-1]) + "\n"

    def missing_jsonld(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        del files["ontology/knowledge.jsonld"]

    for mutate in (drop_ttl_edge, drop_csv_node, missing_jsonld):
        assert _recheck(mutate)["deterministicMaterialization"] is False, mutate.__name__


def test_missing_source_binding_fails_source_coverage() -> None:
    def drop_listing(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        rows = json.loads(files["source/collection-files.json"])
        files["source/collection-files.json"] = json.dumps(rows[:1])

    def drop_document(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        documents.pop()

    for mutate in (drop_listing, drop_document):
        assert _recheck(mutate)["sourceCoverage"] is False, mutate.__name__


def test_missing_or_dangling_evidence_fails_evidence_coverage() -> None:
    def dangling_chunk(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        rows = [json.loads(line) for line in files["rag/chunks.jsonl"].splitlines()]
        rows[0]["evidenceIds"] = ["ev_missing"]
        files["rag/chunks.jsonl"] = "".join(json.dumps(row) + "\n" for row in rows)

    def no_chunks(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        files["rag/chunks.jsonl"] = ""

    def document_without_units(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        keep = units[0].source_version_id
        units[:] = [unit for unit in units if unit.source_version_id == keep]

    for mutate in (dangling_chunk, no_chunks, document_without_units):
        assert _recheck(mutate)["evidenceCoverage"] is False, mutate.__name__


ENTITY_TEXT = "2025 revenue was 100 million won. TAVONEL Research Institute reported the result."


def _jsonld_graph(files: dict[str, str]) -> list[dict[str, object]]:
    graph = json.loads(files["ontology/knowledge.jsonld"])["@graph"]
    assert isinstance(graph, list)
    return graph


def _set_jsonld(files: dict[str, str], graph: list[dict[str, object]]) -> None:
    document = json.loads(files["ontology/knowledge.jsonld"])
    document["@graph"] = graph
    files["ontology/knowledge.jsonld"] = json.dumps(document)


def test_jsonld_links_that_disagree_with_the_model_fail_deterministic_materialization() -> None:
    def swap_relation(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        graph = _jsonld_graph(files)
        node = next(item for item in graph if item["@type"] == "relation")
        node["subjectId"], node["objectId"] = node["objectId"], node["subjectId"]
        _set_jsonld(files, graph)

    def drop_claim_entities(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        graph = _jsonld_graph(files)
        node = next(item for item in graph if item["@type"] == "claim" and item["entityIds"])
        node["entityIds"] = []
        _set_jsonld(files, graph)

    def claim_cites_missing_evidence(
        files: dict[str, str], documents: list[CanonicalDocument], units: list[PreviousUnit]
    ) -> None:
        graph = _jsonld_graph(files)
        next(item for item in graph if item["@type"] == "claim")["evidenceId"] = "ev_missing"
        _set_jsonld(files, graph)

    for mutate in (swap_relation, drop_claim_entities, claim_cites_missing_evidence):
        checks = _recheck(mutate, text=ENTITY_TEXT)
        assert checks["deterministicMaterialization"] is False, mutate.__name__


def test_payload_links_disagreeing_with_model_links_fail_even_when_serialised_faithfully() -> None:
    """A model whose relation payload and `links` disagree, serialised exactly as the model says."""
    from akc_product_core.compiler import _jsonld_links_agree, _jsonld_node

    _, response = _compile(_document("doc-a", ENTITY_TEXT))
    raw = response.candidate.canonical_knowledge_model["objects"]
    assert isinstance(raw, list)
    objects = [dict(item) for item in raw]
    assert _jsonld_links_agree([_jsonld_node(item) for item in objects], objects)

    relation = next(item for item in objects if item["kind"] == "relation")
    relation["links"] = list(reversed(relation["links"]))
    assert not _jsonld_links_agree([_jsonld_node(item) for item in objects], objects)
