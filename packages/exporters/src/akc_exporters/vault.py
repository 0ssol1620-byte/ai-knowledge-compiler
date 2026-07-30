"""Obsidian Vault assembly and explicit conflict-safe merge plans."""

from __future__ import annotations

import json
import posixpath
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import unquote

import yaml
from akc_cir import (
    CanonicalDocument,
    ContractModel,
    KnowledgeBundle,
    KnowledgeNote,
    NoteType,
    QualityReport,
    ReviewStatus,
    sha256_digest,
)
from akc_security import ensure_portable_markdown_safe, safe_relative_path

from .filenames import (
    collision_key,
    portable_slug,
    stable_markdown_filename,
    with_collision_suffix,
)
from .markdown import MarkdownArtifact, source_map_json

_SOURCE_HASH = re.compile(r"^source_sha256:\s*[\"']?([^\"'\s]+)", re.MULTILINE)
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
_WIKILINK = re.compile(r"\[\[([^|\]]+)(?:\|[^\]]*)?]]")
_EXTERNAL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_MANAGED_START = re.compile(
    r"^<!-- AKC:managed:start hash=(sha256:[0-9a-f]{64}) -->\n",
    re.MULTILINE,
)
_MANAGED_END = re.compile(r"^<!-- AKC:managed:end -->$", re.MULTILINE)
_NOTE_FOLDERS = {
    NoteType.CONCEPT: "20-Concepts",
    NoteType.PERSON: "30-People",
    NoteType.ORGANIZATION: "40-Organizations",
    NoteType.PROJECT: "50-Projects",
    NoteType.GLOSSARY: "60-Glossary",
}
_MOC_FILES = {
    NoteType.CONCEPT: "00-Home/Concepts-MOC.md",
    NoteType.PERSON: "00-Home/People-MOC.md",
    NoteType.ORGANIZATION: "00-Home/Organizations-MOC.md",
    NoteType.PROJECT: "00-Home/Projects-MOC.md",
    NoteType.GLOSSARY: "00-Home/Glossary-MOC.md",
}
_MOC_TITLES = {
    NoteType.CONCEPT: "Concepts",
    NoteType.PERSON: "People",
    NoteType.ORGANIZATION: "Organizations",
    NoteType.PROJECT: "Projects",
    NoteType.GLOSSARY: "Glossary",
}


class MergePolicy(StrEnum):
    ERROR = "error"
    KEEP_EXISTING = "keep_existing"
    RENAME_INCOMING = "rename_incoming"
    REPLACE_SAME_SOURCE = "replace_same_source"
    UPDATE_MANAGED = "update_managed"


class VaultConflict(ContractModel):
    existing_path: str
    incoming_path: str
    reason: str
    resolution: str | None = None
    resolved_path: str | None = None


class BrokenVaultLink(ContractModel):
    source_path: str
    target: str
    resolved_path: str | None = None
    reason: str


class VaultMergePlan(ContractModel):
    files: dict[str, bytes]
    conflicts: tuple[VaultConflict, ...]
    broken_links: tuple[BrokenVaultLink, ...] = ()
    safe_to_apply: bool


@dataclass(frozen=True)
class _ManagedSection:
    text: str
    start: int
    end: int
    declared_hash: str
    actual_hash: str

    @property
    def is_valid(self) -> bool:
        return self.declared_hash == self.actual_hash


def _managed_section(content: bytes) -> _ManagedSection | None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    starts = list(_MANAGED_START.finditer(text))
    ends = list(_MANAGED_END.finditer(text))
    if len(starts) != 1 or len(ends) != 1 or starts[0].end() > ends[0].start():
        return None
    end = ends[0].end()
    if text[end : end + 1] == "\n":
        end += 1
    body = text[starts[0].end() : ends[0].start()]
    return _ManagedSection(
        text=text,
        start=starts[0].start(),
        end=end,
        declared_hash=starts[0].group(1),
        actual_hash=sha256_digest(body),
    )


def _managed_block(body: str) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
    digest = sha256_digest(normalized)
    return f"<!-- AKC:managed:start hash={digest} -->\n{normalized}<!-- AKC:managed:end -->\n"


def _safe_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        character
        for character in normalized
        if character in {"\n", "\t"} or not unicodedata.category(character).startswith("C")
    )
    for character in ("\\", "[", "]", "<", ">", "`", "|"):
        normalized = normalized.replace(character, f"\\{character}")
    return normalized.strip()


def _sort_text(values: tuple[str, ...]) -> list[str]:
    return sorted(set(values), key=lambda value: unicodedata.normalize("NFKC", value).casefold())


def _relative_link(
    source_path: str,
    target_path: str,
    label: str,
    *,
    wikilinks: bool,
) -> str:
    safe_target = safe_relative_path(target_path)
    safe_label = _safe_text(label)
    if wikilinks:
        target = safe_target.removesuffix(".md")
        return f"[[{target}|{safe_label}]]"
    parent = str(PurePosixPath(source_path).parent)
    relative = posixpath.relpath(safe_target, start=parent)
    return f"[{safe_label}]({relative})"


def _note_frontmatter(note: KnowledgeNote, document: CanonicalDocument) -> str:
    payload = {
        "akmp_version": "1.0",
        "id": note.note_id,
        "title": note.title,
        "aliases": _sort_text(note.aliases),
        "tags": _sort_text(note.tags),
        "note_type": note.note_type.value,
        "content_origin": note.content_origin.value,
        "review_status": note.review_status.value,
        "source_document_id": document.document_id,
        "evidence_block_ids": sorted(set(note.evidence_block_ids)),
    }
    rendered = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    return f"---\n{rendered}\n---\n\n"


def _note_markdown(
    note: KnowledgeNote,
    *,
    note_path: str,
    note_paths: Mapping[str, str],
    document_path: str,
    document: CanonicalDocument,
    wikilinks: bool,
) -> str:
    body = [f"# {_safe_text(note.title)}", ""]
    if note.summary:
        body.extend(("## Summary", "", _safe_text(note.summary), ""))
    if note.claims:
        body.extend(("## Claims", ""))
        for claim in note.claims:
            evidence = ", ".join(f"`{_safe_text(value)}`" for value in claim.source_block_ids)
            body.append(f"- {_safe_text(claim.text)}")
            body.append(
                "  - Evidence: "
                f"{_relative_link(note_path, document_path, document.title, wikilinks=wikilinks)}"
                f" · {evidence}"
            )
            body.append(f"  - Origin: `{claim.origin.value}` · confidence `{claim.confidence:.4f}`")
        body.append("")
    related = [
        candidate for candidate in note.related_note_candidates if candidate.target_id in note_paths
    ]
    if related:
        body.extend(("## Related notes", ""))
        for candidate in sorted(
            related,
            key=lambda value: (note_paths[value.target_id], value.relation, value.target_id),
        ):
            body.append(
                "- "
                + _relative_link(
                    note_path,
                    note_paths[candidate.target_id],
                    candidate.relation,
                    wikilinks=wikilinks,
                )
                + f" — {_safe_text(candidate.reason)}"
            )
        body.append("")
    body.extend(
        (
            "## Provenance",
            "",
            "- Source: "
            + _relative_link(
                note_path,
                document_path,
                document.title,
                wikilinks=wikilinks,
            ),
            "- Evidence blocks: "
            + ", ".join(f"`{_safe_text(value)}`" for value in note.evidence_block_ids),
            f"- Review status: `{note.review_status.value}`",
        )
    )
    managed_body = "\n".join(body).strip() + "\n"
    ensure_portable_markdown_safe(_note_frontmatter(note, document) + managed_body)
    return _note_frontmatter(note, document) + _managed_block(managed_body)


def _validate_bundle(document: CanonicalDocument, bundle: KnowledgeBundle) -> None:
    if bundle.document_id != document.document_id:
        raise ValueError("knowledge bundle document ID does not match canonical document")
    available = {block.id for block in document.blocks}
    referenced = {
        block_id
        for note in bundle.notes
        for block_id in (
            *note.evidence_block_ids,
            *(value for claim in note.claims for value in claim.source_block_ids),
            *(
                value
                for candidate in note.related_note_candidates
                for value in candidate.source_block_ids
            ),
        )
    }
    referenced.update(
        block_id for relation in bundle.relations for block_id in relation.evidence_block_ids
    )
    referenced.update(
        block_id for conflict in bundle.conflicts for block_id in conflict.evidence_block_ids
    )
    missing = sorted(referenced - available)
    if missing:
        raise ValueError(f"knowledge bundle references unknown blocks: {missing}")


def _put_file(
    files: dict[str, bytes],
    key_to_path: dict[str, str],
    path: str,
    content: bytes | str,
) -> None:
    safe = safe_relative_path(path)
    key = collision_key(safe)
    if key in key_to_path:
        raise ValueError(
            f"generated Vault path collision: {safe!r} conflicts with {key_to_path[key]!r}"
        )
    files[safe] = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    key_to_path[key] = safe


def compile_vault(
    document: CanonicalDocument,
    artifact: MarkdownArtifact,
    *,
    quality_report: QualityReport | None = None,
    knowledge_bundle: KnowledgeBundle | None = None,
    wikilinks: bool = False,
    binary_assets: dict[str, bytes] | None = None,
) -> dict[str, bytes]:
    document_key = portable_slug(document.document_id)
    files: dict[str, bytes] = {}
    key_to_path: dict[str, str] = {}
    _put_file(files, key_to_path, artifact.path, artifact.markdown)
    _put_file(
        files,
        key_to_path,
        f"source-map/{document_key}.json",
        source_map_json(artifact.source_map),
    )

    note_paths: dict[str, str] = {}
    if knowledge_bundle is not None:
        _validate_bundle(document, knowledge_bundle)
        for note in knowledge_bundle.notes:
            folder = _NOTE_FOLDERS.get(note.note_type)
            if folder is None:
                continue
            note_paths[note.note_id] = (
                f"{folder}/{stable_markdown_filename(note.title, note.note_id)}"
            )

    home_body = "\n".join(
        (
            "# Knowledge Vault",
            "",
            "- [Documents](Documents-MOC.md)",
            "- [Topics](Topics-MOC.md)",
            "- [Review queue](Review-Queue.md)",
        )
    )
    _put_file(files, key_to_path, "00-Home/Home.md", _managed_block(home_body))
    documents_body = "\n".join(
        (
            "# Documents",
            "",
            "- "
            + _relative_link(
                "00-Home/Documents-MOC.md",
                artifact.path,
                document.title,
                wikilinks=wikilinks,
            ),
        )
    )
    _put_file(
        files,
        key_to_path,
        "00-Home/Documents-MOC.md",
        _managed_block(documents_body),
    )

    topics_lines = ["# Topics", ""]
    for note_type in _NOTE_FOLDERS:
        moc_path = _MOC_FILES[note_type]
        topics_lines.append(
            "- "
            + _relative_link(
                "00-Home/Topics-MOC.md",
                moc_path,
                _MOC_TITLES[note_type],
                wikilinks=wikilinks,
            )
        )
        notes = (
            []
            if knowledge_bundle is None
            else [
                note
                for note in knowledge_bundle.notes
                if note.note_type == note_type and note.note_id in note_paths
            ]
        )
        moc_lines = [f"# {_MOC_TITLES[note_type]}", ""]
        if notes:
            for note in sorted(
                notes,
                key=lambda value: (
                    unicodedata.normalize("NFKC", value.title).casefold(),
                    value.note_id,
                ),
            ):
                moc_lines.append(
                    "- "
                    + _relative_link(
                        moc_path,
                        note_paths[note.note_id],
                        note.title,
                        wikilinks=wikilinks,
                    )
                    + f" · `{note.review_status.value}`"
                )
        else:
            moc_lines.append("_No notes._")
        _put_file(files, key_to_path, moc_path, _managed_block("\n".join(moc_lines)))
    _put_file(
        files,
        key_to_path,
        "00-Home/Topics-MOC.md",
        _managed_block("\n".join(topics_lines)),
    )

    review_lines = ["# Review Queue", ""]
    if knowledge_bundle is not None:
        pending_notes = [
            note
            for note in knowledge_bundle.notes
            if note.note_id in note_paths
            and note.review_status not in {ReviewStatus.USER_VERIFIED, ReviewStatus.REJECTED}
        ]
        for note in sorted(
            pending_notes,
            key=lambda value: (
                value.review_status.value,
                unicodedata.normalize("NFKC", value.title).casefold(),
                value.note_id,
            ),
        ):
            review_lines.append(
                "- [ ] "
                + _relative_link(
                    "00-Home/Review-Queue.md",
                    note_paths[note.note_id],
                    note.title,
                    wikilinks=wikilinks,
                )
                + f" · `{note.review_status.value}`"
            )
        for conflict in sorted(knowledge_bundle.conflicts, key=lambda value: value.id):
            evidence = ", ".join(
                f"`{_safe_text(value)}`" for value in sorted(conflict.evidence_block_ids)
            )
            review_lines.append(
                f"- [ ] Conflict `{_safe_text(conflict.id)}`"
                f" · `{conflict.dimension.value}` · evidence {evidence}"
            )
    if len(review_lines) == 2:
        review_lines.append("_No pending review items._")
    _put_file(
        files,
        key_to_path,
        "00-Home/Review-Queue.md",
        _managed_block("\n".join(review_lines)),
    )

    if knowledge_bundle is not None:
        for note in sorted(knowledge_bundle.notes, key=lambda value: value.note_id):
            path = note_paths.get(note.note_id)
            if path is None:
                continue
            _put_file(
                files,
                key_to_path,
                path,
                _note_markdown(
                    note,
                    note_path=path,
                    note_paths=note_paths,
                    document_path=artifact.path,
                    document=document,
                    wikilinks=wikilinks,
                ),
            )

    _put_file(
        files,
        key_to_path,
        "README.md",
        (
            "# AI Knowledge Markdown Profile 1.0\n\n"
            "Generated files preserve source provenance in `source-map/`.\n"
        ),
    )
    for path, content in sorted(artifact.table_assets.items()):
        normalized = path.removeprefix("../")
        _put_file(files, key_to_path, normalized, content)
    for path, content in sorted(artifact.supplemental_assets.items()):
        normalized = path.removeprefix("../")
        _put_file(files, key_to_path, normalized, content)
    for path, binary_content in sorted((binary_assets or {}).items()):
        _put_file(files, key_to_path, path.removeprefix("../"), binary_content)
    if quality_report is not None:
        _put_file(
            files,
            key_to_path,
            f"quality/{document_key}.json",
            json.dumps(
                quality_report.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
    result = dict(sorted(files.items()))
    broken = validate_internal_links(result)
    if broken:
        descriptions = ", ".join(
            f"{item.source_path} -> {item.target} ({item.reason})" for item in broken
        )
        raise ValueError(f"generated Vault contains broken internal links: {descriptions}")
    return result


def _resolve_internal_target(
    source_path: str,
    target: str,
    *,
    wikilink: bool,
) -> tuple[str | None, str | None]:
    decoded = unquote(target.strip().strip("<>")).replace("\\", "/")
    if not decoded or decoded.startswith("#"):
        return None, None
    if _EXTERNAL_SCHEME.match(decoded) or decoded.startswith("//"):
        return None, None
    path_only = decoded.split("#", 1)[0].split("?", 1)[0]
    if not path_only:
        return None, None
    if wikilink:
        candidate = path_only
        # Wikilink targets omit the Markdown extension. A document title may
        # legitimately contain dots (for example ``report.v2--id``), which
        # must not be mistaken for a real file extension.
        if not candidate.casefold().endswith(".md"):
            candidate += ".md"
    else:
        parent = str(PurePosixPath(source_path).parent)
        candidate = posixpath.normpath(posixpath.join(parent, path_only))
    try:
        return safe_relative_path(candidate), None
    except ValueError:
        return None, "unsafe_relative_path"


def validate_internal_links(files: Mapping[str, bytes]) -> tuple[BrokenVaultLink, ...]:
    normalized: dict[str, str] = {}
    for path in sorted(files):
        safe = safe_relative_path(path)
        key = collision_key(safe)
        if key in normalized:
            raise ValueError("Vault has a case-insensitive path collision")
        normalized[key] = safe

    broken: list[BrokenVaultLink] = []
    for source_path, content in sorted(files.items()):
        safe_source = safe_relative_path(source_path)
        if PurePosixPath(safe_source).suffix.casefold() != ".md":
            continue
        try:
            text = bytes(content).decode("utf-8")
        except UnicodeDecodeError:
            broken.append(
                BrokenVaultLink(
                    source_path=safe_source,
                    target="<document>",
                    reason="invalid_utf8",
                )
            )
            continue
        targets = [(match.group(1), False) for match in _MARKDOWN_LINK.finditer(text)] + [
            (match.group(1), True) for match in _WIKILINK.finditer(text)
        ]
        for target, wikilink in targets:
            resolved, reason = _resolve_internal_target(
                safe_source,
                target,
                wikilink=wikilink,
            )
            if resolved is None:
                if reason is not None:
                    broken.append(
                        BrokenVaultLink(
                            source_path=safe_source,
                            target=target,
                            reason=reason,
                        )
                    )
                continue
            actual = normalized.get(collision_key(resolved))
            if actual is None:
                broken.append(
                    BrokenVaultLink(
                        source_path=safe_source,
                        target=target,
                        resolved_path=resolved,
                        reason="target_missing",
                    )
                )
    return tuple(broken)


def _source_hash(content: bytes) -> str | None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    match = _SOURCE_HASH.search(text)
    return match.group(1) if match else None


def plan_vault_merge(
    existing: Mapping[str, bytes],
    incoming: Mapping[str, bytes],
    *,
    policy: MergePolicy = MergePolicy.ERROR,
) -> VaultMergePlan:
    merged: dict[str, bytes] = {}
    key_to_path: dict[str, str] = {}
    for path, content in sorted(existing.items()):
        safe = safe_relative_path(path)
        key = collision_key(safe)
        if key in key_to_path:
            raise ValueError("existing Vault already has a case-insensitive path collision")
        key_to_path[key] = safe
        merged[safe] = bytes(content)

    conflicts: list[VaultConflict] = []
    for incoming_path, content in sorted(incoming.items()):
        safe = safe_relative_path(incoming_path)
        key = collision_key(safe)
        existing_path = key_to_path.get(key)
        if existing_path is None:
            merged[safe] = bytes(content)
            key_to_path[key] = safe
            continue
        if merged[existing_path] == content:
            continue
        if policy == MergePolicy.UPDATE_MANAGED:
            existing_section = _managed_section(merged[existing_path])
            incoming_section = _managed_section(bytes(content))
            if incoming_section is None or not incoming_section.is_valid:
                conflicts.append(
                    VaultConflict(
                        existing_path=existing_path,
                        incoming_path=safe,
                        reason="incoming_managed_section_invalid",
                    )
                )
                continue
            if existing_section is None:
                conflicts.append(
                    VaultConflict(
                        existing_path=existing_path,
                        incoming_path=safe,
                        reason="existing_file_not_managed",
                    )
                )
                continue
            if not existing_section.is_valid:
                conflicts.append(
                    VaultConflict(
                        existing_path=existing_path,
                        incoming_path=safe,
                        reason="managed_section_modified",
                    )
                )
                continue
            incoming_managed = incoming_section.text[incoming_section.start : incoming_section.end]
            updated = (
                existing_section.text[: existing_section.start]
                + incoming_managed
                + existing_section.text[existing_section.end :]
            ).encode("utf-8")
            merged[existing_path] = updated
            conflicts.append(
                VaultConflict(
                    existing_path=existing_path,
                    incoming_path=safe,
                    reason="managed_section_update",
                    resolution="updated_managed_section",
                    resolved_path=existing_path,
                )
            )
            continue
        if policy == MergePolicy.KEEP_EXISTING:
            conflicts.append(
                VaultConflict(
                    existing_path=existing_path,
                    incoming_path=safe,
                    reason="content_differs",
                    resolution="kept_existing",
                    resolved_path=existing_path,
                )
            )
            continue
        if policy == MergePolicy.RENAME_INCOMING:
            renamed = with_collision_suffix(safe, sha256_digest(content))
            while collision_key(renamed) in key_to_path:
                renamed = with_collision_suffix(renamed, renamed)
            merged[renamed] = bytes(content)
            key_to_path[collision_key(renamed)] = renamed
            conflicts.append(
                VaultConflict(
                    existing_path=existing_path,
                    incoming_path=safe,
                    reason="content_differs",
                    resolution="renamed_incoming",
                    resolved_path=renamed,
                )
            )
            continue
        if policy == MergePolicy.REPLACE_SAME_SOURCE:
            existing_hash = _source_hash(merged[existing_path])
            incoming_hash = _source_hash(bytes(content))
            if existing_hash and existing_hash == incoming_hash:
                merged[existing_path] = bytes(content)
                conflicts.append(
                    VaultConflict(
                        existing_path=existing_path,
                        incoming_path=safe,
                        reason="same_source_revision",
                        resolution="replaced_existing",
                        resolved_path=existing_path,
                    )
                )
                continue
        conflicts.append(
            VaultConflict(
                existing_path=existing_path,
                incoming_path=safe,
                reason="unresolved_content_conflict",
            )
        )
    unresolved = any(conflict.resolution is None for conflict in conflicts)
    existing_broken = {
        (
            item.source_path,
            item.target,
            item.resolved_path,
            item.reason,
        )
        for item in validate_internal_links(existing)
    }
    broken_links = tuple(
        item
        for item in validate_internal_links(merged)
        if (
            item.source_path,
            item.target,
            item.resolved_path,
            item.reason,
        )
        not in existing_broken
    )
    return VaultMergePlan(
        files=dict(sorted(merged.items())),
        conflicts=tuple(conflicts),
        broken_links=broken_links,
        safe_to_apply=not unresolved and not broken_links,
    )
