"""CI fixture provenance and adoption contracts; no legacy compilation cases run."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load_module("parser_upgrade_fixture", ROOT / "scripts/prepare_parser_upgrade_fixtures.py")


class TestParserUpgradeCIContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="parser-upgrade-ci-contract-")
        cls.addClassCleanup(temporary.cleanup)
        cls.temp = Path(temporary.name)
        cls.history_repo = Path(os.environ.get("AKC_UPGRADE_CI_HISTORY_REPO", str(ROOT)))
        cls.output = cls.temp / "fixtures"
        cls.env_file = cls.temp / "github-env.txt"
        cls.manifest = fixture.prepare(cls.history_repo, cls.output, cls.env_file)

    def test_every_historical_import_source_is_bound_to_fixed_commit_tree_and_blob(self) -> None:
        self.assertEqual(self.manifest["historical_commit"], fixture.HISTORICAL_COMMIT)
        self.assertEqual(self.manifest["historical_tree"], fixture.HISTORICAL_TREE)
        sources, blobs = fixture.historical_sources(self.history_repo)
        records = self.manifest["files"]
        self.assertEqual(len(records), 2 * len(sources))
        for schema in (1, 2):
            root = Path(self.manifest["roots"][str(schema)])
            selected = [record for record in records if record["schema"] == schema]
            self.assertEqual({record["path"] for record in selected}, sources.keys())
            for record in selected:
                relative = record["path"]
                raw = (root / relative).read_bytes()
                self.assertEqual(record["source_git_blob"], blobs[relative])
                self.assertEqual(record["source_sha256"], fixture.sha256(sources[relative]))
                self.assertEqual(record["fixture_sha256"], fixture.sha256(raw))
                self.assertEqual(record["fixture_git_blob"], fixture.git_blob(raw))
                if schema == 1 or relative != fixture.EXTRACTION_PATH:
                    self.assertEqual(raw, sources[relative])
        self.assertIn("unpublished", self.manifest["v2_origin"])
        self.assertEqual(
            json.loads((self.output / "fixture-manifest.json").read_text(encoding="utf-8")),
            self.manifest,
        )

    def test_exported_fixture_roots_import_real_historical_versions_and_origins(self) -> None:
        exports = dict(
            line.split("=", 1) for line in self.env_file.read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual(
            set(exports), {"AKC_UPGRADE_LEGACY_V1_ROOT", "AKC_UPGRADE_LEGACY_V2_ROOT"},
        )
        for schema in (1, 2):
            root = Path(exports[f"AKC_UPGRADE_LEGACY_V{schema}_ROOT"])
            self.assertEqual(str(root), self.manifest["roots"][str(schema)])
            environment = dict(os.environ)
            # Same pytest-cov opt-out as the upgrade test: this child runs from
            # a temp cwd without pyproject.toml, so inherited coverage would
            # write statement-only data the suite's branch data cannot combine.
            for name in (
                "COV_CORE_SOURCE",
                "COV_CORE_CONFIG",
                "COV_CORE_DATAFILE",
                "COVERAGE_PROCESS_START",
            ):
                environment.pop(name, None)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONPATH"] = os.pathsep.join((
                str(root / "packages/compiler-runtime/src"),
                str(root / "packages/cir-python/src"),
            ))
            command = [sys.executable, "-c", (
                "import json,hashlib; from pathlib import Path; "
                "from akc_compiler_runtime import extraction,pipeline; import akc_cir; "
                "print(json.dumps({'schema':extraction.PARSER_CACHE_VERSION,"
                "'files':[{'path':m.__file__,"
                "'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()} "
                "for m in (extraction,pipeline,akc_cir)]}))"
            )]
            result = subprocess.run(  # noqa: S603 - fixed local import probe, no compilation.
                command, cwd=self.temp, env=environment, capture_output=True,
                text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual(record["schema"], schema)
            self.assertEqual(record["files"][0]["sha256"], (
                fixture.V1_EXTRACTION_SHA256 if schema == 1 else fixture.V2_EXTRACTION_SHA256
            ))
            self.assertEqual(record["files"][1]["sha256"], fixture.LEGACY_PIPELINE_SHA256)
            for module in record["files"]:
                self.assertTrue(Path(module["path"]).is_relative_to(root))
            print(json.dumps({"historical_import_probe_only": True, **record}))

    def test_missing_local_history_fails_without_destination_or_environment_exports(self) -> None:
        empty_repo = self.temp / "no-history"
        empty_repo.mkdir()
        output = self.temp / "unsupported-fixtures"
        environment_file = self.temp / "unsupported-env.txt"
        with self.assertRaises(subprocess.CalledProcessError):
            fixture.prepare(empty_repo, output, environment_file)
        self.assertFalse(output.exists())
        self.assertFalse(environment_file.exists())
        with (
            patch.object(fixture, "HISTORICAL_TREE", "0" * 40),
            self.assertRaisesRegex(ValueError, "commit/tree mismatch"),
        ):
            fixture.prepare(self.history_repo, output, environment_file)
        self.assertFalse(output.exists())
        self.assertFalse(environment_file.exists())

    def test_existing_fixture_destination_is_refused(self) -> None:
        before = (self.output / "fixture-manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            fixture.prepare(self.history_repo, self.output, self.env_file)
        self.assertEqual((self.output / "fixture-manifest.json").read_bytes(), before)

    def test_v2_reconstruction_rejects_other_parser_bytes(self) -> None:
        raw = (Path(self.manifest["roots"]["1"]) / fixture.EXTRACTION_PATH).read_bytes()
        with self.assertRaisesRegex(ValueError, "Unpinned"):
            fixture.reconstruct_v2(raw + b"\n")
        self.assertEqual(fixture.sha256(fixture.reconstruct_v2(raw)), fixture.V2_EXTRACTION_SHA256)

    def _workflow(self, name: str, job: str, following_job: str) -> str:
        root = Path(os.environ.get("AKC_UPGRADE_CI_CONTRACT_ROOT", str(ROOT)))
        text = (root / ".github/workflows" / name).read_text(encoding="utf-8")
        return text.split(f"  {job}:\n", 1)[1].split(f"  {following_job}:\n", 1)[0]

    def test_focused_python_prepares_before_collection_and_executes_all_affected_files(
        self,
    ) -> None:
        text = self._workflow(
            "pr91-focused-qualification.yml", "python-focused", "application-images",
        )
        self.assertIn("fetch-depth: 0", text)
        preparation = "python scripts/prepare_parser_upgrade_fixtures.py"
        self.assertIn(preparation, text)
        self.assertLess(text.index(preparation), text.index("pytest --collect-only"))
        self.assertIn('--github-env "$GITHUB_ENV"', text)
        files = text.split("          files=(\n", 1)[1].split("          )", 1)[0].split()
        self.assertEqual(len(files), len(set(files)))
        self.assertIn("tests/unit/test_document_remaining_state_extraction.py", files)
        self.assertIn("tests/integration/test_document_parser_policy_upgrade.py", files)
        self.assertIn("tests/unit/test_parser_upgrade_ci_contract.py", files)
        self.assertIn('pytest "${files[@]}"', text)
        self.assertIn("BASE_SHA: 956b2efb458bb6062e94f83247acd83696bd3a57", text)
        self.assertIn('check "Full-tree collection" "$COLLECT_OUTCOME"', text)

    def test_broad_python_prepares_both_interpreters_before_existing_pytest_gates(self) -> None:
        text = self._workflow("ci.yml", "python-core", "web-and-contracts")
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("persist-credentials: false", text)
        preparation = "python scripts/prepare_parser_upgrade_fixtures.py"
        self.assertIn(preparation, text)
        self.assertIn('--github-env "$GITHUB_ENV"', text)
        self.assertLess(
            text.index(preparation), text.index("Test with core-library coverage gate"),
        )
        self.assertIn('python-version: ["3.12", "3.13"]', text)
        self.assertIn("--cov-fail-under=80", text)
        self.assertEqual(text.count("python -m uv run --locked --extra dev pytest"), 2)

    def test_missing_upgrade_roots_raise_error_instead_of_skipping_class(self) -> None:
        root = Path(os.environ.get("AKC_UPGRADE_CI_CONTRACT_ROOT", str(ROOT)))
        module = load_module(
            "parser_upgrade_integration_contract",
            root / "tests/integration/test_document_parser_policy_upgrade.py",
        )
        with patch.dict(os.environ, {}, clear=True):
            try:
                with self.assertRaisesRegex(RuntimeError, "Historical parser fixtures missing"):
                    module.TestDocumentParserPolicyUpgrade.setUpClass()
            except unittest.SkipTest:
                self.fail("Missing historical fixtures skipped the entire upgrade class")


if __name__ == "__main__":
    unittest.main(verbosity=2)
