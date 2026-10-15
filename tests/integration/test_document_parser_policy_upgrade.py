"""Real prior-parser worlds upgraded through the production recompile entry point.

Direct stdlib unittest execution needs AKC_UPGRADE_LEGACY_V1_ROOT and
AKC_UPGRADE_LEGACY_V2_ROOT pointing to readonly historical runtime trees. The
targeted runner provides them; absent histories are an explicit integration
fixture prerequisite, never emulated with a parser or pytest stub.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from akc_cir.recompilation import content_hash
from akc_cir.world_state import PublishRefused, publication_manifest
from akc_compiler_runtime import Pipeline, extraction

REMAINING = "The shared entity remains available through October 2026."
EXISTING = "The shared entity is described in this record."
AVAILABILITY = "policies/availability.md"
UNRELATED = "notes/unrelated.md"
FILES = {
    AVAILABILITY: "---\nrequired_permission: entity.read\n---\n# Shared Entity\n\n"
    + EXISTING + "\n" + REMAINING + "\n",
    UNRELATED: "# Unrelated Record\n\nThe unrelated record is awaiting review.\n",
}
LEGACY_COMPILE = r'''
import hashlib, json, sys
from pathlib import Path
from akc_compiler_runtime import Pipeline, extraction
from akc_compiler_runtime import pipeline as runtime_pipeline
schema = int(sys.argv[3])
expected_extraction = {
    1: "3c5bf8c24e9cd4a12f380ec396ea0a3941e9f94d8b0d0b0530fc9d91d3066312",
    2: "45e9179ee9886b500986ef8314293c77e90acabc14c0420eabed78171edc5ae0",
}[schema]
extraction_sha = hashlib.sha256(Path(extraction.__file__).read_bytes()).hexdigest()
pipeline_sha = hashlib.sha256(Path(runtime_pipeline.__file__).read_bytes()).hexdigest()
assert extraction_sha == expected_extraction
assert pipeline_sha == "d794d9e7d1a5ac064ce27dfe6a1d5ba1c512993f88ea419e9c9b97f77f2dd154"
assert extraction.PARSER_CACHE_VERSION == schema
pipeline = Pipeline(Path(sys.argv[2]))
result = pipeline.compile_workspace(Path(sys.argv[1]))
world = pipeline.store.load_world()
assert result.published and world is not None
assert "parser/context" not in world.artifact_hashes
cache = json.loads((pipeline.store.base / "parsed/WS-1.json").read_text())
assert cache["context"]["parser_schema"] == schema
print(json.dumps({
    "parser_schema": schema, "extraction_file": extraction.__file__,
    "extraction_sha256": extraction_sha, "pipeline_file": runtime_pipeline.__file__,
    "pipeline_sha256": pipeline_sha, "world_state_id": world.world_state_id,
    "manifest_hash": world.manifest.manifest_hash,
    "values": sorted(row["value"] for row in world.claims.values()),
    "parser_context_marker_absent": True,
}))
'''


class TestDocumentParserPolicyUpgrade(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.legacy_v1 = os.environ.get("AKC_UPGRADE_LEGACY_V1_ROOT")
        cls.legacy_v2 = os.environ.get("AKC_UPGRADE_LEGACY_V2_ROOT")
        if not cls.legacy_v1 or not cls.legacy_v2:
            raise RuntimeError(
                "Historical parser fixtures missing; run "
                "scripts/prepare_parser_upgrade_fixtures.py and export both "
                "AKC_UPGRADE_LEGACY roots"
            )

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="parser-policy-upgrade-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.store = self.root / "store"

    def _write_sources(self, *, empty: bool = False) -> None:
        for relative, text in (() if empty else FILES.items()):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

    def _seed_legacy(self, schema: int = 1, *, empty: bool = False):
        self._write_sources(empty=empty)
        legacy = Path(self.legacy_v1 if schema == 1 else self.legacy_v2)
        environment = dict(os.environ)
        # pytest-cov would start coverage in this child from its cwd (a temp
        # dir without pyproject.toml): statement-only data that cannot combine
        # with the suite's branch data. The historical compiler is a fixture,
        # not coverage scope; same opt-out as test_ip_privilege_guard.py.
        for name in (
            "COV_CORE_SOURCE",
            "COV_CORE_CONFIG",
            "COV_CORE_DATAFILE",
            "COVERAGE_PROCESS_START",
        ):
            environment.pop(name, None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = os.pathsep.join((
            str(legacy / "packages/compiler-runtime/src"),
            str(Path(self.legacy_v1) / "packages/cir-python/src"),
        ))
        command = [
            sys.executable, "-c", LEGACY_COMPILE, str(self.source), str(self.store), str(schema),
        ]
        result = subprocess.run(  # noqa: S603 - fixed local historical compiler fixture.
            command, cwd=self.root, env=environment, capture_output=True,
            text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["parser_schema"], schema)
        self.assertEqual(record["world_state_id"], "WS-1")
        if not empty:
            self.assertEqual(REMAINING in record["values"], schema == 2)
        pipeline = Pipeline(self.store)
        previous = pipeline.store.load_world()
        self.assertIsNotNone(previous)
        assert previous is not None
        self.assertNotIn("parser/context", previous.artifact_hashes)
        immutable = self._old_world_bytes(pipeline)
        receipt_root = os.environ.get("AKC_UPGRADE_RECEIPTS_DIR")
        if receipt_root:
            target = Path(receipt_root) / self._testMethodName
            target.mkdir(parents=True, exist_ok=True)
            (target / "legacy-runtime.json").write_text(json.dumps(record, indent=2) + "\n")
            for relative, raw in immutable.items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            for relative, text in (() if empty else FILES.items()):
                path = target / "source" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
        print(json.dumps({"genuine_legacy_seed": self._testMethodName, **record}))
        return pipeline, previous, immutable

    @staticmethod
    def _old_world_bytes(pipeline: Pipeline) -> dict[str, bytes]:
        return {
            relative: (pipeline.store.base / relative).read_bytes()
            for relative in ("worlds/WS-1.json", "claims/WS-1.json", "parsed/WS-1.json")
        }

    @staticmethod
    def _store_bytes(pipeline: Pipeline) -> dict[str, bytes]:
        paths = [pipeline.store.base / "meta.json", pipeline.store.base / "pointer.json"]
        for directory in ("worlds", "claims", "parsed"):
            paths.extend(sorted((pipeline.store.base / directory).glob("*.json")))
        return {
            path.relative_to(pipeline.store.base).as_posix(): path.read_bytes() for path in paths
        }

    def _assert_marker(self, pipeline: Pipeline):
        world = pipeline.store.load_world()
        self.assertIsNotNone(world)
        assert world is not None
        marker = content_hash(pipeline._parser_context())
        self.assertEqual(world.artifact_hashes.get("parser/context"), marker)
        self.assertEqual(world.manifest.artifact_hashes.get("parser/context"), marker)
        rebuilt = publication_manifest(
            world_state_id=world.world_state_id,
            compiler_version=world.manifest.compiler_version,
            artifact_hashes=world.artifact_hashes,
        )
        self.assertEqual(rebuilt.manifest_hash, world.manifest.manifest_hash)
        return world

    def _assert_upgraded(self, pipeline, previous, result, immutable) -> None:
        self.assertTrue(result.published)
        self.assertFalse(result.no_op)
        self.assertEqual(result.previous_world_state_id, "WS-1")
        self.assertEqual(result.world_state_id, "WS-2")
        self.assertIsNone(result.equivalence)  # Existing full-compile path, not selective bypass.
        self.assertEqual(self._old_world_bytes(pipeline), immutable)
        world = self._assert_marker(pipeline)
        before = {row["value"]: row for row in previous.claims.values()}
        after = {row["value"]: row for row in world.claims.values()}
        self.assertIn(REMAINING, after)
        self.assertEqual(world.cursor[AVAILABILITY], previous.cursor[AVAILABILITY])
        for field in (
            "logical_id", "evidence_id", "sha256", "document_version_id", "required_permission",
        ):
            self.assertEqual(after[EXISTING][field], before[EXISTING][field])
        retained = after[REMAINING]
        self.assertEqual(retained["required_permission"], "entity.read")
        self.assertEqual(retained["temporal_source"], "unknown")
        self.assertIsNone(retained["valid_from"])
        self.assertIsNone(retained["valid_to"])
        cache = pipeline.store.load_parsed_cache(world, context=pipeline._parser_context())
        self.assertEqual(cache[AVAILABILITY]["required_permission"], "entity.read")
        self.assertIn(REMAINING, [claim["text"] for claim in cache[AVAILABILITY]["claims"]])

    def test_real_v1_unchanged_sources_upgrade_once_and_then_noop(self) -> None:
        pipeline, previous, immutable = self._seed_legacy()
        result = pipeline.recompile(self.source)
        self._assert_upgraded(pipeline, previous, result, immutable)
        before_noop = self._store_bytes(pipeline)
        again = Pipeline(self.store).recompile(self.source)
        self.assertTrue(again.no_op)
        self.assertFalse(again.published)
        self.assertEqual(again.world_state_id, "WS-2")
        self.assertEqual(self._store_bytes(pipeline), before_noop)

    def test_real_v1_unrelated_edit_matches_manual_full_recovery_then_normal_selective_oracle(
        self,
    ) -> None:
        pipeline, previous, immutable = self._seed_legacy()
        manual_store = self.root / "manual-full-store"
        shutil.copytree(self.store, manual_store)
        unrelated = self.source / UNRELATED
        unrelated.write_text("# Unrelated Record\n\nThe unrelated record is ready for review.\n")
        # Pre-fix default flow raises OracleRefused here. The repaired entry
        # point chooses full migration before carrying any old clean rows.
        result = pipeline.recompile(self.source)
        self._assert_upgraded(pipeline, previous, result, immutable)
        manual = Pipeline(manual_store).compile_workspace(self.source)
        self.assertEqual(result.claims, manual.claims)
        self.assertEqual(result.evidence_index, manual.evidence_index)
        self.assertEqual(result.manifest_hash, manual.manifest_hash)
        protected_before = {
            key: row for key, row in result.claims.items() if row["rel_path"] == AVAILABILITY
        }
        unrelated.write_text(
            "# Unrelated Record\n\nThe unrelated record is ready for final review.\n"
        )
        selective = pipeline.recompile(self.source)
        self.assertTrue(selective.published)
        self.assertIsNotNone(selective.equivalence)
        assert selective.equivalence is not None
        self.assertTrue(selective.equivalence.equivalent)
        self.assertEqual(
            {key: row for key, row in selective.claims.items() if row["rel_path"] == AVAILABILITY},
            protected_before,
        )
        self._assert_marker(pipeline)

    def test_real_markerless_v2_world_migrates_once_without_claim_or_identity_changes(self) -> None:
        pipeline, previous, immutable = self._seed_legacy(2)
        result = pipeline.recompile(self.source)
        self._assert_upgraded(pipeline, previous, result, immutable)
        self.assertEqual(result.claims, previous.claims)
        self.assertTrue(Pipeline(self.store).recompile(self.source).no_op)

    def test_real_empty_v1_world_migrates_once_then_keeps_noop_despite_empty_cache(self) -> None:
        pipeline, previous, immutable = self._seed_legacy(empty=True)
        result = pipeline.recompile(self.source)
        self.assertTrue(result.published)
        self.assertEqual(result.previous_world_state_id, previous.world_state_id)
        self.assertEqual(result.claims, {})
        self.assertEqual(self._old_world_bytes(pipeline), immutable)
        world = self._assert_marker(pipeline)
        self.assertEqual(
            pipeline.store.load_parsed_cache(world, context=pipeline._parser_context()), {}
        )
        snapshot = self._store_bytes(pipeline)
        self.assertTrue(Pipeline(self.store).recompile(self.source).no_op)
        self.assertEqual(self._store_bytes(pipeline), snapshot)

    def test_different_parser_context_marker_forces_one_same_prior_full_compile(self) -> None:
        self._write_sources()
        pipeline = Pipeline(self.store)
        initial = pipeline.compile_workspace(self.source)
        before = self._assert_marker(pipeline)
        changed = Pipeline(self.store, options=replace(pipeline.options, max_depth=1))
        self.assertNotEqual(
            content_hash(pipeline._parser_context()), content_hash(changed._parser_context())
        )
        upgraded = changed.recompile(self.source)
        self.assertTrue(upgraded.published)
        self.assertEqual(upgraded.previous_world_state_id, initial.world_state_id)
        self.assertEqual(upgraded.claims, before.claims)
        self.assertIsNone(upgraded.equivalence)
        self._assert_marker(changed)
        self.assertTrue(changed.recompile(self.source).no_op)

    def test_marker_present_missing_cache_cold_parses_without_forcing_full_publish(self) -> None:
        self._cache_miss_case(corrupt=False)

    def test_marker_present_corrupt_cache_cold_parses_and_keeps_selective_oracle(self) -> None:
        self._cache_miss_case(corrupt=True)

    def _cache_miss_case(self, *, corrupt: bool) -> None:
        self._write_sources()
        pipeline = Pipeline(self.store)
        initial = pipeline.compile_workspace(self.source)
        world = self._assert_marker(pipeline)
        cache = pipeline.store.base / "parsed" / f"{world.world_state_id}.json"
        if corrupt:
            cache.write_text("{", encoding="utf-8")
        else:
            cache.unlink()
        snapshot = self._store_bytes(pipeline)
        with patch.object(extraction, "parse_file", wraps=extraction.parse_file) as parse_spy:
            noop = pipeline.recompile(self.source)
        self.assertEqual(parse_spy.call_count, len(FILES))
        self.assertTrue(noop.no_op)
        self.assertEqual(noop.claims, initial.claims)
        self.assertEqual(self._store_bytes(pipeline), snapshot)
        (self.source / UNRELATED).write_text(
            "# Unrelated Record\n\nThe unrelated record is ready for review.\n"
        )
        with patch.object(extraction, "parse_file", wraps=extraction.parse_file) as parse_spy:
            selective = pipeline.recompile(self.source)
        self.assertEqual(parse_spy.call_count, len(FILES))
        self.assertTrue(selective.published)
        self.assertIsNotNone(selective.equivalence)
        assert selective.equivalence is not None
        self.assertTrue(selective.equivalence.equivalent)
        self._assert_marker(pipeline)

    def test_unsealed_extra_context_marker_cannot_authorize_incremental_reuse(self) -> None:
        pipeline, previous, _ = self._seed_legacy()
        path = pipeline.store.base / "worlds/WS-1.json"
        record = json.loads(path.read_text())
        original_manifest = record["manifest"]
        record["artifact_hashes"]["parser/context"] = content_hash(pipeline._parser_context())
        path.write_text(json.dumps(record), encoding="utf-8")
        reopened = Pipeline(self.store)
        loaded = reopened.store.load_world()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertNotIn("parser/context", loaded.manifest.artifact_hashes)
        self.assertEqual(loaded.manifest.verify(loaded.artifact_hashes), ())
        immutable = self._old_world_bytes(reopened)
        result = reopened.recompile(self.source)
        self._assert_upgraded(reopened, previous, result, immutable)
        self.assertEqual(json.loads(path.read_text())["manifest"], original_manifest)
        self.assertTrue(reopened.recompile(self.source).no_op)

    def test_corrupt_context_artifact_still_fails_existing_manifest_verification(self) -> None:
        self._write_sources()
        pipeline = Pipeline(self.store)
        pipeline.compile_workspace(self.source)
        world = self._assert_marker(pipeline)
        path = pipeline.store.base / "worlds" / f"{world.world_state_id}.json"
        record = json.loads(path.read_text())
        record["artifact_hashes"]["parser/context"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(record))
        with self.assertRaises(PublishRefused):
            Pipeline(self.store)
        self.assertEqual(pipeline.store.active_world_state_id(), world.world_state_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
