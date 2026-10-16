"""Synthetic acceptance tests for the ontology store's additive compatibility boundary.

`OntologyStore` claims to add one ``ontology.json`` beside a world's published
``manifest.json``/``state.json`` and to refuse manifest schemas it does not
know. These tests hold it to both claims with synthetic files on a temp
directory. They are evidence for that boundary only: no database, and no
migration, is exercised or implied here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from akc_cir.base import canonical_json, sha256_digest
from akc_cir.ontology import (
    ONTOLOGY_MANIFEST_FILENAME,
    ONTOLOGY_MANIFEST_SCHEMA_VERSION,
    OntologyManifest,
    OntologyManifestError,
    OntologyState,
    OntologyStore,
    build_ontology_manifest,
)

WORLD_ID = "atlas-demo"

# Deliberately not what OntologyStore would write: CRLF line endings, no
# trailing newline, non-ASCII text. Any rewrite of these files shows up as a
# byte difference.
PUBLISHED_MANIFEST = '{"world_id": "atlas-demo",\r\n "title": "Ünïcode wörld"}'.encode()
PUBLISHED_STATE = b'{"status":"published","revision":7}'


def _seed_published_world(root: Path) -> Path:
    world = root / WORLD_ID
    world.mkdir(parents=True)
    (world / "manifest.json").write_bytes(PUBLISHED_MANIFEST)
    (world / "state.json").write_bytes(PUBLISHED_STATE)
    return world


def _listing(directory: Path) -> set[str]:
    return {entry.name for entry in directory.iterdir()}


def _assert_published_untouched(world: Path) -> None:
    assert (world / "manifest.json").read_bytes() == PUBLISHED_MANIFEST
    assert (world / "state.json").read_bytes() == PUBLISHED_STATE


def test_saving_adds_only_ontology_json_and_preserves_published_bytes(tmp_path: Path) -> None:
    world = _seed_published_world(tmp_path)
    assert _listing(world) == {"manifest.json", "state.json"}
    store = OntologyStore(tmp_path)

    saved = store.save(
        build_ontology_manifest(world_id=WORLD_ID, ontology_version=1, state=OntologyState.DRAFT)
    )

    assert saved == world / ONTOLOGY_MANIFEST_FILENAME
    # Exactly one new sibling; no temp file left behind.
    assert _listing(world) == {"manifest.json", "state.json", ONTOLOGY_MANIFEST_FILENAME}
    _assert_published_untouched(world)
    assert store.load(WORLD_ID).ontology_version == 1


def test_updating_rewrites_only_ontology_json_and_preserves_published_bytes(
    tmp_path: Path,
) -> None:
    world = _seed_published_world(tmp_path)
    store = OntologyStore(tmp_path)
    store.save(
        build_ontology_manifest(world_id=WORLD_ID, ontology_version=1, state=OntologyState.DRAFT)
    )
    first = (world / ONTOLOGY_MANIFEST_FILENAME).read_bytes()

    store.save(
        build_ontology_manifest(world_id=WORLD_ID, ontology_version=2, state=OntologyState.DRAFT)
    )

    assert _listing(world) == {"manifest.json", "state.json", ONTOLOGY_MANIFEST_FILENAME}
    assert (world / ONTOLOGY_MANIFEST_FILENAME).read_bytes() != first
    assert store.load(WORLD_ID).ontology_version == 2
    _assert_published_untouched(world)


def _rehashed_with_schema(manifest: OntologyManifest, schema_version: str) -> OntologyManifest:
    """The same manifest under another schema version, with a hash that covers it."""
    relabelled = manifest.model_copy(update={"schema_version": schema_version})
    digest = sha256_digest(canonical_json(relabelled.json_body()))
    return relabelled.model_copy(update={"manifest_hash": digest})


@pytest.mark.parametrize(
    "schema_version",
    ["akc.ontology-manifest-0", "akc.ontology-manifest-2"],
    ids=["older", "unknown-newer"],
)
def test_an_unsupported_schema_with_a_correct_hash_is_refused_by_schema(
    tmp_path: Path, schema_version: str
) -> None:
    assert schema_version != ONTOLOGY_MANIFEST_SCHEMA_VERSION
    world = _seed_published_world(tmp_path)
    store = OntologyStore(tmp_path)
    current = build_ontology_manifest(
        world_id=WORLD_ID, ontology_version=1, state=OntologyState.DRAFT
    )
    foreign = _rehashed_with_schema(current, schema_version)
    # The hash is right, so the only thing load can object to is the schema.
    assert foreign.verify_hash()

    # Written as an earlier writer would have left it, not through save().
    path = store.ontology_path(WORLD_ID)
    path.write_text(
        json.dumps(
            foreign.model_dump(mode="json", by_alias=False),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    on_disk = path.read_bytes()

    with pytest.raises(
        OntologyManifestError,
        match=re.escape(f"unsupported ontology manifest schema {schema_version!r}"),
    ):
        store.load(WORLD_ID)

    # Refusal is read-only: the foreign manifest and the published siblings stay as found.
    assert path.read_bytes() == on_disk
    _assert_published_untouched(world)


@pytest.mark.parametrize(
    "schema_version",
    ["akc.ontology-manifest-0", "akc.ontology-manifest-2"],
    ids=["older", "unknown-newer"],
)
def test_save_refuses_an_unsupported_schema_with_a_correct_hash_before_writing(
    tmp_path: Path, schema_version: str
) -> None:
    assert schema_version != ONTOLOGY_MANIFEST_SCHEMA_VERSION
    world = _seed_published_world(tmp_path)
    store = OntologyStore(tmp_path)
    current = build_ontology_manifest(
        world_id=WORLD_ID, ontology_version=1, state=OntologyState.DRAFT
    )
    foreign = _rehashed_with_schema(current, schema_version)
    # The hash is right, so the only thing save can object to is the schema.
    assert foreign.verify_hash()
    expected_error = re.escape(f"unsupported ontology manifest schema {schema_version!r}")

    # No ontology.json yet: refusal must not create one (or a temp file).
    with pytest.raises(OntologyManifestError, match=expected_error):
        store.save(foreign)
    assert _listing(world) == {"manifest.json", "state.json"}
    _assert_published_untouched(world)

    # An existing ontology.json: refusal must leave its bytes as found.
    path = store.save(current)
    on_disk = path.read_bytes()
    with pytest.raises(OntologyManifestError, match=expected_error):
        store.save(foreign)
    assert _listing(world) == {"manifest.json", "state.json", ONTOLOGY_MANIFEST_FILENAME}
    assert path.read_bytes() == on_disk
    _assert_published_untouched(world)
