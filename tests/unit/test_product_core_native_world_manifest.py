"""Tiny existing-parser fixtures for complete referenced native Worlds."""

import copy
import hashlib
import json

import pytest
from akc_cir.base import canonical_json, sha256_digest
from akc_cir.identity import document_version_id, source_id
from akc_product_core import native_world_manifest as native
from akc_product_core.native_cir import parse_native_request, serialize_native_draft
from akc_product_core.native_facts import project_native_facts
from test_product_core_native_cir import _body, _fixture, _rebind_cir_hashes

RELEASE = "sha256:" + "a" * 64


def wire(value):
    return (canonical_json(value) + "\n").encode("utf-8")


def inputs(kind="normal", payload=None):
    request = parse_native_request(_body(payload or _fixture(kind)))
    facts = project_native_facts(request)
    return wire(facts), wire(serialize_native_draft(request).package), facts


def compile_fixture(kind="normal", payload=None):
    facts_body, cir_body, facts = inputs(kind, payload)
    result = native.reduce_native_manifest(facts_body, cir_body, core_release_digest=RELEASE)
    refs = {r.kind: r for r in result.manifest.artifacts}
    blobs = {
        refs["native_facts"].artifact_id: facts_body,
        refs["full_cir_package"].artifact_id: cir_body,
        refs["canonical_knowledge_model"].artifact_id: result.canonical_model,
    }
    return result, blobs, facts


@pytest.mark.parametrize(
    "kind", ["normal", "merged", "unicode", "zero", "duplicate-header", "locator", "formula"]
)
def test_complete_artifact_verification_resolution_and_determinism(kind):
    result, blobs, facts = compile_fixture(kind)
    body = native.manifest_bytes(result.manifest)
    verified = native.verify_native_manifest(body, blobs)
    other, other_blobs, _ = compile_fixture(kind)
    assert body == native.manifest_bytes(other.manifest)
    assert blobs == other_blobs
    assert verified.facts == facts
    assert result.manifest.cell_count == len(facts.evidence)
    assert result.manifest.knowledge_object_count == len(verified.knowledge_model.objects)
    assert len(body) < 4096
    assert len(result.canonical_model) <= native.MAX_NATIVE_MODEL_BYTES
    for reference in result.manifest.artifacts:
        assert reference.sha256 == sha256_digest(blobs[reference.artifact_id])
        assert reference.byte_length == len(blobs[reference.artifact_id])
    assert result.manifest.status == "review_required"
    assert result.manifest.approval_status == "unbound"
    assert result.manifest.candidate_promotion is False
    assert result.manifest.parent_world_state_id is None
    assert result.manifest.signature_status == "external_signer_required"
    model = verified.knowledge_model
    pairs = [o for o in model.objects if o.kind.value in {"claim", "note"}]
    evidence_objects = [o for o in model.objects if o.kind.value == "evidence"]
    assert {o.payload["factId"] for o in pairs} == {e.fact_id for e in facts.evidence}
    assert {o.payload["evidenceId"] for o in evidence_objects} == {
        e.evidence_id for e in facts.evidence
    }
    assert all(
        o.origin.value == "native_extracted" and o.verification_state.value == "unresolved"
        for o in model.objects
    )
    assert not any(o.kind.value in {"entity", "relation"} for o in model.objects)
    assert not any(
        "sheet" in o.payload or "observation" in o.payload or "rawText" in o.payload for o in pairs
    )
    for ev in facts.evidence:
        resolved = native.resolve_native_cell(body, blobs, evidence_id=ev.evidence_id)
        assert resolved.evidence == ev
        assert resolved.cell.id == resolved.fact.cell_id == ev.cell_id
        assert resolved.cell.source_refs == ev.source_refs
        assert resolved.cell.raw_text == resolved.fact.raw_text
        assert resolved.cell.normalized_text == resolved.fact.normalized_text
        assert (
            resolved.sheet
            == facts.canonical_documents[0].metadata["sheets"][ev.source_refs[0].page_index0]
        )
        assert resolved.evidence.source_refs[0].bbox1000 is None
    with pytest.raises(ValueError, match="not in this manifest"):
        native.resolve_native_cell(body, blobs, evidence_id="unknown-evidence")


def test_literal_empty_false_zero_error_format_and_extra_metadata():
    payload = _fixture()
    doc = payload["documents"][0]["canonicalDocument"]
    doc["metadata"]["sheets"][0]["large_extra"] = "e\u0301" * 2048
    table = next(b["table"] for b in doc["blocks"] if "table" in b)
    states = [("", "string"), ("False", "boolean"), ("0", "number"), ("#DIV/0!", "error")]
    for cell, (value, kind) in zip(table["cells"], states, strict=True):
        cell.update(
            rawTextVerbatim=True,
            rawText=value,
            normalizedText=value,
            valueType=kind,
            numberFormat="  $0.00 %  ",
        )
    _rebind_cir_hashes(payload)
    result, blobs, facts = compile_fixture(payload=payload)
    verified = native.verify_native_manifest(native.manifest_bytes(result.manifest), blobs)
    for ev, (value, kind) in zip(facts.evidence, states, strict=True):
        resolved = native.resolve_native_cell(
            native.manifest_bytes(result.manifest), blobs, evidence_id=ev.evidence_id
        )
        assert resolved.fact.observation.value == value
        assert resolved.cell.value_type == kind
        assert resolved.cell.number_format == "  $0.00 %  "
        assert resolved.sheet["large_extra"] == "e\u0301" * 2048
    notes = [o for o in verified.knowledge_model.objects if o.kind.value == "note"]
    assert len(notes) == 1 and notes[0].payload["observationKind"] == "source_error"
    assert b"large_extra" not in result.canonical_model
    assert result.manifest.validation["semanticBinding"] == "unbound"


@pytest.mark.parametrize(
    "cached,unavailable", [(False, False), (True, False), (True, True), (False, True)]
)
def test_formula_variants_remain_in_authoritative_facts(cached, unavailable):
    payload = _fixture("formula")
    cell = next(
        c
        for b in payload["documents"][0]["canonicalDocument"]["blocks"]
        if "table" in b
        for c in b["table"]["cells"]
        if c.get("formula")
    )
    if cached:
        cell.update(normalizedText="0", valueType="number")
        cell["qualityFlags"] = [
            f for f in cell["qualityFlags"] if f != "formula_cached_value_missing"
        ]
    if unavailable:
        cell.pop("formula")
        cell["rawText"] = ""
        cell["qualityFlags"].append("formula_text_unavailable")
    _rebind_cir_hashes(payload)
    result, blobs, facts = compile_fixture(payload=payload)
    ev = next(e for e in facts.evidence if e.cell_id == cell["id"])
    resolved = native.resolve_native_cell(
        native.manifest_bytes(result.manifest), blobs, evidence_id=ev.evidence_id
    )
    assert resolved.fact.observation.kind == "formula_expression"
    assert resolved.fact.observation.evaluated is False
    assert resolved.fact.observation.expression == (None if unavailable else "=1+2")
    assert resolved.fact.observation.cached_text_informational == ("0" if cached else None)


@pytest.mark.parametrize("kind", ["native_facts", "full_cir_package", "canonical_knowledge_model"])
@pytest.mark.parametrize("attack", ["missing", "changed", "truncated"])
def test_referenced_artifact_missing_tampered_or_truncated_refuses(kind, attack):
    result, blobs, _ = compile_fixture()
    ref = next(r for r in result.manifest.artifacts if r.kind == kind)
    if attack == "missing":
        del blobs[ref.artifact_id]
    elif attack == "changed":
        blobs[ref.artifact_id] += b" "
    else:
        blobs[ref.artifact_id] = blobs[ref.artifact_id][:-1]
    with pytest.raises(ValueError):
        native.verify_native_manifest(native.manifest_bytes(result.manifest), blobs)


@pytest.mark.parametrize(
    "mutation",
    ["scope", "membership", "release", "count", "kind", "promotion", "previous", "digest"],
)
def test_manifest_fields_are_bound(mutation):
    result, blobs, _ = compile_fixture()
    raw = json.loads(native.manifest_bytes(result.manifest))
    if mutation == "scope":
        raw["workspaceId"] = "wrong-workspace"
    elif mutation == "membership":
        raw["sources"].append(copy.deepcopy(raw["sources"][0]))
    elif mutation == "release":
        raw["coreReleaseDigest"] = "sha256:" + "b" * 64
    elif mutation == "count":
        raw["cellCount"] += 1
    elif mutation == "kind":
        raw["artifacts"][0]["kind"] = "full_cir_package"
    elif mutation == "promotion":
        raw["candidatePromotion"] = True
    elif mutation == "previous":
        raw["parentWorldStateId"] = "previous-world"
    else:
        raw["manifestDigest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        native.verify_native_manifest(wire(raw), blobs)


def test_coherently_rehashed_false_model_still_refuses():
    result, blobs, _ = compile_fixture()
    model = json.loads(result.canonical_model)
    claim = next(o for o in model["objects"] if o["kind"] == "claim")
    claim["payload"]["factId"] = "native_fact_" + "0" * 64
    forged_model = wire(model)
    raw = json.loads(native.manifest_bytes(result.manifest))
    old_ref = raw["artifacts"][2]
    new_ref = native._reference("canonical_knowledge_model", forged_model)
    raw["artifacts"][2] = json.loads(canonical_json(new_ref))
    work = {k: v for k, v in raw.items() if k not in {"worldStateId", "manifestDigest"}}
    raw["worldStateId"] = native._id("native_refs_ws", canonical_json(work))
    raw["manifestDigest"] = sha256_digest(
        wire({k: v for k, v in raw.items() if k != "manifestDigest"})
    )
    del blobs[old_ref["artifactId"]]
    blobs[new_ref.artifact_id] = forged_model
    with pytest.raises(ValueError, match="projection binding mismatch"):
        native.verify_native_manifest(wire(raw), blobs)


def test_wrong_package_and_changed_input_identity_refuse():
    facts_body, cir_body, _ = inputs()
    _, other_cir, _ = inputs("merged")
    with pytest.raises(ValueError, match="CIR package binding"):
        native.reduce_native_manifest(facts_body, other_cir, core_release_digest=RELEASE)
    raw = json.loads(facts_body)
    raw["documents"][0]["sourceVersionId"] = "wrong-version"
    with pytest.raises(ValueError):
        native.reduce_native_manifest(wire(raw), cir_body, core_release_digest=RELEASE)


def test_exact_model_and_manifest_fences(monkeypatch):
    facts_body, cir_body, _ = inputs()
    result = native.reduce_native_manifest(facts_body, cir_body, core_release_digest=RELEASE)
    model_size = len(result.canonical_model)
    manifest_size = len(native.manifest_bytes(result.manifest))
    for cap in [model_size, model_size + 1]:
        monkeypatch.setattr(native, "MAX_NATIVE_MODEL_BYTES", cap)
        assert (
            native.reduce_native_manifest(
                facts_body, cir_body, core_release_digest=RELEASE
            ).canonical_model
            == result.canonical_model
        )
    monkeypatch.setattr(native, "MAX_NATIVE_MODEL_BYTES", model_size - 1)
    with pytest.raises(ValueError):
        native.reduce_native_manifest(facts_body, cir_body, core_release_digest=RELEASE)
    monkeypatch.setattr(native, "MAX_NATIVE_MODEL_BYTES", 32 * 1024 * 1024)
    for cap in [manifest_size, manifest_size + 1]:
        monkeypatch.setattr(native, "MAX_NATIVE_MANIFEST_BYTES", cap)
        assert native.manifest_bytes(
            native.reduce_native_manifest(
                facts_body, cir_body, core_release_digest=RELEASE
            ).manifest
        ) == native.manifest_bytes(result.manifest)
    monkeypatch.setattr(native, "MAX_NATIVE_MANIFEST_BYTES", manifest_size - 1)
    with pytest.raises(ValueError):
        native.reduce_native_manifest(facts_body, cir_body, core_release_digest=RELEASE)


@pytest.mark.parametrize("limit", ["early", "final-byte"])
def test_projected_refusal_precedes_cko_construction(monkeypatch, limit):
    facts_body, cir_body, _ = inputs()
    size = len(
        native.reduce_native_manifest(
            facts_body, cir_body, core_release_digest=RELEASE
        ).canonical_model
    )
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("CKO construction started before byte admission")

    monkeypatch.setattr(native, "MAX_NATIVE_MODEL_BYTES", 128 if limit == "early" else size - 1)
    monkeypatch.setattr(native, "build_knowledge_object", forbidden)
    with pytest.raises(ValueError, match="projected byte limit"):
        native.reduce_native_manifest(facts_body, cir_body, core_release_digest=RELEASE)
    assert calls == []


def test_grid_preflight_before_nested_facts_model(monkeypatch):
    import akc_cir.models as cir_models

    facts_body, cir_body, _ = inputs()
    raw = json.loads(facts_body)
    table = next(b["table"] for b in raw["canonicalDocuments"][0]["blocks"] if "table" in b)
    table.update(rowCount=100_000, columnCount=1_024)
    table["cells"][0].update(rowSpan=100_000, columnSpan=1_024)
    calls = []

    def forbidden(*args):
        calls.append(True)
        raise AssertionError("grid expansion reached")

    monkeypatch.setattr(cir_models, "range", forbidden, raising=False)
    with pytest.raises(ValueError, match="native cell/grid limit"):
        native.reduce_native_manifest(wire(raw), cir_body, core_release_digest=RELEASE)
    assert calls == []


@pytest.mark.parametrize("body", [b"{}", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"])
def test_strict_manifest_wire_refuses(body):
    with pytest.raises(ValueError):
        native.verify_native_manifest(body, {})


def test_core_release_changes_binding_without_semantic_compiler(monkeypatch):
    from akc_product_core import semantics

    def forbidden(*args, **kwargs):
        raise AssertionError("semantic compiler called")

    monkeypatch.setattr(semantics, "compile_semantics", forbidden)
    facts_body, cir_body, _ = inputs()
    first = native.reduce_native_manifest(facts_body, cir_body, core_release_digest=RELEASE)
    second = native.reduce_native_manifest(
        facts_body, cir_body, core_release_digest="sha256:" + "b" * 64
    )
    assert first.manifest.world_state_id != second.manifest.world_state_id
    assert (
        hashlib.sha256(first.canonical_model).digest()
        != hashlib.sha256(second.canonical_model).digest()
    )


@pytest.mark.parametrize(
    "kind,value",
    [
        ("date", "2025-03-27"),
        ("datetime", "2025-03-27T12:34:56"),
        ("time", "12:34:56"),
        ("duration", "P1DT2H"),
    ],
)
def test_temporal_literals_resolve_without_conversion(kind, value):
    payload = _fixture()
    cell = next(
        c
        for b in payload["documents"][0]["canonicalDocument"]["blocks"]
        if "table" in b
        for c in b["table"]["cells"]
    )
    cell.update(rawText=value, normalizedText=value, valueType=kind, numberFormat="yyyy-mm-dd")
    _rebind_cir_hashes(payload)
    result, blobs, facts = compile_fixture(payload=payload)
    ev = next(e for e in facts.evidence if e.cell_id == cell["id"])
    resolved = native.resolve_native_cell(
        native.manifest_bytes(result.manifest), blobs, evidence_id=ev.evidence_id
    )
    assert resolved.fact.observation.value == value
    assert resolved.cell.raw_text == value and resolved.cell.value_type == kind
    assert resolved.cell.number_format == "yyyy-mm-dd"


def test_complete_multiple_source_membership_and_input_order():
    first, second = _fixture(), _fixture("unicode")
    envelope = second["documents"][0]
    envelope["nativeId"] = "another-book"
    envelope["sourceId"] = source_id(
        tenant_id=first["tenantId"],
        connector_type=envelope["connectorType"],
        native_id="another-book",
    )
    envelope["sourceVersionId"] = document_version_id(
        source=envelope["sourceId"], content_sha256=envelope["contentSha256"]
    )
    cir = envelope["canonicalDocument"]
    cir.update(documentId=envelope["sourceId"], documentVersionId=envelope["sourceVersionId"])
    for block in cir["blocks"]:
        refs = list(block["sourceRefs"])
        if "table" in block:
            refs.extend(block["table"]["sourceRefs"])
            refs.extend(r for c in block["table"]["cells"] for r in c["sourceRefs"])
        for ref in refs:
            ref.update(
                documentId=envelope["sourceId"], documentVersionId=envelope["sourceVersionId"]
            )
    _rebind_cir_hashes(second)
    first["documents"].append(envelope)
    first["documents"].sort(key=lambda d: d["sourceId"], reverse=True)
    result, blobs, facts = compile_fixture(payload=first)
    assert [s.source_id for s in result.manifest.sources] == sorted(
        d["sourceId"] for d in first["documents"]
    )
    assert facts.input_document_order == tuple(d["sourceVersionId"] for d in first["documents"])
    verified = native.verify_native_manifest(native.manifest_bytes(result.manifest), blobs)
    assert verified.facts == facts and len(facts.canonical_documents) == 2
    # An internally rehashed header cannot hide one of the complete source artifacts.
    raw = json.loads(native.manifest_bytes(result.manifest))
    raw["sources"].pop()
    work = {k: v for k, v in raw.items() if k not in {"worldStateId", "manifestDigest"}}
    raw["worldStateId"] = native._id("native_refs_ws", canonical_json(work))
    raw["manifestDigest"] = sha256_digest(
        wire({k: v for k, v in raw.items() if k != "manifestDigest"})
    )
    with pytest.raises(ValueError, match="projection binding mismatch"):
        native.verify_native_manifest(wire(raw), blobs)


@pytest.mark.parametrize("attack", ["fact-value", "evidence-id", "duplicate-cell", "mixed-ocr"])
def test_existing_fact_projection_validation_is_required(attack):
    facts_body, cir_body, _ = inputs()
    raw = json.loads(facts_body)
    cell = raw["documents"][0]["tables"][0]["rows"][0]["cells"][0]
    if attack == "fact-value":
        cell["observation"]["value"] = "fabricated"
    elif attack == "evidence-id":
        cell["evidenceId"] = "wrong-evidence"
    elif attack == "duplicate-cell":
        raw["documents"][0]["tables"][0]["rows"][0]["cells"].append(copy.deepcopy(cell))
    else:
        raw["regions"] = [{"id": "pdf-region", "text": "mixed"}]
    with pytest.raises(ValueError):
        native.reduce_native_manifest(wire(raw), cir_body, core_release_digest=RELEASE)


@pytest.mark.parametrize("kind", ["facts", "package"])
def test_input_byte_fence_before_json_decode(monkeypatch, kind):
    facts_body, cir_body, _ = inputs()

    def forbidden(*args, **kwargs):
        raise AssertionError("oversized input decoded")

    monkeypatch.setattr(native.json, "loads", forbidden)
    body = facts_body if kind == "facts" else cir_body
    cap = (
        native.MAX_NATIVE_FACTS_OUTPUT_BYTES if kind == "facts" else native.MAX_NATIVE_PACKAGE_BYTES
    )
    with pytest.raises(ValueError, match="input byte limit"):
        native._load(body, min(cap, len(body) - 1))


def test_unexpected_artifact_refuses():
    result, blobs, _ = compile_fixture()
    blobs["unexpected-artifact"] = b"{}"
    with pytest.raises(ValueError, match="unexpected artifacts"):
        native.verify_native_manifest(native.manifest_bytes(result.manifest), blobs)
