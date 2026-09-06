from __future__ import annotations

# ruff: noqa: E402, I001 - the local tools path must be installed before imports

import io
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import sfir1_execution as sx
import sfir1_worker as worker


PART = b"""<ECFR>
<DIV8 TYPE="SECTION" N="12.33"><HEAD>Section 12.33 unrelated</HEAD><P>UNRELATED</P></DIV8>
<DIV8 TYPE="SECTION" N="12.34"><HEAD>Section 12.34 first target</HEAD><P>FIRST</P></DIV8>
</ECFR>"""


class Response(io.BytesIO):
    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def test_two_sections_same_part_and_date_fetch_once(monkeypatch, tmp_path):
    calls: list[str] = []

    def open_once(request, **_kwargs):
        calls.append(request.full_url)
        return Response(PART)

    monkeypatch.setattr(worker.urllib.request, "urlopen", open_once)
    root = tmp_path / "raw-parts"
    url = "https://www.ecfr.gov/api/versioner/v1/full/2026-08-25/title-12.xml?part=12"
    first = worker._stream_ecfr_section(url, "12.34", cache_root=root)
    unrelated = worker._stream_ecfr_section(url, "12.33", cache_root=root)
    assert len(calls) == 1
    assert b"FIRST" in first and b"UNRELATED" not in first
    assert b"UNRELATED" in unrelated and b"FIRST" not in unrelated


def test_corrupt_content_addressed_part_refuses_without_refetch(monkeypatch, tmp_path):
    calls = 0

    def opener(_request, **_kwargs):
        nonlocal calls
        calls += 1
        return Response(PART)

    monkeypatch.setattr(worker.urllib.request, "urlopen", opener)
    root = tmp_path / "raw-parts"
    url = "https://www.ecfr.gov/api/versioner/v1/full/2026-08-25/title-12.xml?part=12"
    worker._stream_ecfr_section(url, "12.34", cache_root=root)
    pointer = next((root / "pointers").glob("*.json"))
    digest = json.loads(pointer.read_text(encoding="utf-8"))["sha256"]
    (root / "blobs" / f"{digest}.xml").write_bytes(b"corrupt")
    with pytest.raises(sx.Refused, match="failed hash or size verification"):
        worker._stream_ecfr_section(url, "12.34", cache_root=root)
    assert calls == 1


def test_malformed_tail_refuses_even_if_target_precedes_it(monkeypatch, tmp_path):
    malformed = b'<ECFR><DIV8 TYPE="SECTION" N="12.34"><P>FIRST</P></DIV8><BROKEN>'
    monkeypatch.setattr(
        worker.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(malformed)
    )
    url = "https://www.ecfr.gov/api/versioner/v1/full/2026-08-25/title-12.xml?part=12"
    with pytest.raises(sx.Refused, match="malformed or unreadable"):
        worker._stream_ecfr_section(url, "12.34", cache_root=tmp_path / "raw-parts")


def test_partial_download_refuses_without_publishing_pointer(monkeypatch, tmp_path):
    class TruncatedResponse(Response):
        def __init__(self):
            super().__init__(PART)
            self.headers = {"Content-Length": str(len(PART) + 17)}

    monkeypatch.setattr(
        worker.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: TruncatedResponse(),
    )
    root = tmp_path / "raw-parts"
    url = "https://www.ecfr.gov/api/versioner/v1/full/2026-08-25/title-12.xml?part=12"
    with pytest.raises(sx.Refused, match="ended before declared Content-Length"):
        worker._stream_ecfr_section(url, "12.34", cache_root=root)
    assert not list((root / "pointers").glob("*.json")) if (root / "pointers").exists() else True
    assert not list((root / "tmp").glob("*.partial"))
