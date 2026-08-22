from __future__ import annotations

import json

import pytest
from filter_omnidoc_ground_truth import build_subset


def annotation(filename: str) -> dict[str, object]:
    return {"page_info": {"image_path": filename}, "layout_dets": []}


def test_subset_follows_manifest_order_and_requires_isolation_receipt() -> None:
    rows = [annotation("b.jpg"), annotation("a.jpg")]
    manifest = {
        "case_count": 2,
        "ground_truth_mounted": False,
        "cases": [{"filename": "a.jpg"}, {"filename": "b.jpg"}],
    }
    subset, filenames = build_subset(rows, manifest)
    assert filenames == ["a.jpg", "b.jpg"]
    assert [row["page_info"]["image_path"] for row in subset] == filenames


@pytest.mark.parametrize(
    ("rows", "manifest"),
    [
        ([annotation("a.jpg")], {"case_count": 1, "cases": [{"filename": "a.jpg"}]}),
        (
            [annotation("a.jpg")],
            {
                "case_count": 2,
                "ground_truth_mounted": False,
                "cases": [{"filename": "a.jpg"}, {"filename": "a.jpg"}],
            },
        ),
        (
            [annotation("a.jpg")],
            {
                "case_count": 1,
                "ground_truth_mounted": False,
                "cases": [{"filename": "missing.jpg"}],
            },
        ),
    ],
)
def test_subset_fails_closed(rows: list[dict[str, object]], manifest: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        build_subset(rows, manifest)


def test_receipt_inputs_are_json_serializable() -> None:
    rows = [annotation("a.jpg")]
    manifest = {
        "case_count": 1,
        "ground_truth_mounted": False,
        "cases": [{"filename": "a.jpg"}],
    }
    subset, filenames = build_subset(rows, manifest)
    assert json.loads(json.dumps(subset)) == subset
    assert filenames == ["a.jpg"]
