from typing import ClassVar

from paddleocr_vl_stage2 import markdown_result


class FakeResult:
    markdown: ClassVar[dict[str, str]] = {"markdown_texts": "# Verified Markdown\n"}


def test_markdown_attribute_is_authoritative_over_json() -> None:
    assert markdown_result(FakeResult(), {"res": {"text": "raw json"}}) == "# Verified Markdown\n"


def test_markdown_json_fallback_remains_supported() -> None:
    assert markdown_result(object(), {"res": {"markdown": {"text": "fallback"}}}) == "fallback"
