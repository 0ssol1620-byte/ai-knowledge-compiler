"""Parser-only reuse: sealed outputs, cold fallback and pointer-last storage."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from akc_cir.recompilation import content_hash
from akc_cir.world_state import publication_manifest
from akc_compiler_runtime import CompileOptions, Pipeline, extraction, store


def _workspace(tmp_path: Path) -> tuple[Path, Pipeline]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "plan.md").write_text(
        "# Launch\n\nThe launch is October 15, 2026.\n", encoding="utf-8"
    )
    (source / "stable.py").write_text(
        "# The release requires approval.\ndef release():\n    pass\n", encoding="utf-8"
    )
    (source / "empty.md").write_text("# Empty\n", encoding="utf-8")
    return source, Pipeline(tmp_path / "store")


def _spy(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    calls: Counter[str] = Counter()
    real = extraction.parse_file

    def parse(file: extraction.ParsedFile, **kwargs: str) -> extraction.ParsedDocument:
        calls[file.rel_path] += 1
        return real(file, **kwargs)

    monkeypatch.setattr(extraction, "parse_file", parse)
    return calls


def _edit(source: Path) -> None:
    path = source / "plan.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("October", "November"), encoding="utf-8"
    )


def _bytes(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_first_recompile_parses_each_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, pipeline = _workspace(tmp_path)
    calls = _spy(monkeypatch)
    assert pipeline.recompile(source).published
    assert calls == Counter({"plan.md": 1, "stable.py": 1, "empty.md": 1})


def test_restart_reuses_empty_and_code_outputs_with_fresh_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, pipeline = _workspace(tmp_path)
    initial = pipeline.compile_workspace(source)
    world = pipeline.store.load_world()
    assert world is not None
    cached = pipeline.store.load_parsed_cache(world, context=pipeline._parser_context())
    assert set(cached) == {"plan.md", "stable.py", "empty.md"}
    assert cached["empty.md"]["claims"] == []
    calls = _spy(monkeypatch)
    before = _bytes(pipeline.store.base)
    real_scan = extraction.scan_source_files
    scanned = []

    def scan(root: Path) -> list[extraction.ParsedFile]:
        scanned[:] = [replace(file) for file in real_scan(root)]
        return scanned

    real_decode = extraction.parsed_document_from_record
    attached = []

    def decode(record: object, file: extraction.ParsedFile, **kwargs: str):
        document = real_decode(record, file, **kwargs)
        assert document.file is file
        attached.append(file)
        return document

    monkeypatch.setattr(extraction, "scan_source_files", scan)
    monkeypatch.setattr(extraction, "parsed_document_from_record", decode)
    restarted = Pipeline(pipeline.store.root)
    again = restarted.recompile(source)
    assert again.no_op and not again.published
    assert again.world_state_id == initial.world_state_id
    assert calls == Counter()
    assert attached == scanned
    assert _bytes(pipeline.store.base) == before
    _edit(source)
    incremental = restarted.recompile(source)
    assert calls == Counter({"plan.md": 1})
    assert incremental.equivalence is not None and incremental.equivalence.equivalent


def _reseal(pipeline: Pipeline, cache: dict[str, object]) -> None:
    """Test malformed-but-checksummed output, separately from checksum corruption."""
    path = pipeline.store.base / "worlds" / "WS-1.json"
    world = json.loads(path.read_text(encoding="utf-8"))
    world["artifact_hashes"]["parsed/documents"] = content_hash(cache)
    manifest = publication_manifest(
        world_state_id="WS-1", compiler_version=world["compiler_version"],
        artifact_hashes=world["artifact_hashes"],
    )
    world["manifest"]["artifact_hashes"] = dict(manifest.artifact_hashes)
    world["manifest"]["manifest_hash"] = manifest.manifest_hash
    path.write_text(json.dumps(world), encoding="utf-8")


@pytest.mark.parametrize("damage", [
    "missing", "legacy", "json", "tampered", "scope", "schema", "paths", "hash",
    "source", "version", "claims", "line", "permission", "unknown-field",
])
def test_unusable_cache_cold_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    source, pipeline = _workspace(tmp_path)
    pipeline.compile_workspace(source)
    path = pipeline.store.base / "parsed" / "WS-1.json"
    cache = json.loads(path.read_text(encoding="utf-8"))
    if damage == "missing":
        path.unlink()
    elif damage == "legacy":
        world_path = pipeline.store.base / "worlds" / "WS-1.json"
        world = json.loads(world_path.read_text(encoding="utf-8"))
        del world["artifact_hashes"]["parsed/documents"]
        manifest = publication_manifest(
            world_state_id="WS-1", compiler_version=world["compiler_version"],
            artifact_hashes=world["artifact_hashes"],
        )
        world["manifest"]["artifact_hashes"] = dict(manifest.artifact_hashes)
        world["manifest"]["manifest_hash"] = manifest.manifest_hash
        world_path.write_text(json.dumps(world), encoding="utf-8")
    elif damage == "json":
        path.write_text("{", encoding="utf-8")
    else:
        record = cache["documents"]["stable.py"]
        if damage == "tampered":
            record["claims"][0]["text"] = "The release is approved by everyone."
        elif damage == "scope":
            cache["context"]["tenant_id"] = "other-tenant"
        elif damage == "schema":
            cache["context"]["parser_schema"] = -1
        elif damage == "paths":
            del cache["documents"]["empty.md"]
        elif damage == "hash":
            record["sha256"] = "0" * 64
        elif damage == "source":
            record["source"] = "other-source"
        elif damage == "version":
            record["document_version"] = "other-version"
        elif damage == "claims":
            record["claims"] = None
        elif damage == "line":
            record["claims"][0]["line_number"] = True
        elif damage == "permission":
            record["required_permission"] = []
        elif damage == "unknown-field":
            record["extra"] = "unexpected"
        path.write_text(json.dumps(cache), encoding="utf-8")
        if damage != "tampered":
            _reseal(pipeline, cache)
    calls = _spy(monkeypatch)
    _edit(source)
    result = Pipeline(pipeline.store.root).recompile(source)
    assert result.published
    assert result.equivalence is not None and result.equivalence.equivalent
    assert calls["plan.md"] == 1
    assert calls["stable.py"] == 1
    if damage in {"missing", "legacy", "json", "tampered", "scope", "schema", "paths", "hash"}:
        assert calls["empty.md"] == 1
    else:
        assert calls["empty.md"] == 0


@pytest.mark.parametrize("option", ["tenant_id", "workspace_id", "connector_type", "max_depth"])
def test_context_options_cannot_hit_other_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, option: str
) -> None:
    source, pipeline = _workspace(tmp_path)
    pipeline.compile_workspace(source)
    calls = _spy(monkeypatch)
    value = 2 if option == "max_depth" else "other"
    restarted = Pipeline(pipeline.store.root, options=replace(CompileOptions(), **{option: value}))
    restarted.recompile(source)
    assert calls == Counter({"plan.md": 1, "stable.py": 1, "empty.md": 1})


def test_parser_version_change_cannot_reuse_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, pipeline = _workspace(tmp_path)
    pipeline.compile_workspace(source)
    calls = _spy(monkeypatch)
    monkeypatch.setattr(extraction, "PARSER_CACHE_VERSION", extraction.PARSER_CACHE_VERSION + 1)
    pipeline.recompile(source)
    assert calls == Counter({"plan.md": 1, "stable.py": 1, "empty.md": 1})


def test_forced_compile_remains_uncached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, pipeline = _workspace(tmp_path)
    pipeline.compile_workspace(source)
    calls = _spy(monkeypatch)
    assert pipeline.compile_workspace(source).published
    assert calls == Counter({"plan.md": 1, "stable.py": 1, "empty.md": 1})


def test_parser_artifact_write_precedes_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, pipeline = _workspace(tmp_path)
    pipeline.compile_workspace(source)
    pointer = (pipeline.store.base / "pointer.json").read_bytes()
    _edit(source)
    writes = []
    real_write = store._write_json_atomic

    def fail_cache(path: Path, payload: object) -> None:
        writes.append(path)
        if path.parent.name == "parsed":
            raise OSError("synthetic cache write failure")
        real_write(path, payload)

    monkeypatch.setattr(store, "_write_json_atomic", fail_cache)
    with pytest.raises(OSError, match="synthetic cache write failure"):
        pipeline.recompile(source)
    assert (pipeline.store.base / "pointer.json").read_bytes() == pointer
    assert writes[-1].parent.name == "parsed"
    assert all(path.name != "pointer.json" for path in writes)
