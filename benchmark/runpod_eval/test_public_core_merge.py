import json
import os
import struct
import zlib
from pathlib import Path

import pytest
from public_core_merge import (
    _io_path,
    _write_json,
    build_parsebench_result,
    normalize_parsebench_markdown,
)


def _write_png(path: Path, width: int = 200, height: int = 100) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def test_parsebench_normalization_closes_table_and_promotes_header() -> None:
    markdown = '<table><tr><td colspan=2>A</td></tr><tr><td>B</td></tr>'
    result = normalize_parsebench_markdown(markdown)
    assert result.count("</table>") == 1
    assert '<th colspan="2">A</th>' in result
    assert "<thead>" in result


def test_build_parsebench_result_preserves_text_and_scales_layout(tmp_path: Path) -> None:
    image = tmp_path / "case.png"
    _write_png(image)
    result = build_parsebench_result(
        case={
            "case_id": "parsebench-a",
            "source_relative_path": "docs/layout/sample.pdf",
        },
        markdown="# Heading\n\nBody",
        model_payload=[
            [
                {"type": "title", "bbox": [0.1, 0.2, 0.5, 0.4], "content": "Heading"},
                {"type": "text", "bbox": [0.1, 0.5, 0.9, 0.8], "content": "Body"},
            ]
        ],
        input_path=image,
        worker_index=2,
        run_summary_sha256="sha256:" + "a" * 64,
    )
    assert result["request"]["example_id"] == "layout/sample"
    assert result["pipeline_name"] == "mineru-3.4.4-vlm-c1-frozen"
    assert result["product_type"] == "layout_detection"
    assert result["output"]["markdown"] == "# Heading\n\nBody"
    assert result["output"]["image_width"] == 200
    assert result["output"]["image_height"] == 100
    title = result["output"]["predictions"][0]
    assert title["bbox"] == [20.0, 20.0, 100.0, 40.0]
    assert title["label"] == "Title"
    assert result["raw_output"]["worker_index"] == 2


def test_build_parsebench_result_rejects_multi_page_model_payload(tmp_path: Path) -> None:
    image = tmp_path / "case.png"
    _write_png(image)
    with pytest.raises(ValueError, match="exactly one page"):
        build_parsebench_result(
            case={"case_id": "x", "source_relative_path": "docs/text/x.pdf"},
            markdown="x",
            model_payload=[[], []],
            input_path=image,
            worker_index=0,
            run_summary_sha256="sha256:" + "0" * 64,
        )


def test_generated_parsebench_result_is_json_serializable(tmp_path: Path) -> None:
    image = tmp_path / "case.png"
    _write_png(image)
    result = build_parsebench_result(
        case={"case_id": "x", "source_relative_path": "docs/text/x.pdf"},
        markdown="x",
        model_payload=[[{"type": "text", "bbox": [0, 0, 1, 1], "content": "x"}]],
        input_path=image,
        worker_index=0,
        run_summary_sha256="sha256:" + "0" * 64,
    )
    json.dumps(result, ensure_ascii=False)


def test_text_category_keeps_parse_output(tmp_path: Path) -> None:
    image = tmp_path / "case.png"
    _write_png(image)
    result = build_parsebench_result(
        case={"case_id": "x", "source_relative_path": "docs/text/x.pdf"},
        markdown="x",
        model_payload=[[{"type": "text", "bbox": [0, 0, 1, 1], "content": "x"}]],
        input_path=image,
        worker_index=0,
        run_summary_sha256="sha256:" + "0" * 64,
    )
    assert result["product_type"] == "parse"
    assert result["request"]["example_id"] == "text/x"
    assert result["output"]["layout_pages"][0]["items"][0]["bbox"]["label"] == "Text"


@pytest.mark.skipif(os.name != "nt", reason="Windows extended paths only")
def test_write_json_supports_windows_paths_longer_than_260(tmp_path: Path) -> None:
    destination = tmp_path / ("a" * 180) / ("b" * 90 + ".json")
    assert len(str(destination)) > 260

    digest = _write_json(destination, {"status": "ok"})

    assert digest.startswith("sha256:")
    assert json.loads(_io_path(destination).read_text(encoding="utf-8")) == {
        "status": "ok"
    }
