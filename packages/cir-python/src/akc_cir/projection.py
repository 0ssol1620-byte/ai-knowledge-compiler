"""Projecting a compiled world into an Obsidian vault -- idempotently, provenance up front.

Truth lock 2026-08-24, gap #6: `exports.py` carried an OBSIDIAN profile, but
nothing generated the per-world directory architecture with provenance
frontmatter. This module is that generator, and it is governed by two rules.

**Obsidian syntax is never authoritative provenance** (docs/akmp/AKMP-1.0.md).
Folders and Wikilinks are reading aids; the lineage of every generated note
travels in YAML frontmatter -- tavonel_id, world_state_id, entity_type,
authority_state, valid_from/valid_to, source_refs, last_compiled_at. A note
whose frontmatter cannot answer *who says this, and from which compiled world*
has no business being in the vault.

**§8.1: 문서에 없는 날짜를 확정값으로 저장 금지.** The generator invents no
timestamp. `last_compiled_at` is the world state's own `compiled_at`, validity
windows come from the records, and a record the sources left undated carries
nulls rather than a guessed date. Refusing invented time is also what makes
regeneration idempotent: two runs over one unchanged world state produce
byte-identical files, so the second run writes nothing and preserves mtimes --
which is what keeps Obsidian sync, git status, and file watchers quiet.

Bitemporality survives the projection (masterplan §13): reality's window rides
in frontmatter next to system time, so a vault reader can ask both *when was
this true* and *which compile said so*. The Timeline folder indexes dated
records oldest-first; the Sources folder renders one page per cited document.
Neither exists unless the profile declares it -- the folder architecture is a
`ProjectionProfile` parameter, never a hardcoded convention here.

Safety: the projection writes only inside `out_dir`, and refuses to aim it at
-- or inside -- the directory the world was compiled from (`source_root` in the
mapping). A view that can overwrite its own sources is not a view.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = [
    "DEFAULT_FOLDERS",
    "REQUIRED_FRONTMATTER_FIELDS",
    "SOURCES_FOLDER",
    "TIMELINE_FOLDER",
    "ProjectionProfile",
    "ProjectionRefused",
    "ProjectionResult",
    "generate",
]

#: The two reserved folder roles. When a profile declares them, the projection
#: adds the date-sorted Timeline index and one Sources page per cited document;
#: records may never file themselves under them.
TIMELINE_FOLDER = "Timeline"
SOURCES_FOLDER = "Sources"

#: The default vault architecture. A default only -- every consumer passes its
#: own `ProjectionProfile`, and `generate` reads folders exclusively from it.
DEFAULT_FOLDERS = (
    "People",
    "Organizations",
    "Projects",
    "Decisions",
    "Policies",
    "Products",
    "Issues",
    "Research",
    TIMELINE_FOLDER,
    SOURCES_FOLDER,
)

_RESERVED = frozenset({TIMELINE_FOLDER, SOURCES_FOLDER})

#: Frontmatter fields every projected note must carry. The projection's own
#: contract, enforced by construction and checked by the unit suite.
REQUIRED_FRONTMATTER_FIELDS = (
    "tavonel_id",
    "world_state_id",
    "entity_type",
    "authority_state",
    "valid_from",
    "valid_to",
    "source_refs",
    "last_compiled_at",
)


class ProjectionRefused(ValueError):
    """A projection that would misstate provenance or damage its source stops here."""


@dataclass(frozen=True, slots=True)
class ProjectionProfile:
    """The folder architecture of one vault. Parameter, not convention.

    Folders are path components exactly as given; names that could escape the
    output directory or collide on a case-insensitive filesystem are rejected
    here, once, instead of being survived everywhere downstream.
    """

    folders: tuple[str, ...] = DEFAULT_FOLDERS

    def __post_init__(self) -> None:
        if not self.folders:
            raise ProjectionRefused("a projection profile needs at least one folder")
        seen: set[str] = set()
        for folder in self.folders:
            _ensure_safe_name(folder, what="profile folder")
            folded = folder.casefold()
            if folded in seen:
                raise ProjectionRefused(
                    f"profile folders must be unique (case-insensitively): {folder!r}"
                )
            seen.add(folded)


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """What one generation pass did. Idempotence shows up as counts, not effects."""

    #: Notes created or rewritten this pass (content differed from disk).
    files_written: int
    #: Notes already byte-identical on disk -- untouched, mtime preserved.
    files_unchanged: int
    #: Every directory the projected architecture occupies, sorted.
    dirs: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _NoteSpec:
    """One validated record (entity or claim) ready to render."""

    tavonel_id: str
    entity_type: str
    title: str
    authority_state: str
    valid_from: str | None
    valid_to: str | None
    source_refs: tuple[str, ...]
    body: str
    attributes: tuple[tuple[str, object], ...]


# -- input validation ------------------------------------------------------


def _ensure_safe_name(value: str, *, what: str) -> None:
    """Reject anything that could not travel as a single path component."""
    if (
        not value
        or value.strip() != value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or not value.isprintable()
    ):
        raise ProjectionRefused(f"{what} is not a safe path component: {value!r}")


def _require_str(record: Mapping[str, object], key: str, where: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProjectionRefused(f"{where}: {key} must be a non-empty string")
    return value


def _optional_date(record: Mapping[str, object], key: str, where: str) -> str | None:
    """Validity dates pass through verbatim; absent stays absent (§8.1)."""
    value = record.get(key)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    raise ProjectionRefused(
        f"{where}: {key} must be null, an ISO string, or a datetime -- "
        "the projection does not normalize or invent dates"
    )


def _require_refs(record: Mapping[str, object], where: str) -> tuple[str, ...]:
    value = record.get("source_refs")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) == 0:
        raise ProjectionRefused(
            f"{where}: source_refs must be a non-empty list. A note without "
            "provenance does not get written."
        )
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ProjectionRefused(f"{where}: every source_ref must be a non-empty string")
        refs.append(item)
    return tuple(dict.fromkeys(refs))


def _collect_records(
    world_state: Mapping[str, object],
    profile: ProjectionProfile,
) -> tuple[_NoteSpec, ...]:
    specs: list[_NoteSpec] = []
    seen_ids: set[str] = set()
    known = ", ".join(profile.folders)
    for kind in ("entities", "claims"):
        raw_records = world_state.get(kind)
        if raw_records is None:
            continue
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            raise ProjectionRefused(f"world_state.{kind} must be a list of records")
        for index, raw in enumerate(raw_records):
            where = f"{kind}[{index}]"
            if not isinstance(raw, Mapping):
                raise ProjectionRefused(f"{where}: each record must be a mapping")
            tavonel_id = _require_str(raw, "tavonel_id", where)
            _ensure_safe_name(tavonel_id, what=f"{where} tavonel_id")
            if tavonel_id in seen_ids:
                raise ProjectionRefused(
                    f"duplicate tavonel_id {tavonel_id!r}: wikilinks must resolve "
                    "to exactly one note across the vault"
                )
            seen_ids.add(tavonel_id)
            entity_type = _require_str(raw, "entity_type", where)
            if entity_type in _RESERVED:
                raise ProjectionRefused(
                    f"{where}: entity_type {entity_type!r} is reserved for the "
                    f"{TIMELINE_FOLDER}/{SOURCES_FOLDER} projections; records file "
                    "themselves under knowledge folders only"
                )
            if entity_type not in profile.folders:
                raise ProjectionRefused(
                    f"{where}: entity_type {entity_type!r} is not a folder of this "
                    f"profile ({known}). Extend the profile parameter -- the "
                    "generator hardcodes none."
                )
            display_value = raw.get("name") or raw.get("text")
            summary_value = raw.get("summary") or raw.get("text")
            title = (
                display_value
                if isinstance(display_value, str) and display_value
                else tavonel_id
            )
            body = summary_value if isinstance(summary_value, str) else ""
            specs.append(
                _NoteSpec(
                    tavonel_id=tavonel_id,
                    entity_type=entity_type,
                    title=title,
                    authority_state=_require_str(raw, "authority_state", where),
                    valid_from=_optional_date(raw, "valid_from", where),
                    valid_to=_optional_date(raw, "valid_to", where),
                    source_refs=_require_refs(raw, where),
                    body=body,
                    attributes=_attributes(raw, where),
                )
            )
    return tuple(specs)


def _attributes(raw: Mapping[str, object], where: str) -> tuple[tuple[str, object], ...]:
    value = raw.get("attributes")
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise ProjectionRefused(f"{where}: attributes must be a mapping when present")
    return tuple(sorted(((str(key), item) for key, item in value.items())))


# -- deterministic rendering ------------------------------------------------


def _yaml_scalar(value: object) -> str:
    """Render one scalar as a YAML node, deterministically.

    Strings are emitted JSON-style, which is valid YAML double-quoting and
    cannot be re-read as a different type: a date stays a string, "null" stays
    a string, and 한글 survives verbatim.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, datetime):
        return json.dumps(value.isoformat(), ensure_ascii=False)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return json.dumps(encoded, ensure_ascii=False)


def _frontmatter(fields: Sequence[tuple[str, object]]) -> str:
    lines = ["---"]
    for key, value in fields:
        if isinstance(value, (list, tuple)):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_yaml_scalar(item)}" for item in value)
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.extend(("---", ""))
    return "\n".join(lines)


def _cited_documents(spec: _NoteSpec) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref.split("#", 1)[0] for ref in spec.source_refs))


def _render_note(
    spec: _NoteSpec,
    *,
    world_state_id: str,
    compiled_at: str,
    profile: ProjectionProfile,
) -> str:
    fields: list[tuple[str, object]] = [
        ("tavonel_id", spec.tavonel_id),
        ("world_state_id", world_state_id),
        ("entity_type", spec.entity_type),
        ("authority_state", spec.authority_state),
        ("valid_from", spec.valid_from),
        ("valid_to", spec.valid_to),
        ("source_refs", list(spec.source_refs)),
        ("last_compiled_at", compiled_at),
        ("title", spec.title),
    ]
    lines = [f"# {spec.title}", ""]
    if spec.body:
        lines.extend((spec.body, ""))
    if spec.attributes:
        lines.extend(("## Attributes", ""))
        lines.extend(f"- **{key}**: {_yaml_scalar(value)}" for key, value in spec.attributes)
        lines.append("")
    lines.extend(("## Provenance", ""))
    if SOURCES_FOLDER in profile.folders:
        links = ", ".join(
            f"[[{SOURCES_FOLDER}/{doc}|{doc}]]" for doc in _cited_documents(spec)
        )
        lines.extend((f"Cited sources: {links}", ""))
    else:
        lines.extend("- " + ref for ref in spec.source_refs)
        lines.append("")
    lines.append(
        f"_Projected from world state `{world_state_id}`, authority "
        f"`{spec.authority_state}`, compiled {compiled_at}_"
    )
    return _frontmatter(fields) + "\n".join(lines) + "\n"


def _render_timeline(
    specs: tuple[_NoteSpec, ...],
    *,
    world_state_id: str,
    compiled_at: str,
) -> str:
    dated = [spec for spec in specs if spec.valid_from or spec.valid_to]
    ordered = sorted(
        dated,
        key=lambda spec: (spec.valid_from or spec.valid_to or "", spec.tavonel_id),
    )
    fields = [
        ("tavonel_id", f"{TIMELINE_FOLDER.lower()}_index"),
        ("world_state_id", world_state_id),
        ("entity_type", TIMELINE_FOLDER),
        ("authority_state", "DERIVED"),
        ("valid_from", ordered[0].valid_from if ordered else None),
        ("valid_to", None),
        ("source_refs", [spec.tavonel_id for spec in ordered]),
        ("last_compiled_at", compiled_at),
        ("title", TIMELINE_FOLDER),
    ]
    lines = [f"# {TIMELINE_FOLDER}", "", f"{len(dated)} dated record(s), oldest first.", ""]
    lines.extend(
        f"- {spec.valid_from or spec.valid_to} - [[{spec.tavonel_id}|{spec.title}]]"
        for spec in ordered
    )
    undated = len(specs) - len(dated)
    if undated:
        lines.extend(
            (
                "",
                f"_{undated} record(s) carry no validity window and are omitted -- "
                "§8.1 forbids dating them on their behalf._",
            )
        )
    return _frontmatter(fields) + "\n".join(lines) + "\n"


def _render_source_page(
    document: str,
    citations: tuple[_NoteSpec, ...],
    *,
    world_state_id: str,
    compiled_at: str,
) -> str:
    citing = tuple(dict.fromkeys(spec.tavonel_id for spec in citations))
    refs = tuple(
        dict.fromkeys(
            ref
            for spec in citations
            for ref in spec.source_refs
            if ref.split("#", 1)[0] == document
        )
    )
    fields = [
        ("tavonel_id", f"src_{document}"),
        ("world_state_id", world_state_id),
        ("entity_type", SOURCES_FOLDER),
        ("authority_state", "DERIVED"),
        ("valid_from", None),
        ("valid_to", None),
        ("source_refs", list(citing)),
        ("last_compiled_at", compiled_at),
        ("title", document),
    ]
    lines = [f"# {document}", "", f"{len(citations)} note(s) cite this source.", ""]
    lines.extend(f"- [[{spec.tavonel_id}|{spec.title}]]" for spec in citations)
    lines.extend(("", "## Raw references", ""))
    lines.extend(f"- {ref}" for ref in refs)
    return _frontmatter(fields) + "\n".join(lines) + "\n"


# -- plan assembly and idempotent writes ------------------------------------


def _build_plan(
    specs: tuple[_NoteSpec, ...],
    *,
    world_state_id: str,
    compiled_at: str,
    profile: ProjectionProfile,
) -> dict[str, bytes]:
    plan: dict[str, bytes] = {}
    for spec in sorted(specs, key=lambda item: (item.entity_type, item.tavonel_id)):
        content = _render_note(
            spec, world_state_id=world_state_id, compiled_at=compiled_at, profile=profile
        )
        plan[f"{spec.entity_type}/{spec.tavonel_id}.md"] = content.encode("utf-8")
    if TIMELINE_FOLDER in profile.folders:
        timeline = _render_timeline(specs, world_state_id=world_state_id, compiled_at=compiled_at)
        plan[f"{TIMELINE_FOLDER}/index.md"] = timeline.encode("utf-8")
    if SOURCES_FOLDER in profile.folders:
        citations: dict[str, list[_NoteSpec]] = {}
        for spec in specs:
            for document in _cited_documents(spec):
                citations.setdefault(document, []).append(spec)
        for document in sorted(citations):
            page = _render_source_page(
                document,
                tuple(citations[document]),
                world_state_id=world_state_id,
                compiled_at=compiled_at,
            )
            plan[f"{SOURCES_FOLDER}/{document}.md"] = page.encode("utf-8")
    return plan


def _reject_source_collision(out_dir: Path, source_root: object) -> None:
    """The projection may never write into -- or onto -- the source it views."""
    if source_root is None:
        return
    if not isinstance(source_root, (str, os.PathLike)):
        raise ProjectionRefused("world_state.source_root must be a filesystem path when present")
    out_path = os.path.normcase(str(Path(out_dir).resolve()))
    src_path = os.path.normcase(str(Path(source_root).resolve()))
    if out_path == src_path:
        raise ProjectionRefused(
            f"out_dir resolves to the source directory itself ({source_root}); "
            "a projection may not write over the corpus it was compiled from"
        )
    if out_path.startswith(src_path.rstrip(os.sep) + os.sep):
        raise ProjectionRefused(
            f"out_dir {out_dir} lies inside the source directory ({source_root}); "
            "projecting into the source would let generated notes masquerade as evidence"
        )


def _atomic_write(target: Path, payload: bytes) -> None:
    """Write via a sibling temp file and rename, so readers never see a half-note."""
    descriptor, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def generate(
    world_state: Mapping[str, object],
    profile: ProjectionProfile,
    out_dir: Path,
) -> ProjectionResult:
    """Project one compiled world state into an Obsidian directory tree.

    Every record under ``entities`` and ``claims`` becomes one markdown note
    carrying full provenance frontmatter; the profile decides which folders
    exist. Writes are idempotent: a note whose rendered bytes already sit on
    disk is left alone, preserving its mtime.
    """
    world_state_id = _require_str(world_state, "world_state_id", "world_state")

    compiled_raw = world_state.get("compiled_at")
    if isinstance(compiled_raw, datetime):
        compiled_at = compiled_raw.isoformat()
    elif isinstance(compiled_raw, str) and compiled_raw.strip():
        compiled_at = compiled_raw
    else:
        raise ProjectionRefused(
            "world_state.compiled_at is missing. The projection stamps "
            "last_compiled_at from the compile it projects and never invents a "
            "timestamp (§8.1); without it, regeneration could not be idempotent."
        )

    _reject_source_collision(out_dir, world_state.get("source_root"))

    specs = _collect_records(world_state, profile)
    plan = _build_plan(
        specs, world_state_id=world_state_id, compiled_at=compiled_at, profile=profile
    )

    written = 0
    unchanged = 0
    for relative, payload in plan.items():
        target = out_dir / relative
        if target.exists() and target.read_bytes() == payload:
            unchanged += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, payload)
        written += 1

    dirs = tuple(sorted({(out_dir / relative).parent for relative in plan}, key=os.fspath))
    return ProjectionResult(files_written=written, files_unchanged=unchanged, dirs=dirs)
