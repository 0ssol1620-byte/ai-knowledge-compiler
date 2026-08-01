from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest
from akc_cir import (
    CanonicalKnowledgeModel,
    KnowledgeObjectKind,
    KnowledgeOrigin,
    KnowledgeVerificationState,
    SourceRef,
    build_knowledge_object,
    canonical_json,
)
from akc_exporters import (
    Ed25519Signer,
    KnowledgePackageError,
    SemanticAssetManifest,
    SemanticBlueprintManifest,
    build_knowledge_package,
    canonical_knowledge_model_bytes,
    import_knowledge_package,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _groups() -> dict[str, dict[str, bytes]]:
    return {
        "source": {"original/source.pdf": b"source"},
        "canonical": {"model.json": b'{"blocks":[]}'},
        "obsidian": {"Home.md": b"# Home\n", "Notes/Document.md": b"# Document\n"},
        "ontology": {
            "knowledge.ttl": b"@prefix str: <urn:structara:> .\n",
            "knowledge.owl": b"<rdf:RDF />\n",
            "knowledge.jsonld": b"{}\n",
            "knowledge.skos.ttl": b"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n",
            "shapes.shacl.ttl": b"@prefix sh: <http://www.w3.org/ns/shacl#> .\n",
            "vocabulary.md": b"# Vocabulary\n",
            "provenance.jsonld": b"{}\n",
        },
        "graph": {
            "nodes.csv": b"id:ID,label\n1,Document\n",
            "relationships.csv": b":START_ID,:END_ID,:TYPE\n",
            "constraints.cypher": b"CREATE CONSTRAINT document_id IF NOT EXISTS;\n",
            "indexes.cypher": b"CREATE INDEX document_label IF NOT EXISTS;\n",
            "import.cypher": b"// strict import\n",
        },
        "rag": {
            "documents.jsonl": b'{"id":"document-1"}\n',
            "chunks.jsonl": b'{"id":"chunk-1"}\n',
            "metadata.jsonl": b'{"id":"chunk-1","verified":true}\n',
            "evidence.jsonl": b'{"id":"chunk-1","source":"block-1"}\n',
            "retrieval-profile.json": b'{"mode":"hybrid"}\n',
        },
        "provenance": {"activities.jsonl": b'{"id":"activity-1"}\n'},
        "validation": {
            "report.json": b'{"critical":0}',
            "round-trip.json": b'{"critical_loss":0}',
        },
    }


def _signer() -> Ed25519Signer:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return Ed25519Signer.from_pem(signer_id="release-test-key", private_key_pem=pem)


def _semantic_model() -> tuple[
    CanonicalKnowledgeModel,
    tuple[SemanticBlueprintManifest, ...],
    str,
]:
    source = SourceRef(
        document_id="document-001",
        document_version_id="document-001-v1",
        page_index0=0,
        page_number1=1,
    )
    assets = tuple(
        SemanticAssetManifest(
            path=path,
            media_type="text/markdown" if path.endswith(".md") else "application/yaml",
            size_bytes=10,
            sha256="sha256:" + character * 64,
        )
        for path, character in (
            ("prompts/compiler.md", "1"),
            ("validators/rules.yaml", "2"),
            ("templates/views.yaml", "3"),
        )
    )
    blueprint = SemanticBlueprintManifest(
        blueprint_id="test-blueprint",
        blueprint_version="1.0.0",
        module_sha256="sha256:" + "4" * 64,
        assets=assets,
        prompt_assets=(assets[0],),
        validator_assets=(assets[1],),
        template_assets=(assets[2],),
        validator_ids=("source_coverage",),
        template_ids=("Home",),
        export_profiles=("portable",),
    )
    blueprint_object = build_knowledge_object(
        stable_id="asset:blueprint:test-blueprint:1.0.0",
        tenant_id="tenant-001",
        collection_id="col-001",
        kind=KnowledgeObjectKind.ASSET,
        source_refs=(source,),
        origin=KnowledgeOrigin.RULE_DERIVED,
        verification_state=KnowledgeVerificationState.VERIFIED,
        created_by_activity="activity-001",
        version=1,
        payload={
            "semantic_role": "knowledge_blueprint_module",
            "manifest": blueprint.model_dump(mode="json"),
        },
    )
    architecture_plan = {
        "schema_version": "1.0",
        "collection_id": "col-001",
        "knowledge_blueprint_id": blueprint.blueprint_id,
    }
    architecture_plan_sha256 = (
        "sha256:" + hashlib.sha256(canonical_json(architecture_plan).encode("utf-8")).hexdigest()
    )
    root = build_knowledge_object(
        stable_id="collection:col-001",
        tenant_id="tenant-001",
        collection_id="col-001",
        kind=KnowledgeObjectKind.COLLECTION,
        source_refs=(source,),
        origin=KnowledgeOrigin.RULE_DERIVED,
        verification_state=KnowledgeVerificationState.VERIFIED,
        created_by_activity="activity-001",
        version=1,
        links=(blueprint_object.stable_id,),
        payload={
            "architecture_plan": architecture_plan,
            "architecture_plan_sha256": architecture_plan_sha256,
        },
    )
    return (
        CanonicalKnowledgeModel(
            tenant_id="tenant-001",
            collection_id="col-001",
            objects=(root, blueprint_object),
        ),
        (blueprint,),
        architecture_plan_sha256,
    )


def test_signed_package_round_trip_preserves_every_profile() -> None:
    signer = _signer()
    package, receipt = build_knowledge_package(
        _groups(),
        collection_id="col-001",
        architecture_plan_sha256="sha256:" + "a" * 64,
        signer=signer,
    )
    imported = import_knowledge_package(
        package,
        verifier=signer.public_verifier(),
        require_signature=True,
    )
    assert receipt.signed
    assert imported.receipt == receipt
    assert imported.files["obsidian/Home.md"] == b"# Home\n"
    assert imported.files["obsidian/Notes/Document.md"] == b"# Document\n"
    assert imported.files["graph/nodes.csv"].startswith(b"id:ID")


def test_unsigned_package_is_allowed_for_local_export_but_not_production_import() -> None:
    package, receipt = build_knowledge_package(
        _groups(),
        collection_id="col-001",
        architecture_plan_sha256="sha256:" + "b" * 64,
    )
    assert not receipt.signed
    assert import_knowledge_package(package).receipt.signature_status == "external_signer_required"
    with pytest.raises(KnowledgePackageError, match="signed package"):
        import_knowledge_package(package, require_signature=True)


def test_import_rejects_payload_tampering() -> None:
    package, _ = build_knowledge_package(
        _groups(),
        collection_id="col-001",
        architecture_plan_sha256="sha256:" + "c" * 64,
    )
    with zipfile.ZipFile(io.BytesIO(package), "r") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["rag/chunks.jsonl"] = b'{"id":"tampered"}\n'
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(KnowledgePackageError, match="hash mismatch"):
        import_knowledge_package(output.getvalue())


def test_package_requires_all_portable_output_roots() -> None:
    groups = _groups()
    del groups["ontology"]
    with pytest.raises(KnowledgePackageError, match="ontology"):
        build_knowledge_package(
            groups,
            collection_id="col-001",
            architecture_plan_sha256="sha256:" + "d" * 64,
        )


def test_import_rejects_a_manifest_that_omits_a_required_profile_file() -> None:
    package, _ = build_knowledge_package(
        _groups(),
        collection_id="col-001",
        architecture_plan_sha256="sha256:" + "e" * 64,
    )
    with zipfile.ZipFile(io.BytesIO(package), "r") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["manifest.json"])
    manifest["files"] = [
        entry for entry in manifest["files"] if entry["path"] != "obsidian/Home.md"
    ]
    files.pop("obsidian/Home.md")
    manifest_bytes = (
        json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    files["manifest.json"] = manifest_bytes
    files["checksums.sha256"] = (
        "".join(
            f"{entry['sha256'].removeprefix('sha256:')}  {entry['path']}\n"
            for entry in manifest["files"]
        )
        + f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(KnowledgePackageError, match="obsidian profile is incomplete"):
        import_knowledge_package(output.getvalue())


def test_package_rejects_noncanonical_architecture_digest() -> None:
    with pytest.raises(KnowledgePackageError, match="canonical SHA-256"):
        build_knowledge_package(
            _groups(),
            collection_id="col-001",
            architecture_plan_sha256="not-a-digest",
        )


def test_semantic_profile_rehydrates_canonical_model_and_blueprint_receipts() -> None:
    model, blueprints, architecture_plan_sha256 = _semantic_model()
    groups = _groups()
    groups["canonical"]["model.json"] = canonical_knowledge_model_bytes(model)

    package, receipt = build_knowledge_package(
        groups,
        collection_id="col-001",
        architecture_plan_sha256=architecture_plan_sha256,
        semantic_model=model,
        blueprint_modules=blueprints,
    )
    imported = import_knowledge_package(package, require_semantic_profile=True)

    assert receipt.semantic_round_trip
    assert imported.receipt == receipt
    assert imported.semantic_model == model
    assert imported.semantic_profile is not None
    assert imported.semantic_profile.blueprint_modules == blueprints
    assert imported.manifest["semantic_profile"]["object_count"] == 2


def test_semantic_build_rejects_an_ad_hoc_canonical_payload() -> None:
    model, blueprints, architecture_plan_sha256 = _semantic_model()
    with pytest.raises(KnowledgePackageError, match="authoritative semantic model"):
        build_knowledge_package(
            _groups(),
            collection_id="col-001",
            architecture_plan_sha256=architecture_plan_sha256,
            semantic_model=model,
            blueprint_modules=blueprints,
        )


def test_semantic_build_rejects_architecture_plan_digest_divergence() -> None:
    model, blueprints, _ = _semantic_model()
    groups = _groups()
    groups["canonical"]["model.json"] = canonical_knowledge_model_bytes(model)

    with pytest.raises(KnowledgePackageError, match="canonical collection root"):
        build_knowledge_package(
            groups,
            collection_id="col-001",
            architecture_plan_sha256="sha256:" + "a" * 64,
            semantic_model=model,
            blueprint_modules=blueprints,
        )


def test_semantic_import_rejects_reledgered_architecture_plan_digest_tampering() -> None:
    model, blueprints, architecture_plan_sha256 = _semantic_model()
    groups = _groups()
    groups["canonical"]["model.json"] = canonical_knowledge_model_bytes(model)
    package, _ = build_knowledge_package(
        groups,
        collection_id="col-001",
        architecture_plan_sha256=architecture_plan_sha256,
        semantic_model=model,
        blueprint_modules=blueprints,
    )
    with zipfile.ZipFile(io.BytesIO(package), "r") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["manifest.json"])
    manifest["architecture_plan_sha256"] = "sha256:" + "f" * 64
    manifest_bytes = (
        json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    files["manifest.json"] = manifest_bytes
    files["checksums.sha256"] = (
        "".join(
            f"{entry['sha256'].removeprefix('sha256:')}  {entry['path']}\n"
            for entry in manifest["files"]
        )
        + f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    with pytest.raises(KnowledgePackageError, match="canonical collection root"):
        import_knowledge_package(output.getvalue(), require_semantic_profile=True)


def test_semantic_profile_can_be_required_on_import() -> None:
    package, _ = build_knowledge_package(
        _groups(),
        collection_id="col-001",
        architecture_plan_sha256="sha256:" + "b" * 64,
    )
    with pytest.raises(KnowledgePackageError, match="semantic profile is required"):
        import_knowledge_package(package, require_semantic_profile=True)
