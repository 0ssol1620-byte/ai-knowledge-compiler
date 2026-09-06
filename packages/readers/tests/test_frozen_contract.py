"""The bundled contract artifacts are verbatim and the enums do not fork."""

from __future__ import annotations

import hashlib
from importlib.resources import files

from akc_cir.inspection import FailureCode
from akc_readers.enums import (
    CAPABILITY_STATUS_ACCEPTED_AT_UPLOAD,
    ENUMS_JSON,
    EVIDENCE_LOCATOR_SCHEMA_JSON,
    FAILURE_CLASSES_WITHOUT_FAILURE_CODE,
    FAILURE_CODE_TO_CLASS,
    FAILURE_CODES_WITHOUT_FAILURE_CLASS,
    CapabilityStatus,
    FailureClass,
    LocatorKind,
    ReaderFeature,
    ReaderRegistryStatus,
    RepresentationKind,
    SourceFamily,
    frozen_contract,
)

# USKC_LANE_CONTRACT_2026-09-06.md §4.0 / contract/SHA256SUMS.
FROZEN_SHA256 = {
    ENUMS_JSON: "3c668dc9c22289b27a7d0dd8b072cf23fa0511fd8fe888875770171e664f11d1",
    EVIDENCE_LOCATOR_SCHEMA_JSON: (
        "13608314b63dfba8aef94de5cafc47d3712d0ed2a134a7a00e0f7aad4f8ff9c6"
    ),
}


def test_bundled_contract_artifacts_are_byte_identical_to_the_frozen_copies() -> None:
    for resource, expected in FROZEN_SHA256.items():
        payload = files("akc_readers").joinpath(resource).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected, resource


def test_every_enum_carries_exactly_the_frozen_value_list() -> None:
    frozen = frozen_contract(ENUMS_JSON)
    for name, enum_type in (
        ("SourceFamily", SourceFamily),
        ("CapabilityStatus", CapabilityStatus),
        ("RepresentationKind", RepresentationKind),
        ("ReaderFeature", ReaderFeature),
        ("LocatorKind", LocatorKind),
        ("ReaderRegistryStatus", ReaderRegistryStatus),
        ("FailureClass", FailureClass),
    ):
        assert [member.value for member in enum_type] == frozen[name], name
    assert {status.value for status in CAPABILITY_STATUS_ACCEPTED_AT_UPLOAD} == set(
        frozen["CapabilityStatusAcceptedAtUpload"]
    )


def test_locator_schema_enum_matches_the_locator_kind_enum() -> None:
    schema = frozen_contract(EVIDENCE_LOCATOR_SCHEMA_JSON)
    assert schema["properties"]["locatorKind"]["enum"] == [kind.value for kind in LocatorKind]


def test_failure_mapping_names_its_gaps_in_both_directions() -> None:
    """§45 and FailureCode F0-F48 are lossy both ways; the gaps are data."""
    mapped_classes = set(FAILURE_CODE_TO_CLASS.values())
    assert set(FAILURE_CLASSES_WITHOUT_FAILURE_CODE) == set(FailureClass) - mapped_classes
    assert FailureClass.SOURCE_DELETED in FAILURE_CLASSES_WITHOUT_FAILURE_CODE
    assert FailureClass.PRESERVATION_FAILED in FAILURE_CLASSES_WITHOUT_FAILURE_CODE
    assert set(FAILURE_CODES_WITHOUT_FAILURE_CLASS) == set(FailureCode) - set(FAILURE_CODE_TO_CLASS)
    for code in (
        FailureCode.F2_UPLOAD_STORAGE,
        FailureCode.F7_PARSER_EXCEPTION,
        FailureCode.F9_SUSPICIOUSLY_SHORT,
        FailureCode.F21_TEMPORAL_UNCERTAINTY,
        FailureCode.F27_COST_BUDGET_EXCEEDED,
    ):
        assert code in FAILURE_CODES_WITHOUT_FAILURE_CLASS


def test_the_two_transliterated_failure_class_enums_cannot_drift() -> None:
    """`FailureClass` is deliberately defined twice and must stay one vocabulary.

    ADR-007 records why: `akc_cir` sits *below* the reader plane and must not
    import from `akc_readers`, so each package transliterates the frozen list.
    This test lives here because `packages/readers/tests` is the only scope that
    may import both, and it is the seam that keeps the two copies honest.
    """
    from akc_cir.evidence_locator_resolvers import FailureClass as CirFailureClass

    reader_values = [member.value for member in FailureClass]
    cir_values = [member.value for member in CirFailureClass]
    assert reader_values == cir_values
    assert reader_values == frozen_contract(ENUMS_JSON)["FailureClass"]


def test_reader_features_cover_the_frozen_feature_vocabulary() -> None:
    assert ReaderFeature.TRACK_CHANGES in ReaderFeature
    assert len(list(ReaderFeature)) == len(frozen_contract(ENUMS_JSON)["ReaderFeature"])
