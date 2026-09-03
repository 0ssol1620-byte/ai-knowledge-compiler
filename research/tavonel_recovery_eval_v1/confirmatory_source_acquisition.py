#!/usr/bin/env python3
"""Predeclared fresh-source acquisition contract for TAVONEL-R Stage 1.

The source contract can be inspected and sealed before runtime qualification,
but *no fresh network acquisition* is permitted until both the Primary and
Strong development-runtime qualification receipts exist and independently
re-verify against the live repository bytes.

Primary Stage 1 is fixed at 150 Dr.DocBench pages + 150 SEC pages.  DART is a
separate optional external-validity lane and is deliberately absent here.

This module intentionally separates:

1. source-contract terms (safe to freeze before acquisition),
2. candidate discovery/materialization (qualification-gated),
3. deterministic selection (implemented in confirmatory_selection.py), and
4. hidden evaluator material (never mounted by the runtime driver).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from confirmatory_selection import STAGE1_FAMILY_QUOTAS
from runtime_attestation import verify_attestation_payload


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RECEIPT_ROOT = HERE / "receipts"
QUAL_ROOT = RECEIPT_ROOT / "runtime-qualification"
PRIMARY_ATTESTATION = QUAL_ROOT / "primary.json"
STRONG_ATTESTATION = QUAL_ROOT / "strong.json"
DEFAULT_CONTRACT = RECEIPT_ROOT / "fresh-source-contract.json"
DEFAULT_SOURCE_ROOT = HERE / ".private" / "fresh-confirmatory-source"

CONTRACT_SCHEMA = "tavonel.recovery.fresh_source_contract.v1"
SOURCE_MANIFEST_SCHEMA = "tavonel.recovery.fresh_source_manifest.v1"
SEC_INDEX_ROW_SCHEMA = "tavonel.recovery.sec_index_candidate.v1"

DRDOC_REPO_ID = "2077AIDataFoundation/DrDocBench"
DRDOC_REQUESTED_REVISION = "main"
DRDOC_SPLIT = "dev"
DRDOC_IMAGE_RE = re.compile(
    r"^dev/(?P<subject>[^/]+)/(?P<document_uuid>[^/]+)/images/page_(?P<page>\d+)\.(?:jpg|jpeg|png)$",
    re.IGNORECASE,
)

SEC_START_DATE = date(2026, 5, 1)
SEC_END_DATE = date(2026, 8, 28)
SEC_FORMS = ("10-K", "10-Q")
SEC_PREFILTER_COUNT = 48
SEC_PREFILTER_SALT = "tavonel-r-sec-stage1-filing-prefilter-v1"
SEC_MIN_INTERVAL_SECONDS = 0.25  # 4 req/s, below SEC's published 10 req/s ceiling.
SEC_USER_AGENT_ENV = "TAVONEL_SEC_USER_AGENT"

_SEC_MASTER_LINE = re.compile(
    r"^(?P<cik>\d+)\|(?P<company>[^|]+)\|(?P<form>[^|]+)\|"
    r"(?P<filed>\d{4}-\d{2}-\d{2})\|(?P<filename>edgar/data/[^|\s]+\.txt)$"
)
_SEC_DOC_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)


class SourceAcquisitionRefused(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SourceAcquisitionRefused(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAcquisitionRefused(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise SourceAcquisitionRefused(f"{label} must be a JSON object")
    return value


def _write_once(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise SourceAcquisitionRefused(f"immutable artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def source_contract() -> dict[str, Any]:
    """Return the outcome-blind source contract without contacting any source."""

    if dict(STAGE1_FAMILY_QUOTAS) != {"drdocbench": 150, "sec": 150}:
        raise SourceAcquisitionRefused("selection code no longer matches the 150/150 source contract")
    body = {
        "schema": CONTRACT_SCHEMA,
        "state": "PRE_ACQUISITION_TERMS",
        "primary_stage1_pages": 300,
        "primary_family_quotas": dict(STAGE1_FAMILY_QUOTAS),
        "scientific_outcomes_used_to_define_sources": False,
        "qualification_required_before_network_acquisition": True,
        "drdocbench": {
            "dataset_repo_id": DRDOC_REPO_ID,
            "requested_revision": DRDOC_REQUESTED_REVISION,
            "split": DRDOC_SPLIT,
            "page_identity": "document_uuid + original page number + exact image sha256",
            "runtime_surface": "selected page image bytes only",
            "evaluation_surface": "matching public dev JSON/Markdown kept outside runtime mount",
            "revision_rule": "resolve requested revision once after qualification, then pin commit hash",
            "rights": (
                "annotation metadata follows the dataset-declared CC0-1.0 terms; underlying "
                "source-document rights remain with original publishers and are not relicensed"
            ),
        },
        "sec": {
            "official_origin": "https://www.sec.gov",
            "index_surface": "/Archives/edgar/daily-index/YYYY/QTRN/master.YYYYMMDD.idx",
            "date_range_inclusive": [SEC_START_DATE.isoformat(), SEC_END_DATE.isoformat()],
            "forms": list(SEC_FORMS),
            "filing_prefilter_count": SEC_PREFILTER_COUNT,
            "filing_prefilter_salt_digest": _sha_bytes(SEC_PREFILTER_SALT.encode()),
            "filing_prefilter_rule": (
                "eligible exact-form master-index rows sorted by "
                "sha256(prefilter_salt|CIK|form|filed_date|archive_filename), then first N"
            ),
            "submission_surface": "/Archives/<master-index filename>",
            "primary_document_rule": (
                "parse complete submission SGML; documents whose TYPE exactly equals filing form; "
                "choose lowest numeric SEQUENCE then FILENAME"
            ),
            "page_identity": (
                "archive filename + primary-document sha256 + pinned renderer digest + page ordinal "
                "+ rendered page sha256"
            ),
            "renderer_requirement": (
                "SEC page candidates cannot enter selection until a separate immutable renderer "
                "receipt pins browser/PDF rasterizer versions and output settings"
            ),
            "automated_access": {
                "declared_user_agent_required": True,
                "user_agent_env": SEC_USER_AGENT_ENV,
                "max_requests_per_second": 4,
            },
        },
        "secondary_external_validity": {
            "dart": {"quota": 100, "included_in_primary_result": False, "required": False}
        },
        "forbidden_selection_inputs": [
            "model output",
            "accuracy",
            "parser disagreement result",
            "strong-model recovery result",
            "hidden evaluator truth",
            "model-inferred difficulty",
        ],
    }
    return {**body, "source_contract_digest": _digest(body)}


def seal_source_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    report = source_contract()
    _write_once(path, report)
    return report


def verify_source_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    report = _load_object(path, label="fresh source contract")
    body = {key: value for key, value in report.items() if key != "source_contract_digest"}
    if report.get("schema") != CONTRACT_SCHEMA or _digest(body) != report.get(
        "source_contract_digest"
    ):
        raise SourceAcquisitionRefused("fresh source contract digest does not recompute")
    if report.get("primary_family_quotas") != dict(STAGE1_FAMILY_QUOTAS):
        raise SourceAcquisitionRefused("fresh source contract quota drifted")
    return report


def _verify_attestation(path: Path, role: str) -> dict[str, Any]:
    payload = _load_object(path, label=f"{role} runtime qualification")
    try:
        digest = verify_attestation_payload(payload, REPO)
    except Exception as exc:  # normalized into the source-acquisition gate
        raise SourceAcquisitionRefused(f"{role} runtime qualification does not re-verify") from exc
    if payload.get("role") != role:
        raise SourceAcquisitionRefused(f"{role} runtime qualification role mismatch")
    if payload.get("attestation_digest") != digest:
        raise SourceAcquisitionRefused(f"{role} runtime qualification digest mismatch")
    if payload.get("fresh_confirmatory_observation") is not False:
        raise SourceAcquisitionRefused(f"{role} qualification observed fresh confirmatory data")
    if payload.get("sensitive_material_included") is not False:
        raise SourceAcquisitionRefused(f"{role} qualification contains sensitive material")
    return payload


def require_qualified_pair() -> dict[str, str]:
    """Fail before any network request unless both role receipts independently verify."""

    primary = _verify_attestation(PRIMARY_ATTESTATION, "primary")
    strong = _verify_attestation(STRONG_ATTESTATION, "strong")
    return {
        "primary_attestation_digest": str(primary["attestation_digest"]),
        "strong_attestation_digest": str(strong["attestation_digest"]),
    }


def _sec_user_agent() -> str:
    value = str(os.environ.get(SEC_USER_AGENT_ENV, "")).strip()
    if not value or "@" not in value or len(value) > 240:
        raise SourceAcquisitionRefused(
            f"{SEC_USER_AGENT_ENV} must declare the SEC automated-access identity and contact"
        )
    return value


def _http_get(url: str, *, user_agent: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "identity",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        if response.status != 200:
            raise SourceAcquisitionRefused(f"source returned HTTP {response.status}: {url}")
        return response.read()


def _quarter(value: date) -> int:
    return (value.month - 1) // 3 + 1


def sec_master_index_urls() -> tuple[str, ...]:
    rows: list[str] = []
    current = SEC_START_DATE
    while current <= SEC_END_DATE:
        if current.weekday() < 5:
            rows.append(
                "https://www.sec.gov/Archives/edgar/daily-index/"
                f"{current.year}/QTR{_quarter(current)}/master.{current:%Y%m%d}.idx"
            )
        current += timedelta(days=1)
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class SecFiling:
    cik: str
    company: str
    form: str
    filed_date: str
    archive_filename: str

    @property
    def stable_id(self) -> str:
        return "|".join((self.cik, self.form, self.filed_date, self.archive_filename))

    def as_record(self) -> dict[str, Any]:
        return {
            "schema": SEC_INDEX_ROW_SCHEMA,
            "cik": self.cik,
            "company": self.company,
            "form": self.form,
            "filed_date": self.filed_date,
            "archive_filename": self.archive_filename,
        }


def parse_sec_master_index(text: str) -> tuple[SecFiling, ...]:
    rows: list[SecFiling] = []
    for line in text.splitlines():
        match = _SEC_MASTER_LINE.match(line.strip())
        if match is None:
            continue
        if match.group("form") not in SEC_FORMS:
            continue
        filed = date.fromisoformat(match.group("filed"))
        if not SEC_START_DATE <= filed <= SEC_END_DATE:
            continue
        rows.append(
            SecFiling(
                cik=match.group("cik"),
                company=match.group("company").strip(),
                form=match.group("form"),
                filed_date=filed.isoformat(),
                archive_filename=match.group("filename"),
            )
        )
    return tuple(rows)


def preselect_sec_filings(rows: Iterable[SecFiling]) -> tuple[SecFiling, ...]:
    unique: dict[str, SecFiling] = {}
    for row in rows:
        unique.setdefault(row.stable_id, row)

    def key(row: SecFiling) -> tuple[bytes, str]:
        ranked = hashlib.sha256(f"{SEC_PREFILTER_SALT}|{row.stable_id}".encode()).digest()
        return ranked, row.stable_id

    ordered = sorted(unique.values(), key=key)
    if len(ordered) < SEC_PREFILTER_COUNT:
        raise SourceAcquisitionRefused(
            f"SEC eligible filing inventory has {len(ordered)}, below frozen prefilter count "
            f"{SEC_PREFILTER_COUNT}"
        )
    return tuple(ordered[:SEC_PREFILTER_COUNT])


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{re.escape(name)}>\s*([^\r\n<]+)", block, re.IGNORECASE)
    return "" if match is None else match.group(1).strip()


def extract_sec_primary_document(submission: bytes, filing_form: str) -> dict[str, Any]:
    """Extract the prospectively declared primary document from complete EDGAR SGML."""

    text = submission.decode("latin-1")
    candidates: list[tuple[int, str, str]] = []
    for block in _SEC_DOC_RE.findall(text):
        if _tag(block, "TYPE") != filing_form:
            continue
        filename = _tag(block, "FILENAME")
        sequence_raw = _tag(block, "SEQUENCE")
        match = re.search(r"<TEXT>(.*)</TEXT>", block, re.IGNORECASE | re.DOTALL)
        if not filename or match is None:
            continue
        try:
            sequence = int(sequence_raw)
        except ValueError:
            sequence = 2**31 - 1
        candidates.append((sequence, filename, match.group(1)))
    if not candidates:
        raise SourceAcquisitionRefused(f"SEC submission has no primary {filing_form} document")
    sequence, filename, content = sorted(candidates, key=lambda row: (row[0], row[1]))[0]
    raw = content.encode("latin-1")
    return {
        "sequence": sequence,
        "filename": filename,
        "content": raw,
        "content_sha256": _sha_bytes(raw),
    }


def drdocbench_inventory_from_tree(
    tree_entries: Sequence[Mapping[str, Any]], *, resolved_revision: str
) -> tuple[tuple[dict[str, Any], ...], dict[str, dict[str, str]]]:
    """Normalize a pinned HF tree without reading public ground-truth content."""

    if not re.fullmatch(r"[0-9a-f]{40}", resolved_revision):
        raise SourceAcquisitionRefused("Dr.DocBench resolved revision must be a 40-hex commit")
    by_path = {str(row.get("path") or ""): row for row in tree_entries}
    candidates: list[dict[str, Any]] = []
    evaluator_paths: dict[str, dict[str, str]] = {}
    for path, row in sorted(by_path.items()):
        match = DRDOC_IMAGE_RE.match(path)
        if match is None:
            continue
        lfs = row.get("lfs")
        oid = str(lfs.get("oid") or "") if isinstance(lfs, Mapping) else ""
        if oid.startswith("sha256:"):
            oid = oid.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", oid):
            raise SourceAcquisitionRefused(
                f"Dr.DocBench image lacks a transportable sha256 LFS oid: {path}"
            )
        subject = match.group("subject")
        document_uuid = match.group("document_uuid")
        page_number = int(match.group("page"))
        page_id = f"drdocbench:{document_uuid}:page-{page_number}"
        family_id = f"drdocbench:{document_uuid}"
        candidate = {
            "source_family": "drdocbench",
            "family_id": family_id,
            "document_id": document_uuid,
            "page_id": page_id,
            "source_locator": (
                f"https://huggingface.co/datasets/{DRDOC_REPO_ID}/resolve/"
                f"{resolved_revision}/{urllib.parse.quote(path, safe='/')}"
            ),
            "source_revision": resolved_revision,
            "source_sha256": "sha256:" + oid,
            "acquisition_identity": f"hf-dataset:{DRDOC_REPO_ID}@{resolved_revision}:{path}",
            "metadata": {"subject": subject, "page_number": page_number},
        }
        candidates.append(candidate)
        stem = f"page_{page_number}"
        base = f"dev/{subject}/{document_uuid}"
        json_path = f"{base}/json/{stem}.json"
        md_path = f"{base}/mds/{stem}.md"
        evaluator_paths[page_id] = {
            "json": json_path if json_path in by_path else "",
            "markdown": md_path if md_path in by_path else "",
        }
    return tuple(candidates), evaluator_paths


def build_source_manifest(
    *,
    contract: Mapping[str, Any],
    candidate_records: Sequence[Mapping[str, Any]],
    qualification: Mapping[str, str],
    source_revisions: Mapping[str, str],
) -> dict[str, Any]:
    if contract.get("source_contract_digest") != source_contract()["source_contract_digest"]:
        raise SourceAcquisitionRefused("source manifest contract differs from live predeclared terms")
    families = {str(row.get("source_family") or "") for row in candidate_records}
    if not families.issubset({"drdocbench", "sec"}):
        raise SourceAcquisitionRefused(f"source manifest contains unsupported primary family: {families}")
    if not candidate_records:
        raise SourceAcquisitionRefused("source manifest requires candidate pages")
    body = {
        "schema": SOURCE_MANIFEST_SCHEMA,
        "source_contract_digest": contract["source_contract_digest"],
        "qualification_attestation_digests": dict(qualification),
        "source_revisions": dict(sorted(source_revisions.items())),
        "candidate_count": len(candidate_records),
        "candidates": [dict(row) for row in candidate_records],
        "scientific_outcomes_observed_during_acquisition": False,
        "hidden_evaluator_content_in_runtime_manifest": False,
    }
    return {**body, "source_manifest_digest": _digest(body)}


def acquire_sec_index_inventory() -> tuple[SecFiling, ...]:
    """Qualification-gated SEC metadata acquisition; no filing body is fetched here."""

    require_qualified_pair()
    verify_source_contract()
    user_agent = _sec_user_agent()
    rows: list[SecFiling] = []
    for url in sec_master_index_urls():
        try:
            raw = _http_get(url, user_agent=user_agent)
        except urllib.error.HTTPError as exc:
            # Weekday indexes can be absent on US market/federal holidays. Missing
            # dates are not silently replaced; the final inventory records only
            # the exact files that were successfully present in the frozen range.
            if exc.code != 404:
                raise SourceAcquisitionRefused(
                    f"SEC master index request failed with HTTP {exc.code}: {url}"
                ) from exc
            time.sleep(SEC_MIN_INTERVAL_SECONDS)
            continue
        except (OSError, TimeoutError) as exc:
            raise SourceAcquisitionRefused(
                f"SEC master index transport failed: {type(exc).__name__}"
            ) from exc
        rows.extend(parse_sec_master_index(raw.decode("latin-1")))
        time.sleep(SEC_MIN_INTERVAL_SECONDS)
    return preselect_sec_filings(rows)


def plan() -> dict[str, Any]:
    contract = source_contract()
    return {
        "schema": "tavonel.recovery.fresh_source_acquisition_plan.v1",
        "source_contract_digest": contract["source_contract_digest"],
        "primary_family_quotas": dict(STAGE1_FAMILY_QUOTAS),
        "network_acquisition_currently_authorized": (
            PRIMARY_ATTESTATION.is_file() and STRONG_ATTESTATION.is_file()
        ),
        "fresh_source_bytes_read": False,
        "sec_declared_user_agent_required": True,
        "sec_master_index_url_count": len(sec_master_index_urls()),
        "sec_renderer_required_before_page_candidates": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    sub.add_parser("seal-contract")
    sub.add_parser("verify-contract")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = plan()
        elif args.command == "seal-contract":
            value = seal_source_contract()
        else:
            value = verify_source_contract()
    except SourceAcquisitionRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())