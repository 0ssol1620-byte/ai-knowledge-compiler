from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_api.parsers import FileValidationError, parse_document
from akc_api.settings import Settings
from pypdf import PdfWriter

_TEST_PDF_PASSWORD = "correct horse"


def _encrypted_pdf(password: str | None = None) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(
        user_password=password or _TEST_PDF_PASSWORD,
        algorithm="AES-256-R5",
    )
    writer.write(output)
    return output.getvalue()


def test_parser_requires_and_validates_encrypted_pdf_password(tmp_path: Path) -> None:
    data = _encrypted_pdf()
    settings = Settings(env="test", data_dir=tmp_path)

    with pytest.raises(FileValidationError) as missing:
        parse_document("protected.pdf", data, settings)
    assert missing.value.code == "ENCRYPTED_PDF"

    with pytest.raises(FileValidationError) as invalid:
        parse_document(
            "protected.pdf",
            data,
            settings,
            pdf_password=b"incorrect",
        )
    assert invalid.value.code == "PDF_PASSWORD_INVALID"

    parsed = parse_document(
        "protected.pdf",
        data,
        settings,
        pdf_password=b"correct horse",
    )
    assert parsed.document_type == "pdf"
    assert len(parsed.pages) == 1


def _sandbox_request(workspace: Path, data: bytes, *, has_password: bool) -> dict[str, object]:
    source = workspace / "source.bin"
    preview = workspace / "previews"
    source.write_bytes(data)
    return {
        "workspace": str(workspace),
        "source_path": str(source),
        "preview_dir": str(preview),
        "filename": "protected.pdf",
        "content_type": "application/pdf",
        "sha256": hashlib.sha256(data).hexdigest(),
        "tenant_id": "tenant-encrypted-pdf-test",
        "document_id": "document-encrypted-pdf-test",
        "document_version_id": "document-encrypted-pdf-test:v1",
        "created_at": datetime.now(UTC).isoformat(),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "max_upload_bytes": 50 * 1024 * 1024,
        "max_pages": 10,
        "max_archive_files": 100,
        "max_archive_uncompressed_bytes": 10 * 1024 * 1024,
        "max_archive_ratio": 20.0,
        "max_extracted_chars_per_page": 100_000,
        "max_extracted_chars_total": 1_000_000,
        "preview_enabled": False,
        "preview_dpi": 110,
        "preview_max_long_edge": 1800,
        "preview_thumbnail_long_edge": 360,
        "preview_max_pixels": 20_000_000,
        "preview_max_bytes_per_asset": 8 * 1024 * 1024,
        "preview_max_total_bytes": 16 * 1024 * 1024,
        "inference_raster_dpis": [200, 300],
        "inference_raster_max_pixels": 40_000_000,
        "inference_raster_max_bytes_per_asset": 32 * 1024 * 1024,
        "inference_raster_max_total_bytes": 64 * 1024 * 1024,
        "child_memory_bytes": 512 * 1024 * 1024,
        "child_file_bytes": 128 * 1024 * 1024,
        "child_open_files": 128,
        "timeout_seconds": 20,
        "pdf_password_from_stdin": has_password,
    }


def _run_sandbox(
    tmp_path: Path,
    *,
    password: bytes | None,
) -> tuple[dict[str, object], str]:
    workspace = tmp_path.resolve()
    workspace.mkdir(parents=True)
    data = _encrypted_pdf()
    request = _sandbox_request(workspace, data, has_password=password is not None)
    request_path = workspace / "request.json"
    result_path = workspace / "result.json"
    serialized = json.dumps(request, separators=(",", ":"))
    request_path.write_text(serialized, encoding="utf-8")
    payload = len(password).to_bytes(4, "big") + password if password is not None else None
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "akc_worker_document.sandbox_runner",
            str(request_path),
            str(result_path),
        ],
        input=payload,
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return json.loads(result_path.read_text(encoding="utf-8")), serialized


def test_sandbox_receives_password_only_over_bounded_stdin_pipe(tmp_path: Path) -> None:
    result, request_text = _run_sandbox(tmp_path / "correct", password=b"correct horse")
    assert result["ok"] is True
    assert "correct horse" not in request_text
    assert "correct horse" not in repr(result)

    invalid, _ = _run_sandbox(tmp_path / "invalid", password=b"incorrect")
    assert invalid == {
        "schema_version": "1.0",
        "ok": False,
        "error_code": "PDF_PASSWORD_INVALID",
        "retryable": False,
    }

    missing, _ = _run_sandbox(tmp_path / "missing", password=None)
    assert missing == {
        "schema_version": "1.0",
        "ok": False,
        "error_code": "ENCRYPTED_PDF",
        "retryable": False,
    }


def test_sandbox_rejects_truncated_or_oversized_password_frames(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    workspace.mkdir(exist_ok=True)
    data = _encrypted_pdf()
    request = _sandbox_request(workspace, data, has_password=True)
    request_path = workspace / "request.json"
    result_path = workspace / "result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    for payload in (b"\x00\x00\x00\x05abc", (1025).to_bytes(4, "big")):
        completed = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "akc_worker_document.sandbox_runner",
                str(request_path),
                str(result_path),
            ],
            input=payload,
            check=False,
            capture_output=True,
            timeout=30,
        )
        assert completed.returncode == 0
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["error_code"] == "PDF_PASSWORD_CHANNEL_INVALID"
