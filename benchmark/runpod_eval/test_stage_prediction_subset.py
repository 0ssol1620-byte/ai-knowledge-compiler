from __future__ import annotations

import pytest
from stage_prediction_subset import case_ids


def test_case_ids_follow_manifest_order() -> None:
    assert case_ids(
        {
            "case_count": 2,
            "cases": [{"filename": "b.jpg"}, {"filename": "a.pdf_0.jpg"}],
        }
    ) == ["b", "a.pdf_0"]


@pytest.mark.parametrize(
    "manifest",
    [
        {"case_count": 1, "cases": []},
        {"case_count": 1, "cases": [{"filename": "../a.jpg"}]},
        {"case_count": 2, "cases": [{"filename": "a.jpg"}, {"filename": "a.png"}]},
    ],
)
def test_case_ids_fail_closed(manifest: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        case_ids(manifest)
