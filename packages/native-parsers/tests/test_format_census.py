"""Drive the declared format census through the real Core gates."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_api.parsers import ALLOWED_EXTENSIONS as G2_ALLOWED
from akc_api.parsers import FileValidationError, parse_document, validate_file
from akc_api.settings import Settings
from akc_native_parsers import (
    SUPPORTED_EXTENSIONS,
    ParseContext,
    ParserLimits,
    StructuredParseError,
    parse_non_pdf_to_cir,
    parse_pdf_to_cir,
)
from akc_native_parsers.format_census import (
    CENSUS,
    CONDITIONS,
    LEGACY_TEXT,
    NATIVE_CIR,
    RASTER,
    REFUSED,
    census_json,
)
from akc_security import ALLOWED_EXTENSIONS as G1_ALLOWED
from akc_security import BLOCKED_EXTENSIONS as G1_BLOCKED
from akc_security import PLAN_LIMITS, PlanTier, UploadLimits, validate_upload_bytes
from akc_security.files import EXPECTED_MIME
from akc_worker_document.sandbox_runner import _STRUCTURED_NATIVE_EXTENSIONS
from PIL import Image

from tests.fixtures.build_safe_fixture_matrix import MANIFEST_PATH, build_fixture_matrix

CTX = ParseContext(
    tenant_id="tenant-1",
    document_id="doc-1",
    document_version_id="ver-1",
    created_at=datetime(2026, 1, 1, tzinfo=UTC),
    retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
)
ACCEPTED_EXTS = sorted(ext for row in CENSUS if row.g1 == "accept" for ext in row.extensions)
NATIVE_EXTS = {"." + e for e in SUPPORTED_EXTENSIONS}


def _image(fmt: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, fmt)
    return out.getvalue()


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return build_fixture_matrix(tmp_path_factory.mktemp("census"))


@pytest.fixture(scope="module")
def samples(fixtures: dict[str, Path]) -> dict[str, bytes]:
    """One minimal valid sample per accepted extension."""

    html = fixtures["valid-html-table"].read_bytes()
    return {
        ".pdf": fixtures["valid-text-pdf"].read_bytes(),
        ".docx": fixtures["valid-docx-table"].read_bytes(),
        ".pptx": fixtures["valid-pptx-group"].read_bytes(),
        ".xlsx": fixtures["valid-xlsx-formula"].read_bytes(),
        ".html": html,
        ".htm": html,
        ".srt": b"1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        ".vtt": b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n",
        ".csv": b"a,b\n1,2\n",
        ".txt": b"plain text\n",
        ".md": b"# title\n",
        ".png": _image("PNG"),
        ".jpg": _image("JPEG"),
        ".jpeg": _image("JPEG"),
        ".webp": _image("WEBP"),
        ".tif": _image("TIFF"),
        ".tiff": _image("TIFF"),
    }


def _settings(tmp_path: Path) -> Settings:
    return Settings(env="test", data_dir=tmp_path)


def _g2(
    name: str, data: bytes, tmp_path: Path, mime: str | None = None, sha: str | None = None
) -> tuple[str, str]:
    return validate_file(
        filename=name,
        declared_mime=mime or EXPECTED_MIME[Path(name).suffix],
        data=data,
        expected_sha256=sha or hashlib.sha256(data).hexdigest(),
        settings=_settings(tmp_path),
    )


def _code(exc: pytest.ExceptionInfo[FileValidationError]) -> str:
    return exc.value.code


def test_declared_census_matches_every_gate_constant() -> None:
    owners: dict[str, str] = {}
    for row in CENSUS:
        for ext in row.extensions:
            assert ext not in owners, f"{ext} in {owners[ext]} and {row.id}"
            owners[ext] = row.id
    accepted = {e for r in CENSUS if r.g1 == "accept" for e in r.extensions}
    blocked = {e for r in CENSUS if r.g1 == "extension_blocked" for e in r.extensions}
    assert accepted == set(G1_ALLOWED) == set(G2_ALLOWED) == set(EXPECTED_MIME)
    assert blocked == set(G1_BLOCKED)
    declared_native = {e for r in CENSUS if r.parse_path == NATIVE_CIR for e in r.extensions}
    assert declared_native == NATIVE_EXTS | {".pdf"}
    assert set(_STRUCTURED_NATIVE_EXTENSIONS) == NATIVE_EXTS
    assert set(owners) >= set(G1_ALLOWED) | set(G1_BLOCKED)


def test_every_stratum_behaves_as_declared_at_the_upload_gate(
    samples: dict[str, bytes],
) -> None:
    for row in CENSUS:
        for ext in row.extensions:
            result = validate_upload_bytes(f"sample{ext}", samples.get(ext, b"%PDF-1.7 x"))
            if row.g1 == "accept":
                assert result.accepted, (ext, result.reason_code)
            else:
                assert not result.accepted, ext
                assert result.reason_code == row.g1, (ext, result.reason_code)


def test_refused_strata_are_refused_at_g2_and_the_native_parser(tmp_path: Path) -> None:
    for row in CENSUS:
        if row.parse_path != REFUSED:
            continue
        for ext in row.extensions:
            with pytest.raises(FileValidationError) as g2:
                _g2(f"sample{ext}", b"x", tmp_path, "application/octet-stream")
            assert _code(g2) == row.g2, ext
            with pytest.raises(StructuredParseError):
                parse_non_pdf_to_cir(
                    filename=f"sample{ext}",
                    declared_mime="application/octet-stream",
                    data=b"x",
                    context=CTX,
                )


def test_accepted_strata_reach_their_declared_parse_path(
    samples: dict[str, bytes], tmp_path: Path
) -> None:
    for row in CENSUS:
        if row.g1 != "accept":
            continue
        for ext in row.extensions:
            data, name, mime = samples[ext], f"sample{ext}", EXPECTED_MIME[ext]
            _g2(name, data, tmp_path)
            if ext == ".pdf":
                doc = parse_pdf_to_cir(filename=name, declared_mime=mime, data=data, context=CTX)
                assert doc.metadata["documentType"] == "pdf"
            elif row.parse_path == NATIVE_CIR:
                doc = parse_non_pdf_to_cir(
                    filename=name, declared_mime=mime, data=data, context=CTX
                )
                assert doc.blocks, ext
            else:
                parsed = parse_document(name, data, _settings(tmp_path))
                assert parsed.pages, ext
                if row.parse_path == LEGACY_TEXT:
                    # structure lost, by declaration: page text only
                    assert all(isinstance(p.text, str) for p in parsed.pages)
                if row.parse_path == RASTER:
                    assert parsed.pages[0].text.strip() == ""


def test_no_extension_is_accepted_without_a_parse_path() -> None:
    for row in CENSUS:
        if row.g1 == "accept":
            assert row.parse_path in {NATIVE_CIR, LEGACY_TEXT, RASTER}, row.id
        else:
            assert row.parse_path == REFUSED and row.remediation, row.id


def test_census_json_is_canonical() -> None:
    value = json.loads(census_json())
    assert [r["id"] for r in value["rows"]] == [r.id for r in CENSUS]
    assert [c["id"] for c in value["conditions"]] == [c["id"] for c in CONDITIONS]


# --- condition matrix -------------------------------------------------------


@pytest.mark.parametrize("ext", ACCEPTED_EXTS)
def test_condition_wrong_claimed_mime_is_refused(
    ext: str, samples: dict[str, bytes], tmp_path: Path
) -> None:
    other = "image/gif"
    result = validate_upload_bytes(f"s{ext}", samples[ext], claimed_content_type=other)
    assert result.reason_code == "claimed_mime_mismatch"
    with pytest.raises(FileValidationError) as exc:
        _g2(f"s{ext}", samples[ext], tmp_path, other)
    assert _code(exc) == "MIME_MISMATCH"
    if ext in NATIVE_EXTS:
        with pytest.raises(StructuredParseError, match="MIME_MISMATCH"):
            parse_non_pdf_to_cir(
                filename=f"s{ext}", declared_mime=other, data=samples[ext], context=CTX
            )


@pytest.mark.parametrize("ext", ACCEPTED_EXTS)
def test_condition_wrong_magic_is_refused(ext: str) -> None:
    bad = b"\xff\xfe\xfd\xfc not a " + ext.encode() + b" file"
    result = validate_upload_bytes(f"s{ext}", bad)
    assert not result.accepted and result.reason_code == "file_signature_mismatch"


def test_condition_wrong_magic_at_g2_and_native(tmp_path: Path) -> None:
    bad = b"MZ not a document"
    for ext in (".pdf", ".docx", ".pptx", ".xlsx"):
        with pytest.raises(FileValidationError) as exc:
            _g2(f"s{ext}", bad, tmp_path)
        assert _code(exc) == "MAGIC_MISMATCH"
    with pytest.raises(StructuredParseError, match="MAGIC_MISMATCH"):
        parse_pdf_to_cir(
            filename="s.pdf", declared_mime=EXPECTED_MIME[".pdf"], data=bad, context=CTX
        )
    with pytest.raises(StructuredParseError, match="MAGIC_MISMATCH"):
        parse_non_pdf_to_cir(
            filename="s.docx", declared_mime=EXPECTED_MIME[".docx"], data=bad, context=CTX
        )


def test_condition_locked_pdf_needs_a_password(fixtures: dict[str, Path], tmp_path: Path) -> None:
    data = fixtures["valid-encrypted-pdf"].read_bytes()
    assert validate_upload_bytes("s.pdf", data).accepted
    with pytest.raises(FileValidationError) as exc:
        parse_document("s.pdf", data, _settings(tmp_path))
    assert _code(exc) == "ENCRYPTED_PDF"
    with pytest.raises(StructuredParseError, match="ENCRYPTED_PDF"):
        parse_pdf_to_cir(
            filename="s.pdf", declared_mime=EXPECTED_MIME[".pdf"], data=data, context=CTX
        )


def _cond(cid: str) -> dict[str, str]:
    return next(c for c in CONDITIONS if c["id"] == cid)


def test_condition_password_protected_ooxml_is_only_a_generic_signature_mismatch() -> None:
    locked = _cond("locked")
    # A password-protected OOXML file is an OLE compound file wearing a .docx name.
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    result = validate_upload_bytes("locked.docx", ole)
    assert not result.accepted and result.reason_code == "file_signature_mismatch"
    assert locked["reason_quality"] == "generic"
    assert locked["ooxml_g1"] == result.reason_code


def test_condition_over_limit_size(
    samples: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(PLAN_LIMITS, PlanTier.FREE, UploadLimits(max_file_bytes=1024))
    for ext in ACCEPTED_EXTS:
        result = validate_upload_bytes(f"s{ext}", samples[ext] + b"\x00" * 4096)
        assert result.reason_code == "file_too_large", ext
    tiny = ParserLimits(max_input_bytes=16)
    for ext in (".docx", ".html", ".srt"):
        with pytest.raises(StructuredParseError, match="FILE_TOO_LARGE"):
            parse_non_pdf_to_cir(
                filename=f"s{ext}",
                declared_mime=EXPECTED_MIME[ext],
                data=samples[ext],
                context=CTX,
                limits=tiny,
            )
    with pytest.raises(StructuredParseError, match="FILE_TOO_LARGE"):
        parse_pdf_to_cir(
            filename="s.pdf",
            declared_mime=EXPECTED_MIME[".pdf"],
            data=samples[".pdf"],
            context=CTX,
            limits=tiny,
        )


def test_condition_g2_size_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(FileValidationError) as exc:
        validate_file(
            filename="big.txt",
            declared_mime="text/plain",
            data=b"a" * (settings.max_upload_bytes + 1),
            expected_sha256="0" * 64,
            settings=settings,
        )
    assert _code(exc) == "FILE_TOO_LARGE"


@pytest.mark.parametrize("ext", [".docx", ".pptx", ".xlsx"])
def test_condition_malformed_container_is_refused(ext: str) -> None:
    bad = b"PK\x03\x04" + b"\x00" * 64
    result = validate_upload_bytes(f"s{ext}", bad)
    assert not result.accepted and result.reason_code == _cond("malformed")["ooxml_g1"]
    with pytest.raises(StructuredParseError):
        parse_non_pdf_to_cir(
            filename=f"s{ext}", declared_mime=EXPECTED_MIME[ext], data=bad, context=CTX
        )


def test_condition_malformed_pdf_parses_to_a_stable_error(fixtures: dict[str, Path]) -> None:
    data = fixtures["hostile-malformed-xref"].read_bytes()
    with pytest.raises(StructuredParseError, match="PDF_PARSE_FAILED"):
        parse_pdf_to_cir(
            filename="s.pdf", declared_mime=EXPECTED_MIME[".pdf"], data=data, context=CTX
        )


def _lying_member_docx(raw: bytes) -> bytes:
    """Under-declare word/document.xml's size in the central directory only."""

    buf = bytearray(raw)
    at = buf.find(b"PK\x01\x02")
    patched = False
    while at >= 0:
        name_len = struct.unpack_from("<H", buf, at + 28)[0]
        if bytes(buf[at + 46 : at + 46 + name_len]) == b"word/document.xml":
            struct.pack_into("<I", buf, at + 24, 10)
            patched = True
        at = buf.find(b"PK\x01\x02", at + 1)
    assert patched
    return bytes(buf)


def test_condition_lying_member_size_is_never_a_successful_parse(
    samples: dict[str, bytes],
) -> None:
    data = _lying_member_docx(samples[".docx"])
    result = validate_upload_bytes("s.docx", data)
    # zipfile stops at the declared size and fails the CRC check.
    cond = _cond("lying_member_size")
    assert cond["reason_quality"] == "generic"
    assert not result.accepted and result.reason_code
    assert result.reason_code.startswith("Bad CRC-32")  # unstable zipfile text, declared as such
    assert cond["native"] == "unwrapped zipfile.BadZipFile"
    with pytest.raises(zipfile.BadZipFile):
        parse_non_pdf_to_cir(
            filename="s.docx", declared_mime=EXPECTED_MIME[".docx"], data=data, context=CTX
        )


# --- hostile fixture verdicts -------------------------------------------------

# Where each non-accept manifest entry is stopped, as observed at the pinned gates:
# "g1" = refused at the upload gate with that reason; "later" = accepted at G1.
_HOSTILE_VERDICTS: dict[str, tuple[str, str]] = {
    "hostile-fake-extension": ("g1", "extension_not_allowed"),
    "hostile-zip-bomb-docx": ("g1", "archive_compression_ratio"),
    "hostile-external-relationship": ("g1", "ooxml_external_relationship"),
    "hostile-svg-script": ("g1", "extension_blocked"),
    "hostile-malformed-xref": ("later", "PDF_PARSE_FAILED"),
    "hostile-oversized-image": ("later", "INVALID_IMAGE"),  # refused by parse_document
    "hostile-javascript-link": ("later", "observed gap: not enforced in Core"),
    "hostile-prompt-injection": ("later", "flagged downstream, never trusted"),
    "valid-encrypted-pdf": ("later", "ENCRYPTED_PDF"),
}


def test_fixture_matrix_hostile_verdicts_hold(fixtures: dict[str, Path]) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    non_accept = {e["id"] for e in manifest["fixtures"] if e["expected"] != "accept"}
    assert non_accept == set(_HOSTILE_VERDICTS)  # a new manifest entry must be mapped
    for entry in manifest["fixtures"]:
        fid = entry["id"]
        path = fixtures[fid]
        result = validate_upload_bytes(path.name, path.read_bytes())
        if entry["expected"] == "accept":
            assert result.accepted, (fid, result.reason_code)
        else:
            layer, detail = _HOSTILE_VERDICTS[fid]
            if layer == "g1":
                assert not result.accepted and result.reason_code == detail, fid
            else:
                assert result.accepted, fid


def test_fixture_matrix_late_verdicts_are_stopped_after_g1(
    fixtures: dict[str, Path], tmp_path: Path
) -> None:
    pdf_mime = EXPECTED_MIME[".pdf"]
    with pytest.raises(StructuredParseError, match="PDF_PARSE_FAILED"):
        parse_pdf_to_cir(
            filename="x.pdf",
            declared_mime=pdf_mime,
            data=fixtures["hostile-malformed-xref"].read_bytes(),
            context=CTX,
        )
    with pytest.raises(StructuredParseError, match="ENCRYPTED_PDF"):
        parse_pdf_to_cir(
            filename="x.pdf",
            declared_mime=pdf_mime,
            data=fixtures["valid-encrypted-pdf"].read_bytes(),
            context=CTX,
        )
    big = fixtures["hostile-oversized-image"]
    with pytest.raises(FileValidationError) as exc:
        parse_document(big.name, big.read_bytes(), _settings(tmp_path))
    assert _code(exc) == "INVALID_IMAGE"
    # Observed gap (follow-up): nothing in Core sanitises javascript: links; they pass as text.
    js = fixtures["hostile-javascript-link"]
    parsed = parse_document(js.name, js.read_bytes(), _settings(tmp_path))
    assert "javascript:alert(1)" in "".join(p.text for p in parsed.pages)


def test_scan_pdf_parses_to_figure_blocks_without_text(fixtures: dict[str, Path]) -> None:
    doc = parse_pdf_to_cir(
        filename="s.pdf",
        declared_mime=EXPECTED_MIME[".pdf"],
        data=fixtures["valid-scan-pdf"].read_bytes(),
        context=CTX,
    )
    kinds = {str(getattr(b.type, "value", b.type)).lower() for b in doc.blocks}
    assert kinds == {"figure"}


# --- HWP stays refused ----------------------------------------------------------


@pytest.mark.parametrize("ext", [".hwp", ".hwpx", ".hml"])
def test_korean_hwp_family_stays_refused(ext: str, tmp_path: Path) -> None:
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    for data in (ole, b"PK\x03\x04" + b"\x00" * 64, b"<HWPML/>"):
        result = validate_upload_bytes(f"s{ext}", data)
        assert not result.accepted and result.reason_code == "extension_not_allowed"
    with pytest.raises(FileValidationError):
        _g2(f"s{ext}", ole, tmp_path, "application/x-hwp")
    with pytest.raises(StructuredParseError, match="UNSUPPORTED_NON_PDF_TYPE"):
        parse_non_pdf_to_cir(
            filename=f"s{ext}", declared_mime="application/x-hwp", data=ole, context=CTX
        )
    assert ext not in G1_ALLOWED and ext not in G2_ALLOWED
    assert ext not in NATIVE_EXTS and ext not in _STRUCTURED_NATIVE_EXTENSIONS
    assert next(r for r in CENSUS if ext in r.extensions).parse_path == REFUSED
