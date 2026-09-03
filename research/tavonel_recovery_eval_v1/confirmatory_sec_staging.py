#!/usr/bin/env python3
"""Fail-closed SEC filing staging for the TAVONEL-R confirmatory corpus.

This module does not contact SEC. It turns already acquired complete-submission
bytes plus explicitly acquired archive assets into a local render bundle. The
bundle is accepted only when every local asset referenced by the primary filing
HTML is present and hash-bound. External/non-SEC resources are never silently
loaded by the renderer.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from confirmatory_source_acquisition import SecFiling, SourceAcquisitionRefused


BUNDLE_SCHEMA = "tavonel.recovery.sec_render_bundle.v1"
_DOCUMENT_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)
_TEXT_RE = re.compile(r"<TEXT>(.*)</TEXT>", re.IGNORECASE | re.DOTALL)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


class SecStagingRefused(SourceAcquisitionRefused):
    pass


def _sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{re.escape(name)}>\s*([^\r\n<]+)", block, re.IGNORECASE)
    return "" if match is None else match.group(1).strip()


def _safe_relative_asset(value: str) -> str | None:
    raw = value.strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.casefold().startswith(("data:", "mailto:", "javascript:", "about:")):
        return None
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raise SecStagingRefused(f"external asset reference is forbidden: {raw[:120]}")
    path = urllib.parse.unquote(parsed.path).replace("\\", "/")
    normalized = posixpath.normpath(path)
    if normalized in {"", "."}:
        return None
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        raise SecStagingRefused(f"unsafe SEC asset path: {raw[:120]}")
    return pure.as_posix()


@dataclass(frozen=True, slots=True)
class SubmissionDocument:
    sequence: int
    document_type: str
    filename: str
    description: str
    content: bytes

    @property
    def sha256(self) -> str:
        return _sha_bytes(self.content)


def parse_submission_documents(submission: bytes) -> tuple[SubmissionDocument, ...]:
    text = submission.decode("latin-1")
    result: list[SubmissionDocument] = []
    names: set[str] = set()
    for block in _DOCUMENT_RE.findall(text):
        filename = _tag(block, "FILENAME")
        document_type = _tag(block, "TYPE")
        if not filename or not document_type:
            continue
        safe = _safe_relative_asset(filename)
        if safe is None:
            raise SecStagingRefused("SEC document filename is empty after normalization")
        if safe in names:
            raise SecStagingRefused(f"duplicate SEC document filename: {safe}")
        names.add(safe)
        match = _TEXT_RE.search(block)
        if match is None:
            continue
        sequence_raw = _tag(block, "SEQUENCE")
        try:
            sequence = int(sequence_raw)
        except ValueError:
            sequence = 2**31 - 1
        result.append(
            SubmissionDocument(
                sequence=sequence,
                document_type=document_type,
                filename=safe,
                description=_tag(block, "DESCRIPTION"),
                content=match.group(1).encode("latin-1"),
            )
        )
    if not result:
        raise SecStagingRefused("complete submission contains no stageable documents")
    return tuple(sorted(result, key=lambda row: (row.sequence, row.filename)))


def primary_document(
    documents: Sequence[SubmissionDocument], filing_form: str
) -> SubmissionDocument:
    candidates = [row for row in documents if row.document_type == filing_form]
    if not candidates:
        raise SecStagingRefused(f"complete submission contains no exact {filing_form} document")
    return sorted(candidates, key=lambda row: (row.sequence, row.filename))[0]


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): (value or "") for key, value in attrs}
        folded = tag.casefold()
        if folded in {"img", "source", "input", "video", "audio", "script", "iframe"}:
            if values.get("src"):
                self.references.append(values["src"])
        if folded == "link" and "stylesheet" in values.get("rel", "").casefold():
            if values.get("href"):
                self.references.append(values["href"])
        style = values.get("style")
        if style:
            self.references.extend(match.group(2) for match in _CSS_URL_RE.finditer(style))
        srcset = values.get("srcset")
        if srcset:
            for item in srcset.split(","):
                candidate = item.strip().split()[0] if item.strip() else ""
                if candidate:
                    self.references.append(candidate)

    def handle_data(self, data: str) -> None:
        # CSS inside <style> is also visible as data. Scanning all text is safe:
        # only url(...) patterns are considered and later path validation applies.
        self.references.extend(match.group(2) for match in _CSS_URL_RE.finditer(data))


def required_local_assets(primary_html: bytes) -> tuple[str, ...]:
    try:
        text = primary_html.decode("utf-8")
    except UnicodeDecodeError:
        text = primary_html.decode("latin-1")
    parser = _AssetParser()
    parser.feed(text)
    assets: set[str] = set()
    for value in parser.references:
        normalized = _safe_relative_asset(value)
        if normalized is not None:
            assets.add(normalized)
    return tuple(sorted(assets))


def archive_base_url(filing: SecFiling) -> str:
    path = PurePosixPath(filing.archive_filename)
    if len(path.parts) < 4 or path.parts[0:2] != ("edgar", "data"):
        raise SecStagingRefused("SEC master-index archive filename shape is invalid")
    accession = path.stem.replace("-", "")
    if not accession.isdigit():
        raise SecStagingRefused("SEC accession in archive filename is invalid")
    cik = path.parts[2]
    if not cik.isdigit():
        raise SecStagingRefused("SEC CIK in archive filename is invalid")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"


def archive_asset_url(filing: SecFiling, relative_asset: str) -> str:
    safe = _safe_relative_asset(relative_asset)
    if safe is None:
        raise SecStagingRefused("SEC archive asset path is empty")
    return archive_base_url(filing) + urllib.parse.quote(safe, safe="/")


def build_render_bundle(
    *,
    filing: SecFiling,
    submission: bytes,
    acquired_assets: Mapping[str, bytes],
    output_dir: Path,
) -> dict[str, Any]:
    # Immutable bundle creation is a prerequisite, not a late write-time
    # detail. Refuse an existing destination before parsing or completeness
    # work so retries cannot be mistaken for a fresh scientific artifact.
    if output_dir.exists():
        raise SecStagingRefused("SEC render bundle output directory already exists")
    documents = parse_submission_documents(submission)
    primary = primary_document(documents, filing.form)
    required = required_local_assets(primary.content)
    normalized_assets: dict[str, bytes] = {}
    for raw_name, content in acquired_assets.items():
        safe = _safe_relative_asset(str(raw_name))
        if safe is None:
            continue
        if safe in normalized_assets:
            raise SecStagingRefused(f"duplicate acquired SEC asset: {safe}")
        normalized_assets[safe] = bytes(content)
    embedded = {row.filename: row.content for row in documents}
    missing = [name for name in required if name not in normalized_assets and name not in embedded]
    if missing:
        raise SecStagingRefused(
            "SEC render bundle is missing required local assets: " + ", ".join(missing[:8])
        )
    output_dir.mkdir(parents=True)
    complete = output_dir / "complete-submission.txt"
    complete.write_bytes(submission)
    staged: dict[str, str] = {}

    def write_relative(name: str, content: bytes) -> None:
        path = output_dir / Path(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SecStagingRefused(f"SEC render bundle path collision: {name}")
        path.write_bytes(content)
        staged[name] = _sha_bytes(content)

    write_relative(primary.filename, primary.content)
    for name in required:
        if name == primary.filename:
            continue
        content = normalized_assets.get(name, embedded.get(name))
        if content is None:  # defended above; keep fail-closed if code changes.
            raise SecStagingRefused(f"SEC render asset disappeared during staging: {name}")
        write_relative(name, content)

    body = {
        "schema": BUNDLE_SCHEMA,
        "filing_stable_id": filing.stable_id,
        "form": filing.form,
        "archive_filename": filing.archive_filename,
        "complete_submission_sha256": _sha_bytes(submission),
        "primary_filename": primary.filename,
        "primary_sha256": primary.sha256,
        "required_local_assets": list(required),
        "staged_file_sha256": dict(sorted(staged.items())),
        "external_assets_permitted": False,
        "missing_required_assets": [],
    }
    report = {**body, "render_bundle_digest": _digest(body)}
    (output_dir / "render-bundle.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return report


__all__ = [
    "BUNDLE_SCHEMA",
    "SecStagingRefused",
    "SubmissionDocument",
    "archive_asset_url",
    "archive_base_url",
    "build_render_bundle",
    "parse_submission_documents",
    "primary_document",
    "required_local_assets",
]