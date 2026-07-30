"""Fail-closed OpenDART source acquisition for the private benchmark corpus.

The adapter downloads public disclosure source packages only. It does not
create labels, quality scores, or release claims. API credentials are accepted
through an environment variable or an explicitly supplied local credential
file and are never persisted in receipts, URLs, exceptions, or logs.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from defusedxml import ElementTree

DART_API_ORIGIN = "https://opendart.fss.or.kr"
DART_LIST_ENDPOINT = f"{DART_API_ORIGIN}/api/list.json"
DART_DOCUMENT_ENDPOINT = f"{DART_API_ORIGIN}/api/document.xml"
DART_CONFIRMATION = "PUBLIC_DART_BENCHMARK_ONLY"

_API_KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{40}$")
_CORP_CODE_PATTERN = re.compile(r"^[0-9]{8}$")
_DATE_PATTERN = re.compile(r"^[0-9]{8}$")
_RECEIPT_PATTERN = re.compile(r"^[0-9]{14}$")
_SAFE_SOURCE_EXTENSIONS = frozenset({".xml", ".xhtml", ".html", ".htm", ".txt"})
_MAX_SEARCH_BYTES = 2 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 512
_MAX_COMPRESSION_RATIO = 250
_DART_SUCCESS = "000"
_DART_NO_DATA = "013"


class DartApiError(RuntimeError):
    """A sanitized OpenDART protocol or transport failure."""

    def __init__(self, status: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"OpenDART request failed ({status}): {message}")
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class DartDisclosure:
    corp_code: str
    corp_name: str
    stock_code: str
    report_name: str
    receipt_number: str
    receipt_date: str
    filer_name: str


@dataclass(frozen=True)
class AcquiredFile:
    relative_path: str
    media_type: str
    size_bytes: int
    sha256: str
    source_member: str


@dataclass(frozen=True)
class AcquisitionReceipt:
    schema_version: str
    source: str
    acquired_at: str
    disclosure: DartDisclosure
    archive_relative_path: str
    archive_size_bytes: int
    archive_sha256: str
    files: tuple[AcquiredFile, ...]
    labels_present: bool
    eligible_for_quality_claims: bool


Transport = Callable[[str, float, int], tuple[bytes, str]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _redacted_url(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _read_bounded(stream: BinaryIO, maximum_bytes: int) -> bytes:
    buffer = bytearray()
    while True:
        chunk = stream.read(min(64 * 1024, maximum_bytes + 1 - len(buffer)))
        if not chunk:
            return bytes(buffer)
        buffer.extend(chunk)
        if len(buffer) > maximum_bytes:
            raise DartApiError("RESPONSE_TOO_LARGE", "response exceeded the configured limit")


def _default_transport(url: str, timeout: float, maximum_bytes: int) -> tuple[bytes, str]:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "opendart.fss.or.kr"
        or parsed.port not in {None, 443}
    ):
        raise DartApiError("UNSAFE_ENDPOINT", "request origin is not the approved OpenDART host")
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={
            "Accept": "application/json, application/zip, application/xml",
            "User-Agent": "AI-Knowledge-Compiler-Benchmark/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            final = urllib.parse.urlsplit(response.geturl())
            if (
                final.scheme != "https"
                or final.hostname != "opendart.fss.or.kr"
                or final.port not in {None, 443}
            ):
                raise DartApiError(
                    "UNSAFE_REDIRECT",
                    "OpenDART redirected outside the approved origin",
                )
            content_type = response.headers.get_content_type()
            return _read_bounded(response, maximum_bytes), content_type
    except DartApiError:
        raise
    except urllib.error.HTTPError as exc:
        raise DartApiError(
            f"HTTP_{exc.code}",
            f"HTTP failure at {_redacted_url(url)}",
            retryable=exc.code >= 500 or exc.code == 429,
        ) from exc
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        raise DartApiError(
            "TRANSPORT_ERROR",
            f"transport failure at {_redacted_url(url)}",
            retryable=True,
        ) from exc


def load_dart_api_key(
    *,
    environment: Mapping[str, str] | None = None,
    credential_file: Path | None = None,
) -> str:
    """Load a DART key without including the secret in any error."""

    values = os.environ if environment is None else environment
    direct = values.get("AKC_DART_API_KEY", "").strip()
    if direct:
        if _API_KEY_PATTERN.fullmatch(direct) is None:
            raise ValueError("AKC_DART_API_KEY must be a 40-character alphanumeric key")
        return direct

    configured_file = credential_file
    if configured_file is None and values.get("AKC_DART_CREDENTIAL_FILE"):
        configured_file = Path(values["AKC_DART_CREDENTIAL_FILE"])
    if configured_file is None:
        raise ValueError(
            "set AKC_DART_API_KEY or provide --credential-file/AKC_DART_CREDENTIAL_FILE"
        )
    try:
        text = configured_file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("DART credential file cannot be read") from exc

    candidates: list[str] = []
    for line in text.splitlines():
        if "dart" not in line.casefold():
            continue
        candidates.extend(re.findall(r"(?<![A-Za-z0-9])[A-Za-z0-9]{40}(?![A-Za-z0-9])", line))
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise ValueError("credential file must contain exactly one labeled DART API key")
    return unique[0]


def _validate_date(value: str, name: str) -> str:
    if _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{name} must be a real calendar date") from exc
    return value


def _parse_error_xml(payload: bytes) -> tuple[str, str] | None:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return None
    status = (root.findtext(".//status") or "").strip()
    message = (root.findtext(".//message") or "").strip()
    if status:
        return status, message or "OpenDART returned an unspecified error"
    return None


class DartClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 30,
        transport: Transport = _default_transport,
    ) -> None:
        if _API_KEY_PATTERN.fullmatch(api_key) is None:
            raise ValueError("OpenDART API key must be a 40-character alphanumeric value")
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("timeout_seconds must be within (0, 120]")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport

    def _get(
        self,
        endpoint: str,
        parameters: Mapping[str, str],
        *,
        maximum_bytes: int,
    ) -> tuple[bytes, str]:
        query = urllib.parse.urlencode({"crtfc_key": self._api_key, **parameters})
        return self._transport(f"{endpoint}?{query}", self._timeout, maximum_bytes)

    def search_business_reports(
        self,
        *,
        begin_date: str,
        end_date: str,
        corporation_code: str | None = None,
        page: int = 1,
        page_count: int = 100,
    ) -> list[DartDisclosure]:
        begin = _validate_date(begin_date, "begin_date")
        end = _validate_date(end_date, "end_date")
        if begin > end:
            raise ValueError("begin_date must not be after end_date")
        if corporation_code is not None and _CORP_CODE_PATTERN.fullmatch(corporation_code) is None:
            raise ValueError("corporation_code must contain exactly eight digits")
        if page < 1 or page > 99_999:
            raise ValueError("page must be between 1 and 99999")
        if page_count < 1 or page_count > 100:
            raise ValueError("page_count must be between 1 and 100")

        parameters = {
            "bgn_de": begin,
            "end_de": end,
            "last_reprt_at": "Y",
            "pblntf_ty": "A",
            "pblntf_detail_ty": "A001",
            "sort": "date",
            "sort_mth": "desc",
            "page_no": str(page),
            "page_count": str(page_count),
        }
        if corporation_code:
            parameters["corp_code"] = corporation_code
        payload, _ = self._get(
            DART_LIST_ENDPOINT,
            parameters,
            maximum_bytes=_MAX_SEARCH_BYTES,
        )
        try:
            result = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DartApiError("INVALID_JSON", "disclosure search returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise DartApiError("INVALID_JSON", "disclosure search returned a non-object payload")
        status = str(result.get("status", ""))
        if status == _DART_NO_DATA:
            return []
        if status != _DART_SUCCESS:
            raise DartApiError(
                status or "MISSING_STATUS",
                str(result.get("message") or "OpenDART search failed"),
                retryable=status in {"020", "800", "900"},
            )

        rows = result.get("list", [])
        if not isinstance(rows, list):
            raise DartApiError("INVALID_JSON", "disclosure search list is malformed")
        disclosures: list[DartDisclosure] = []
        for row in rows:
            if not isinstance(row, dict):
                raise DartApiError("INVALID_JSON", "disclosure search row is malformed")
            receipt_number = str(row.get("rcept_no", "")).strip()
            corp_code = str(row.get("corp_code", "")).strip()
            receipt_date = str(row.get("rcept_dt", "")).strip()
            if (
                _RECEIPT_PATTERN.fullmatch(receipt_number) is None
                or _CORP_CODE_PATTERN.fullmatch(corp_code) is None
                or _DATE_PATTERN.fullmatch(receipt_date) is None
            ):
                raise DartApiError(
                    "INVALID_JSON",
                    "disclosure search returned an invalid identifier",
                )
            disclosures.append(
                DartDisclosure(
                    corp_code=corp_code,
                    corp_name=str(row.get("corp_name", "")).strip(),
                    stock_code=str(row.get("stock_code", "")).strip(),
                    report_name=str(row.get("report_nm", "")).strip(),
                    receipt_number=receipt_number,
                    receipt_date=receipt_date,
                    filer_name=str(row.get("flr_nm", "")).strip(),
                )
            )
        return disclosures

    def download_document_archive(self, receipt_number: str) -> bytes:
        if _RECEIPT_PATTERN.fullmatch(receipt_number) is None:
            raise ValueError("receipt_number must contain exactly fourteen digits")
        payload, _ = self._get(
            DART_DOCUMENT_ENDPOINT,
            {"rcept_no": receipt_number},
            maximum_bytes=_MAX_ARCHIVE_BYTES,
        )
        if not zipfile.is_zipfile(io.BytesIO(payload)):
            error = _parse_error_xml(payload)
            if error is None:
                raise DartApiError(
                    "INVALID_ARCHIVE",
                    "document endpoint did not return a ZIP archive",
                )
            status, message = error
            raise DartApiError(status, message, retryable=status in {"020", "800", "900"})
        return payload


def _safe_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        raise DartApiError("UNSAFE_ARCHIVE", "archive contains too many members")
    selected: list[zipfile.ZipInfo] = []
    total_size = 0
    for member in members:
        name = member.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if member.is_dir() or path.is_absolute() or ".." in path.parts or member.flag_bits & 0x1:
            if member.is_dir():
                continue
            raise DartApiError("UNSAFE_ARCHIVE", "archive contains an unsafe member")
        total_size += member.file_size
        if total_size > _MAX_EXTRACTED_BYTES:
            raise DartApiError("UNSAFE_ARCHIVE", "archive expands beyond the configured limit")
        compressed = max(1, member.compress_size)
        if (
            member.file_size > 1024 * 1024
            and member.file_size / compressed > _MAX_COMPRESSION_RATIO
        ):
            raise DartApiError("UNSAFE_ARCHIVE", "archive member compression ratio is unsafe")
        if path.suffix.casefold() in _SAFE_SOURCE_EXTENSIONS:
            selected.append(member)
    if not selected:
        raise DartApiError("UNSUPPORTED_ARCHIVE", "archive has no supported source document")
    return sorted(selected, key=lambda value: value.filename.casefold())


def _media_type(extension: str) -> str:
    return {
        ".xml": "application/xml",
        ".xhtml": "application/xhtml+xml",
        ".html": "text/html",
        ".htm": "text/html",
        ".txt": "text/plain",
    }[extension]


def _write_receipt(
    *,
    output_root: Path,
    disclosure: DartDisclosure,
    archive_payload: bytes,
) -> AcquisitionReceipt:
    root = output_root.resolve()
    case_root = root / disclosure.receipt_number
    source_root = case_root / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    archive_path = case_root / f"{disclosure.receipt_number}.zip"
    archive_path.write_bytes(archive_payload)

    acquired: list[AcquiredFile] = []
    with zipfile.ZipFile(io.BytesIO(archive_payload)) as archive:
        for index, member in enumerate(_safe_archive_members(archive), start=1):
            extension = PurePosixPath(member.filename).suffix.casefold()
            data = archive.read(member)
            target = source_root / (
                f"{index:04d}-{_sha256(member.filename.encode())[:12]}{extension}"
            )
            target.write_bytes(data)
            acquired.append(
                AcquiredFile(
                    relative_path=target.relative_to(root).as_posix(),
                    media_type=_media_type(extension),
                    size_bytes=len(data),
                    sha256=_sha256(data),
                    source_member=member.filename,
                )
            )

    receipt = AcquisitionReceipt(
        schema_version="1.0",
        source="OpenDART",
        acquired_at=_utc_now(),
        disclosure=disclosure,
        archive_relative_path=archive_path.relative_to(root).as_posix(),
        archive_size_bytes=len(archive_payload),
        archive_sha256=_sha256(archive_payload),
        files=tuple(acquired),
        labels_present=False,
        eligible_for_quality_claims=False,
    )
    receipt_payload = json.dumps(
        asdict(receipt),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    (case_root / "acquisition-receipt.json").write_text(
        receipt_payload + "\n",
        encoding="utf-8",
    )
    return receipt


def acquire_disclosures(
    *,
    client: DartClient,
    output_root: Path,
    begin_date: str,
    end_date: str,
    corporation_code: str | None,
    maximum_filings: int,
    confirmation: str,
) -> list[AcquisitionReceipt]:
    if confirmation != DART_CONFIRMATION:
        raise ValueError(f"confirmation must equal {DART_CONFIRMATION}")
    if maximum_filings < 1 or maximum_filings > 50:
        raise ValueError("maximum_filings must be between 1 and 50")
    disclosures = client.search_business_reports(
        begin_date=begin_date,
        end_date=end_date,
        corporation_code=corporation_code,
        page_count=min(100, maximum_filings),
    )[:maximum_filings]
    receipts: list[AcquisitionReceipt] = []
    failures: list[dict[str, object]] = []
    for disclosure in disclosures:
        try:
            receipts.append(
                _write_receipt(
                    output_root=output_root,
                    disclosure=disclosure,
                    archive_payload=client.download_document_archive(disclosure.receipt_number),
                )
            )
        except DartApiError as exc:
            failures.append(
                {
                    "receipt_number": disclosure.receipt_number,
                    "status": exc.status,
                    "retryable": exc.retryable,
                }
            )
    manifest = {
        "schema_version": "1.0",
        "source": "OpenDART",
        "created_at": _utc_now(),
        "query": {
            "begin_date": begin_date,
            "end_date": end_date,
            "corporation_code": corporation_code,
            "report_type": "A001",
            "last_report_only": True,
        },
        "receipt_count": len(receipts),
        "acquisition_failure_count": len(failures),
        "receipts": [
            {
                "receipt_number": receipt.disclosure.receipt_number,
                "receipt_path": (f"{receipt.disclosure.receipt_number}/acquisition-receipt.json"),
                "archive_sha256": receipt.archive_sha256,
            }
            for receipt in receipts
        ],
        "failures": failures,
        "labels_present": False,
        "eligible_for_quality_claims": False,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "acquisition-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    if disclosures and not receipts:
        raise DartApiError(
            "NO_ARCHIVES_ACQUIRED",
            "OpenDART returned no usable source package in the bounded candidate set",
        )
    return receipts
