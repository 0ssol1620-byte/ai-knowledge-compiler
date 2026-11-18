from __future__ import annotations

import functools
import io
import struct
import tracemalloc
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


@pytest.mark.parametrize("enc", ["euc-kr", "cp949", "utf-32", "shift_jis", "x-bogus"])
def test_hwpml_unsupported_xml_encoding_is_held_not_raised(enc: str) -> None:
    data = f'<?xml version="1.0" encoding="{enc}"?><HWPML/>'.encode()
    assert _held(detect_hwp_format(data), "HWP_SIGNATURE_MISMATCH").detail == "XML_ENCODING"


def test_hwpx_corrupt_deflate_member_is_held_not_raised() -> None:
    raw = bytearray(_zip(HWPX, compression=zipfile.ZIP_STORED))
    at = raw.index(b"Contents/content.hpf")  # local header name; method field is 8 bytes before
    raw[at - 22 + 0 : at - 22 + 2] = b"\x08\x00"
    # patch the central directory entry too
    cd = raw.index(b"Contents/content.hpf", raw.index(b"PK\x01\x02"))
    raw[cd - 46 + 10 : cd - 46 + 12] = b"\x08\x00"
    _held(detect_hwp_format(bytes(raw)), "HWP_SIGNATURE_MISMATCH")


def _seed_zip(method: int) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=method) as z:
        z.writestr("mimetype", b"application/hwp+zip")
        z.writestr("Contents/content.hpf", b"<package>" + b"x" * 200 + b"</package>")
        z.writestr("META-INF/container.xml", b"<container/>")
    return out.getvalue()


def test_mutated_archives_never_raise() -> None:
    # Root-cause guard: any 1-4 byte mutation of a valid package (all four compression
    # methods) must come back as a format or Held, never as an exception from the zip stack
    # (LZMAError, negative seek ValueError, unsupported zip version, UnicodeDecodeError, ...).
    state = 7

    def rand(n: int) -> int:  # fixed-seed LCG: reproducible, no stdlib PRNG
        nonlocal state
        state = (state * 6364136223846793005 + 1442695040888963407) % 2**64
        return (state >> 33) % n

    seeds = [
        _seed_zip(m)
        for m in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA)
    ]
    for _ in range(6000):
        buf = bytearray(seeds[rand(len(seeds))])
        for _ in range(1 + rand(4)):
            buf[rand(len(buf))] = rand(256)
        result = detect_hwp_format(bytes(buf))
        assert result == "hwpx" or isinstance(result, Held)


def test_hwpx_corrupt_lzma_and_unsupported_zip_version_are_held() -> None:
    raw = bytearray(_seed_zip(zipfile.ZIP_LZMA))
    at = raw.index(b"Contents/content.hpf") + len(b"Contents/content.hpf")
    raw[at + 4 : at + 8] = bytes([255]) * 4  # corrupt LZMA header/props of the member
    assert isinstance(detect_hwp_format(bytes(raw)), Held)
    ver = bytearray(_seed_zip(zipfile.ZIP_STORED))
    ver[ver.index(b"PK" + bytes([1, 2])) + 6] = 116  # central-directory "version needed" 11.6
    assert isinstance(detect_hwp_format(bytes(ver)), Held)


_BOMB_BYTES = 16 * 1024 * 1024
_PEAK_BUDGET = 4 * 1024 * 1024


@functools.cache
def _honest_bomb(method: int) -> bytes:
    members = {**HWPX, "Contents/section0.xml": b"\x00" * _BOMB_BYTES}
    return _zip(members, compression=method)


def _lie_about_size(data: bytes, name: bytes, declared: int) -> bytes:
    # rewrite the declared uncompressed size in the local header (offset 22) and the
    # central-directory entry (offset 24); the compressed stream still expands to 16 MB
    raw = bytearray(data)
    local = raw.index(name) - 30
    central = raw.index(name, raw.index(b"PK\x01\x02")) - 46
    raw[local + 22 : local + 26] = struct.pack("<I", declared)
    raw[central + 24 : central + 28] = struct.pack("<I", declared)
    return bytes(raw)


def _peak_of(data: bytes) -> tuple[object, int]:
    tracemalloc.start()
    try:
        result = detect_hwp_format(data)
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize(
    "method",
    [zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA],
    ids=["deflate", "bz2", "lzma"],
)
@pytest.mark.parametrize("declared", [0, 1, 100, 4096])
def test_member_lying_about_its_size_is_held_within_a_bounded_memory_peak(
    method: int, declared: int
) -> None:
    # Root-cause guard: the header-declared sizes pass every container check, so the only
    # bound on decompression is the read itself. Whatever the method and the lie, the
    # detector holds the package without ever inflating past the declared size.
    data = _lie_about_size(_honest_bomb(method), b"Contents/section0.xml", declared)
    result, peak = _peak_of(data)
    assert isinstance(result, Held), result
    assert peak < _PEAK_BUDGET, f"peak {peak / 1e6:.1f} MB"
    if method != zipfile.ZIP_DEFLATED:
        assert result.reason_code == "HWP_CONTAINER_LIMIT"
        assert result.detail == "ARCHIVE_COMPRESSION_METHOD"


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA], ids=["bz2", "lzma"])
def test_hwpx_with_unbounded_compression_method_is_held(method: int) -> None:
    # stdlib bz2/lzma readers have no per-chunk output cap; HWPX (OCF) uses stored/deflate only
    held = _held(detect_hwp_format(_zip(HWPX, compression=method)), "HWP_CONTAINER_LIMIT")
    assert held.detail == "ARCHIVE_COMPRESSION_METHOD"
    assert detect_hwp_format(_zip(HWPX, compression=zipfile.ZIP_STORED)) == "hwpx"
