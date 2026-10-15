"""Routing over actual local Git metadata; all new commits/events are synthetic.

No runtime compilation, network, CI dispatch or previous test suite execution.
Historical Git objects are read from the checkout; writes stay in a temporary
repository with no remote. The private reviewed tree object is not required.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/classify_pr91_affected_scope.py"
spec = importlib.util.spec_from_file_location("pr91_scope_classifier", SCRIPT)
assert spec is not None and spec.loader is not None
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class TestPR91AffectedScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="pr91-scope-synthetic-git-")
        cls.addClassCleanup(temporary.cleanup)
        cls.temp = Path(temporary.name)
        cls.repo = cls.temp / "synthetic-repository"
        cls.git_executable = shutil.which("git")
        if cls.git_executable is None:
            raise RuntimeError("Actual Git required; no metadata stubs permitted")
        cls.environment = dict(os.environ)
        cls.environment.update(
            {
                "GIT_AUTHOR_NAME": "Synthetic CI contract fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic CI contract fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_AUTHOR_DATE": "2026-10-10T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2026-10-10T00:00:00+00:00",
                "GIT_NO_REPLACE_OBJECTS": "1",
            }
        )
        overlay_file = os.environ.get("AKC_PR91_SCOPE_GIT_OBJECT_ENV")
        if overlay_file:
            overlay = json.loads(Path(overlay_file).read_text(encoding="utf-8"))
            objects = [overlay["GIT_OBJECT_DIRECTORY"]]
            objects.extend(overlay["GIT_ALTERNATE_OBJECT_DIRECTORIES"].split(os.pathsep))
        else:
            history_repo = Path(os.environ.get("AKC_PR91_SCOPE_HISTORY_REPO", str(ROOT)))
            result = subprocess.run(  # noqa: S603 - fixed local Git object-directory lookup.
                [cls.git_executable, "-C", str(history_repo), "rev-parse", "--git-path", "objects"],
                capture_output=True,
                text=True,
                check=True,
            )
            path = Path(result.stdout.strip())
            objects = [str(path if path.is_absolute() else history_repo / path)]
        cls.environment.pop("GIT_OBJECT_DIRECTORY", None)
        cls.environment.pop("GIT_INDEX_FILE", None)
        cls.environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(objects)
        subprocess.run(  # noqa: S603 - local temporary repository, no remote or source writes.
            [cls.git_executable, "init", "--quiet", str(cls.repo)],
            env=cls.environment,
            check=True,
            capture_output=True,
        )
        cls.environment["GIT_INDEX_FILE"] = str(cls.temp / "synthetic.index")
        cls._git("read-tree", scope.ANCHOR_TREE)
        for path, blob in scope.PINNED_PAYLOAD.items():
            cls._git("update-index", "--add", "--cacheinfo", "100644", blob, path)
        # Explicit synthetic workflow/control data tests classification only.
        for path in (
            ".github/workflows/ci.yml",
            ".github/workflows/pr91-focused-qualification.yml",
            "scripts/classify_pr91_affected_scope.py",
            "tests/unit/test_pr91_affected_scope.py",
            "tests/unit/test_pr91_affected_workflow_contract.py",
        ):
            cls._add(path, b"# Synthetic routing metadata fixture; no CI execution\n")
        cls.payload_tree = cls._git("write-tree").decode().strip()
        cls.head = cls._commit(cls.payload_tree)
        cls._git("update-ref", "refs/heads/synthetic-routing-fixture", cls.head)
        cls._git("symbolic-ref", "HEAD", "refs/heads/synthetic-routing-fixture")
        cls.previous_anchor = (
            cls._git("rev-list", "--parents", "-n", "1", scope.ANCHOR_COMMIT).decode().split()[1]
        )

    @classmethod
    def _git(cls, *arguments: str, raw: bytes | None = None) -> bytes:
        return subprocess.run(  # noqa: S603 - fixed Git operations in temporary synthetic repo.
            [cls.git_executable, "-C", str(cls.repo), *arguments],
            input=raw,
            env=cls.environment,
            capture_output=True,
            check=True,
        ).stdout

    @classmethod
    def _add(cls, path: str, raw: bytes, mode: str = "100644") -> None:
        blob = cls._git("hash-object", "-w", "--stdin", raw=raw).decode().strip()
        cls._git("update-index", "--add", "--cacheinfo", mode, blob, path)

    @classmethod
    def _commit(cls, tree: str, parent: str | None = None) -> str:
        return (
            cls._git(
                "commit-tree",
                tree,
                "-p",
                parent or scope.ANCHOR_COMMIT,
                raw=b"Synthetic local-only routing contract metadata\n",
            )
            .decode()
            .strip()
        )

    def setUp(self) -> None:
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", self.head)

    def _event(self, *, number: int = 91, base: str | None = None) -> dict:
        return {
            "repository": {"full_name": scope.REPOSITORY},
            "number": number,
            "pull_request": {
                "number": number,
                "head": {"sha": self.head, "repo": {"full_name": scope.REPOSITORY}},
                "base": {"sha": base or scope.ANCHOR_COMMIT},
            },
        }

    def _classify(self, event: dict | None = None, *, name="pull_request", kind="ci") -> dict:
        with patch.dict(os.environ, self.environment, clear=True):
            return scope.classify(self.repo, event or self._event(), name, kind)

    def _changed_head(self, changes: dict[str, bytes | None], *, mode="100644") -> str:
        self._git("read-tree", self.payload_tree)
        for path, raw in changes.items():
            if raw is None:
                self._git("update-index", "--force-remove", path)
            else:
                self._add(path, raw, mode)
        head = self._commit(self._git("write-tree").decode().strip())
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", head)
        return head

    def test_known_payload_and_named_controls_select_only_required_checks(self) -> None:
        result = self._classify()
        self.assertEqual(result["mode"], "parser-delta", result)
        self.assertFalse(result["full_qualification"])
        self.assertEqual(
            result["selection"],
            {
                "python": True,
                "images": False,
                "web": False,
                "db": False,
                "model": False,
                "joined": False,
                "security_core": True,
                "dependency_audit": False,
                "codeql_languages": ["python"],
            },
        )
        self.assertEqual(len(result["required_tests"]), 16)
        self.assertEqual(result["identity"]["head_commit"], self.head)
        self.assertEqual(result["delta"]["base_commit"], scope.ANCHOR_COMMIT)
        self.assertIn("Static anchor/head equality", result["unchanged_inputs"]["qualification"])
        self.assertNotIn(
            "packages/compiler-runtime/src/akc_compiler_runtime",
            result["unchanged_inputs"]["wheel_packages"],
        )
        self.assertEqual(
            result["delta"]["python_paths"],
            sorted(row["path"] for row in result["delta"]["paths"] if row["path"].endswith(".py")),
        )
        self.assertIn("no test/audit/image/release pass", result["qualification_semantics"])

    def test_cumulative_pr_changes_are_recorded_separately_and_do_not_route_delta(self) -> None:
        result = self._classify(self._event(base=self.previous_anchor))
        self.assertEqual(result["mode"], "parser-delta", result)
        self.assertEqual(result["cumulative_pr_diff"]["merge_base"], self.previous_anchor)
        self.assertNotEqual(result["cumulative_pr_diff"]["paths"], result["delta"]["paths"])
        self.assertEqual(result["delta"]["base_commit"], scope.ANCHOR_COMMIT)

    def test_same_scope_decision_for_each_workflow_kind(self) -> None:
        for kind in sorted(scope.WORKFLOW_KINDS):
            with self.subTest(kind=kind):
                self.assertEqual(self._classify(kind=kind)["mode"], "parser-delta")

    def test_head_mismatch_fork_and_malformed_event_fail_closed(self) -> None:
        mismatch = self._event()
        mismatch["pull_request"]["head"]["sha"] = scope.ANCHOR_COMMIT
        fork = self._event()
        fork["pull_request"]["head"]["repo"]["full_name"] = "synthetic/fork"
        wrong_number = self._event()
        wrong_number["pull_request"]["number"] = 92
        for event in (mismatch, fork, wrong_number, {"repository": {}}, []):
            with self.subTest(event=event):
                with patch.dict(os.environ, self.environment, clear=True):
                    result = scope.classify(self.repo, event, "pull_request", "ci")
                self.assertEqual(result["mode"], "broad-required")
                self.assertFalse(result["selection"]["python"])

    def test_unknown_paths_lock_changes_and_ci_control_near_matches_fail_closed(self) -> None:
        for path in (
            "unexpected.md",
            "uv.lock",
            ".github/workflows/ci.yml.extra",
            "scripts/another_router.py",
        ):
            with self.subTest(path=path):
                head = self._changed_head({path: b"Synthetic unknown input\n"})
                event = self._event()
                event["pull_request"]["head"]["sha"] = head
                result = self._classify(event)
                self.assertEqual(result["mode"], "broad-required")
                self.assertIn("unknown-path", result["reason_codes"])

    def test_k06_exact_test_delta_requires_parser_route(self) -> None:
        path = scope.K06_TEST_DELTA_PATH
        self.assertIn(path, scope.REQUIRED_TESTS)
        head = self._changed_head({path: b"# Synthetic K06 test correction\n"})
        event = self._event()
        event["pull_request"]["head"]["sha"] = head
        for kind in sorted(scope.WORKFLOW_KINDS):
            with self.subTest(kind=kind):
                result = self._classify(event, kind=kind)
                self.assertEqual(result["mode"], "parser-delta", result)
                self.assertTrue(result["selection"]["python"])
                self.assertFalse(result["full_qualification"])
                self.assertIn(path, result["delta"]["python_paths"])
                self.assertIn(path, result["required_tests"])

        self._git("read-tree", scope.ANCHOR_TREE)
        self._add(path, b"# Synthetic K06-only test correction\n")
        k06_only = self._commit(self._git("write-tree").decode().strip())
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", k06_only)
        event["pull_request"]["head"]["sha"] = k06_only
        result = self._classify(event)
        self.assertEqual(result["mode"], "broad-required")
        self.assertIn("unsupported-combination", result["reason_codes"])

    def test_k06_near_match_deletion_and_symlink_still_fail_closed(self) -> None:
        path = scope.K06_TEST_DELTA_PATH
        for changed, mode, reason in (
            ({path + ".extra": b"# Near match\n"}, "100644", "unknown-path"),
            (
                {"tests/integration/another_runtime_test.py": b"# New path\n"},
                "100644",
                "unknown-path",
            ),
            ({path: None}, "100644", "unsupported-change"),
            ({path: b"symlink-target"}, "120000", "unsupported-change"),
        ):
            with self.subTest(paths=list(changed), mode=mode):
                head = self._changed_head(changed, mode=mode)
                event = self._event()
                event["pull_request"]["head"]["sha"] = head
                result = self._classify(event)
                self.assertEqual(result["mode"], "broad-required")
                self.assertIn(reason, result["reason_codes"])

    def test_each_of_six_frozen_payload_blobs_is_mandatory(self) -> None:
        for path in scope.PINNED_PAYLOAD:
            with self.subTest(path=path):
                head = self._changed_head({path: b"Synthetic payload drift\n"})
                event = self._event()
                event["pull_request"]["head"]["sha"] = head
                result = self._classify(event)
                self.assertEqual(result["mode"], "broad-required")
                self.assertIn("payload-mismatch", result["reason_codes"])

    def test_deleted_renamed_symlink_and_executable_controls_are_not_admitted(self) -> None:
        path = "scripts/classify_pr91_affected_scope.py"
        cases = [
            ({path: None}, "100644"),
            ({path: None, "scripts/renamed_scope.py": b"Synthetic rename\n"}, "100644"),
            ({path: b"synthetic-link-target"}, "120000"),
            ({path: b"Synthetic executable\n"}, "100755"),
        ]
        for changes, mode in cases:
            with self.subTest(mode=mode, changes=list(changes)):
                head = self._changed_head(changes, mode=mode)
                event = self._event()
                event["pull_request"]["head"]["sha"] = head
                self.assertEqual(self._classify(event)["mode"], "broad-required")

    def test_missing_history_bad_anchor_and_divergent_lineage_fail_closed(self) -> None:
        missing = self._event(base="0" * 40)
        self.assertEqual(self._classify(missing)["mode"], "broad-required")
        with patch.object(scope, "ANCHOR_TREE", "0" * 40):
            self.assertIn("anchor-tree-mismatch", self._classify()["reason_codes"])
        with patch.object(scope, "ANCHOR_COMMIT", "0" * 40):
            self.assertEqual(self._classify()["mode"], "broad-required")
        # A real orphan synthetic commit, not a fabricated ancestry response.
        orphan = (
            self._git("commit-tree", self.payload_tree, raw=b"Synthetic orphan\n").decode().strip()
        )
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", orphan)
        event = self._event(base=orphan)
        event["pull_request"]["head"]["sha"] = orphan
        self.assertEqual(self._classify(event)["mode"], "broad-required")

    def test_missing_required_control_test_source_is_not_a_narrow_pass(self) -> None:
        head = self._changed_head({"tests/unit/test_pr91_affected_workflow_contract.py": None})
        event = self._event()
        event["pull_request"]["head"]["sha"] = head
        self.assertEqual(self._classify(event)["mode"], "broad-required")

    def test_original_other_pr_main_manual_and_schedule_policies_remain_full(self) -> None:
        events = [
            ("pull_request", self._event(number=92)),
            (
                "push",
                {
                    "repository": {"full_name": scope.REPOSITORY},
                    "ref": "refs/heads/main",
                    "after": self.head,
                },
            ),
            ("workflow_dispatch", {"repository": {"full_name": scope.REPOSITORY}}),
            ("schedule", {"repository": {"full_name": scope.REPOSITORY}}),
        ]
        for name, event in events:
            with self.subTest(name=name):
                result = self._classify(event, name=name)
                self.assertEqual(result["mode"], "full", result)
                self.assertTrue(result["full_qualification"])
                self.assertTrue(result["selection"]["dependency_audit"])
                self.assertEqual(
                    result["selection"]["codeql_languages"], ["python", "javascript-typescript"]
                )
        invalid = deepcopy(events[1][1])
        invalid["ref"] = "refs/heads/synthetic-other-branch"
        self.assertEqual(self._classify(invalid, name="push")["mode"], "broad-required")

    def test_cli_outputs_selection_and_no_pass_outputs_for_required_broad(self) -> None:
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                event = self._event()
                if not accepted:
                    event["pull_request"]["head"]["sha"] = "0" * 40
                prefix = self.temp / f"cli-{accepted}"
                event_path = prefix.with_suffix(".event.json")
                output = prefix.with_suffix(".receipt.json")
                github_output = prefix.with_suffix(".github-output.txt")
                event_path.write_text(json.dumps(event), encoding="utf-8")
                command = [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(self.repo),
                    "--event-path",
                    str(event_path),
                    "--event-name",
                    "pull_request",
                    "--workflow-kind",
                    "ci",
                    "--output",
                    str(output),
                    "--github-output",
                    str(github_output),
                ]
                result = subprocess.run(  # noqa: S603 - fixed local classifier CLI.
                    command,
                    env=self.environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(result.returncode, 0 if accepted else 1, result.stderr)
                record = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(record["mode"], "parser-delta" if accepted else "broad-required")
                if accepted:
                    outputs = dict(
                        line.split("=", 1)
                        for line in github_output.read_text(encoding="utf-8").splitlines()
                    )
                    self.assertEqual(outputs["mode"], "parser-delta")
                    self.assertEqual(outputs["full_qualification"], "false")
                    self.assertEqual(json.loads(outputs["codeql_languages"]), ["python"])
                else:
                    self.assertFalse(github_output.exists())
                print(
                    json.dumps(
                        {
                            "synthetic_cli_contract": True,
                            "accepted": accepted,
                            "exit_code": result.returncode,
                            "mode": record["mode"],
                        }
                    )
                )

    def _joined_registration_head(self, overrides=None, modes=None) -> str:
        # Actual synthetic Git metadata only, never the reviewed Node runtime payload.
        changes = {
            path: b"// Synthetic joined selection source; not runtime evidence\n"
            for path in scope.JOINED_SOURCE_PATHS
        }
        changes.update(overrides or {})
        self._git("read-tree", self.payload_tree)
        for path, raw in changes.items():
            if raw is None:
                self._git("update-index", "--force-remove", path)
            elif (modes or {}).get(path) == "160000":
                self._git("update-index", "--add", "--cacheinfo", "160000", self.head, path)
            else:
                self._add(path, raw, (modes or {}).get(path, "100644"))
        head = self._commit(self._git("write-tree").decode().strip())
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", head)
        return head

    def _joined_registration_event(self, head: str) -> dict:
        event = self._event()
        event["pull_request"]["head"]["sha"] = head
        return event

    def test_joined_registration_exact_eight_sources_select_joined_in_each_workflow(self) -> None:
        expected_paths = {
            "tests/e2e/joined/g1-11-runtime-producer.mjs",
            "tests/e2e/joined/g1-11-runtime-producer.test.mjs",
            "tests/e2e/joined/g1-11-producer-review-correction.test.mjs",
            "tests/e2e/joined/HOOKS-AND-REVIEW.md",
            "tests/e2e/joined/g1-11-seven-member-scenario.mjs",
            "tests/e2e/joined/g1-11-seven-member-scenario.test.mjs",
            "tests/e2e/joined/joined-e2e.mjs",
            "tests/e2e/joined/materialize-g1-11-contract-fixture.mjs",
        }
        self.assertEqual(set(scope.JOINED_SOURCE_PATHS), expected_paths)
        self.assertEqual(len(scope.JOINED_SOURCE_PATHS), 8)
        head = self._joined_registration_head()
        event = self._joined_registration_event(head)
        for kind in sorted(scope.WORKFLOW_KINDS):
            with self.subTest(kind=kind):
                result = self._classify(event, kind=kind)
                self.assertEqual(result["mode"], "parser-delta", result)
                self.assertFalse(result["full_qualification"])
                self.assertEqual(
                    result["selection"],
                    {
                        "python": True,
                        "images": False,
                        "web": False,
                        "db": False,
                        "model": False,
                        "joined": True,
                        "security_core": True,
                        "dependency_audit": False,
                        "codeql_languages": ["python"],
                    },
                )
                self.assertEqual(set(result["joined_sources"]["changed_paths"]), expected_paths)
                self.assertEqual(set(result["joined_sources"]["entries"]), expected_paths)
                self.assertEqual(result["required_tests"], list(scope.REQUIRED_TESTS))
                self.assertEqual(len(result["required_tests"]), 16)
                self.assertEqual(
                    result["required_joined_tests"],
                    [
                        "tests/e2e/joined/g1-11-runtime-producer.test.mjs",
                        "tests/e2e/joined/g1-11-producer-review-correction.test.mjs",
                        "tests/e2e/joined/g1-11-seven-member-scenario.test.mjs",
                    ],
                )
                for path, row in result["joined_sources"]["entries"].items():
                    self.assertEqual(row["mode"], "100644")
                    self.assertEqual(row["kind"], "blob")
                    self.assertEqual(
                        row["blob"], self._git("rev-parse", f"{head}:{path}").decode().strip()
                    )
                self.assertIn("no Node or runtime pass", result["joined_sources"]["qualification"])
        for path, blob in scope.PINNED_PAYLOAD.items():
            self.assertEqual(self._git("rev-parse", f"{head}:{path}").decode().strip(), blob)
        print(
            json.dumps(
                {
                    "synthetic_joined_routing": True,
                    "head": head,
                    "source_count": 8,
                    "payload_count": 6,
                    "runtime_executed": False,
                }
            )
        )

    def test_joined_registration_parser_only_false_and_original_full_policy_unchanged(self) -> None:
        parser = self._classify()
        self.assertEqual(parser["mode"], "parser-delta", parser)
        self.assertFalse(parser["selection"]["joined"])
        self.assertEqual(parser["required_joined_tests"], [])
        self.assertIsNone(parser["joined_sources"])
        head = self._joined_registration_head()
        event = self._joined_registration_event(head)
        event["number"] = event["pull_request"]["number"] = 92
        full = self._classify(event)
        self.assertEqual(full["mode"], "full", full)
        self.assertTrue(full["full_qualification"])
        self.assertEqual(
            full["selection"],
            {
                "python": True,
                "images": True,
                "web": True,
                "db": True,
                "model": True,
                "joined": True,
                "security_core": True,
                "dependency_audit": True,
                "codeql_languages": ["python", "javascript-typescript"],
            },
        )

    def test_joined_registration_every_source_is_mandatory_when_activated(self) -> None:
        for path in scope.JOINED_SOURCE_PATHS:
            with self.subTest(missing=path):
                head = self._joined_registration_head({path: None})
                result = self._classify(self._joined_registration_event(head))
                self.assertEqual(result["mode"], "broad-required", result)
                self.assertFalse(result["selection"]["joined"])
                self.assertFalse(result["full_qualification"])
                # An anchor-existing file is a forbidden deletion; newly registered sources
                # absent at both revisions fail the full finite source-presence contract.
                self.assertTrue(
                    {"joined-source-missing", "unsupported-change"}.intersection(
                        result["reason_codes"]
                    ),
                    result,
                )
                self.assertEqual(result["required_joined_tests"], [])

    def test_joined_registration_unsafe_modes_deletion_and_rename_fail_closed(self) -> None:
        path = "tests/e2e/joined/g1-11-runtime-producer.mjs"
        for mode in ("100755", "120000", "160000"):
            with self.subTest(mode=mode):
                head = self._joined_registration_head(modes={path: mode})
                result = self._classify(self._joined_registration_event(head))
                self.assertEqual(result["mode"], "broad-required", result)
                self.assertIn("unsupported-change", result["reason_codes"])
                self.assertFalse(result["selection"]["joined"])
        old = "tests/e2e/joined/joined-e2e.mjs"
        for overrides in (
            {old: None},
            {old: None, "tests/e2e/joined/renamed-joined-e2e.mjs": b"// Synthetic rename target\n"},
        ):
            with self.subTest(changes=list(overrides)):
                head = self._joined_registration_head(overrides)
                result = self._classify(self._joined_registration_event(head))
                self.assertEqual(result["mode"], "broad-required", result)
                self.assertTrue(
                    {"unsupported-change", "unknown-path"}.intersection(result["reason_codes"]),
                    result,
                )
                self.assertFalse(result["selection"]["joined"])

    def _joined_registration_raw_path_head(self, path: str, raw: bytes) -> str:
        # Git for Windows refuses LF names in update-index. Preserve the negative
        # with genuine raw tree objects; never materialize this path on disk/index.
        regular_head = self._joined_registration_head()
        root = self._git("rev-parse", regular_head + "^{tree}").decode().strip()
        blob = self._git("hash-object", "-w", "--stdin", raw=raw).decode().strip()

        def insert(tree: str, parts: list[bytes]) -> str:
            entries = {}
            for row in self._git("ls-tree", "-z", tree).split(b"\0"):
                if row:
                    metadata, name = row.split(b"\t", 1)
                    entries[name] = metadata
            name = parts[0]
            if len(parts) == 1:
                entries[name] = f"100644 blob {blob}".encode("ascii")
            else:
                metadata = entries[name].split()
                self.assertEqual(metadata[1], b"tree")
                subtree = insert(metadata[2].decode("ascii"), parts[1:])
                entries[name] = f"040000 tree {subtree}".encode("ascii")
            payload = b"".join(
                metadata + b"\t" + name + b"\0" for name, metadata in entries.items()
            )
            return self._git("mktree", "-z", raw=payload).decode().strip()

        tree = insert(root, path.encode("utf-8").split(b"/"))
        head = self._commit(tree, parent=regular_head)
        self.assertIn(b"\t" + path.encode("utf-8") + b"\0", self._git("ls-tree", "-r", "-z", head))
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", head)
        return head

    def test_joined_registration_near_matches_and_linebreak_paths_never_broaden(self) -> None:
        for path, reason in (
            ("tests/e2e/joined/g1-11-runtime-producer.mjs.extra", "unknown-path"),
            ("tests/e2e/joined/another-contract.test.mjs", "unknown-path"),
            ("tests/e2e/joined/materialize-g1-11-contract-fixture.mjs.extra", "unknown-path"),
            ("tests/e2e/joined/g1-11-runtime-producer.mjs\nuntrusted", "invalid-path"),
        ):
            with self.subTest(path=path):
                raw = b"// Synthetic unknown source\n"
                head = (
                    self._joined_registration_raw_path_head(path, raw)
                    if "\n" in path or "\r" in path
                    else self._joined_registration_head({path: raw})
                )
                result = self._classify(self._joined_registration_event(head))
                self.assertEqual(result["mode"], "broad-required", result)
                self.assertIn(reason, result["reason_codes"])
                self.assertFalse(result["selection"]["joined"])
                self.assertFalse(result["selection"]["python"])
                self.assertFalse(result["full_qualification"])

    def test_joined_registration_cannot_relax_frozen_parser_payload(self) -> None:
        path = "packages/compiler-runtime/src/akc_compiler_runtime/extraction.py"
        head = self._joined_registration_head({path: b"# Synthetic parser payload drift\n"})
        result = self._classify(self._joined_registration_event(head))
        self.assertEqual(result["mode"], "broad-required", result)
        self.assertIn("payload-mismatch", result["reason_codes"])
        self.assertFalse(result["selection"]["joined"])
        self.assertFalse(result["selection"]["python"])
        self.assertIsNone(result["joined_sources"])

    def test_joined_registration_valid_sources_cannot_override_event_identity(self) -> None:
        head = self._joined_registration_head()
        mismatch = self._joined_registration_event(head)
        mismatch["pull_request"]["head"]["sha"] = self.head
        fork = self._joined_registration_event(head)
        fork["pull_request"]["head"]["repo"]["full_name"] = "synthetic/fork"
        for event, reason in ((mismatch, "head-mismatch"), (fork, "fork-or-missing-repo")):
            with self.subTest(reason=reason):
                result = self._classify(event)
                self.assertEqual(result["mode"], "broad-required", result)
                self.assertIn(reason, result["reason_codes"])
                self.assertFalse(result["selection"]["joined"])

    def test_joined_registration_cli_exports_true_only_for_valid_finite_sources(self) -> None:
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                overrides = (
                    {}
                    if accepted
                    else {"tests/e2e/joined/not-registered.mjs": b"// Synthetic unknown source\n"}
                )
                head = self._joined_registration_head(overrides)
                event = self._joined_registration_event(head)
                prefix = self.temp / f"joined-cli-{accepted}"
                event_path = prefix.with_suffix(".event.json")
                output = prefix.with_suffix(".receipt.json")
                github_output = prefix.with_suffix(".github-output.txt")
                event_path.write_text(json.dumps(event), encoding="utf-8")
                result = subprocess.run(  # noqa: S603 - fixed local classifier CLI, not CI.
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--repo",
                        str(self.repo),
                        "--event-path",
                        str(event_path),
                        "--event-name",
                        "pull_request",
                        "--workflow-kind",
                        "joined",
                        "--output",
                        str(output),
                        "--github-output",
                        str(github_output),
                    ],
                    env=self.environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(result.returncode, 0 if accepted else 1, result.stderr)
                record = json.loads(output.read_text(encoding="utf-8"))
                if accepted:
                    values = dict(
                        line.split("=", 1)
                        for line in github_output.read_text(encoding="utf-8").splitlines()
                    )
                    self.assertEqual(values["mode"], "parser-delta")
                    self.assertEqual(values["joined"], "true")
                    self.assertEqual(values["full_qualification"], "false")
                    for name in ("images", "web", "db", "model", "dependency_audit"):
                        self.assertEqual(values[name], "false")
                    self.assertTrue(record["selection"]["joined"])
                else:
                    self.assertFalse(github_output.exists())
                    self.assertEqual(record["mode"], "broad-required")
                    self.assertFalse(record["selection"]["joined"])
                print(
                    json.dumps(
                        {
                            "synthetic_joined_cli": True,
                            "accepted": accepted,
                            "exit_code": result.returncode,
                            "runtime_executed": False,
                        }
                    )
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestK15FiniteEntityAdmission(unittest.TestCase):
    """New contracts share only fixture helpers; discovery never duplicates prior tests."""

    setUpClass = TestPR91AffectedScope.__dict__["setUpClass"]
    setUp = TestPR91AffectedScope.__dict__["setUp"]
    _git = TestPR91AffectedScope.__dict__["_git"]
    _add = TestPR91AffectedScope.__dict__["_add"]
    _commit = TestPR91AffectedScope.__dict__["_commit"]
    _event = TestPR91AffectedScope.__dict__["_event"]
    _classify = TestPR91AffectedScope.__dict__["_classify"]

    def _k15_head(self, *, parser=True, joined=False, overrides=None, modes=None):
        self._git("read-tree", self.payload_tree if parser else scope.ANCHOR_TREE)
        for path in (
            "scripts/classify_pr91_affected_scope.py",
            "tests/unit/test_pr91_affected_scope.py",
            "tests/unit/test_pr91_affected_workflow_contract.py",
        ):
            self._add(path, b"# Synthetic exact routing control fixture\n")
        for path, blob in scope.ENTITY_PAYLOAD.items():
            self._git("update-index", "--add", "--cacheinfo", "100644", blob, path)
        if joined:
            for path in scope.JOINED_SOURCE_PATHS:
                self._add(path, b"// Synthetic joined source presence, not G1 evidence\n")
        for path, raw in (overrides or {}).items():
            if raw is None:
                self._git("update-index", "--force-remove", path)
            else:
                mode = (modes or {}).get(path, "100644")
                if mode == "160000":
                    self._git(
                        "update-index", "--add", "--cacheinfo", mode, scope.ANCHOR_COMMIT, path
                    )
                else:
                    self._add(path, raw, mode)
        head = self._commit(self._git("write-tree").decode().strip())
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", head)
        return head

    def _k15_event(self, head):
        event = self._event()
        event["pull_request"]["head"]["sha"] = head
        return event

    def test_k15_exact_pair_and_entity_only_selection(self):
        self.assertEqual(
            scope.ENTITY_PAYLOAD,
            {
                "packages/cir-python/src/akc_cir/entity.py":
                    "7536ab16f28be68d2d6d43aa261702f5bb491349",
                "tests/unit/test_entity.py": "aeddade75b55a00b70ffe0a7aed05a89a3123839",
            },
        )
        head = self._k15_head(parser=False)
        for kind in scope.WORKFLOW_KINDS:
            result = self._classify(self._k15_event(head), kind=kind)
            self.assertEqual(result["mode"], "entity-delta", result)
            self.assertEqual(result["required_tests"], list(scope.ENTITY_REQUIRED_TESTS))
            self.assertEqual(result["required_joined_tests"], [])
            self.assertFalse(result["full_qualification"])
            self.assertEqual(
                result["selection"],
                {
                    "python": True,
                    "images": False,
                    "web": False,
                    "db": False,
                    "model": False,
                    "joined": False,
                    "security_core": True,
                    "dependency_audit": False,
                    "codeql_languages": ["python"],
                },
            )
            self.assertEqual(set(result["entity_sources"]["entries"]), set(scope.ENTITY_PAYLOAD))

    def test_k15_combined_preserves_parser_and_joined_exact_selection(self):
        original = self._classify()
        self.assertEqual(original["mode"], "parser-delta")
        self.assertEqual(original["required_tests"], list(scope.REQUIRED_TESTS))
        for joined in (False, True):
            head = self._k15_head(joined=joined)
            result = self._classify(self._k15_event(head))
            self.assertEqual(result["mode"], "parser-entity-delta", result)
            self.assertEqual(
                result["required_tests"], [*scope.REQUIRED_TESTS, "tests/unit/test_entity.py"]
            )
            self.assertEqual(result["selection"], dict(original["selection"], joined=joined))
            self.assertEqual(
                result["required_joined_tests"], list(scope.REQUIRED_JOINED_TESTS) if joined else []
            )

    def test_k15_k06_delta_cannot_sneak_into_entity_only_route(self):
        head = self._k15_head(
            parser=False,
            overrides={scope.K06_TEST_DELTA_PATH: b"# Synthetic entity-plus-K06 test\n"},
        )
        event = self._k15_event(head)
        for kind in sorted(scope.WORKFLOW_KINDS):
            with self.subTest(kind=kind):
                result = self._classify(event, kind=kind)
                self.assertEqual(result["mode"], "broad-required")
                self.assertIn("unsupported-combination", result["reason_codes"])
                self.assertFalse(result["selection"]["python"])

    def test_k15_k06_delta_on_combined_route_keeps_k06_mandatory(self):
        head = self._k15_head(
            parser=True,
            overrides={scope.K06_TEST_DELTA_PATH: b"# Synthetic combined K06 test\n"},
        )
        event = self._k15_event(head)
        for kind in sorted(scope.WORKFLOW_KINDS):
            with self.subTest(kind=kind):
                result = self._classify(event, kind=kind)
                self.assertEqual(result["mode"], "parser-entity-delta", result)
                self.assertIn(scope.K06_TEST_DELTA_PATH, result["required_tests"])
                self.assertIn(scope.K06_TEST_DELTA_PATH, result["delta"]["python_paths"])
                self.assertTrue(result["selection"]["python"])

    def test_k15_payload_pair_missing_or_drift_fail_closed(self):
        for path in scope.ENTITY_PAYLOAD:
            for raw in (None, b"# not the reviewed K15 source\n"):
                with self.subTest(path=path, raw=raw):
                    head = self._k15_head(overrides={path: raw})
                    result = self._classify(self._k15_event(head))
                    self.assertEqual(result["mode"], "broad-required", result)
                    self.assertTrue(
                        {"entity-payload-mismatch", "unsupported-change"}.intersection(
                            result["reason_codes"]
                        )
                    )
                    self.assertFalse(result["selection"]["python"])
                    self.assertIsNone(result["entity_sources"])

    def test_k15_unsafe_type_rename_and_unknown_neighbors_fail_closed(self):
        for path in scope.ENTITY_PAYLOAD:
            for mode in ("100755", "120000", "160000"):
                head = self._k15_head(overrides={path: b"unsafe"}, modes={path: mode})
                result = self._classify(self._k15_event(head))
                self.assertEqual(result["mode"], "broad-required", result)
                self.assertIn("unsupported-change", result["reason_codes"])
        for changes in (
            {"packages/cir-python/src/akc_cir/entity.py.extra": b"x"},
            {"tests/unit/test_entity_extra.py": b"x"},
            {
                "packages/cir-python/src/akc_cir/entity.py": None,
                "packages/cir-python/src/akc_cir/entity-renamed.py": b"x",
            },
        ):
            head = self._k15_head(overrides=changes)
            result = self._classify(self._k15_event(head))
            self.assertEqual(result["mode"], "broad-required", result)
            self.assertTrue(
                {"unknown-path", "unsupported-change"}.intersection(result["reason_codes"])
            )

    def test_k15_event_identity_ancestry_and_frozen_inputs_fail_closed(self):
        head = self._k15_head()
        event = self._k15_event(head)
        mismatch = deepcopy(event)
        mismatch["pull_request"]["head"]["sha"] = scope.ANCHOR_COMMIT
        fork = deepcopy(event)
        fork["pull_request"]["head"]["repo"]["full_name"] = "foreign/repo"
        malformed = deepcopy(event)
        malformed["number"] = True
        for bad in (mismatch, fork, malformed):
            result = self._classify(bad)
            self.assertEqual(result["mode"], "broad-required", result)
        with patch.object(scope, "ANCHOR_TREE", "f" * 40):
            self.assertEqual(self._classify(event)["mode"], "broad-required")
        for path in (next(iter(scope.PINNED_PAYLOAD)), "uv.lock"):
            head = self._k15_head(overrides={path: b"unreviewed drift"})
            result = self._classify(self._k15_event(head))
            self.assertEqual(result["mode"], "broad-required", result)

    def test_k15_actual_published_tree_regular_sources_and_cli_receipt(self):
        # Bind the immutable published base available in this PR's object history.
        # The reviewed helper keeps Git operations in the same temporary repository.
        source_tree = self._git(
            "rev-parse", "5f0bca3284825d7bc30a02080acf673289771c27^{tree}"
        ).decode().strip()
        self.assertEqual(source_tree, "581cfdae95cc5716e39e487b7de7e1b8ae939457")
        self.assertEqual(self._git("cat-file", "-t", source_tree).decode().strip(), "tree")
        head = self._commit(source_tree)
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", head)
        event = self._k15_event(head)
        result = self._classify(event, kind="focused")
        self.assertEqual(result["mode"], "parser-entity-delta", result)
        self.assertEqual(result["identity"]["head_tree"], source_tree)
        self.assertTrue(result["selection"]["joined"])
        for path, blob in scope.ENTITY_PAYLOAD.items():
            self.assertEqual(
                result["entity_sources"]["entries"][path],
                {"mode": "100644", "kind": "blob", "blob": blob},
            )
        filename = self.temp / "k15-cli-event.json"
        filename.write_text(json.dumps(event))
        output = self.temp / "k15-cli-report.json"
        ghoutput = self.temp / "k15-gh-output.txt"
        child = subprocess.run(  # noqa: S603 - fixed task-owned command
            [
                sys.executable,
                str(SCRIPT),
                "--repo",
                str(self.repo),
                "--event-path",
                str(filename),
                "--event-name",
                "pull_request",
                "--workflow-kind",
                "focused",
                "--output",
                str(output),
                "--github-output",
                str(ghoutput),
            ],
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
        values = dict(line.split("=", 1) for line in ghoutput.read_text().splitlines())
        self.assertEqual(values["mode"], "parser-entity-delta")
        self.assertEqual(values["full_qualification"], "false")
        print(
            json.dumps(
                {
                    "synthetic_commit_over_actual_local_tree": head,
                    "tree": result["identity"]["head_tree"],
                    "entity_entries": result["entity_sources"]["entries"],
                    "actual_ci": False,
                }
            )
        )

    def test_k15_discovery_contains_only_new_methods_and_exact_shared_fixture_helpers(self):
        ids = [
            case._testMethodName
            for case in unittest.defaultTestLoader.loadTestsFromTestCase(type(self))
        ]
        self.assertEqual(
            set(ids),
            {
                "test_k15_actual_published_tree_regular_sources_and_cli_receipt",
                "test_k15_combined_preserves_parser_and_joined_exact_selection",
                "test_k15_discovery_contains_only_new_methods_and_exact_shared_fixture_helpers",
                "test_k15_event_identity_ancestry_and_frozen_inputs_fail_closed",
                "test_k15_exact_pair_and_entity_only_selection",
                "test_k15_k06_delta_cannot_sneak_into_entity_only_route",
                "test_k15_k06_delta_on_combined_route_keeps_k06_mandatory",
                "test_k15_payload_pair_missing_or_drift_fail_closed",
                "test_k15_unsafe_type_rename_and_unknown_neighbors_fail_closed",
            },
        )
        self.assertEqual(len(ids), 9)
        self.assertTrue(all(name.startswith("test_k15_") for name in ids))
        self.assertFalse(
            any(name in ids for name in TestPR91AffectedScope.__dict__ if name.startswith("test_"))
        )
        for helper in ("setUpClass", "setUp", "_git", "_add", "_commit", "_event", "_classify"):
            self.assertIs(type(self).__dict__[helper], TestPR91AffectedScope.__dict__[helper])


class TestOcrV3ProductCoreAdmission(unittest.TestCase):
    """OCR v3 product-core is its own finite scope; shared fixture helpers only."""

    setUpClass = TestPR91AffectedScope.__dict__["setUpClass"]
    setUp = TestPR91AffectedScope.__dict__["setUp"]
    _git = TestPR91AffectedScope.__dict__["_git"]
    _add = TestPR91AffectedScope.__dict__["_add"]
    _commit = TestPR91AffectedScope.__dict__["_commit"]
    _event = TestPR91AffectedScope.__dict__["_event"]
    _classify = TestPR91AffectedScope.__dict__["_classify"]

    FOUR = (
        "packages/product-core/src/akc_product_core/contracts.py",
        "packages/product-core/src/akc_product_core/compiler.py",
        "packages/product-core/src/akc_product_core/journal.py",
        "tests/unit/test_product_core_ocr_v3.py",
    )
    MODE = "parser-entity-ocr-v3-delta"

    def _ocr_head(
        self, *, parser=True, entity=True, joined=False, ocr=FOUR, overrides=None, modes=None
    ):
        self._git("read-tree", self.payload_tree if parser else scope.ANCHOR_TREE)
        for path in (
            "scripts/classify_pr91_affected_scope.py",
            "tests/unit/test_pr91_affected_scope.py",
            "tests/unit/test_pr91_affected_workflow_contract.py",
        ):
            self._add(path, b"# Synthetic exact routing control fixture\n")
        if entity:
            for path, blob in scope.ENTITY_PAYLOAD.items():
                self._git("update-index", "--add", "--cacheinfo", "100644", blob, path)
        if joined:
            for path in scope.JOINED_SOURCE_PATHS:
                self._add(path, b"// Synthetic joined source presence, not G1 evidence\n")
        for path in ocr:
            self._add(path, b"# Synthetic OCR v3 product-core source; not OCR evidence\n")
        for path, raw in (overrides or {}).items():
            if raw is None:
                self._git("update-index", "--force-remove", path)
            else:
                mode = (modes or {}).get(path, "100644")
                if mode == "160000":
                    self._git(
                        "update-index", "--add", "--cacheinfo", mode, scope.ANCHOR_COMMIT, path
                    )
                else:
                    self._add(path, raw, mode)
        head = self._commit(self._git("write-tree").decode().strip())
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", head)
        return head

    def _ocr_event(self, head):
        event = self._event()
        event["pull_request"]["head"]["sha"] = head
        return event

    def _refused(self, head, reasons):
        result = self._classify(self._ocr_event(head))
        self.assertEqual(result["mode"], "broad-required", result)
        self.assertTrue(set(reasons).intersection(result["reason_codes"]), result)
        self.assertFalse(result["selection"]["python"])
        self.assertFalse(result["full_qualification"])
        self.assertIsNone(result["ocr_v3_product_core"])
        return result

    def test_ocr_v3_exact_four_paths_select_own_scope_in_each_workflow(self):
        self.assertEqual(scope.OCR_V3_SOURCE_PATHS, self.FOUR)
        self.assertEqual(scope.OCR_V3_MODE, self.MODE)
        self.assertEqual(
            scope.OCR_V3_REQUIRED_TESTS,
            (
                "tests/unit/test_product_core_ocr_v3.py",
                "tests/unit/test_product_core_journal.py",
                "tests/unit/test_product_core_journal_maintenance.py",
                "tests/unit/test_product_core_region_anchors.py",
                "tests/unit/test_product_core_bridge.py",
            ),
        )
        parser_entity = self._classify(self._ocr_event(self._ocr_head(ocr=())))
        self.assertEqual(parser_entity["mode"], "parser-entity-delta", parser_entity)
        self.assertIsNone(parser_entity["ocr_v3_product_core"])
        for joined in (False, True):
            head = self._ocr_head(joined=joined)
            for kind in sorted(scope.WORKFLOW_KINDS):
                with self.subTest(joined=joined, kind=kind):
                    result = self._classify(self._ocr_event(head), kind=kind)
                    self.assertEqual(result["mode"], self.MODE, result)
                    self.assertFalse(result["full_qualification"])
                    self.assertEqual(result["reason_codes"], ["reviewed-" + self.MODE])
                    self.assertEqual(
                        result["selection"], dict(parser_entity["selection"], joined=joined)
                    )
                    self.assertFalse(result["selection"]["images"])
                    self.assertEqual(
                        result["required_tests"],
                        [
                            *scope.REQUIRED_TESTS,
                            "tests/unit/test_entity.py",
                            *scope.OCR_V3_REQUIRED_TESTS,
                        ],
                    )
                    self.assertEqual(
                        result["required_joined_tests"],
                        list(scope.REQUIRED_JOINED_TESTS) if joined else [],
                    )
                    ocr = result["ocr_v3_product_core"]
                    self.assertEqual(ocr["changed_paths"], sorted(self.FOUR))
                    self.assertEqual(set(ocr["entries"]), set(self.FOUR))
                    for path, row in ocr["entries"].items():
                        self.assertEqual((row["mode"], row["kind"]), ("100644", "blob"))
                        self.assertEqual(
                            row["blob"], self._git("rev-parse", f"{head}:{path}").decode().strip()
                        )
                    self.assertEqual(ocr["type_check_packages"], ["packages/product-core/src"])
                    self.assertTrue(ocr["pending_debt"])
                    self.assertIn("product-core/Dockerfile image", " ".join(ocr["pending_debt"]))
                    self.assertIn("no OCR accuracy, package, image", ocr["qualification"])
                    boundary = result["unchanged_inputs"]["image_boundary"]
                    self.assertIn("packaged wheel", boundary)
                    self.assertIn("pending debt", boundary)
                    self.assertNotIn("excludes compiler-runtime", boundary)
                    for path in self.FOUR:
                        self.assertIn(path, result["delta"]["python_paths"])
                    self.assertEqual(
                        set(result["entity_sources"]["entries"]), set(scope.ENTITY_PAYLOAD)
                    )

    def test_ocr_v3_requires_its_reviewed_test_in_the_change_set(self):
        for subset in (self.FOUR[:1], self.FOUR[:3]):
            with self.subTest(changed=subset):
                self._refused(self._ocr_head(ocr=subset), {"ocr-test-missing"})
        test_only = self._classify(self._ocr_event(self._ocr_head(ocr=self.FOUR[3:])))
        self.assertEqual(test_only["mode"], self.MODE, test_only)
        self.assertEqual(test_only["ocr_v3_product_core"]["changed_paths"], [self.FOUR[3]])
        self._refused(
            self._ocr_head(overrides={"tests/unit/test_product_core_bridge.py": None}),
            {"unknown-path", "unsupported-change"},
        )

    def test_ocr_v3_adjacent_paths_fail_closed(self):
        for path in (
            "packages/product-core/src/akc_product_core/native_cir.py",
            "packages/product-core/src/akc_product_core/api.py",
            "packages/product-core/src/akc_product_core/contracts.py.extra",
            "packages/product-core/src/akc_product_core/ocr/contracts.py",
            "packages/product-core/src/akc_product_core/journal_v3.py",
            "packages/product-core/tests/test_product_core_ocr_v3.py",
            "tests/unit/test_product_core_ocr_v4.py",
            "tests/unit/test_product_core_ocr_v3_extra.py",
            "tests/integration/test_product_core_ocr_v3.py",
            "infra/product-core/Dockerfile",
        ):
            with self.subTest(path=path):
                self._refused(
                    self._ocr_head(overrides={path: b"# Synthetic adjacent path\n"}),
                    {"unknown-path"},
                )

    def test_ocr_v3_unsafe_modes_deletion_and_rename_fail_closed(self):
        for path in self.FOUR:
            for mode in ("100755", "120000", "160000"):
                with self.subTest(path=path, mode=mode):
                    head = self._ocr_head(overrides={path: b"unsafe"}, modes={path: mode})
                    self._refused(head, {"unsupported-change"})
        journal = "packages/product-core/src/akc_product_core/journal.py"
        compiler = "packages/product-core/src/akc_product_core/compiler.py"
        for overrides in (
            {journal: None},
            {compiler: None, "packages/product-core/src/akc_product_core/compiler_v3.py": b"x"},
        ):
            with self.subTest(changes=list(overrides)):
                self._refused(
                    self._ocr_head(overrides=overrides), {"unsupported-change", "unknown-path"}
                )

    def test_ocr_v3_never_rides_parser_only_or_entity_only_routes(self):
        for parser, entity in ((True, False), (False, True)):
            with self.subTest(parser=parser, entity=entity):
                self._refused(
                    self._ocr_head(parser=parser, entity=entity), {"unsupported-combination"}
                )
        self._refused(self._ocr_head(parser=False, entity=False), {"payload-mismatch"})

    def test_ocr_v3_keeps_pinned_payload_identity_and_frozen_input_guards(self):
        parser_path = next(iter(scope.PINNED_PAYLOAD))
        entity_path = next(iter(scope.ENTITY_PAYLOAD))
        for path, reasons in (
            (parser_path, {"payload-mismatch"}),
            (entity_path, {"entity-payload-mismatch"}),
            ("uv.lock", {"unknown-path"}),
            ("pyproject.toml", {"unknown-path"}),
        ):
            with self.subTest(path=path):
                self._refused(self._ocr_head(overrides={path: b"unreviewed drift\n"}), reasons)
        head = self._ocr_head()
        event = self._ocr_event(head)
        mismatch = deepcopy(event)
        mismatch["pull_request"]["head"]["sha"] = scope.ANCHOR_COMMIT
        fork = deepcopy(event)
        fork["pull_request"]["head"]["repo"]["full_name"] = "foreign/repo"
        for bad, reason in ((mismatch, "head-mismatch"), (fork, "fork-or-missing-repo")):
            result = self._classify(bad)
            self.assertEqual(result["mode"], "broad-required", result)
            self.assertIn(reason, result["reason_codes"])
            self.assertIsNone(result["ocr_v3_product_core"])
        with patch.object(scope, "ANCHOR_TREE", "f" * 40):
            result = self._classify(event)
            self.assertIn("anchor-tree-mismatch", result["reason_codes"])
            self.assertIsNone(result["ocr_v3_product_core"])
        other = deepcopy(event)
        other["number"] = other["pull_request"]["number"] = 92
        self.assertEqual(self._classify(other)["mode"], "full")

    def test_ocr_v3_actual_c051d2b0_tree_and_cli_receipt(self):
        # The published commit that added the module; its tree is fixed history.
        source_tree = self._git(
            "rev-parse", "c051d2b0cd252686e03b2d1567e1a9867748e03e^{tree}"
        ).decode().strip()
        self.assertEqual(source_tree, "ccc4cb89434610f5daf242cf55bae0b35d11e596")
        head = self._commit(source_tree)
        self._git("update-ref", "refs/heads/synthetic-routing-fixture", head)
        event = self._ocr_event(head)
        result = self._classify(event, kind="focused")
        self.assertEqual(result["mode"], self.MODE, result)
        self.assertTrue(result["selection"]["joined"])
        self.assertEqual(result["ocr_v3_product_core"]["changed_paths"], sorted(self.FOUR))
        filename = self.temp / "ocr-v3-cli-event.json"
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                if not accepted:
                    event["pull_request"]["head"]["sha"] = "0" * 40
                filename.write_text(json.dumps(event), encoding="utf-8")
                output = self.temp / f"ocr-v3-cli-{accepted}.json"
                ghoutput = self.temp / f"ocr-v3-gh-{accepted}.txt"
                child = subprocess.run(  # noqa: S603 - fixed local classifier CLI, not CI.
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--repo",
                        str(self.repo),
                        "--event-path",
                        str(filename),
                        "--event-name",
                        "pull_request",
                        "--workflow-kind",
                        "focused",
                        "--output",
                        str(output),
                        "--github-output",
                        str(ghoutput),
                    ],
                    env=self.environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(child.returncode, 0 if accepted else 1, child.stderr)
                record = json.loads(output.read_text(encoding="utf-8"))
                if accepted:
                    values = dict(
                        line.split("=", 1) for line in ghoutput.read_text().splitlines()
                    )
                    self.assertEqual(values["mode"], self.MODE)
                    self.assertEqual(values["full_qualification"], "false")
                    self.assertEqual(values["joined"], "true")
                    for name in ("images", "web", "db", "model", "dependency_audit"):
                        self.assertEqual(values[name], "false")
                else:
                    self.assertFalse(ghoutput.exists())
                    self.assertEqual(record["mode"], "broad-required")
                    self.assertIsNone(record["ocr_v3_product_core"])
