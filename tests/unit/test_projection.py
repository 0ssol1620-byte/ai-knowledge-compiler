"""Tests for the Obsidian projection generator (truth-lock gap #6)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from akc_cir.projection import (
    DEFAULT_FOLDERS,
    REQUIRED_FRONTMATTER_FIELDS,
    SOURCES_FOLDER,
    TIMELINE_FOLDER,
    ProjectionProfile,
    ProjectionRefused,
    generate,
)

WORLD_STATE_ID = "ws_alpha"
COMPILED_AT = "2026-08-24T09:00:00+00:00"


def _world() -> dict[str, Any]:
    """One small compiled world: two entities, one superseded claim."""
    return {
        "world_state_id": WORLD_STATE_ID,
        "compiled_at": COMPILED_AT,
        "entities": [
            {
                "tavonel_id": "ent_ada",
                "entity_type": "People",
                "name": "Ada Lovelace",
                "authority_state": "CURRENT",
                "valid_from": "1815-12-10",
                "valid_to": None,
                "source_refs": ["doc_bio#page=1", "doc_letters#page=3"],
                "summary": "Wrote the notes on the Analytical Engine.",
                "attributes": {"role": "mathematician"},
            },
            {
                "tavonel_id": "org_engine_society",
                "entity_type": "Organizations",
                "name": "Analytical Engine Society",
                "authority_state": "CURRENT",
                "valid_from": "1843-01-01",
                "valid_to": None,
                "source_refs": ["doc_letters#page=5"],
            },
        ],
        "claims": [
            {
                "tavonel_id": "claim_note_g",
                "entity_type": "Research",
                "text": "Note G sketches the first published algorithm.",
                "authority_state": "SUPERSEDED",
                "valid_from": "1843-07-01",
                "valid_to": "1843-08-01",
                "source_refs": ["doc_letters#page=7"],
            }
        ],
    }


def _project(world: dict[str, Any], tmp_path: Path, *, name: str = "vault") -> Path:
    out_dir = tmp_path / name
    generate(world, ProjectionProfile(), out_dir)
    return out_dir


def _frontmatter_of(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} must open with YAML frontmatter"
    closing = text.index("\n---", 4)
    parsed = yaml.safe_load(text[4:closing])
    assert isinstance(parsed, dict), f"{path.name} frontmatter must parse to a mapping"
    return parsed


def _mtimes(root: Path) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in sorted(root.rglob("*.md"))}


def test_default_profile_matches_the_vault_architecture() -> None:
    assert DEFAULT_FOLDERS[:-2] == (
        "People",
        "Organizations",
        "Projects",
        "Decisions",
        "Policies",
        "Products",
        "Issues",
        "Research",
    )
    assert DEFAULT_FOLDERS[-2:] == (TIMELINE_FOLDER, SOURCES_FOLDER)


def test_generate_creates_notes_with_provenance_frontmatter(tmp_path: Path) -> None:
    out_dir = tmp_path / "vault"

    result = generate(_world(), ProjectionProfile(), out_dir)

    # 3 record notes + Timeline index + 2 cited-source pages.
    assert result.files_written == 6
    assert result.files_unchanged == 0
    assert {path.name for path in result.dirs} == {
        "People",
        "Organizations",
        "Research",
        TIMELINE_FOLDER,
        SOURCES_FOLDER,
    }

    note = out_dir / "People" / "ent_ada.md"
    frontmatter = _frontmatter_of(note)
    assert set(REQUIRED_FRONTMATTER_FIELDS) <= set(frontmatter)
    assert frontmatter["tavonel_id"] == "ent_ada"
    assert frontmatter["world_state_id"] == WORLD_STATE_ID
    assert frontmatter["entity_type"] == "People"
    assert frontmatter["authority_state"] == "CURRENT"
    assert frontmatter["valid_from"] == "1815-12-10"
    assert frontmatter["valid_to"] is None
    assert frontmatter["source_refs"] == ["doc_bio#page=1", "doc_letters#page=3"]
    assert frontmatter["last_compiled_at"] == COMPILED_AT
    assert "# Ada Lovelace" in note.read_text(encoding="utf-8")

    claim_note = out_dir / "Research" / "claim_note_g.md"
    claim_frontmatter = _frontmatter_of(claim_note)
    assert claim_frontmatter["entity_type"] == "Research"
    assert claim_frontmatter["valid_to"] == "1843-08-01"


def test_timeline_index_is_date_sorted_and_sources_pages_group_citations(
    tmp_path: Path,
) -> None:
    out_dir = _project(_world(), tmp_path)

    timeline = (out_dir / TIMELINE_FOLDER / "index.md").read_text(encoding="utf-8")
    ada_position = timeline.index("[[ent_ada|Ada Lovelace]]")
    org_position = timeline.index("[[org_engine_society|Analytical Engine Society]]")
    claim_position = timeline.index("[[claim_note_g|")
    assert ada_position < org_position < claim_position, "timeline must be oldest valid_from first"

    letters_page = (out_dir / SOURCES_FOLDER / "doc_letters.md").read_text(encoding="utf-8")
    assert "[[ent_ada|Ada Lovelace]]" in letters_page
    assert "[[org_engine_society|" in letters_page
    assert "[[claim_note_g|" in letters_page
    assert "- doc_letters#page=7" in letters_page

    bio_frontmatter = _frontmatter_of(out_dir / SOURCES_FOLDER / "doc_bio.md")
    assert bio_frontmatter["source_refs"] == ["ent_ada"], "derived pages cite their sources too"


def test_regeneration_is_idempotent_and_preserves_mtimes(tmp_path: Path) -> None:
    world = _world()
    out_dir = tmp_path / "vault"

    generate(world, ProjectionProfile(), out_dir)
    before = _mtimes(out_dir)

    rerun = generate(world, ProjectionProfile(), out_dir)

    assert rerun.files_written == 0
    assert rerun.files_unchanged == 6
    assert _mtimes(out_dir) == before, "byte-identical regeneration must not touch a file"


def test_world_change_rewrites_only_the_changed_entity(tmp_path: Path) -> None:
    out_dir = _project(_world(), tmp_path)
    before = _mtimes(out_dir)

    changed_world = _world()
    assert isinstance(changed_world["entities"], list)
    changed_world["entities"][0]["authority_state"] = "REVISED"

    # Some filesystems coalesce rapid writes into the same timestamp tick.
    # Age this file explicitly so the assertion still detects a real rewrite.
    changed = out_dir / "People" / "ent_ada.md"
    old_time_ns = before[changed] - 1_000_000_000
    os.utime(changed, ns=(old_time_ns, old_time_ns))
    before[changed] = changed.stat().st_mtime_ns

    rerun = generate(changed_world, ProjectionProfile(), out_dir)

    assert rerun.files_written == 1
    assert rerun.files_unchanged == 5
    assert changed.stat().st_mtime_ns > before[changed]
    assert 'authority_state: "REVISED"' in changed.read_text(encoding="utf-8")
    after = _mtimes(out_dir)
    untouched = [path for path in before if path != changed]
    assert all(after[path] == before[path] for path in untouched)


@pytest.mark.parametrize(
    ("out_dir_name",),
    [
        pytest.param("vault", id="out_dir equals the source directory"),
        pytest.param("vault/nested/deeper", id="out_dir inside the source directory"),
    ],
)
def test_rejects_out_dir_equal_to_or_inside_source_root(
    tmp_path: Path, out_dir_name: str
) -> None:
    world = _world()
    world["source_root"] = str(tmp_path / "vault")

    with pytest.raises(ProjectionRefused, match="source"):
        generate(world, ProjectionProfile(), tmp_path / out_dir_name)

    # A sibling of the source is still fine -- only writing *into* it is refused.
    elsewhere = generate(world, ProjectionProfile(), tmp_path / "elsewhere")
    assert elsewhere.files_written == 6


def test_profile_is_a_parameter_not_a_convention(tmp_path: Path) -> None:
    world = _world()
    assert isinstance(world["entities"], list)
    world["entities"][0]["entity_type"] = "Clients"
    world["entities"][1]["entity_type"] = "Ledger"
    world["claims"][0]["entity_type"] = "Ledger"

    out_dir = tmp_path / "custom-vault"
    result = generate(world, ProjectionProfile(folders=("Clients", "Ledger")), out_dir)

    # Records only: no Timeline index, no Sources pages -- they are profile-declared.
    assert result.files_written == 3
    assert {path.name for path in result.dirs} == {"Clients", "Ledger"}
    assert (out_dir / "Clients" / "ent_ada.md").exists()
    assert not (out_dir / "People").exists()
    assert not (out_dir / TIMELINE_FOLDER / "index.md").exists()


def test_records_without_provenance_or_known_folder_are_refused(tmp_path: Path) -> None:
    no_provenance = _world()
    assert isinstance(no_provenance["claims"], list)
    no_provenance["claims"][0]["source_refs"] = []
    with pytest.raises(ProjectionRefused, match="provenance"):
        generate(no_provenance, ProjectionProfile(), tmp_path / "a")

    unknown_folder = _world()
    assert isinstance(unknown_folder["entities"], list)
    unknown_folder["entities"][0]["entity_type"] = "Astral"
    with pytest.raises(ProjectionRefused, match="profile"):
        generate(unknown_folder, ProjectionProfile(), tmp_path / "b")

    reserved_folder = _world()
    assert isinstance(reserved_folder["claims"], list)
    reserved_folder["claims"][0]["entity_type"] = TIMELINE_FOLDER
    with pytest.raises(ProjectionRefused, match="reserved"):
        generate(reserved_folder, ProjectionProfile(), tmp_path / "c")


def test_missing_compiled_at_is_refused_rather_than_invented(tmp_path: Path) -> None:
    world = _world()
    del world["compiled_at"]
    with pytest.raises(ProjectionRefused, match="compiled_at"):
        generate(world, ProjectionProfile(), tmp_path / "vault")
