"""EvidenceLocator v2 — frozen contract fidelity and the legacy PDF adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from akc_cir.evidence_locator import (
    EVIDENCE_LOCATOR_SCHEMA,
    EvidenceLocatorUnion,
    LocatorKind,
    PdfLocator,
    from_legacy,
    locator_anchor_id,
    parse_locator,
)
from akc_cir.evidence_locator_resolvers import FailureClass
from akc_cir.models import BBox1000, SourceRef
from akc_cir.schema import SCHEMA_MODELS
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "packages" / "contracts" / "schemas" / "evidence-locator.v2.schema.json"
ENUMS_PATH = REPO_ROOT / "packages" / "contracts" / "schemas" / "uskc-enums.v1.json"

# sha256 of the campaign's frozen artifacts (contract/SHA256SUMS, 2026-09-06).
# These files are copies; if a digest moves, the copy diverged from the contract.
FROZEN_DIGESTS = {
    SCHEMA_PATH: "13608314b63dfba8aef94de5cafc47d3712d0ed2a134a7a00e0f7aad4f8ff9c6",
    ENUMS_PATH: "3c668dc9c22289b27a7d0dd8b072cf23fa0511fd8fe888875770171e664f11d1",
}

BASE = {
    "schemaVersion": EVIDENCE_LOCATOR_SCHEMA,
    "sourceVersionId": "sv_0001",
    "representationId": "rep_0001",
}

VALID_LOCATORS: dict[str, dict[str, Any]] = {
    "pdf": {**BASE, "locatorId": "loc_pdf", "locatorKind": "pdf", "page": 18,
            "bbox1000": [100, 200, 400, 260], "objectId": "obj-3"},
    "image": {**BASE, "locatorId": "loc_img", "locatorKind": "image",
              "bbox1000": [0, 0, 1000, 1000], "imageId": "img-1"},
    "docx": {**BASE, "locatorId": "loc_docx", "locatorKind": "docx", "paragraphId": "p-12"},
    "xlsx": {**BASE, "locatorId": "loc_xlsx", "locatorKind": "xlsx", "sheet": "Revenue",
             "cell": "B2", "formula": "=SUM(B3:B9)"},
    "pptx": {**BASE, "locatorId": "loc_pptx", "locatorKind": "pptx", "slideNumber1": 4,
             "shapeId": "sh-2", "textRange": {"start": 0, "end": 12}},
    "email": {**BASE, "locatorId": "loc_mail", "locatorKind": "email",
              "messageId": "<a@b.example>", "mimePart": "1.2"},
    "json": {**BASE, "locatorId": "loc_json", "locatorKind": "json", "pointer": "/report/rows/0"},
    "xml": {**BASE, "locatorId": "loc_xml", "locatorKind": "xml", "xpath": "/root/item[1]"},
    "code": {**BASE, "locatorId": "loc_code", "locatorKind": "code",
             "commitSha": "0a1b2c3d4e5f6071", "filePath": "src/main.py",
             "span": {"startLine": 10, "startCol": 0, "endLine": 12, "endCol": 4}},
    "cad": {**BASE, "locatorId": "loc_cad", "locatorKind": "cad", "modelId": "m-1",
            "entityId": "{GUID-1}", "assemblyPath": ["root", "sub"]},
    "media": {**BASE, "locatorId": "loc_media", "locatorKind": "media",
              "startMs": 1000, "endMs": 4500, "speakerId": "spk-2"},
    "database": {**BASE, "locatorId": "loc_db", "locatorKind": "database",
                 "datasourceVersion": "v7", "table": "invoices", "primaryKey": {"id": 41}},
    "api": {**BASE, "locatorId": "loc_api", "locatorKind": "api",
            "endpoint": "GET /v1/invoices/41", "responseDigest": f"sha256:{'a' * 64}"},
}

INVALID_LOCATORS: dict[str, dict[str, Any]] = {
    "xlsx-without-sheet": {**BASE, "locatorId": "x1", "locatorKind": "xlsx", "cell": "B2"},
    "xlsx-without-anchor": {**BASE, "locatorId": "x2", "locatorKind": "xlsx", "sheet": "S"},
    "pdf-without-bbox": {**BASE, "locatorId": "x3", "locatorKind": "pdf", "page": 2},
    "pdf-page-zero": {**BASE, "locatorId": "x4", "locatorKind": "pdf", "page": 0,
                      "bbox1000": [1, 1, 2, 2]},
    "docx-without-anchor": {**BASE, "locatorId": "x5", "locatorKind": "docx",
                            "sectionId": "s-1"},
    "code-without-span": {**BASE, "locatorId": "x6", "locatorKind": "code",
                          "commitSha": "0a1b2c3", "filePath": "a.py"},
    "wrong-schema-version": {**BASE, "locatorId": "x7", "locatorKind": "json",
                             "pointer": "/a", "schemaVersion": "tavonel.evidence_locator.v1"},
    "unknown-kind": {**BASE, "locatorId": "x8", "locatorKind": "spreadsheet"},
    "bad-digest": {**BASE, "locatorId": "x9", "locatorKind": "json", "pointer": "/a",
                   "contentDigest": "sha256:notahexdigest"},
    "database-empty-key": {**BASE, "locatorId": "x10", "locatorKind": "database",
                           "datasourceVersion": "v1", "table": "t", "primaryKey": {}},
    "pptx-without-anchor": {**BASE, "locatorId": "x11", "locatorKind": "pptx",
                            "shapeId": "sh-1"},
}


@pytest.fixture(scope="module")
def frozen_schema() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_copied_contract_artifacts_are_byte_identical_to_the_frozen_originals() -> None:
    for path, digest in FROZEN_DIGESTS.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path


def test_transliterated_enums_carry_the_frozen_value_lists() -> None:
    frozen = json.loads(ENUMS_PATH.read_text(encoding="utf-8"))
    assert [kind.value for kind in LocatorKind] == frozen["LocatorKind"]
    assert [item.value for item in FailureClass] == frozen["FailureClass"]
    assert sorted(VALID_LOCATORS) == sorted(frozen["LocatorKind"])


@pytest.mark.parametrize("kind", sorted(VALID_LOCATORS))
def test_every_variant_validates_under_both_the_schema_and_the_model(
    kind: str, frozen_schema: jsonschema.Draft202012Validator
) -> None:
    payload = VALID_LOCATORS[kind]
    frozen_schema.validate(payload)
    locator = parse_locator(payload)
    assert locator.locator_kind == kind
    assert locator.model_dump(mode="json", by_alias=True, exclude_none=True) == payload


@pytest.mark.parametrize("case", sorted(INVALID_LOCATORS))
def test_invalid_payloads_are_rejected_by_both_the_schema_and_the_model(
    case: str, frozen_schema: jsonschema.Draft202012Validator
) -> None:
    payload = INVALID_LOCATORS[case]
    assert not frozen_schema.is_valid(payload), case
    with pytest.raises(ValidationError):
        parse_locator(payload)


def test_the_model_is_stricter_than_the_schema_on_unknown_fields(
    frozen_schema: jsonschema.Draft202012Validator,
) -> None:
    """The frozen schema has no ``additionalProperties: false``; the model does."""
    payload = {**VALID_LOCATORS["json"], "smuggledField": "x"}
    assert frozen_schema.is_valid(payload)
    with pytest.raises(ValidationError):
        parse_locator(payload)


def test_union_is_registered_for_typescript_generation() -> None:
    assert SCHEMA_MODELS["evidence-locator"] is EvidenceLocatorUnion


def test_legacy_pdf_evidence_round_trips_through_the_adapter(source_ref: SourceRef) -> None:
    locator = from_legacy(source_ref, representation_id="rep_0001")
    assert isinstance(locator, PdfLocator)
    assert locator.source_version_id == source_ref.document_version_id
    assert locator.page == source_ref.page_number1
    assert locator.to_legacy(document_id=source_ref.document_id) == source_ref


@pytest.mark.parametrize("page_index0", [0, 7, 249])
def test_round_trip_holds_across_pages_and_boxes(page_index0: int) -> None:
    reference = SourceRef(
        document_id="doc_002",
        document_version_id="docver_002",
        page_index0=page_index0,
        page_number1=page_index0 + 1,
        bbox1000=BBox1000([0, 1, 1000, 999]),
        native_object_id="native_obj_1",
    )
    locator = from_legacy(reference, representation_id="rep_0002")
    assert locator.object_id == "native_obj_1"
    assert locator.to_legacy(document_id="doc_002") == reference


def test_a_source_ref_without_a_box_is_refused_rather_than_given_one() -> None:
    reference = SourceRef(
        document_id="doc_003",
        document_version_id="docver_003",
        page_index0=0,
        page_number1=1,
    )
    with pytest.raises(ValueError, match="requires bbox1000"):
        from_legacy(reference, representation_id="rep_0003")


def test_generated_locator_ids_are_the_anchor_and_survive_the_schema(
    source_ref: SourceRef, frozen_schema: jsonschema.Draft202012Validator
) -> None:
    locator = from_legacy(source_ref, representation_id="rep_0001")
    assert locator.locator_id == locator_anchor_id(locator)
    frozen_schema.validate(locator.model_dump(mode="json", by_alias=True, exclude_none=True))


def test_anchor_id_ignores_locator_id_and_excerpt_but_not_the_anchor() -> None:
    base = parse_locator(VALID_LOCATORS["xlsx"])
    renamed = base.model_copy(update={"locator_id": "loc_other", "excerpt": "1,000,000"})
    assert locator_anchor_id(renamed) == locator_anchor_id(base)
    moved = base.model_copy(update={"cell": "B3"})
    assert locator_anchor_id(moved) != locator_anchor_id(base)


def test_anchor_ids_are_usable_as_locator_ids_for_every_variant() -> None:
    for payload in VALID_LOCATORS.values():
        locator = parse_locator(payload)
        anchor = locator_anchor_id(locator)
        assert parse_locator({**payload, "locatorId": anchor}).locator_id == anchor


def test_explicit_locator_id_is_kept(source_ref: SourceRef) -> None:
    locator = from_legacy(source_ref, representation_id="rep_0001", locator_id="loc_fixed")
    assert locator.locator_id == "loc_fixed"


@pytest.mark.parametrize(
    "locator_id", ["  ../../etc/passwd  ", "<script>", "x" * 400, "", "loc bad"]
)
def test_a_caller_supplied_locator_id_is_validated_not_written_through(
    source_ref: SourceRef, locator_id: str
) -> None:
    """``model_copy(update=...)`` skips validation; the adapter must not.

    A locator carrying an id the frozen schema rejects cannot be re-parsed, so
    it was never a validated contract object.
    """
    with pytest.raises(ValidationError):
        from_legacy(source_ref, representation_id="rep_0001", locator_id=locator_id)


@pytest.mark.parametrize(
    ("field", "extra"),
    [
        ("image_asset_id", {"image_asset_id": "img_asset_9"}),
        # SourceRef itself requires the time pair, so it is set as a pair.
        ("time_start_ms", {"time_start_ms": 1000, "time_end_ms": 4000}),
    ],
)
def test_a_source_ref_the_pdf_variant_cannot_carry_is_refused_not_silently_dropped(
    field: str, extra: dict[str, Any]
) -> None:
    """The live native parsers emit these on FIGURE and media blocks.

    The pdf variant has nowhere to keep them, so wrapping would return a
    ``SourceRef`` that is not the input. Refusing is the fail-closed reading.
    """
    reference = SourceRef(
        document_id="doc_004",
        document_version_id="docver_004",
        page_index0=0,
        page_number1=1,
        bbox1000=BBox1000([10, 10, 20, 20]),
        **extra,
    )
    with pytest.raises(ValueError, match=field):
        from_legacy(reference, representation_id="rep_0004")


def test_a_media_span_that_ends_before_it_starts_is_refused_by_the_model_only(
    frozen_schema: jsonschema.Draft202012Validator,
) -> None:
    """The frozen schema cannot compare two of its own fields, so it accepts a
    reversed span. The model is the boundary that refuses it — recorded here
    because §7 F-6 already notes the schema is the looser of the two."""
    payload = {**BASE, "locatorId": "x12", "locatorKind": "media",
               "startMs": 5000, "endMs": 1000}
    assert frozen_schema.is_valid(payload)
    with pytest.raises(ValueError, match="startMs must not exceed endMs"):
        parse_locator(payload)


def test_the_default_serialization_validates_against_the_frozen_schema(
    frozen_schema: jsonschema.Draft202012Validator,
) -> None:
    """No optional in the frozen schema has ``null`` in its type union.

    A consumer calling the obvious ``model_dump_json()`` must not get a payload
    that the schema — and Lane C's ``jsonschema`` check — rejects.
    """
    for payload in VALID_LOCATORS.values():
        locator = parse_locator(payload)
        frozen_schema.validate(json.loads(locator.model_dump_json()))
        frozen_schema.validate(locator.model_dump(mode="json"))
        frozen_schema.validate(json.loads(EvidenceLocatorUnion(locator).model_dump_json()))
        frozen_schema.validate(EvidenceLocatorUnion(locator).model_dump(mode="json"))
    # exclude_none is a default, not a lock: an explicit False still produces
    # the null-bearing payload, and that one is what the schema refuses.
    minimal = parse_locator(VALID_LOCATORS["json"])
    assert "contentDigest" not in minimal.model_dump(mode="json")
    assert not frozen_schema.is_valid(minimal.model_dump(mode="json", exclude_none=False))
