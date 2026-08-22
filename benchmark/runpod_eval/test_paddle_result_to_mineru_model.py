from __future__ import annotations

import pytest
from paddle_result_to_mineru_model import paddle_response_to_mineru_model


def test_paddle_response_to_mineru_model_normalizes_and_orders_blocks() -> None:
    payload = {
        "error": None,
        "pages": [
            {
                "res": {
                    "width": 200,
                    "height": 100,
                    "parsing_res_list": [
                        {
                            "block_bbox": [20, 20, 220, 80],
                            "block_content": "later",
                            "block_label": "paragraph-title",
                            "block_order": 2,
                        },
                        {
                            "block_bbox": [0, 0, 100, 50],
                            "block_content": "first",
                            "block_label": "text",
                            "block_order": 1,
                        },
                        {
                            "block_bbox": [10, 70, 50, 90],
                            "block_content": "unordered",
                            "block_label": "footer",
                            "block_order": None,
                        },
                    ],
                }
            }
        ],
    }

    converted = paddle_response_to_mineru_model(payload)

    assert [block["content"] for block in converted[0]] == [
        "first",
        "later",
        "unordered",
    ]
    assert converted[0][1]["bbox"] == pytest.approx([0.1, 0.2, 1.0, 0.8])
    assert converted[0][1]["type"] == "paragraph_title"


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "timeout", "pages": []},
        {"error": None, "pages": []},
        {
            "error": None,
            "pages": [{"res": {"width": 1, "height": 1, "parsing_res_list": []}}],
        },
    ],
)
def test_paddle_response_to_mineru_model_fails_closed(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        paddle_response_to_mineru_model(payload)
