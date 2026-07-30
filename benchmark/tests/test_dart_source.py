from __future__ import annotations

import io
import json
import urllib.parse
import zipfile
from pathlib import Path

import pytest

from benchmark.sources.dart import (
    DART_CONFIRMATION,
    DartApiError,
    DartClient,
    acquire_disclosures,
    load_dart_api_key,
)

KEY = "A" * 40


def _archive(files: dict[str, bytes]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return target.getvalue()


def test_load_key_prefers_environment_and_never_returns_unlabeled_values(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials.txt"
    credentials.write_text(
        f"Github API = {'B' * 40}\nDART API = {KEY}\n",
        encoding="utf-8",
    )
    assert load_dart_api_key(environment={}, credential_file=credentials) == KEY
    assert load_dart_api_key(environment={"AKC_DART_API_KEY": "C" * 40}) == "C" * 40

    credentials.write_text(f"Github API = {'B' * 40}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one labeled"):
        load_dart_api_key(environment={}, credential_file=credentials)


def test_search_uses_business_report_contract_without_leaking_key() -> None:
    seen_url = ""

    def transport(url: str, timeout: float, maximum: int) -> tuple[bytes, str]:
        nonlocal seen_url
        seen_url = url
        assert timeout == 30
        assert maximum == 2 * 1024 * 1024
        return (
            json.dumps(
                {
                    "status": "000",
                    "message": "정상",
                    "list": [
                        {
                            "corp_code": "00126380",
                            "corp_name": "삼성전자",
                            "stock_code": "005930",
                            "report_nm": "사업보고서 (2025.12)",
                            "rcept_no": "20260312001234",
                            "rcept_dt": "20260312",
                            "flr_nm": "삼성전자",
                        }
                    ],
                },
                ensure_ascii=False,
            ).encode(),
            "application/json",
        )

    rows = DartClient(KEY, transport=transport).search_business_reports(
        begin_date="20260301",
        end_date="20260401",
    )
    assert rows[0].receipt_number == "20260312001234"
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(seen_url).query)
    assert query["pblntf_detail_ty"] == ["A001"]
    assert query["last_reprt_at"] == ["Y"]
    assert KEY not in repr(rows)


def test_acquisition_hashes_sources_and_never_claims_labels(tmp_path: Path) -> None:
    archive = _archive(
        {
            "report/main.xml": "<DOCUMENT><TITLE>사업보고서</TITLE></DOCUMENT>".encode(),
            "report/readme.txt": b"public disclosure source",
            "report/image.png": b"not extracted",
        }
    )

    def transport(url: str, _timeout: float, _maximum: int) -> tuple[bytes, str]:
        if urllib.parse.urlsplit(url).path.endswith("/list.json"):
            return (
                json.dumps(
                    {
                        "status": "000",
                        "list": [
                            {
                                "corp_code": "00126380",
                                "corp_name": "삼성전자",
                                "stock_code": "005930",
                                "report_nm": "사업보고서",
                                "rcept_no": "20260312001234",
                                "rcept_dt": "20260312",
                                "flr_nm": "삼성전자",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ).encode(),
                "application/json",
            )
        return archive, "application/zip"

    receipts = acquire_disclosures(
        client=DartClient(KEY, transport=transport),
        output_root=tmp_path,
        begin_date="20260301",
        end_date="20260401",
        corporation_code=None,
        maximum_filings=1,
        confirmation=DART_CONFIRMATION,
    )
    assert len(receipts) == 1
    assert receipts[0].labels_present is False
    assert receipts[0].eligible_for_quality_claims is False
    assert {item.media_type for item in receipts[0].files} == {
        "application/xml",
        "text/plain",
    }
    manifest = json.loads((tmp_path / "acquisition-manifest.json").read_text(encoding="utf-8"))
    assert manifest["eligible_for_quality_claims"] is False
    assert KEY not in json.dumps(manifest)


@pytest.mark.parametrize(
    "files",
    [
        {"../escape.xml": b"x"},
        {"only.png": b"x"},
    ],
)
def test_acquisition_rejects_unsafe_or_unsupported_archives(
    tmp_path: Path,
    files: dict[str, bytes],
) -> None:
    archive = _archive(files)

    def transport(url: str, _timeout: float, _maximum: int) -> tuple[bytes, str]:
        if urllib.parse.urlsplit(url).path.endswith("/list.json"):
            return (
                json.dumps(
                    {
                        "status": "000",
                        "list": [
                            {
                                "corp_code": "00126380",
                                "corp_name": "삼성전자",
                                "stock_code": "005930",
                                "report_nm": "사업보고서",
                                "rcept_no": "20260312001234",
                                "rcept_dt": "20260312",
                                "flr_nm": "삼성전자",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ).encode(),
                "application/json",
            )
        return archive, "application/zip"

    client = DartClient(
        KEY,
        transport=transport,
    )
    with pytest.raises(DartApiError):
        acquire_disclosures(
            client=client,
            output_root=tmp_path,
            begin_date="20260301",
            end_date="20260401",
            corporation_code=None,
            maximum_filings=1,
            confirmation=DART_CONFIRMATION,
        )


def test_document_endpoint_surfaces_sanitized_protocol_error() -> None:
    payload = b"<result><status>020</status><message>request limit</message></result>"
    client = DartClient(KEY, transport=lambda *_: (payload, "application/xml"))
    with pytest.raises(DartApiError) as exc_info:
        client.download_document_archive("20260312001234")
    assert exc_info.value.status == "020"
    assert exc_info.value.retryable is True
    assert KEY not in str(exc_info.value)


def test_acquisition_records_unavailable_archive_and_continues(tmp_path: Path) -> None:
    archive = _archive({"main.xml": b"<DOCUMENT />"})

    def transport(url: str, _timeout: float, _maximum: int) -> tuple[bytes, str]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/list.json"):
            return (
                json.dumps(
                    {
                        "status": "000",
                        "list": [
                            {
                                "corp_code": "00126380",
                                "corp_name": "삼성전자",
                                "stock_code": "005930",
                                "report_nm": "사업보고서",
                                "rcept_no": "20260312000001",
                                "rcept_dt": "20260312",
                                "flr_nm": "삼성전자",
                            },
                            {
                                "corp_code": "00126380",
                                "corp_name": "삼성전자",
                                "stock_code": "005930",
                                "report_nm": "사업보고서",
                                "rcept_no": "20260312000002",
                                "rcept_dt": "20260312",
                                "flr_nm": "삼성전자",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ).encode(),
                "application/json",
            )
        receipt = urllib.parse.parse_qs(parsed.query)["rcept_no"][0]
        if receipt.endswith("1"):
            return (
                b"<result><status>014</status><message>missing</message></result>",
                "application/xml",
            )
        return archive, "application/zip"

    receipts = acquire_disclosures(
        client=DartClient(KEY, transport=transport),
        output_root=tmp_path,
        begin_date="20260301",
        end_date="20260401",
        corporation_code=None,
        maximum_filings=2,
        confirmation=DART_CONFIRMATION,
    )
    assert [receipt.disclosure.receipt_number for receipt in receipts] == [
        "20260312000002"
    ]
    manifest = json.loads((tmp_path / "acquisition-manifest.json").read_text(encoding="utf-8"))
    assert manifest["acquisition_failure_count"] == 1
    assert manifest["failures"] == [
        {
            "receipt_number": "20260312000001",
            "status": "014",
            "retryable": False,
        }
    ]
