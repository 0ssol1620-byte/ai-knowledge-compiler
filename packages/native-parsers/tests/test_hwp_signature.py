from __future__ import annotations

import io
import zipfile

import pytest
from akc_native_parsers.hwp_contract import Held
from akc_native_parsers.hwp_signature import (
    HWP3_SIGNATURE,
    OLE_MAGIC,
    detect_hwp_format,
)
from akc_native_parsers.models import ParserLimits


def _zip(members: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as z:
        for name, payload in members.items():
            z.writestr(name, payload)
    return out.getvalue()


HWPX = {
    "mimetype": b"application/hwp+zip",
    "version.xml": b"<v/>",
    "Contents/content.hpf": b"<package/>",
    "META-INF/container.xml": b"<container/>",
}
HWP5 = (
    OLE_MAGIC
    + b"\x00" * 64
    + "FileHeader".encode("utf-16-le")
    + b"\x00" * 32
    + b"HWP Document File"
    + b"\x00" * 15
)


def _held(result: object, code: str) -> Held:
    assert isinstance(result, Held), result
    assert result.reason_code == code
    return result


def test_each_family_is_detected_by_content() -> None:
    assert detect_hwp_format(HWP3_SIGNATURE + b"rest") == "hwp3"
    assert detect_hwp_format(HWP5) == "hwp5"
    assert detect_hwp_format(_zip(HWPX)) == "hwpx"
    xml = b'<?xml version="1.0" encoding="UTF-8"?><HWPML Version="2.8"><BODY/></HWPML>'
    assert detect_hwp_format(xml) == "hwpml"
    assert detect_hwp_format("﻿<HWPML/>".encode()) == "hwpml"


def test_extension_lies_content_decides() -> None:
    # the module takes bytes only, so a ".docx" name with HWPX bytes is hwpx
    assert detect_hwp_format(_zip(HWPX)) == "hwpx"
    _held(detect_hwp_format(b"%PDF-1.7\n1 0 obj"), "HWP_SIGNATURE_MISMATCH")
    docx = _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"})
    _held(detect_hwp_format(docx), "HWP_SIGNATURE_MISMATCH")
    _held(detect_hwp_format(b""), "HWP_SIGNATURE_MISMATCH")


def test_ole_that_is_not_hwp_is_held() -> None:
    legacy_doc = OLE_MAGIC + b"\x00" * 512 + "WordDocument".encode("utf-16-le")
    _held(detect_hwp_format(legacy_doc), "HWP_NOT_HWP_OLE")


def test_wrong_hwpx_mimetype_or_missing_members_is_not_hwpx() -> None:
    wrong = _zip({**HWPX, "mimetype": b"application/epub+zip"})
    _held(detect_hwp_format(wrong), "HWP_SIGNATURE_MISMATCH")
    no_content = {k: v for k, v in HWPX.items() if k != "Contents/content.hpf"}
    _held(detect_hwp_format(_zip(no_content)), "HWP_SIGNATURE_MISMATCH")


def test_hwpx_bomb_traversal_symlink_and_ratio_fail_closed() -> None:
    limits = ParserLimits(max_archive_entries=10, max_archive_member_bytes=1000)
    many = {**HWPX, **{f"Contents/s{i}.xml": b"<s/>" for i in range(20)}}
    held = _held(detect_hwp_format(_zip(many), limits), "HWP_CONTAINER_LIMIT")
    assert held.detail == "ARCHIVE_ENTRY_LIMIT"

    big = {**HWPX, "BinData/big.bin": b"\x00" * 5000}
    held = _held(detect_hwp_format(_zip(big), limits), "HWP_CONTAINER_LIMIT")
    assert held.detail == "ARCHIVE_MEMBER_LIMIT"

    ratio = {**HWPX, "BinData/z.bin": b"\x00" * 2_000_000}
    held = _held(detect_hwp_format(_zip(ratio)), "HWP_CONTAINER_LIMIT")
    assert held.detail == "ARCHIVE_RATIO_LIMIT"

    traversal = {**HWPX, "../evil.xml": b"<x/>"}
    held = _held(detect_hwp_format(_zip(traversal)), "HWP_CONTAINER_LIMIT")
    assert held.detail == "ARCHIVE_PATH_TRAVERSAL"

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, payload in HWPX.items():
            z.writestr(name, payload)
        link = zipfile.ZipInfo("Contents/link")
        link.external_attr = 0o120777 << 16
        z.writestr(link, "/etc/passwd")
    held = _held(detect_hwp_format(out.getvalue()), "HWP_CONTAINER_LIMIT")
    assert held.detail == "ARCHIVE_SYMLINK"

    doctype = b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
    _held(detect_hwp_format(_zip({**HWPX, "Contents/content.hpf": doctype})), "HWP_XML_UNSAFE")


def test_hwpml_xxe_and_depth_bomb_fail_closed() -> None:
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE HWPML [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<HWPML>&x;</HWPML>"
    )
    _held(detect_hwp_format(xxe), "HWP_XML_UNSAFE")
    laughs = b'<!DOCTYPE HWPML [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><HWPML>&b;</HWPML>'
    _held(detect_hwp_format(laughs), "HWP_XML_UNSAFE")
    deep = b"<HWPML>" + b"<a>" * 300 + b"</a>" * 300 + b"</HWPML>"
    assert _held(detect_hwp_format(deep), "HWP_XML_UNSAFE").detail == "XML_DEPTH_LIMIT"
    _held(detect_hwp_format(b"<html><body/></html>"), "HWP_SIGNATURE_MISMATCH")
    _held(detect_hwp_format(b"x" * 100, ParserLimits(max_input_bytes=10)), "HWP_CONTAINER_LIMIT")


@pytest.mark.parametrize("cut", [4, 30, 100])
def test_truncated_containers_fail_with_stable_codes(cut: int) -> None:
    zipped = _zip(HWPX, compression=zipfile.ZIP_STORED)
    _held(detect_hwp_format(zipped[:cut]), "HWP_SIGNATURE_MISMATCH")
    _held(detect_hwp_format(HWP5[:8] + b"\x00" * cut), "HWP_NOT_HWP_OLE")
    _held(detect_hwp_format(b"<HWPML><BODY><P>"[: 5 + cut]), "HWP_SIGNATURE_MISMATCH")
