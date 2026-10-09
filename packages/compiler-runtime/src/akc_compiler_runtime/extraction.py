"""Reading real files off disk and extracting rule-based claims from them.

This is the Personal E2E spine's ingest layer: it walks a source directory the
way the desktop watcher's roots do, hashes every file it will own, and parses
markdown plus code into candidate claims with nothing smarter than rules --
headers, dates and status lines. The masterplan is explicit that this layer
must stay boring: every downstream judgement (identity, dependency, authority)
is only as honest as the units it is fed.

Two invariants shape the output:

* **Determinism.** The same bytes always produce the same claims, anchors,
  evidence ids and structural paths, on any machine, in any run. Selective
  recompilation is only provable against a full rebuild when parsing twice
  cannot disagree.
* **Nothing invented.** A date the document never states is not stored as one
  (§8.1): validity stays ``None`` with ``temporal_source="unknown"`` rather
  than being filled with today's date.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from akc_cir.identity import (
    document_version_id,
    evidence_id,
    logical_id_seed,
    normalize_text_for_identity,
    source_id,
)

__all__ = [
    "UNMAPPED_ACL",
    "AuthorityClass",
    "ClaimDraft",
    "ParsedDocument",
    "ParsedFile",
    "SourceStatus",
    "TemporalSource",
    "parse_file",
    "parse_workspace",
    "scan_source_files",
]

MARKDOWN_SUFFIXES = {".md", ".markdown"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx"}
SCAN_SUFFIXES = MARKDOWN_SUFFIXES | CODE_SUFFIXES
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".obsidian", "dist", "build"}

# Bump when extraction rules, draft schema or source/version identity change.
PARSER_CACHE_VERSION = 1

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_MONTH_NAME = "|".join(_MONTHS)
#: Grouped so the month alternation cannot swallow following quantifiers
#: (bare ``a|b`` before ``\\s+\\d`` would bind the tail to ``b`` only).
_MONTH_TOKEN = rf"(?:{_MONTH_NAME})"
#: "October 15", "October 15, 2026", "15 October 2026", "2026-10-15".
_DATE_PATTERNS = (
    re.compile(rf"\b({_MONTH_TOKEN})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE),
    re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_TOKEN})\s*(\d{{4}})?\b", re.IGNORECASE),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
)
_EFFECTIVE_RE = re.compile(
    rf"\beffective\s+(?:date\s+)?(?:on\s+)?({_MONTH_TOKEN}\s+\d{{1,2}}(?:,?\s+\d{{4}})?|\d{{4}}-\d{{2}}-\d{{2}})\b",
    re.IGNORECASE,
)
_UNTIL_RE = re.compile(
    rf"\buntil\s+({_MONTH_TOKEN}\s+\d{{1,2}}(?:,?\s+\d{{4}})?|\d{{4}}-\d{{2}}-\d{{2}})\b",
    re.IGNORECASE,
)
_SUPERSEDED_BY_RE = re.compile(r"\bsuperseded\s+by\b", re.IGNORECASE)
_SUPERSEDES_RE = re.compile(r"\bsupersedes\b", re.IGNORECASE)
_STATUS_LINE_RE = re.compile(r"^\s*(?:status|state)\s*:\s*(\w[\w -]*)$", re.IGNORECASE)
_AUTHORITY_LINE_RE = re.compile(r"^\s*authority\s*:\s*(\w+)\s*$", re.IGNORECASE)
_DATE_LINE_RE = re.compile(r"^\s*(?:date|recorded)\s*:\s*(\S.*)$", re.IGNORECASE)
_DEPENDS_RE = re.compile(r"^\s*(?:[-*]\s*)?depends\s+on\s*:\s*(\S[^\n]*)$", re.IGNORECASE)
_DERIVED_RE = re.compile(r"^\s*(?:[-*]\s*)?derived\s+from\s*:\s*(\S[^\n]*)$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.DOTALL)
#: The one ACL line the runtime maps, spelled exactly, at column 0.
_REQUIRED_PERMISSION_LINE_RE = re.compile(r"required_permission:[ \t]+(\S.*?)[ \t]*")
#: Exactly one permission token.
_PERMISSION_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
#: Substrings that make a front-matter line access-control-ish. Matched on
#: NFKC-casefolded text, so camelCase, kebab and fullwidth spellings all hit.
#: Deliberately broad: a false hit only hides a document (fail closed).
_ACL_TOKEN_RE = re.compile(
    r"permission|acl|access|visib|allow|role|group|reader|share|sharing|privat"
    r"|restrict|confidential|classif|sensitiv"
)
#: A front-matter line starting with any of these can carry a mapping key a
#: line regex cannot read: quoted keys (escapes like ``\x72`` hide the name),
#: flow collections, ``?`` complex keys, anchors, aliases, tags, ``<<`` merges.
_YAML_KEY_SYNTAX = tuple("\"'{[?&*!<")
#: Unquoted scalars YAML reads as null, boolean or number, not as a string.
#: ``required_permission: null`` is ambiguous intent, so it fails closed.
_YAML_NON_STRING_RE = re.compile(
    r"(?i:null|~|true|false|yes|no|on|off|y|n)|[-+.]?[0-9][0-9_.:eE+-]*"
)
#: A ``required_permission`` declaration in any spelling, on a casefolded
#: line. Outside the one mapped front-matter line it is never ignored.
_STRAY_DECLARATION_RE = re.compile(r"[\W_]*required[\W_]*permissions?[\W_]*[:=]")

#: Fail-closed permission for a source whose ACL was declared but cannot be
#: mapped. ``_PERMISSION_TOKEN_RE`` can never produce it, and the pipeline
#: strips it from every caller's permissions, so nobody is ever granted it.
UNMAPPED_ACL = "!acl-unmapped"

_MD_COMMENT_RE = re.compile(r"<!--\s*(.*?)\s*-->", re.DOTALL)
_PY_COMMENT_RE = re.compile(r"^\s*#\s?(.*)$")
_C_COMMENT_RE = re.compile(r"^\s*(?://|/?\*|<!--)\s?(.*?)(?:\*/|-->)?\s*$")
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)|^\s*class\s+(\w+)|^\s*function\s+(\w+)")

_CLAIM_VERB_RE = re.compile(
    r"\b(is|are|shall|will|must|requires?|covers?|applies|effective|launch"
    r"|deadline|schedule[sd]?|ships?|freeze[n]?|decided|approved|gate)\b",
    re.IGNORECASE,
)


class AuthorityClass(StrEnum):
    """Folder-default authority for a personal workspace, lowest first."""

    DRAFT = "DRAFT"
    INFORMAL = "INFORMAL"
    DEPARTMENTAL = "DEPARTMENTAL"
    OFFICIAL = "OFFICIAL"
    CONTRACTUAL = "CONTRACTUAL"
    REGULATORY = "REGULATORY"


class SourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class TemporalSource(StrEnum):
    EXPLICIT = "explicit"
    UNKNOWN = "unknown"


#: Maps an ``Authority:`` line or folder name onto an AuthorityClass value.
_AUTHORITY_ALIASES: dict[str, AuthorityClass] = {
    "draft": AuthorityClass.DRAFT,
    "informal": AuthorityClass.INFORMAL,
    "note": AuthorityClass.INFORMAL,
    "departmental": AuthorityClass.DEPARTMENTAL,
    "spec": AuthorityClass.DEPARTMENTAL,
    "official": AuthorityClass.OFFICIAL,
    "policy": AuthorityClass.OFFICIAL,
    "contractual": AuthorityClass.CONTRACTUAL,
    "contract": AuthorityClass.CONTRACTUAL,
    "regulatory": AuthorityClass.REGULATORY,
}

_FOLDER_AUTHORITY: dict[str, AuthorityClass] = {
    "contracts": AuthorityClass.CONTRACTUAL,
    "policies": AuthorityClass.OFFICIAL,
    "specs": AuthorityClass.DEPARTMENTAL,
    "projects": AuthorityClass.DEPARTMENTAL,
    "meetings": AuthorityClass.INFORMAL,
    "notes": AuthorityClass.INFORMAL,
}


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """One real file on disk, hashed. This is the unit the cursor tracks."""

    rel_path: str  # posix-style, relative to the source root
    sha256: str  # lowercase hex of the file bytes
    text: str


@dataclass(frozen=True, slots=True)
class ClaimDraft:
    """One rule-extracted claim line, before identity is resolved.

    ``anchor`` is the claim's own normalized text: it is what the blocking
    index buckets on and what survives a file rename unchanged.
    """

    anchor: str
    text: str
    subject: str
    section_path: tuple[str, ...]  # heading path inside the document
    line_number: int  # 1-based line in the file
    kind: str  # fact | status | date | dependency
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    recorded_at: datetime | None = None
    temporal_source: TemporalSource = TemporalSource.UNKNOWN
    source_status: SourceStatus = SourceStatus.ACTIVE
    scope: dict[str, str] = field(default_factory=dict)
    depends_on_refs: tuple[str, ...] = ()
    derived_from_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Everything one parsed file contributes to the compile."""

    file: ParsedFile
    source: str  # akc_cir source id (tenant + connector + canonical path)
    document_version: str  # dv_ id keyed on content hash
    authority: AuthorityClass
    claims: tuple[ClaimDraft, ...]
    #: The source's declared access requirement: one permission token,
    #: :data:`UNMAPPED_ACL` when an ACL was declared but cannot be mapped, or
    #: ``None`` when the source declares none.
    required_permission: str | None = None


def scan_source_files(root: Path) -> list[ParsedFile]:
    """Walk ``root`` deterministically and hash every file we would compile."""
    files: list[ParsedFile] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.casefold() not in SCAN_SUFFIXES:
            continue
        raw = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        files.append(
            ParsedFile(
                rel_path=rel,
                sha256=hashlib.sha256(raw).hexdigest(),
                text=raw.decode("utf-8"),
            )
        )
    return files


def parse_workspace(source_dir: Path, *, tenant_id: str = "personal") -> list[ParsedDocument]:
    """Parse every scannable file under ``source_dir``, sorted by rel path."""
    return [
        parse_file(parsed_file, tenant_id=tenant_id, connector_type="filesystem")
        for parsed_file in scan_source_files(source_dir)
    ]


def parsed_document_record(document: ParsedDocument) -> dict[str, object]:
    """Deterministic parser output, excluding the freshly scanned source text."""
    claims = []
    for draft in document.claims:
        row = asdict(draft)
        for name in ("valid_from", "valid_to", "recorded_at"):
            moment = row[name]
            row[name] = moment.isoformat() if moment is not None else None
        for name in ("section_path", "depends_on_refs", "derived_from_refs"):
            row[name] = list(row[name])
        claims.append(row)
    return {
        "rel_path": document.file.rel_path,
        "sha256": document.file.sha256,
        "source": document.source,
        "document_version": document.document_version,
        "authority": document.authority.value,
        "required_permission": document.required_permission,
        "claims": claims,
    }


def parsed_document_from_record(
    record: object, file: ParsedFile, *, tenant_id: str
) -> ParsedDocument:
    """Decode a sealed output and attach current file metadata; reject bad shapes."""
    if not isinstance(record, dict):
        raise ValueError("invalid parsed document")
    src = source_id(tenant_id=tenant_id, connector_type="filesystem", native_id=file.rel_path)
    version = document_version_id(source=src, content_sha256=f"sha256:{file.sha256}")
    if (
        record.get("rel_path") != file.rel_path
        or record.get("sha256") != file.sha256
        or record.get("source") != src
        or record.get("document_version") != version
    ):
        raise ValueError("parsed document binding mismatch")
    permission = record["required_permission"]
    if permission is not None and not isinstance(permission, str):
        raise ValueError("invalid cached permission")
    raw_claims = record["claims"]
    if not isinstance(raw_claims, list):
        raise ValueError("invalid cached claims")
    claims = []
    for raw in raw_claims:
        if not isinstance(raw, dict):
            raise ValueError("invalid cached claim")
        row = dict(raw)
        for name in ("anchor", "text", "subject", "kind"):
            if not isinstance(row[name], str):
                raise ValueError("invalid cached string")
        if type(row["line_number"]) is not int or row["line_number"] < 1:
            raise ValueError("invalid cached line")
        for name in ("section_path", "depends_on_refs", "derived_from_refs"):
            values = row[name]
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError("invalid cached path or references")
            row[name] = tuple(values)
        scope = row["scope"]
        if not isinstance(scope, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in scope.items()
        ):
            raise ValueError("invalid cached scope")
        for name in ("valid_from", "valid_to", "recorded_at"):
            moment = row[name]
            if moment is not None and not isinstance(moment, str):
                raise ValueError("invalid cached time")
            row[name] = datetime.fromisoformat(moment) if moment is not None else None
        row["temporal_source"] = TemporalSource(row["temporal_source"])
        row["source_status"] = SourceStatus(row["source_status"])
        claims.append(ClaimDraft(**row))
    document = ParsedDocument(
        file=file,
        source=src,
        document_version=version,
        authority=AuthorityClass(record["authority"]),
        claims=tuple(claims),
        required_permission=permission,
    )
    if parsed_document_record(document) != record:
        raise ValueError("noncanonical parsed document")
    return document


def parse_file(
    file: ParsedFile, *, tenant_id: str, connector_type: str = "filesystem"
) -> ParsedDocument:
    """Parse one file into a document with its rule-extracted claims."""
    src = source_id(tenant_id=tenant_id, connector_type=connector_type, native_id=file.rel_path)
    version = document_version_id(source=src, content_sha256=f"sha256:{file.sha256}")
    suffix = Path(file.rel_path).suffix.casefold()
    lines = _strip_frontmatter(file.text).splitlines()
    doc_authority = _folder_authority(file.rel_path)

    drafts: list[ClaimDraft] = []
    if suffix in MARKDOWN_SUFFIXES:
        md_claims, doc_authority = _parse_markdown(lines, file.rel_path, doc_authority)
        drafts.extend(md_claims)
    else:
        drafts.extend(_parse_code(lines, file.rel_path, doc_authority))

    return ParsedDocument(
        file=file,
        source=src,
        document_version=version,
        authority=doc_authority,
        claims=tuple(drafts),
        required_permission=source_required_permission(file.text),
    )


# ---------------------------------------------------------------------------
# markdown / code parsing
# ---------------------------------------------------------------------------


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def source_required_permission(text: str) -> str | None:
    """The access requirement a source declares in its front matter.

    This is a line scanner, not a YAML parser, so it maps only what it can
    read for certain and refuses everything else. A leading BOM is dropped and
    CRLF, CR, NEL, LS and PS (YAML 1.1 line breaks) become LF first. In a
    standard block -- exactly ``---`` on the very first line, closed by a
    ``---`` line -- exactly one literal ``required_permission: <token>`` line
    maps; :data:`UNMAPPED_ACL` results when any other line starts with YAML
    key syntax, any other line carries an ACL-ish token, the line repeats, or
    its value is not one token. Any other front-matter shape (``+++`` TOML,
    ``{`` JSON, ``---`` after blank lines, an opener like ``--- # fm`` or
    ``--- !tag``, or unterminated) is not parsed: it is :data:`UNMAPPED_ACL`
    if it carries an ACL-ish token anywhere, else public. A ``required_permission``
    declaration anywhere else in the file (the body, a code comment) is
    :data:`UNMAPPED_ACL` too. Never ``None`` for a declared ACL.

    Limits: ``required_permission`` is the only ACL contract. Vocabulary that
    is not in ``_ACL_TOKEN_RE`` (``permitted_users``, ``audience``, ...) is
    not recognised and stays public. An unquoted null, boolean or number value
    is :data:`UNMAPPED_ACL`; quoted (``"null"``) it is that literal permission.
    """
    text = text.removeprefix("\ufeff")
    for line_break in ("\r\n", "\r", "\x85", "\u2028", "\u2029"):
        text = text.replace(line_break, "\n")
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), len(lines))
    opener = lines[first].strip() if first < len(lines) else ""
    if opener.startswith("{"):
        closer = "}"
    elif opener.startswith(("---", "+++")):
        closer = opener[:3]  # "--- # fm", "--- !tag": a block, just not standard
    else:
        return UNMAPPED_ACL if _declares(lines) else None
    end = next((i for i in range(first + 1, len(lines)) if lines[i].rstrip() == closer), None)
    if end is None:
        # Unterminated: the whole file is the unparsed block.
        return UNMAPPED_ACL if any(_acl_ish(line) for line in lines) else None
    if _declares(lines[end + 1 :]):
        return UNMAPPED_ACL

    if opener != "---" or first != 0:
        return UNMAPPED_ACL if any(_acl_ish(line) for line in lines[first : end + 1]) else None

    declared: list[str] = []
    for line in lines[1:end]:
        exact = _REQUIRED_PERMISSION_LINE_RE.fullmatch(line)
        if exact is not None:
            declared.append(exact.group(1))
            continue
        body = line.strip()
        if body.startswith(_YAML_KEY_SYNTAX) or "<<" in body or _acl_ish(line):
            return UNMAPPED_ACL
    if not declared:
        return None
    if len(declared) != 1:
        return UNMAPPED_ACL
    value = declared[0]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    elif _YAML_NON_STRING_RE.fullmatch(value):
        return UNMAPPED_ACL
    return value if _PERMISSION_TOKEN_RE.fullmatch(value) else UNMAPPED_ACL


def _fold(line: str) -> str:
    """NFKC + casefold, minus invisible format characters (zero-width etc.)."""
    folded = unicodedata.normalize("NFKC", line).casefold()
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


def _acl_ish(line: str) -> bool:
    return _ACL_TOKEN_RE.search(_fold(line)) is not None


def _declares(lines: list[str]) -> bool:
    return any(_STRAY_DECLARATION_RE.match(_fold(line)) for line in lines)


def _folder_authority(rel_path: str) -> AuthorityClass:
    top = rel_path.replace("\\", "/").split("/", 1)[0].casefold()
    return _FOLDER_AUTHORITY.get(top, AuthorityClass.INFORMAL)


def _authority_from_word(word: str) -> AuthorityClass | None:
    return _AUTHORITY_ALIASES.get(word.strip().casefold())


def _parse_date(token: str) -> datetime | None:
    token = token.strip().rstrip(".,;")
    for pattern in _DATE_PATTERNS:
        match = pattern.fullmatch(token) or pattern.search(token)
        if match is None:
            continue
        groups = match.groups()
        try:
            if pattern is _DATE_PATTERNS[0]:
                month = _MONTHS[groups[0].casefold()]
                day = int(groups[1])
                year = int(groups[2]) if groups[2] else 2026
                return _midnight(year, month, day)
            if pattern is _DATE_PATTERNS[1]:
                day = int(groups[0])
                month = _MONTHS[groups[1].casefold()]
                year = int(groups[2]) if groups[2] else 2026
                return _midnight(year, month, day)
            return _midnight(int(groups[0]), int(groups[1]), int(groups[2]))
        except (KeyError, ValueError):
            continue
    return None


def _midnight(year: int, month: int, day: int) -> datetime:
    return datetime.combine(date(year, month, day), datetime.min.time(), tzinfo=UTC)


def _first_date(text: str) -> datetime | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = _parse_date(match.group(0))
            if parsed is not None:
                return parsed
    return None


def _parse_markdown(
    lines: list[str], rel_path: str, doc_authority: AuthorityClass
) -> tuple[list[ClaimDraft], AuthorityClass]:
    """Header/date/status rules over markdown lines.

    A line becomes a claim when it states something with a verb, carries a
    date, or declares status/dependency. Headings build the structural path;
    they are context, never claims themselves. Returns the claims plus the
    document's effective authority: an ``Authority:`` line overrides the
    folder default, and a ``Status: Draft`` line downgrades the whole
    document.
    """
    claims: list[ClaimDraft] = []
    headings: list[str] = []
    explicit_authority: AuthorityClass | None = None
    draft_status = False
    doc_recorded_at: datetime | None = None

    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        if not line.strip():
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            headings = headings[: level - 1]
            headings.append(title)
            continue

        authority_match = _AUTHORITY_LINE_RE.match(line)
        if authority_match:
            explicit_authority = _authority_from_word(authority_match.group(1))
            continue
        date_line = _DATE_LINE_RE.match(line)
        if date_line:
            parsed = _parse_date(date_line.group(1))
            if parsed is not None:
                doc_recorded_at = parsed
            continue

        body = _BULLET_RE.sub(r"\1", line).strip()
        status_line = _STATUS_LINE_RE.match(body)
        effective_from = None
        valid_to = None
        temporal_source = TemporalSource.UNKNOWN
        source_status = SourceStatus.ACTIVE
        kind = "fact"

        effective = _EFFECTIVE_RE.search(body)
        if effective:
            effective_from = _parse_date(effective.group(1))
            if effective_from is not None:
                temporal_source = TemporalSource.EXPLICIT
        until = _UNTIL_RE.search(body)
        if until:
            valid_to = _parse_date(until.group(1))
            if valid_to is not None and temporal_source is TemporalSource.UNKNOWN:
                temporal_source = TemporalSource.EXPLICIT

        if _SUPERSEDED_BY_RE.search(body):
            source_status = SourceStatus.SUPERSEDED
            kind = "status"
        elif _SUPERSEDES_RE.search(body):
            kind = "status"

        depends = _DEPENDS_RE.search(body)
        derived = _DERIVED_RE.search(body)
        depends_refs: tuple[str, ...] = ()
        derived_from_refs: tuple[str, ...] = ()
        if depends and "depends on" in body.casefold():
            depends_refs = (_clean_ref(depends.group(1)),)
            kind = "dependency"
        if derived and "derived from" in body.casefold():
            derived_from_refs = (_clean_ref(derived.group(1)),)
            kind = "dependency"

        has_date = _first_date(body) is not None
        states_something = bool(status_line) or bool(_CLAIM_VERB_RE.search(body))
        # Dependency statements are always claims: they are the graph's edges,
        # and an edge nobody recorded cannot propagate impact.
        if not (has_date or states_something or depends_refs or derived_from_refs):
            continue

        if status_line and status_line.group(1).strip().casefold() == "draft":
            draft_status = True
            kind = "status"

        subject = _subject_from(headings, rel_path)
        claims.append(
            ClaimDraft(
                anchor=normalize_text_for_identity(body),
                text=body,
                subject=subject,
                section_path=_section_path(rel_path, headings),
                line_number=index + 1,
                kind=kind,
                valid_from=effective_from,
                valid_to=valid_to,
                recorded_at=doc_recorded_at,
                temporal_source=temporal_source,
                source_status=source_status,
                depends_on_refs=depends_refs,
                derived_from_refs=derived_from_refs,
            )
        )
    effective_authority = (
        AuthorityClass.DRAFT if draft_status else (explicit_authority or doc_authority)
    )
    return claims, effective_authority


def _parse_code(lines: list[str], rel_path: str, doc_authority: AuthorityClass) -> list[ClaimDraft]:
    """Rule extraction over code comments: dates, deadlines and status words."""
    claims: list[ClaimDraft] = []
    section = Path(rel_path).stem
    comment_re = _PY_COMMENT_RE if rel_path.endswith(".py") else _C_COMMENT_RE
    for index, raw_line in enumerate(lines):
        match = comment_re.match(raw_line)
        if not match:
            def_match = _DEF_RE.match(raw_line)
            if def_match:
                section = next(group for group in def_match.groups() if group)
            continue
        body = match.group(1).strip()
        if not body or len(body) < 12:
            continue
        has_date = _first_date(body) is not None
        states_something = bool(_CLAIM_VERB_RE.search(body))
        if not (has_date or states_something):
            continue
        effective = _EFFECTIVE_RE.search(body)
        valid_from = _parse_date(effective.group(1)) if effective else None
        superseded = bool(_SUPERSEDED_BY_RE.search(body))
        claims.append(
            ClaimDraft(
                anchor=normalize_text_for_identity(body),
                text=body,
                subject=_subject_from([section], rel_path),
                section_path=_section_path(rel_path, [section]),
                line_number=index + 1,
                kind="status" if superseded else "fact",
                valid_from=valid_from,
                temporal_source=TemporalSource.EXPLICIT if valid_from else TemporalSource.UNKNOWN,
                source_status=SourceStatus.SUPERSEDED if superseded else SourceStatus.ACTIVE,
            )
        )
    _ = doc_authority
    return claims


def _clean_ref(ref: str) -> str:
    """Normalize a dependency reference to a workspace-relative posix path.

    Strips trailing prose after an em/en dash or double hyphen, trailing
    parentheticals, anchors and punctuation, so that
    ``policies/launch-governance.md — readiness gate`` resolves.
    """
    ref = ref.strip().rstrip(".;,")
    ref = re.split(r"\s+(?:\u2014|\u2013|--|-)\s+", ref)[0].strip()
    ref = re.sub(r"\s*\(.*\)\s*$", "", ref).strip()
    if "#" in ref:
        ref = ref.split("#", 1)[0]
    return ref.replace("\\", "/")


def _subject_from(headings: list[str], rel_path: str) -> str:
    if headings:
        title = headings[-1].strip().casefold()
        title = re.sub(r"^[\d.\s]+", "", title)
        return normalize_text_for_identity(title) or Path(rel_path).stem.casefold()
    return Path(rel_path).stem.casefold()


def _section_path(rel_path: str, headings: list[str]) -> tuple[str, ...]:
    parts = rel_path.replace("\\", "/").split("/")
    folder_parts = parts[:-1]
    normalized = tuple(normalize_text_for_identity(part) for part in (*folder_parts, *headings))
    return normalized


# ---------------------------------------------------------------------------
# seed ids + evidence (used by pipeline once identities are known)
# ---------------------------------------------------------------------------


def seed_logical_id(*, source: str, draft: ClaimDraft) -> str:
    """The id this claim gets when nothing prior matches it.

    Seeded from the source and its structural path -- deliberately *not* from
    the content -- so rewording a sentence does not silently fork its history,
    while moving it between sections does change where it lives.
    """
    return logical_id_seed(source=source, document_path=draft.section_path, anchor=draft.anchor)


def anchored_evidence_id(*, document_version: str, text: str, line_number: int) -> str:
    """Evidence for a claim line: the line (as page) plus its span text.

    Files have no bounding boxes, so the anchor is the span itself plus the
    1-based line it sits on -- enough to distinguish claims and to show
    movement when a claim shifts lines between versions.
    """
    return evidence_id(
        document_version=document_version,
        page_number1=max(1, min(line_number, 10000)),
        span_text=text,
    )
