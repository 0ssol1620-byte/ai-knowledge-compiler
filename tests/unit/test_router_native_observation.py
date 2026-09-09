"""Native projection completeness/identity regressions, not OCR quality scores."""

from datetime import UTC, datetime

import pytest
from akc_cir import CanonicalDocument
from akc_router.native_observation import NativeObservationStatus, project_native_pages

SHA = "sha256:" + "a" * 64


def document(*, types=("title", "paragraph", "figure"), bad_ref=None):
    blocks = []
    for index, kind in enumerate(types):
        reference = {
            "documentId": "source-a",
            "documentVersionId": "revision-a",
            "pageIndex0": 0,
            "pageNumber1": 1,
            "bbox1000": [10, 10, 900, 200],
        }
        reference.update(bad_ref or {})
        blocks.append(
            {
                "id": f"block-{index}",
                "order": index,
                "type": kind,
                "contentLayer": "extracted",
                "origin": "native_extracted",
                "rawText": f"{kind} content",
                "sourceRefs": [reference],
                "contentHash": SHA,
            }
        )
    return CanonicalDocument.model_validate(
        {
            "tenantId": "tenant-a",
            "documentId": "source-a",
            "documentVersionId": "revision-a",
            "title": "Native fixture",
            "sourceFilename": "fixture.pdf",
            "sourceSha256": SHA,
            "contentLayer": "extracted",
            "blocks": blocks,
            "metadata": {"pages": [{}, {}]},
            "createdAt": datetime(2026, 9, 9, tzinfo=UTC),
        }
    )


def test_title_is_preserved_and_figure_metadata_is_not_ocr_text():
    pages = project_native_pages(document(), expected_source_sha256=SHA, expected_page_count=2)
    assert pages[0].text == "title content\nparagraph content"
    assert pages[0].native_block_ids == ("block-0", "block-1")
    assert pages[0].located_block_count == 2
    assert pages[0].quality_verified is False


def test_empty_declared_page_stays_in_denominator():
    pages = project_native_pages(document(), expected_source_sha256=SHA, expected_page_count=2)
    assert len(pages) == 2
    assert pages[1].status is NativeObservationStatus.NO_TEXT_OBSERVED
    assert pages[1].text == ""
    assert pages[1].geometry_available is False
    assert pages[1].quality_verified is False


def test_figure_only_page_cannot_claim_text_observation():
    pages = project_native_pages(
        document(types=("figure",)), expected_source_sha256=SHA, expected_page_count=2
    )
    assert all(page.status is NativeObservationStatus.NO_TEXT_OBSERVED for page in pages)


@pytest.mark.parametrize("change", [{"documentId": "foreign"}, {"documentVersionId": "stale"}])
def test_foreign_source_reference_is_refused(change):
    with pytest.raises(ValueError, match="REFERENCE_IDENTITY"):
        project_native_pages(
            document(bad_ref=change), expected_source_sha256=SHA, expected_page_count=2
        )


def test_missing_bbox_is_visible_not_silently_filled():
    pages = project_native_pages(
        document(bad_ref={"bbox1000": None}), expected_source_sha256=SHA, expected_page_count=2
    )
    assert pages[0].unlocated_block_count == 2
    assert not pages[0].geometry_available


@pytest.mark.parametrize("count", [True, 0, 3])
def test_declared_page_inventory_must_match(count):
    with pytest.raises(ValueError, match="PAGE"):
        project_native_pages(document(), expected_source_sha256=SHA, expected_page_count=count)


def test_wrong_representation_hash_is_refused():
    with pytest.raises(ValueError, match="SOURCE_BINDING"):
        project_native_pages(
            document(), expected_source_sha256="sha256:" + "b" * 64, expected_page_count=2
        )


def test_unassigned_text_is_refused_instead_of_silently_dropped():
    source = document(types=("paragraph",))
    block = source.blocks[0].model_copy(update={"source_refs": []})
    source = source.model_copy(update={"blocks": [block]})
    with pytest.raises(ValueError, match="NATIVE_TEXT_PAGE_UNASSIGNED"):
        project_native_pages(source, expected_source_sha256=SHA, expected_page_count=2)


def test_mult_page_text_is_not_duplicated_on_every_page():
    source = document(types=("paragraph",))
    block = source.blocks[0]
    second = block.source_refs[0].model_copy(update={"page_index0": 1, "page_number1": 2})
    block = block.model_copy(update={"source_refs": [*block.source_refs, second]})
    source = source.model_copy(update={"blocks": [block]})
    with pytest.raises(ValueError, match="NATIVE_TEXT_PAGE_SPAN_UNRESOLVED"):
        project_native_pages(source, expected_source_sha256=SHA, expected_page_count=2)
