"""WO-BIG-1: a package field the writer may write is a field the validator can read.

`_validation_checks` re-reads `graph/nodes.csv`; an entity named on many lines writes a long
`payload` field. Read with Python's default csv field limit (131,072 characters) that raised
`_csv.Error`, which no handler caught, and the API answered HTTP 500. The documents here are
synthetic and generated in the test, shaped like the WO-BIG-0 probe's `entity` profile: every
line names "Synthetic Holdings" plus a number, which the topic key drops, so one entity node
collects every line of the World.
"""

from __future__ import annotations

import csv
import hashlib

import pytest
from akc_cir.base import canonical_json
from akc_cir.models import BBox1000, BlockType
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest, compiler
from akc_product_core.api import ProductCoreService
from akc_product_core.compiler import (
    OUTPUT_BUDGET_BYTES,
    PACKAGE_CSV_FIELD_MAX_CHARS,
    CoreOutputTooLargeError,
)
from akc_product_core.contracts import ProductCoreRegion

from .test_product_core_api import SECRET, _signed
from .test_product_core_bridge import RELEASE, _document, _request, _sha

ITEMS = (
    "revenue",
    "cost of sales",
    "gross profit",
    "operating income",
    "interest expense",
    "income tax",
    "net income",
    "total assets",
)
DEFAULT_CSV_FIELD_LIMIT = 131_072


def _entity_request(documents: int, regions: int) -> ProductCoreCompileRequest:
    built = []
    for index in range(documents):
        lines = [
            f"Synthetic Holdings {index:03d} reported {ITEMS[j % len(ITEMS)]} of "
            f"{(index * 7919 + j * 104729) % 90000 + 1000} thousand dollars for fiscal "
            f"{2020 + (j // len(ITEMS)) % 6} (line {j + 1})."
            for j in range(regions)
        ]
        native = f"entity-{index:03d}"
        document = _document(native, "\n".join(lines))
        built.append(
            document.model_copy(
                update={
                    "regions": tuple(
                        ProductCoreRegion(
                            region_id=f"region-{native}-{j}",
                            page_index0=0,
                            page_number1=1,
                            order=j,
                            block_type=BlockType.PARAGRAPH,
                            text=line,
                            bbox1000=BBox1000(
                                (
                                    60,
                                    20 + j * 960 // regions,
                                    940,
                                    min(32 + j * 960 // regions, 999),
                                )
                            ),
                            confidence=0.98,
                            authority="regulatory_filing",
                        )
                        for j, line in enumerate(lines)
                    )
                }
            )
        )
    return _request(tuple(built), request_id=f"entity-{documents}x{regions}")


def _widest_payload(files: dict[str, str]) -> int:
    # The test process has the csv default too; read the way the validator now reads.
    rows = compiler._package_csv_rows("graph/nodes.csv", files["graph/nodes.csv"])
    return max(len(row["payload"]) for row in rows)


def test_the_bound_is_the_output_budget_not_the_library_default() -> None:
    # A field is a substring of a package file; a package over the output budget is refused
    # before it is read back, and a character is at least one UTF-8 byte.
    assert PACKAGE_CSV_FIELD_MAX_CHARS == OUTPUT_BUDGET_BYTES
    assert PACKAGE_CSV_FIELD_MAX_CHARS > DEFAULT_CSV_FIELD_LIMIT


def test_the_process_wide_csv_limit_is_put_back_after_a_compile() -> None:
    before = csv.field_size_limit()
    ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _entity_request(2, 4), input_sha256=_sha("restore")
    )
    assert csv.field_size_limit() == before


@pytest.mark.parametrize(("documents", "regions"), [(24, 60), (12, 200)])
def test_one_entity_on_1440_and_2400_lines_compiles_and_validates(
    documents: int, regions: int
) -> None:
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _entity_request(documents, regions), input_sha256=_sha(f"entity-{documents}")
    )

    files = {file.path: file.content for file in response.candidate.package.files}
    # The case this work order is about: one field past the old default limit, read back.
    assert _widest_payload(files) > DEFAULT_CSV_FIELD_LIMIT
    validation = response.candidate.validation
    assert validation["deterministicMaterialization"] is True
    assert validation["sourceCoverage"] is True
    assert validation["evidenceCoverage"] is True


def test_a_field_past_the_bound_is_a_named_refusal_with_counts_and_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "PACKAGE_CSV_FIELD_MAX_CHARS", 4_096)
    before = csv.field_size_limit()

    with pytest.raises(CoreOutputTooLargeError) as refused:
        ProductCoreCompiler(core_release_digest=RELEASE).compile(
            _entity_request(2, 40), input_sha256=_sha("over")
        )

    assert csv.field_size_limit() == before
    detail = refused.value.detail
    assert detail["object"] == "core-package-field"
    assert detail["file"] == "graph/nodes.csv"
    assert detail["column"] == "payload"
    assert detail["budget"] == 4_096
    chars = detail["chars"]
    assert isinstance(chars, int) and chars > 4_096
    assert isinstance(detail["bytes"], int) and detail["bytes"] >= chars
    assert isinstance(detail["row"], int) and detail["row"] >= 1
    counts = detail["counts"]
    assert isinstance(counts, dict)
    assert counts["regions"] == 80
    assert set(counts) == {"regions", "claims", "contradictionPairs", "files"}
    # Numbers and package paths only: nothing a document said.
    assert "Synthetic" not in canonical_json(detail)


def test_a_field_at_the_bound_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _entity_request(2, 40)
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request, input_sha256=_sha("at")
    )
    widest = _widest_payload({f.path: f.content for f in response.candidate.package.files})

    monkeypatch.setattr(compiler, "PACKAGE_CSV_FIELD_MAX_CHARS", widest)
    again = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request, input_sha256=_sha("at")
    )

    assert again.candidate.manifest_digest == response.candidate.manifest_digest
    assert again.candidate.validation["deterministicMaterialization"] is True


def test_an_unreadable_package_csv_is_a_failed_check_not_a_refusal() -> None:
    # Malformed, not oversized: ValueError, which `_validation_checks` turns into the failed
    # check that needed the file (the docstring's rule), never into a size refusal.
    before = csv.field_size_limit()
    with pytest.raises(ValueError, match=r"unreadable package csv: graph/nodes.csv"):
        compiler._package_csv_rows("graph/nodes.csv", "id,kind\nx\ry,z\n")
    assert csv.field_size_limit() == before


def test_the_service_maps_the_refusal_to_422_not_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "PACKAGE_CSV_FIELD_MAX_CHARS", 4_096)
    service = ProductCoreService(hmac_secret=SECRET, core_release_digest=RELEASE)
    request = _entity_request(2, 40)
    body = canonical_json(
        request.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()

    status, payload = service.compile(body=body, headers=_signed(body, request.request_id))

    assert status == 422
    assert payload["code"] == "CORE_OUTPUT_TOO_LARGE"
    assert payload["object"] == "core-package-field"
    assert payload["file"] == "graph/nodes.csv"
    assert payload["column"] == "payload"


def test_manifest_digest_below_the_old_limit_is_unchanged() -> None:
    # 12 documents x 60 lines: one entity on 720 lines, under the old default, compiled before
    # this change. Pinned from the lane base 783d8d0 (receipt WO-BIG-1/digest-before.json).
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _entity_request(12, 60), input_sha256=_sha("entity-12")
    )
    files = {file.path: file.content for file in response.candidate.package.files}
    assert _widest_payload(files) <= DEFAULT_CSV_FIELD_LIMIT
    package = hashlib.sha256(
        canonical_json({f.path: f.sha256 for f in response.candidate.package.files}).encode()
    ).hexdigest()
    assert (response.candidate.manifest_digest, package) == PINNED_BELOW_OLD_LIMIT


PINNED_BELOW_OLD_LIMIT = (
    "sha256:45fccb8d1f12c00d0981a0e120c1b5ece7690eb8a70aacd48bfada60c559c4e9",
    "e33bbf17a3643732f59af71982467e50a566bd001e453473c4645a00e8dbf1d0",
)
