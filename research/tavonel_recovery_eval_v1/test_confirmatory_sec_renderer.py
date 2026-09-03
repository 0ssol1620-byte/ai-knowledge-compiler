from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import confirmatory_sec_renderer as r


def test_prepare_html_injects_frozen_print_css(tmp_path):
    source = tmp_path / "source.htm"
    target = tmp_path / "target.htm"
    source.write_text("<html><head><title>x</title></head><body>A</body></html>", encoding="utf-8")
    r._prepare_html(source, target)
    text = target.read_text(encoding="utf-8")
    assert 'id="tavonel-sec-renderer"' in text
    assert r.PAGE_CSS in text
    assert text.index("tavonel-sec-renderer") < text.index("</head>")


def test_prepare_html_wraps_plain_text(tmp_path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.htm"
    source.write_text("plain filing text", encoding="utf-8")
    r._prepare_html(source, target)
    text = target.read_text(encoding="utf-8")
    assert text.startswith("<html><head>")
    assert "plain filing text" in text


def test_runtime_versions_require_exact_pins(monkeypatch, tmp_path):
    python = tmp_path / "python.exe"
    python.write_bytes(b"fixture")

    class Result:
        returncode = 0
        stdout = json.dumps(
            {"python": "3.13.0", "pypdfium2": r.PYPDFIUM2_VERSION, "pillow": r.PILLOW_VERSION}
        )

    monkeypatch.setattr(r.subprocess, "run", lambda *args, **kwargs: Result())
    assert r._python_runtime_versions(python)["pypdfium2"] == r.PYPDFIUM2_VERSION

    Result.stdout = json.dumps({"python": "3.13.0", "pypdfium2": "0", "pillow": r.PILLOW_VERSION})
    with pytest.raises(r.SecRendererRefused, match="versions drifted"):
        r._python_runtime_versions(python)


def test_qualification_requires_exact_repeat_page_hashes(monkeypatch, tmp_path):
    identity = {
        "chrome": {"path": "chrome", "version": "1", "sha256": "sha256:" + "a" * 64},
        "rasterizer": {"python_path": "python", "python_sha256": "sha256:" + "b" * 64},
        "renderer_module_sha256": "sha256:" + "c" * 64,
        "settings": {},
    }
    monkeypatch.setattr(r, "_runtime_identity", lambda venv=r.DEFAULT_VENV: identity)
    calls = iter(
        (
            {"page_count": 2, "page_sha256": ["sha256:" + "1" * 64, "sha256:" + "2" * 64]},
            {"page_count": 2, "page_sha256": ["sha256:" + "1" * 64, "sha256:" + "3" * 64]},
        )
    )
    monkeypatch.setattr(r, "_render_once", lambda *args, **kwargs: next(calls))
    with pytest.raises(r.SecRendererRefused, match="different page bytes"):
        r.qualify(output=tmp_path / "receipt.json")


def test_qualification_receipt_is_immutable_and_digest_bound(monkeypatch, tmp_path):
    identity = {
        "chrome": {"path": "chrome", "version": "1", "sha256": "sha256:" + "a" * 64},
        "rasterizer": {"python_path": "python", "python_sha256": "sha256:" + "b" * 64},
        "renderer_module_sha256": "sha256:" + "c" * 64,
        "settings": {"render_scale": r.RENDER_SCALE},
    }
    monkeypatch.setattr(r, "_runtime_identity", lambda venv=r.DEFAULT_VENV: identity)
    smoke = {
        "page_count": 2,
        "page_sha256": ["sha256:" + "1" * 64, "sha256:" + "2" * 64],
    }
    monkeypatch.setattr(r, "_render_once", lambda *args, **kwargs: dict(smoke))
    path = tmp_path / "receipt.json"
    report = r.qualify(output=path)
    body = {key: value for key, value in report.items() if key != "renderer_qualification_digest"}
    assert report["renderer_qualification_digest"] == r._digest(body)
    assert report["repeatability_smoke"]["exact_page_bytes_equal"] is True
    with pytest.raises(r.SecRendererRefused, match="already exists"):
        r.qualify(output=path)


def test_render_document_binds_renderer_and_source_hash(monkeypatch, tmp_path):
    source = tmp_path / "source.htm"
    source.write_text("<html>source</html>", encoding="utf-8")
    receipt = {"renderer_qualification_digest": "sha256:" + "a" * 64}
    monkeypatch.setattr(r, "verify_receipt", lambda path=r.DEFAULT_RECEIPT: receipt)
    monkeypatch.setattr(
        r,
        "_render_once",
        lambda *args, **kwargs: {
            "page_count": 2,
            "page_sha256": ["sha256:" + "1" * 64, "sha256:" + "2" * 64],
        },
    )
    value = r.render_document(source_html=source, output_dir=tmp_path / "out")
    assert value["renderer_qualification_digest"] == receipt["renderer_qualification_digest"]
    assert value["source_html_sha256"] == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    body = {key: item for key, item in value.items() if key != "rendered_pages_digest"}
    assert value["rendered_pages_digest"] == r._digest(body)