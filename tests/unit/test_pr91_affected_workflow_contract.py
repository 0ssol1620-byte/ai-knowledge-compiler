"""Bounded stdlib workflow contracts; no YAML parser, CI runner or product suites execute."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(os.environ.get("AKC_AFFECTED_WORKFLOW_ROOT", Path(__file__).resolve().parents[2]))


def existing_executable(candidate: str | Path | None, program: str) -> str:
    """Resolve the installed runtime; caller data cannot select another executable."""
    if candidate is None or not isinstance(candidate, (str, Path)):
        raise ValueError("Existing executable required; no installation fallback")
    path = Path(candidate)
    if "\0" in str(path) or not path.is_absolute():
        raise ValueError("Executable must be an absolute installed path")
    resolved = path.resolve(strict=True)
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("Executable must be a regular file")
    if resolved.name.lower() not in {program, program + ".exe"}:
        raise ValueError("Unexpected executable identity")
    if program == "node":
        installed = shutil.which("node")
        if installed is None or resolved != Path(installed).resolve(strict=True):
            raise ValueError("Node override differs from the installed selected runtime")
    return str(resolved)


def ordinary_directory(path: Path) -> Path:
    if path.is_symlink() or path.is_junction() or not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError("Expected an ordinary task-owned directory")
    if path.resolve(strict=True) != path.absolute():
        raise ValueError("Task directory ancestry redirects its canonical path")
    return path.resolve(strict=True)


def checked_fixture_script(path: Path, root: Path, expected: str) -> str:
    directory = ordinary_directory(root)
    if path.is_symlink() or path.is_junction() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Fixture script must be an ordinary file")
    resolved = path.resolve(strict=True)
    if resolved.parent != directory or path.name not in {"type.sh", "gate.sh"}:
        raise ValueError("Fixture script escaped its task-owned scope")
    if len(expected) > 65536 or path.read_text(encoding="utf-8") != expected:
        raise ValueError("Fixture script differs from its reviewed workflow fragment")
    return str(resolved)


def checked_bash_environment(environment: dict[str, str]) -> dict[str, str]:
    controls = {
        "SCOPE_MODE": {
            "full",
            "parser-delta",
            "parser-entity-delta",
            "entity-delta",
            "parser-entity-ocr-v3-delta",
        },
        "MOCK_MYPY_EXIT": {"0", "23"},
        "TYPE_OUTCOME": {"success", "failure", "skipped", "cancelled", ""},
    }
    for name, allowed in controls.items():
        if name in environment and environment[name] not in allowed:
            raise ValueError("Unknown synthetic Bash control")
    if environment.get("EVIDENCE_DIR") != "evidence" or environment.get("ARGV_FILE") != "argv.txt":
        raise ValueError("Bash fixture outputs must remain inside its temporary cwd")
    return {
        key: value
        for key, value in environment.items()
        if key not in {"BASH_ENV", "ENV", "LD_PRELOAD", "LD_LIBRARY_PATH"}
        and not key.startswith("BASH_FUNC_")
    }


def checked_materializer_arguments(
    script: Path, canonical: Path, root: str, extra: tuple[str, ...]
):
    if not isinstance(root, str) or "\0" in root or len(root) > 4096:
        raise ValueError("Invalid materializer data argument")
    if len(extra) > 8 or any(
        not isinstance(arg, str) or "\0" in arg or len(arg) > 4096 for arg in extra
    ):
        raise ValueError("Invalid materializer argv data")
    fixed = ROOT / "tests/e2e/joined/materialize-g1-11-contract-fixture.mjs"
    if canonical.is_symlink() or canonical.resolve(strict=True) != fixed.resolve(strict=True):
        raise ValueError("Materializer differs from its fixed repository identity")
    original = canonical.read_text(encoding="utf-8")
    if hashlib.sha256(original.encode()).hexdigest() != (
        "d6a0098c66043baa4c70553f5cc93014df32d5fff647bb69d44e434a4001f649"
    ):
        raise ValueError("Materializer differs from reviewed published source")
    if script.is_symlink() or script.is_junction() or not stat.S_ISREG(script.lstat().st_mode):
        raise ValueError("Materializer script must be an ordinary file")
    if script.resolve(strict=True) != canonical.resolve(strict=True):
        owner = ordinary_directory(Path(root).parent)
        if script.name != "corrupt.mjs" or script.resolve(strict=True).parent != owner:
            raise ValueError("Unrecognized task-owned materializer fixture")
        pin = '"sha256": "59bd6a3eb2bcb63dc03ba1b5ec6e8f113eea6fbc68741d07f3be165d31e3db34"'
        if original.count(pin) != 1 or script.read_text(encoding="utf-8") != original.replace(
            pin, '"sha256": "' + "0" * 64 + '"'
        ):
            raise ValueError("Only the existing exact corrupt-digest fixture is allowed")
    # Negative relative/traversal/symlink roots and extra options remain argv data.
    return [str(script.resolve(strict=True)), root, *extra]


def checked_junction_environment(root: Path, link: Path, target: Path) -> dict[str, str]:
    base = ordinary_directory(root)
    ordinary_directory(target)
    if link.name != "link" or target.name != "ordinary" or link.parent.resolve() != base:
        raise ValueError("Junction paths differ from their task-owned scope")
    if target.resolve().parent != base or link.exists() or link.is_symlink() or link.is_junction():
        raise ValueError("Junction must be new and must not escape its task-owned directory")
    environment = dict(os.environ)
    environment["TAVONEL_JUNCTION_LINK"] = str(base / "link")
    environment["TAVONEL_JUNCTION_TARGET"] = str(base / "ordinary")
    return environment


KINDS = {
    "ci": "ci",
    "pr91-focused-qualification": "focused",
    "security": "security",
    "model-ci": "model",
    "joined-e2e": "joined",
}
CI_JOBS = [
    "python-core",
    "web-and-contracts",
    "lighthouse",
    "live-browser-e2e",
    "visual-and-browser-matrix",
    "contracts",
    "infrastructure",
    "postgres-rls-and-role-boundaries",
    "worker-syntax",
]
SECURITY_JOBS = [
    "codeql",
    "dependency-review",
    "filesystem-and-iac",
    "dependency-audit",
    "application-images",
    "ip-privilege-guard",
]
MODEL_JOBS = ["registry", "local-images", "provider-smoke"]
FOCUSED_JOBS = [
    "python-focused",
    "application-images",
    "gpu-local-images",
    "web-focused",
    "joined-e2e",
]
ORIGINAL_NINE = [
    "tests/unit/test_hwpx_structured_parser.py",
    "tests/unit/test_nonpdf_structured_parsers.py",
    "tests/unit/test_product_core_native_cir.py",
    "tests/unit/test_product_core_native_world_manifest.py",
    "tests/unit/test_document_remaining_state_extraction.py",
    "tests/integration/test_document_parser_policy_upgrade.py",
    "tests/unit/test_parser_upgrade_ci_contract.py",
    "tests/security/test_security_boundaries.py",
    "services/api/tests/test_native_nonpdf_worker_e2e.py",
]
SHARED_SEVEN = [
    "tests/integration/test_core_parser_cache.py",
    "tests/integration/test_core_runtime_history_safety_claude.py",
    "tests/integration/test_core_semantic_incremental_runtime.py",
    "tests/unit/test_answer_compiler.py",
    "tests/unit/test_core_semantic_incremental_fixtures.py",
    "tests/unit/test_pr91_affected_scope.py",
    "tests/unit/test_pr91_affected_workflow_contract.py",
]


def source(workflow: str) -> str:
    return (ROOT / ".github/workflows" / f"{workflow}.yml").read_text(encoding="utf-8")


def jobs(workflow: str) -> dict[str, str]:
    text = source(workflow)
    offset = text.index("jobs:\n")
    matches = list(re.finditer(r"^  ([a-z][a-z0-9-]*):\n", text[offset:], re.M))
    blocks = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text) - offset
        blocks[match[1]] = text[offset + match.start() : offset + end]
    return blocks


def required_job(workflow: str, job: str) -> str:
    blocks = jobs(workflow)
    if job not in blocks:
        raise AssertionError(f"{workflow}: required routing job {job} is absent")
    return blocks[job]


def joined_condition_selected(
    condition: str, result: str | None, mode: str | None, joined: str | None
) -> bool:
    """Evaluate only this contract's equality/and/or grammar, not GitHub Actions."""
    values = {"scope_result": result, "scope_mode": mode, "scope_joined": joined}
    for reference, name in (
        ("needs.scope.result", "scope_result"),
        ("needs.scope.outputs.mode", "scope_mode"),
        ("needs.scope.outputs.joined", "scope_joined"),
    ):
        condition = condition.replace(reference, name)
    tree = ast.parse(condition.replace("&&", " and ").replace("||", " or "), mode="eval")

    def value(node: ast.AST):
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            return value(node.left) == value(node.comparators[0])
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            operands = [value(item) for item in node.values]
            if not all(isinstance(item, bool) for item in operands):
                raise ValueError("Non-boolean joined routing operand")
            return all(operands) if isinstance(node.op, ast.And) else any(operands)
        raise ValueError("Unsupported joined routing expression")

    selected = value(tree.body)
    if not isinstance(selected, bool):
        raise ValueError("Joined routing condition must produce a boolean")
    return selected


def embedded_python(text: str) -> list[str]:
    # Only literal Python heredocs in these known workflows are selected. This deliberately
    # does not claim to validate all YAML/shell/expression semantics.
    pattern = r"^ {10,}python3? - <<'PY'[^\n]*\n(.*?)^          PY\n"
    bodies = re.findall(pattern, text, re.M | re.S)
    return [
        "\n".join(line[10:] if line.startswith(" " * 10) else line for line in body.splitlines())
        + "\n"
        for body in bodies
    ]


def gate_code(workflow: str, job: str = "affected-scope") -> str:
    scripts = embedded_python(required_job(workflow, job))
    if len(scripts) != 1 or "def evaluate(" not in scripts[0]:
        raise AssertionError(f"{workflow}/{job}: exact current-outcome evaluator missing")
    return scripts[0]


def outcomes(ids: list[str], mode: str, executed: set[str]) -> dict:
    return {
        "scope": {"result": "success", "outputs": {"mode": mode, "joined": "false"}},
        **{job: {"result": "success" if job in executed else "skipped"} for job in ids},
    }


def run_gate(
    code: str,
    mode: str,
    needs: dict,
    **extra: str,
) -> tuple[SimpleNamespace, dict | None]:
    with tempfile.TemporaryDirectory(prefix="affected-workflow-contract-") as directory:
        env = dict(
            os.environ,
            SCOPE_MODE=mode,
            NEEDS_JSON=json.dumps(needs),
            TESTED_HEAD="a" * 40,
            GITHUB_RUN_ID="700",
            GITHUB_RUN_ATTEMPT="3",
            GITHUB_STEP_SUMMARY=str(Path(directory) / "summary.md"),
            GHAS_AVAILABLE="true",
            IS_PULL_REQUEST="true",
            PROVIDER_SMOKE_SELECTED="false",
        )
        env.update(extra)
        filename = Path(directory) / "gate_witness.py"
        filename.write_text(code, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("__main__", filename)
        if spec is None or spec.loader is None:
            raise AssertionError("Unable to load the literal workflow gate witness")
        module = importlib.util.module_from_spec(spec)
        previous_directory = Path.cwd()
        output = io.StringIO()
        result = SimpleNamespace(returncode=0, stderr="")
        try:
            os.chdir(directory)
            with patch.dict(os.environ, env, clear=True), redirect_stdout(output):
                spec.loader.exec_module(module)
        except ValueError as error:
            result = SimpleNamespace(returncode=1, stderr=str(error))
        finally:
            os.chdir(previous_directory)
        receipts = list((Path(directory) / "artifacts").glob("*.json"))
        report = json.loads(receipts[0].read_text()) if len(receipts) == 1 else None
        return result, report


class TestPR91AffectedWorkflowContract(unittest.TestCase):
    def test_five_classification_jobs_bind_actual_head_and_current_output_receipt(self) -> None:
        for workflow, kind in KINDS.items():
            with self.subTest(workflow=workflow):
                block = required_job(workflow, "scope")
                self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", block)
                self.assertIn("fetch-depth: 0", block)
                self.assertIn("persist-credentials: false", block)
                self.assertIn(f"--workflow-kind {kind}", block)
                self.assertIn('--event-path "$GITHUB_EVENT_PATH"', block)
                self.assertIn('--github-output "$GITHUB_OUTPUT"', block)
                self.assertIn("if: always()", block)
                self.assertIn("if-no-files-found: error", block)
                self.assertNotIn("continue-on-error", block)
                self.assertNotIn("|| true", block)

    def test_unrelated_execution_jobs_require_successful_full_scope(self) -> None:
        sets = {
            "ci": CI_JOBS,
            "model-ci": MODEL_JOBS,
            "joined-e2e": ["joined-e2e"],
            "pr91-focused-qualification": FOCUSED_JOBS[1:],
        }
        for workflow, ids in sets.items():
            for job in ids:
                with self.subTest(workflow=workflow, job=job):
                    block = required_job(workflow, job)
                    self.assertIn("    needs: scope\n", block)
                    self.assertIn("needs.scope.result == 'success'", block)
                    self.assertIn("needs.scope.outputs.mode == 'full'", block)
        provider = required_job("model-ci", "provider-smoke")
        self.assertIn(
            "github.event_name == 'workflow_dispatch' && inputs.run_provider_smoke",
            provider,
        )
        self.assertIn("environment: model-staging", provider)

    def test_narrow_ci_model_joined_omissions_without_execution_or_inherited_pass(self) -> None:
        groups = (("ci", CI_JOBS), ("model-ci", MODEL_JOBS), ("joined-e2e", ["joined-e2e"]))
        for workflow, ids in groups:
            with self.subTest(workflow=workflow):
                result, report = run_gate(
                    gate_code(workflow),
                    "parser-delta",
                    outcomes(ids, "parser-delta", set()),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(report["full_qualified"])
                self.assertEqual(report["qualification"], "affected-only-not-full-qualified")
                self.assertTrue(
                    all(item["execution"] == "not-executed" for item in report["outcomes"].values())
                )
                text = required_job(workflow, "affected-scope").lower()
                text = text.replace("not-full", "not full")
                self.assertIn("not full", text)

    def test_scope_refusal_cancelled_or_mismatched_outputs_fail_closed(self) -> None:
        code = gate_code("ci")
        for mode, scope in (
            ("broad-required", {"result": "failure", "outputs": {}}),
            ("parser-delta", {"result": "cancelled", "outputs": {"mode": "parser-delta"}}),
            ("parser-delta", {"result": "success", "outputs": {"mode": "full"}}),
        ):
            with self.subTest(mode=mode, scope=scope):
                needs = outcomes(CI_JOBS, mode, set())
                needs["scope"] = scope
                result, report = run_gate(code, mode, needs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(report)

    def test_selected_aggregate_rejects_missing_unknown_or_unexpectedly_executed_jobs(self) -> None:
        code = gate_code("ci")
        for change in ("missing", "unknown", "executed", "cancelled"):
            with self.subTest(change=change):
                needs = outcomes(CI_JOBS, "parser-delta", set())
                if change == "missing":
                    del needs[CI_JOBS[-1]]
                elif change == "unknown":
                    needs["unreviewed-job"] = {"result": "success"}
                else:
                    outcome = "success" if change == "executed" else "cancelled"
                    needs[CI_JOBS[-1]]["result"] = outcome
                result, report = run_gate(code, "parser-delta", needs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(report)

    def test_security_core_guards_and_python_codeql_remain_selected(self) -> None:
        for job in ("filesystem-and-iac", "ip-privilege-guard"):
            block = required_job("security", job)
            self.assertIn("needs.scope.outputs.security_core == 'true'", block)
            self.assertNotIn("outputs.mode == 'full'", block)
        codeql = required_job("security", "codeql")
        self.assertIn("fromJSON(needs.scope.outputs.codeql_languages)", codeql)
        self.assertIn(
            "github.event.repository.private == false || vars.AKC_GHAS_ENABLED == 'true'",
            codeql,
        )
        code = gate_code("security")
        selected = {"codeql", "filesystem-and-iac", "ip-privilege-guard"}
        needs = outcomes(SECURITY_JOBS, "parser-delta", selected)
        result, report = run_gate(code, "parser-delta", needs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(report["full_qualified"])
        for job in selected:
            broken = json.loads(json.dumps(needs))
            broken[job]["result"] = "skipped"
            result, _ = run_gate(code, "parser-delta", broken)
            self.assertNotEqual(result.returncode, 0, job)
        needs["codeql"]["result"] = "skipped"
        result, _ = run_gate(code, "parser-delta", needs, GHAS_AVAILABLE="false")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_markers_require_full_mode_and_all_current_required_job_successes(self) -> None:
        groups = (("ci", CI_JOBS), ("security", SECURITY_JOBS), ("model-ci", MODEL_JOBS))
        for workflow, ids in groups:
            with self.subTest(workflow=workflow):
                block = required_job(workflow, "full-qualification")
                self.assertIn("    name: Full qualification\n", block)
                self.assertIn(
                    "if: always() && needs.scope.result == 'success' && "
                    "needs.scope.outputs.mode == 'full'",
                    block,
                )
                needs = outcomes(ids, "full", set(ids))
                extra = {"PROVIDER_SMOKE_SELECTED": "true"} if workflow == "model-ci" else {}
                code = gate_code(workflow, "full-qualification")
                result, report = run_gate(code, "full", needs, **extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(report["full_qualified"])
                self.assertEqual(report["run_id"], "700")
                self.assertEqual(report["run_attempt"], "3")
                for job in ids:
                    for outcome in ("skipped", "cancelled", "failure"):
                        changed = json.loads(json.dumps(needs))
                        changed[job]["result"] = outcome
                        result, report = run_gate(code, "full", changed, **extra)
                        self.assertNotEqual(result.returncode, 0, f"{job}: {outcome}")
                        self.assertIsNone(report)

    def test_full_security_and_model_exemptions_are_only_existing_explicit_conditions(self) -> None:
        selected = set(SECURITY_JOBS) - {"codeql", "dependency-review"}
        needs = outcomes(SECURITY_JOBS, "full", selected)
        result, _ = run_gate(
            gate_code("security", "full-qualification"),
            "full",
            needs,
            GHAS_AVAILABLE="false",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result, _ = run_gate(
            gate_code("security", "full-qualification"),
            "full",
            needs,
            GHAS_AVAILABLE="true",
        )
        self.assertNotEqual(result.returncode, 0)
        needs = outcomes(MODEL_JOBS, "full", {"registry", "local-images"})
        result, _ = run_gate(gate_code("model-ci", "full-qualification"), "full", needs)
        self.assertEqual(result.returncode, 0, result.stderr)
        result, _ = run_gate(
            gate_code("model-ci", "full-qualification"),
            "full",
            needs,
            PROVIDER_SMOKE_SELECTED="true",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_pr91_unknown_path_escalation_runs_the_same_full_path_and_markers(self) -> None:
        # The classifier escalates a PR91 path outside the reviewed payload to mode=full.
        # On the pull_request event that must be the dispatch full path: every full job and
        # the exact Full qualification marker, with no PR-number carve-out narrowing it.
        spec = importlib.util.spec_from_file_location(
            "pr91_scope_full_escalation", ROOT / "scripts/classify_pr91_affected_scope.py"
        )
        if spec is None or spec.loader is None:
            raise AssertionError("Classifier source is unavailable")
        classifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(classifier)
        source_text = (ROOT / "scripts/classify_pr91_affected_scope.py").read_text("utf-8")
        self.assertIn('"unknown-path-full-escalation"', source_text)
        self.assertNotIn('EvidenceError("unknown-path"', source_text)
        selection = classifier._selection("full")
        self.assertTrue(all(value for key, value in selection.items() if key != "codeql_languages"))
        self.assertEqual(selection["codeql_languages"], ["python", "javascript-typescript"])
        marker_if = (
            "    if: always() && needs.scope.result == 'success' && "
            "needs.scope.outputs.mode == 'full'\n"
        )
        groups = (
            ("ci", CI_JOBS, set(CI_JOBS)),
            ("security", SECURITY_JOBS, set(SECURITY_JOBS)),
            ("model-ci", MODEL_JOBS, {"registry", "local-images"}),
        )
        for workflow, ids, executed in groups:
            with self.subTest(workflow=workflow):
                self.assertIn(marker_if, required_job(workflow, "full-qualification"))
                for job in ("full-qualification", *ids):
                    self.assertNotIn("pull_request.number", required_job(workflow, job))
                needs = outcomes(ids, "full", executed)
                code = gate_code(workflow, "full-qualification")
                result, report = run_gate(code, "full", needs, IS_PULL_REQUEST="true")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(report["mode"], "full")
                self.assertTrue(report["full_qualified"])
                self.assertEqual(report["qualification"], "full-current-run")
                self.assertTrue(
                    all(
                        report["outcomes"][job]["execution"] == "executed-current-run"
                        for job in executed
                    )
                )
        for job in FOCUSED_JOBS[1:]:
            block = required_job("pr91-focused-qualification", job)
            self.assertIn("needs.scope.outputs.mode == 'full'", block)
            self.assertIn("github.event.pull_request.number == 91", block)

    def test_focused_original_nine_matrix_and_fixture_preparation_remain_exact(self) -> None:
        block = required_job("pr91-focused-qualification", "python-focused")
        self.assertIn('python-version: ["3.12", "3.13"]', block)
        files = block.split("          files=(\n", 1)[1].split("          )", 1)[0].split()
        self.assertEqual(files, ORIGINAL_NINE)
        self.assertLess(
            block.index("python scripts/prepare_parser_upgrade_fixtures.py"),
            block.index("pytest --collect-only"),
        )
        self.assertIn('--github-env "$GITHUB_ENV"', block)
        self.assertIn('report["required_tests"]', block)
        self.assertIn("Affected-tree collection", block)
        self.assertIn('check "Full-tree collection" "$COLLECT_OUTCOME"', block)

    def test_each_shared_suite_type_lint_and_collection_result_controls_python_gate(self) -> None:
        block = required_job("pr91-focused-qualification", "python-focused")
        for file in SHARED_SEVEN:
            self.assertIn(file, block)
        self.assertIn("packages=(packages/compiler-runtime/src packages/cir-python/src)", block)
        self.assertIn(
            'if [[ "$SCOPE_MODE" == "entity-delta" ]]; then\n'
            "            packages=(packages/cir-python/src)\n          fi",
            block,
        )
        self.assertIn('mypy "${packages[@]}"', block)
        for step in ("collect", "focused", "ruff", "shared", "type"):
            self.assertIn("${{ steps." + step + ".outcome }}", block)
        outputs = (
            "COLLECT_OUTCOME",
            "FOCUSED_OUTCOME",
            "RUFF_OUTCOME",
            "SHARED_OUTCOME",
            "TYPE_OUTCOME",
        )
        for output in outputs:
            self.assertRegex(block, r'check "[^\n]+" "\$' + output + '"')
        self.assertIn('exit "$failed"', block)

    def test_focused_type_command_modes_and_failure_propagation(self) -> None:
        git = shutil.which("git")
        self.assertIsNotNone(git, "Existing Git/Bash required; no installation fallback")
        bash = (
            Path(git).resolve().parent.parent / "bin/bash.exe"
            if os.name == "nt"
            else Path("/bin/bash")
        )
        self.assertTrue(bash.is_file(), "Existing Bash required; no installation fallback")
        bash_executable = existing_executable(bash, "bash")
        block = required_job("pr91-focused-qualification", "python-focused")

        def step_script(label: str) -> str:
            step = block.split("      - name: " + label + "\n", 1)[1].split("      - name:", 1)[0]
            body = step.split("        run: |\n", 1)[1]
            return "\n".join(line[10:] for line in body.splitlines()) + "\n"

        type_script = step_script("Type check affected compiler and CIR packages")
        gate_script = step_script("Fail if any Python focused check failed")
        for mode in ("full", "parser-delta", "parser-entity-delta", "entity-delta"):
            expected = (
                ["packages/cir-python/src"]
                if mode == "entity-delta"
                else ["packages/compiler-runtime/src", "packages/cir-python/src"]
            )
            with tempfile.TemporaryDirectory(prefix="focused-type-contract-") as directory:
                root = Path(directory)
                (root / "evidence").mkdir()
                filename = root / "type.sh"
                fixture_script = (
                    'python() { printf "%s\\n" "$@" > "$ARGV_FILE"; '
                    'return "$MOCK_MYPY_EXIT"; }\n' + type_script
                )
                filename.write_text(fixture_script, encoding="utf-8")
                fixture_path = checked_fixture_script(filename, root, fixture_script)
                env = dict(
                    os.environ, SCOPE_MODE=mode, EVIDENCE_DIR="evidence", ARGV_FILE="argv.txt"
                )
                for code in (0, 23):
                    child = subprocess.run(  # noqa: S603 - installed Bash, owned reviewed script
                        [bash_executable, "--noprofile", "--norc", fixture_path],
                        cwd=root,
                        env=checked_bash_environment(dict(env, MOCK_MYPY_EXIT=str(code))),
                        capture_output=True,
                        text=True,
                        shell=False,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(child.returncode, code, (mode, code, child.stderr))
                    self.assertLessEqual(len(child.stdout) + len(child.stderr), 65536)
                    self.assertEqual(
                        (root / "argv.txt").read_text().splitlines(),
                        ["-m", "uv", "run", "--locked", "--extra", "dev", "mypy", *expected],
                    )
                gate = root / "gate.sh"
                gate.write_text(gate_script, encoding="utf-8")
                gate_path = checked_fixture_script(gate, root, gate_script)
                for outcome in ("success", "failure", "skipped", "cancelled", ""):
                    gate_env = dict(
                        env,
                        COLLECT_OUTCOME="success",
                        FOCUSED_OUTCOME="success",
                        RUFF_OUTCOME="success",
                        SHARED_OUTCOME="success",
                        TYPE_OUTCOME=outcome,
                    )
                    child = subprocess.run(  # noqa: S603 - installed Bash, owned finite gate fixture
                        [bash_executable, "--noprofile", "--norc", gate_path],
                        cwd=root,
                        env=checked_bash_environment(gate_env),
                        capture_output=True,
                        text=True,
                        shell=False,
                        timeout=10,
                        check=False,
                    )
                    self.assertLessEqual(len(child.stdout) + len(child.stderr), 65536)
                    self.assertEqual(
                        child.returncode,
                        0 if outcome == "success" else 1,
                        (mode, outcome, child.stderr),
                    )

    def test_narrow_ruff_uses_safe_exact_anchor_paths_and_full_preserves_legacy_basis(self) -> None:
        block = required_job("pr91-focused-qualification", "python-focused")
        self.assertIn("BASE_SHA: 956b2efb458bb6062e94f83247acd83696bd3a57", block)
        self.assertIn("lint_basis=621b7d692d21ca73e133010e7e234cc0ffe28086", block)
        self.assertIn('report["delta"]["python_paths"]', block)
        self.assertNotIn("files+=(packages/compiler-runtime/src packages/cir-python/src)", block)
        self.assertIn("mapfile -d", block)
        self.assertIn('ruff check --force-exclude -- "${files[@]}"', block)
        self.assertIn('git diff --name-only --diff-filter=d -z "$BASE_SHA" HEAD', block)
        self.assertIn('raise ValueError("Invalid current changed Python path")', block)

    def test_focused_aggregate_requires_current_python_and_exact_omitted_statuses(self) -> None:
        code = gate_code("pr91-focused-qualification", "focused-qualification")
        needs = outcomes(FOCUSED_JOBS, "parser-delta", {"python-focused"})
        result, report = run_gate(code, "parser-delta", needs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(report["full_qualified"])
        needs["python-focused"]["result"] = "failure"
        result, _ = run_gate(code, "parser-delta", needs)
        self.assertNotEqual(result.returncode, 0)

    def test_focused_full_selection_still_does_not_qualify_full_release(self) -> None:
        code = gate_code("pr91-focused-qualification", "focused-qualification")
        needs = outcomes(FOCUSED_JOBS, "full", set(FOCUSED_JOBS))
        result, report = run_gate(code, "full", needs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(report["full_qualified"])
        self.assertEqual(report["qualification"], "focused-only-not-full-release")

    def test_release_latest_attempt_complete_list_and_exact_marker_identity(self) -> None:
        text = source("release-gates")
        for required in (
            "/attempts/${attempt}/jobs?per_page=100",
            "total > 100",
            "len(records) != total",
            'job.get("name") == "Full qualification"',
            'marker.get("run_id") != run_id',
            'payload.get("run_attempt") != attempt',
            'marker.get("head_sha") != sha',
            'marker.get("status") != "completed"',
            'marker.get("conclusion") != "success"',
            "latest_payload=",
            'verify_run "CI"',
            'verify_run "Security"',
            'verify_run "Model CI"',
        ):
            self.assertIn(required, text)
        self.assertIn("if len(markers) != 1:", text)
        self.assertNotIn('marker.get("run_attempt")', text)

    def test_release_documented_job_schema_accepts_missing_attempt_and_rejects_stale_marker(
        self,
    ) -> None:
        scripts = embedded_python(source("release-gates"))
        code = next((script for script in scripts if "def validate_prerequisite(" in script), None)
        self.assertIsNotNone(code, "Executable prerequisite identity guard is absent")
        with tempfile.TemporaryDirectory(prefix="release-guard-contract-") as directory:
            file = Path(directory) / "release_guard.py"
            file.write_text(code, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("release_guard_contract", file)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            run = {
                "name": "CI",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 3,
                "path": ".github/workflows/ci.yml",
            }
            marker = {
                "name": "Full qualification",
                "head_sha": "a" * 40,
                "run_id": 700,
                "status": "completed",
                "conclusion": "success",
            }
            payload = {"total_count": 1, "jobs": [marker]}
            workflow_path = ".github/workflows/ci.yml"
            module.validate_prerequisite(run, payload, run, "CI", 700, 3, "a" * 40, workflow_path)
            suffixed = {**run, "path": workflow_path + "@refs/heads/main"}
            module.validate_prerequisite(
                suffixed,
                payload,
                suffixed,
                "CI",
                700,
                3,
                "a" * 40,
                workflow_path,
            )
            changes = [
                ({**payload, "total_count": 2}, run),
                ({**payload, "total_count": 101}, run),
                ({"total_count": 2, "jobs": [marker, marker]}, run),
                ({**payload, "jobs": [{**marker, "run_id": 699}]}, run),
                ({**payload, "jobs": [{**marker, "head_sha": "b" * 40}]}, run),
                ({**payload, "jobs": [{**marker, "conclusion": "skipped"}]}, run),
                (payload, {**run, "run_attempt": 4}),
                (payload, {**run, "status": "in_progress"}),
                (payload, {**run, "path": ".github/workflows/lookalike.yml"}),
                (payload, {key: value for key, value in run.items() if key != "path"}),
            ]
            for jobs_payload, latest in changes:
                with self.subTest(jobs=jobs_payload, latest=latest), self.assertRaises(ValueError):
                    module.validate_prerequisite(
                        run,
                        jobs_payload,
                        latest,
                        "CI",
                        700,
                        3,
                        "a" * 40,
                        workflow_path,
                    )

    def test_manual_release_prepares_historical_fixtures_before_full_pytest(self) -> None:
        text = source("release-gates")
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("persist-credentials: false", text)
        self.assertLess(
            text.index("python scripts/prepare_parser_upgrade_fixtures.py"),
            text.index(".venv/bin/pytest"),
        )
        self.assertIn('--github-env "$GITHUB_ENV"', text)
        self.assertIn("environment: release-approval", text)

    def test_embedded_python_syntax_and_original_runner_timeout_permissions(self) -> None:
        expected = {
            "ci": {
                "python-core": 25,
                "web-and-contracts": 25,
                "lighthouse": 25,
                "live-browser-e2e": 30,
                "visual-and-browser-matrix": 35,
                "contracts": 15,
                "infrastructure": 15,
                "postgres-rls-and-role-boundaries": 20,
                "worker-syntax": 10,
            },
            "security": {
                "codeql": 30,
                "filesystem-and-iac": 20,
                "dependency-audit": 20,
                "application-images": 35,
                "ip-privilege-guard": 5,
            },
            "model-ci": {"registry": 15, "local-images": 30, "provider-smoke": 10},
            "joined-e2e": {"joined-e2e": 75},
            "pr91-focused-qualification": {
                "python-focused": 25,
                "application-images": 35,
                "gpu-local-images": 30,
                "web-focused": 50,
                "joined-e2e": 75,
            },
        }
        for workflow, limits in expected.items():
            self.assertIn("permissions:\n  contents: read\n", source(workflow))
            for job, minutes in limits.items():
                block = required_job(workflow, job)
                self.assertIn("runs-on: ubuntu-24.04", block)
                self.assertIn(f"timeout-minutes: {minutes}", block)
            for script in embedded_python(source(workflow)):
                ast.parse(script)
        self.assertIn("security-events: write\n  actions: read", source("security"))
        self.assertIn("JOINED_E2E_POST_RESERVE_SECONDS", source("joined-e2e"))


class TestPR91FixtureInputSafety(unittest.TestCase):
    """Direct checks of the new executable/script/data boundaries."""

    def test_node_override_and_unowned_mutations_fail_before_execution(self):
        canonical = ROOT / "tests/e2e/joined/materialize-g1-11-contract-fixture.mjs"
        for candidate in (None, "relative-node", "node\0argument"):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                existing_executable(candidate, "node")
        with tempfile.TemporaryDirectory(prefix="pr91-node-safety-") as directory:
            owner = Path(directory)
            fake = owner / ("node.exe" if os.name == "nt" else "node")
            fake.write_text("not the selected installed runtime")
            with self.assertRaisesRegex(ValueError, "override differs"):
                existing_executable(fake, "node")
            malicious = owner / "arbitrary.mjs"
            malicious.write_text("throw new Error('must not execute')")
            with self.assertRaisesRegex(ValueError, "Unrecognized"):
                checked_materializer_arguments(
                    malicious,
                    canonical,
                    str(owner / "runner-temp"),
                    (),
                )
            malicious = owner / "corrupt.mjs"
            malicious.write_text("throw new Error('not the permitted digest mutation')")
            with self.assertRaisesRegex(ValueError, "exact corrupt-digest"):
                checked_materializer_arguments(
                    malicious,
                    canonical,
                    str(owner / "runner-temp"),
                    (),
                )
        # Malicious-looking arguments remain data for the real program's negative tests.
        args = checked_materializer_arguments(canonical, canonical, "../../outside", ("--eval=x",))
        self.assertEqual(args[1:], ["../../outside", "--eval=x"])

    def test_bash_script_identity_finite_controls_and_startup_hooks(self):
        environment = {
            "SCOPE_MODE": "parser-delta",
            "MOCK_MYPY_EXIT": "0",
            "EVIDENCE_DIR": "evidence",
            "ARGV_FILE": "argv.txt",
            "BASH_ENV": "untrusted",
            "ENV": "untrusted",
            "BASH_FUNC_python%%": "untrusted",
        }
        clean = checked_bash_environment(environment)
        self.assertNotIn("BASH_ENV", clean)
        self.assertNotIn("ENV", clean)
        self.assertNotIn("BASH_FUNC_python%%", clean)
        with self.assertRaises(ValueError):
            checked_bash_environment(dict(environment, MOCK_MYPY_EXIT="0;untrusted"))
        with tempfile.TemporaryDirectory(prefix="pr91-bash-safety-") as directory:
            root = Path(directory)
            script = root / "type.sh"
            expected = "printf 'fixed fixture\\n'\n"
            script.write_text(expected, encoding="utf-8")
            self.assertEqual(checked_fixture_script(script, root, expected), str(script.resolve()))
            script.write_text("different script", encoding="utf-8")
            with self.assertRaises(ValueError):
                checked_fixture_script(script, root, expected)

    def test_junction_paths_are_owned_new_entries_and_not_code(self):
        with tempfile.TemporaryDirectory(prefix="pr91-junction-'quote-") as directory:
            root = Path(directory)
            target = root / "ordinary"
            target.mkdir()
            link = root / "link"
            environment = checked_junction_environment(root, link, target)
            self.assertEqual(environment["TAVONEL_JUNCTION_LINK"], str(link.resolve()))
            self.assertEqual(environment["TAVONEL_JUNCTION_TARGET"], str(target.resolve()))
            with self.assertRaises(ValueError):
                checked_junction_environment(root, root / "unexpected", target)
            link.mkdir()
            with self.assertRaises(ValueError):
                checked_junction_environment(root, link, target)


class TestG111JoinedCIRegistration(unittest.TestCase):
    """New direct contracts only. Never reads model-ci or starts the joined runtime."""

    def selected_needs(self, joined: str = "true", result: str = "success") -> dict:
        needs = outcomes(
            ["joined-e2e"], "parser-delta", {"joined-e2e"} if result == "success" else set()
        )
        needs["scope"]["outputs"]["joined"] = joined
        needs["joined-e2e"]["result"] = result
        return needs

    def materializer(self) -> Path:
        return ROOT / "tests/e2e/joined/materialize-g1-11-contract-fixture.mjs"

    def invoke_materializer(self, root: str, *extra: str, script: Path | None = None):
        node = os.environ.get("AKC_G1_11_CONTRACT_NODE") or shutil.which("node")
        self.assertIsNotNone(node, "Existing Node runtime is required; no installation fallback")
        executable = existing_executable(node, "node")
        arguments = checked_materializer_arguments(
            script or self.materializer(),
            self.materializer(),
            root,
            extra,
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"NODE_OPTIONS", "NODE_PATH", "LD_PRELOAD", "LD_LIBRARY_PATH"}
        }
        result = subprocess.run(  # noqa: S603 - installed Node, pinned source/owned fixture, argv data
            [executable, *arguments],
            env=environment,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
        return result

    def test_joined_registration_routes_only_successful_full_or_selected_parser_delta(self) -> None:
        block = required_job("joined-e2e", "joined-e2e")
        conditions = re.findall(r"^    if: ([^\n]+)$", block, re.M)
        self.assertEqual(len(conditions), 1)
        for result in ("success", "failure", "cancelled", "skipped", "unknown", None):
            for mode in (
                "full",
                "parser-delta",
                "parser-entity-delta",
                "entity-delta",
                "unknown",
                "",
                None,
            ):
                for joined in ("true", "false", "invalid", "", None):
                    expected = result == "success" and (
                        mode == "full"
                        or (mode in ("parser-delta", "parser-entity-delta") and joined == "true")
                    )
                    self.assertEqual(
                        joined_condition_selected(conditions[0], result, mode, joined),
                        expected,
                        (result, mode, joined),
                    )
        self.assertIn("timeout-minutes: 75", block)
        self.assertIn("runs-on: ubuntu-24.04", block)
        self.assertIn("JOINED_E2E_POST_RESERVE_SECONDS", source("joined-e2e"))
        self.assertIn("permissions:\n  contents: read\n", source("joined-e2e"))

    def test_joined_registration_condition_rejects_guard_mutations(self) -> None:
        block = required_job("joined-e2e", "joined-e2e")
        condition = re.findall(r"^    if: ([^\n]+)$", block, re.M)[0]
        mutations = (
            condition.replace("needs.scope.result == 'success' && ", "", 1),
            condition.replace(" && needs.scope.outputs.joined == 'true'", "", 1),
            condition.replace("'parser-entity-delta'", "'entity-delta'", 1),
            condition + " || needs.scope.outputs.mode == 'unknown'",
        )
        for mutation in mutations:
            with self.subTest(condition=mutation):
                self.assertNotEqual(mutation, condition)
                with (
                    patch(
                        __name__ + ".required_job",
                        return_value=block.replace(condition, mutation, 1),
                    ),
                    self.assertRaises(AssertionError),
                ):
                    self.test_joined_registration_routes_only_successful_full_or_selected_parser_delta()

    def test_joined_registration_registers_exact_three_suites_with_step_only_synthetic_fixture(
        self,
    ) -> None:
        block = required_job("joined-e2e", "joined-e2e")
        start = block.index(
            "      - name: G1-11 producer and seven-member synthetic contract tests\n"
        )
        end = block.index("      - name: Install the frozen Foundation web dependencies\n", start)
        step = block[start:end]
        self.assertIn("timeout-minutes: 5", step)
        self.assertIn("set -euo pipefail", step)
        self.assertIn('materialize-g1-11-contract-fixture.mjs "$RUNNER_TEMP"', step)
        self.assertIn('G1_11_FIXTURE_MANIFEST="$fixture_manifest" node --test', step)
        self.assertEqual(
            re.findall(r"core/tests/e2e/joined/([a-z0-9-]+\.test\.mjs)", step),
            [
                "g1-11-runtime-producer.test.mjs",
                "g1-11-producer-review-correction.test.mjs",
                "g1-11-seven-member-scenario.test.mjs",
            ],
        )
        for forbidden in (
            "TAVONEL_JOINED_G1_11_MANIFEST",
            "TAVONEL_JOINED_G1_11_MAX_CREDITS",
            "$GITHUB_ENV",
            "continue-on-error",
            "|| true",
            "curl",
            "wget",
        ):
            self.assertNotIn(forbidden, step)
        self.assertEqual(source("joined-e2e").count("G1_11_FIXTURE_MANIFEST="), 1)
        self.assertIn("run: node --test core/tests/e2e/joined/s3-bucket.test.mjs", block)
        self.assertIn(
            "core/tests/e2e/joined/joined-diagnostics.test.mjs "
            "core/tests/e2e/joined/joined-review-selection.test.mjs",
            block,
        )

    def test_joined_registration_selected_joined_success_is_current_execution_not_full_release(
        self,
    ) -> None:
        result, report = run_gate(gate_code("joined-e2e"), "parser-delta", self.selected_needs())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(report["full_qualified"])
        self.assertEqual(report["qualification"], "affected-only-not-full-qualified")
        self.assertEqual(
            report["outcomes"]["joined-e2e"],
            {"result": "success", "execution": "executed-current-run"},
        )
        self.assertEqual(report["tested_head"], "a" * 40)
        self.assertEqual((report["run_id"], report["run_attempt"]), ("700", "3"))

    def test_joined_registration_selected_joined_rejects_missing_failed_cancelled_skipped_or_extra(
        self,
    ) -> None:
        code = gate_code("joined-e2e")
        for kind in (
            "failure",
            "cancelled",
            "skipped",
            "missing",
            "extra",
            "scope-failure",
            "scope-cancelled",
            "mode-mismatch",
        ):
            with self.subTest(kind=kind):
                needs = self.selected_needs()
                if kind == "missing":
                    del needs["joined-e2e"]
                elif kind == "extra":
                    needs["unreviewed"] = {"result": "success"}
                elif kind == "mode-mismatch":
                    needs["scope"]["outputs"]["mode"] = "full"
                elif kind.startswith("scope-"):
                    needs["scope"]["result"] = kind.split("-", 1)[1]
                else:
                    needs["joined-e2e"]["result"] = kind
                result, report = run_gate(code, "parser-delta", needs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(report)

    def test_joined_registration_parser_only_omits_joined_and_invalid_selection_fails_closed(
        self,
    ) -> None:
        code = gate_code("joined-e2e")
        needs = self.selected_needs("false", "skipped")
        result, report = run_gate(code, "parser-delta", needs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["outcomes"]["joined-e2e"]["execution"], "not-executed")
        self.assertFalse(report["full_qualified"])
        for invalid in (None, "", "TRUE", True, 1, "unreviewed"):
            with self.subTest(flag=invalid):
                broken = self.selected_needs("false", "skipped")
                if invalid is None:
                    del broken["scope"]["outputs"]["joined"]
                else:
                    broken["scope"]["outputs"]["joined"] = invalid
                result, report = run_gate(code, "parser-delta", broken)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(report)
        for mode in ("unknown", "broad-required"):
            broken = self.selected_needs()
            broken["scope"]["outputs"]["mode"] = mode
            result, report = run_gate(code, mode, broken)
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(report)
        result, _ = run_gate(code, "parser-delta", self.selected_needs("false", "success"))
        self.assertNotEqual(result.returncode, 0)

    def test_joined_registration_full_requires_current_joined_success_as_before(self) -> None:
        code = gate_code("joined-e2e")
        needs = outcomes(["joined-e2e"], "full", {"joined-e2e"})
        result, report = run_gate(code, "full", needs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["full_qualified"])
        self.assertEqual(report["qualification"], "full-current-run")
        for outcome in ("skipped", "cancelled", "failure"):
            needs["joined-e2e"]["result"] = outcome
            result, report = run_gate(code, "full", needs)
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(report)

    def test_joined_registration_materializer_emits_exact_manifest_and_all_seven_frozen_payloads(
        self,
    ) -> None:
        pins = {
            "fixture-manifest.json": (
                8752,
                "cb55390d92dacbb236a057416d88140c7ef1e470147bef262375875ebeba9c68",
            ),
            "normal.pdf": (687, "5d83b53cc91711f47f19e7c60c3912a193c9dc6a88681a7b94969aa3046a597f"),
            "duplicate.pdf": (
                687,
                "5d83b53cc91711f47f19e7c60c3912a193c9dc6a88681a7b94969aa3046a597f",
            ),
            "denied.pdf": (687, "59bd6a3eb2bcb63dc03ba1b5ec6e8f113eea6fbc68741d07f3be165d31e3db34"),
            "excluded.pdf": (
                689,
                "3073018e3224b47969fd494a8f7b0ae2c0aa2810833d1a41218601a3fd9aa13d",
            ),
            "failed.pdf": (288, "48d0c46e2123e4b0b4c3c20d75e221affcd396938b19f00f7e7bb01177c73eb9"),
            "unknown.pdf": (
                688,
                "b27f802772746cfbcf7462e0b7834904b80d65f11ae16d055b6ef2fe9178ee50",
            ),
            "unsupported.hwp": (
                305,
                "05870069a77048533c1eb449c5521accc0510a2f56b4181d9e768025debf752e",
            ),
        }
        with tempfile.TemporaryDirectory(prefix="g111-materializer-contract-") as directory:
            result = self.invoke_materializer(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest_path = Path(result.stdout.strip())
            self.assertEqual(manifest_path.parent.parent, Path(directory).resolve())
            self.assertEqual({p.name for p in manifest_path.parent.iterdir()}, set(pins))
            for name, (size, digest) in pins.items():
                payload = (manifest_path.parent / name).read_bytes()
                self.assertEqual(len(payload), size)
                self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)
            manifest = json.loads(manifest_path.read_bytes())
            self.assertEqual(manifest["runtime_status"], "NOT_RUN")
            self.assertEqual(manifest["purpose"], "OFFLINE_SYNTHETIC_FIXTURE_ONLY")
            self.assertEqual(len(manifest["files"]), 7)

    def test_joined_registration_materializer_refuses_traversal_relative_file_missing_or_extra_args(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="g111-materializer-boundary-") as directory:
            sentinel = Path(directory) / "sentinel"
            sentinel.write_bytes(b"KEEP")
            invalids = (
                "relative",
                str(Path(directory) / "missing"),
                str(sentinel),
                directory + os.sep + ".." + os.sep + Path(directory).name,
            )
            for root in invalids:
                with self.subTest(root=root):
                    result = self.invoke_materializer(root)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual({p.name for p in Path(directory).iterdir()}, {"sentinel"})
            result = self.invoke_materializer(directory, "unexpected")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_bytes(), b"KEEP")

    def test_joined_registration_materializer_uses_fresh_destinations_and_never_overwrites(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="g111-materializer-fresh-") as directory:
            one = self.invoke_materializer(directory)
            self.assertEqual(one.returncode, 0, one.stderr)
            first = Path(one.stdout.strip())
            sentinel = first.parent / "sentinel"
            sentinel.write_bytes(b"KEEP")
            before = {p.name: p.read_bytes() for p in first.parent.iterdir()}
            two = self.invoke_materializer(directory)
            self.assertEqual(two.returncode, 0, two.stderr)
            second = Path(two.stdout.strip())
            self.assertNotEqual(first.parent, second.parent)
            self.assertEqual({p.name: p.read_bytes() for p in first.parent.iterdir()}, before)

    def test_joined_registration_materializer_refuses_corrupt_embedded_bytes_before_writes(
        self,
    ) -> None:
        source_bytes = self.materializer().read_text(encoding="utf-8")
        original = '"sha256": "59bd6a3eb2bcb63dc03ba1b5ec6e8f113eea6fbc68741d07f3be165d31e3db34"'
        self.assertEqual(source_bytes.count(original), 1)
        with tempfile.TemporaryDirectory(prefix="g111-materializer-corrupt-") as directory:
            script = Path(directory) / "corrupt.mjs"
            script.write_text(
                source_bytes.replace(original, '"sha256": "' + "0" * 64 + '"'), encoding="utf-8"
            )
            root = Path(directory) / "runner-temp"
            root.mkdir()
            result = self.invoke_materializer(str(root), script=script)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Frozen fixture bytes differ", result.stderr)
            self.assertEqual(list(root.iterdir()), [])

    def test_joined_registration_materializer_refuses_existing_symlink_root_or_ancestor(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="g111-materializer-links-") as directory:
            root = Path(directory)
            target = root / "ordinary"
            target.mkdir()
            child = target / "child"
            child.mkdir()
            link = root / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                # Windows directory junction uses no new grants and exercises
                # the same lstat boundary.
                if os.name != "nt":
                    raise
                powershell = existing_executable(shutil.which("powershell"), "powershell")
                environment = checked_junction_environment(root, link, target)
                result = subprocess.run(  # noqa: S603 - fixed script, validated owned junction data
                    [
                        powershell,
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        "-",
                    ],
                    input="$ErrorActionPreference = 'Stop'\n"
                    "$null = New-Item -ItemType Junction -Path $env:TAVONEL_JUNCTION_LINK "
                    "-Target $env:TAVONEL_JUNCTION_TARGET\n",
                    env=environment,
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
            for path in (link, link / "child"):
                result = self.invoke_materializer(str(path))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
            self.assertEqual({p.name for p in target.iterdir()}, {"child"})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestK15FiniteWorkflowAdmission(unittest.TestCase):
    def test_k15_all_current_aggregates_accept_explicit_modes_and_refuse_unknown(self):
        for mode in ("entity-delta", "parser-entity-delta"):
            for workflow, ids, selected in (
                ("ci", CI_JOBS, set()),
                ("model-ci", MODEL_JOBS, set()),
                ("security", SECURITY_JOBS, {"codeql", "filesystem-and-iac", "ip-privilege-guard"}),
                ("joined-e2e", ["joined-e2e"], set()),
                ("pr91-focused-qualification", FOCUSED_JOBS, {"python-focused"}),
            ):
                needs = outcomes(ids, mode, selected)
                result, report = run_gate(
                    gate_code(
                        workflow,
                        (
                            "focused-qualification"
                            if workflow == "pr91-focused-qualification"
                            else "affected-scope"
                        ),
                    ),
                    mode,
                    needs,
                )
                self.assertEqual(result.returncode, 0, (workflow, result.stderr))
                self.assertFalse(report["full_qualified"])
                for job in set(ids) - selected:
                    self.assertEqual(report["outcomes"][job]["execution"], "not-executed")
                code = gate_code(
                    workflow,
                    (
                        "focused-qualification"
                        if workflow == "pr91-focused-qualification"
                        else "affected-scope"
                    ),
                )
                for broken in (
                    "scope-failure",
                    "mode-mismatch",
                    "unexpected-success",
                    "selected-skipped",
                ):
                    bad = json.loads(json.dumps(needs))
                    if broken == "scope-failure":
                        bad["scope"]["result"] = "failure"
                    elif broken == "mode-mismatch":
                        bad["scope"]["outputs"]["mode"] = "full"
                    elif broken == "unexpected-success":
                        omitted = set(ids) - selected
                        if not omitted:
                            continue
                        bad[sorted(omitted)[0]]["result"] = "success"
                    else:
                        if not selected:
                            continue
                        bad[sorted(selected)[0]]["result"] = "skipped"
                    failed, _ = run_gate(code, mode, bad)
                    self.assertEqual(failed.returncode, 1, (workflow, broken))
                invalid, _ = run_gate(
                    code, "arbitrary-python", outcomes(ids, "arbitrary-python", selected)
                )
                self.assertEqual(invalid.returncode, 1)

    def test_k15_joined_combined_requires_current_success_and_entity_only_cannot_select(self):
        code = gate_code("joined-e2e")
        for mode, joined, success in (
            ("parser-entity-delta", "true", True),
            ("entity-delta", "false", False),
        ):
            needs = outcomes(["joined-e2e"], mode, {"joined-e2e"} if success else set())
            needs["scope"]["outputs"]["joined"] = joined
            result, report = run_gate(code, mode, needs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                report["outcomes"]["joined-e2e"]["execution"],
                "executed-current-run" if success else "not-executed",
            )
            for wrong in (None, "invalid"):
                bad = json.loads(json.dumps(needs))
                if wrong is None:
                    del bad["scope"]["outputs"]["joined"]
                else:
                    bad["scope"]["outputs"]["joined"] = wrong
                failed, _ = run_gate(code, mode, bad)
                self.assertEqual(failed.returncode, 1)
        needs = outcomes(["joined-e2e"], "entity-delta", {"joined-e2e"})
        needs["scope"]["outputs"]["joined"] = "true"
        result, _ = run_gate(code, "entity-delta", needs)
        self.assertEqual(result.returncode, 1)

    def test_k15_focused_actual_commands_select_entity_and_preserve_parser_targets(self):
        block = required_job("pr91-focused-qualification", "python-focused")
        self.assertIn("needs.scope.outputs.mode == 'entity-delta'", block)
        self.assertIn("needs.scope.outputs.mode == 'parser-entity-delta'", block)
        self.assertIn("if: needs.scope.outputs.mode != 'entity-delta'", block)
        self.assertIn("files=(tests/unit/test_entity.py)", block)
        self.assertIn("files+=(tests/unit/test_entity.py)", block)
        for path in ORIGINAL_NINE + SHARED_SEVEN:
            self.assertIn(path, block)
        self.assertIn("packages=(packages/cir-python/src)", block)
        self.assertIn('report["required_tests"]', block)
        for body in embedded_python(block):
            compile(body, "new-focused-heredoc", "exec")
        joined = required_job("joined-e2e", "joined-e2e")
        self.assertIn("needs.scope.outputs.mode == 'parser-entity-delta'", joined)
        self.assertNotIn("needs.scope.outputs.mode == 'entity-delta'", joined)
        self.assertIn("timeout-minutes: 75", joined)
        self.assertNotIn("TAVONEL_JOINED_G1_11_MANIFEST:", joined)

    def test_k15_existing_narrow_contracts_stay_valid_with_new_source_admission(self):
        for workflow, ids, selected in (
            ("ci", CI_JOBS, set()),
            ("model-ci", MODEL_JOBS, set()),
            ("joined-e2e", ["joined-e2e"], set()),
            ("pr91-focused-qualification", FOCUSED_JOBS, {"python-focused"}),
        ):
            code = gate_code(
                workflow,
                (
                    "focused-qualification"
                    if workflow == "pr91-focused-qualification"
                    else "affected-scope"
                ),
            )
            result, report = run_gate(code, "parser-delta", outcomes(ids, "parser-delta", selected))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(report["full_qualified"])
        self.assertIn("name: 'Model scope: omitted jobs not executed'", source("model-ci"))
        self.assertIn("core/tests/e2e/joined/g1-11-runtime-producer.test.mjs", source("joined-e2e"))
        self.assertIn(
            "core/tests/e2e/joined/g1-11-producer-review-correction.test.mjs", source("joined-e2e")
        )
        self.assertIn(
            "core/tests/e2e/joined/g1-11-seven-member-scenario.test.mjs", source("joined-e2e")
        )

    def test_k15_literal_focused_shell_targets_by_mode_without_executing_products(self):
        bash = shutil.which("git")
        if not bash:
            raise RuntimeError("Git installation required")
        bash = (
            Path(bash).resolve().parent.parent / "bin/bash.exe"
            if os.name == "nt"
            else Path("/bin/bash")
        )
        if not bash.is_file():
            raise RuntimeError("Existing Bash required; no install or fallback")
        block = required_job("pr91-focused-qualification", "python-focused")
        labels = [
            "Run only the PR91-affected test files",
            "Run shared parser pipeline and affected routing contracts",
            "Type check affected compiler and CIR packages",
        ]
        for mode in ("entity-delta", "parser-entity-delta", "parser-delta"):
            for label in labels:
                piece = block.split("      - name: " + label + "\n", 1)[1].split(
                    "      - name:", 1
                )[0]
                script = piece.split("        run: |\n", 1)[1]
                script = "\n".join(line[10:] for line in script.splitlines()) + "\n"
                with tempfile.TemporaryDirectory(prefix="k15-command-selector-") as directory:
                    root = Path(directory)
                    for name in ORIGINAL_NINE + SHARED_SEVEN + ["tests/unit/test_entity.py"]:
                        target = root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text("# empty synthetic command-selection input\n")
                    (root / "evidence").mkdir()
                    prefix = 'python() { printf "%s\\n" "$@" > "$ARGV_FILE"; }\n'
                    filename = root / "selected.sh"
                    filename.write_text(prefix + script, encoding="utf-8")
                    environment = dict(
                        os.environ, SCOPE_MODE=mode, EVIDENCE_DIR="evidence", ARGV_FILE="argv.txt"
                    )
                    child = subprocess.run(  # noqa: S603 - fixed task-owned command
                        [
                            str(bash),
                            str(filename),
                        ],
                        cwd=root,
                        env=environment,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(child.returncode, 0, (mode, label, child.stderr))
                    args = (root / "argv.txt").read_text().splitlines()
                    if label == labels[0]:
                        expected = (
                            ["tests/unit/test_entity.py"]
                            if mode == "entity-delta"
                            else ORIGINAL_NINE
                            + (
                                ["tests/unit/test_entity.py"]
                                if mode == "parser-entity-delta"
                                else []
                            )
                        )
                        self.assertEqual(
                            [
                                x
                                for x in args
                                if x.startswith("tests/") or x.startswith("services/")
                            ],
                            expected,
                        )
                    elif label == labels[1]:
                        expected = SHARED_SEVEN[-2:] if mode == "entity-delta" else SHARED_SEVEN
                        self.assertEqual([x for x in args if x.startswith("tests/")], expected)
                    else:
                        expected = (
                            ["packages/cir-python/src"]
                            if mode == "entity-delta"
                            else ["packages/compiler-runtime/src", "packages/cir-python/src"]
                        )
                        self.assertEqual([x for x in args if x.startswith("packages/")], expected)


OCR_V3_MODE = "parser-entity-ocr-v3-delta"
OCR_V3_TESTS = [
    "tests/unit/test_product_core_ocr_v3.py",
    "tests/unit/test_product_core_journal.py",
    "tests/unit/test_product_core_journal_maintenance.py",
    "tests/unit/test_product_core_region_anchors.py",
    "tests/unit/test_product_core_bridge.py",
]


class TestOcrV3ProductCoreWorkflowAdmission(unittest.TestCase):
    """The OCR v3 product-core mode: its own selection, omitted jobs are pending debt."""

    def classifier(self):
        path = ROOT / "scripts/classify_pr91_affected_scope.py"
        spec = importlib.util.spec_from_file_location("pr91_scope_classifier_ocr_v3", path)
        if spec is None or spec.loader is None:
            raise AssertionError("Classifier source is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def step_argv(self, label: str, mock_exit: str = "0") -> tuple[int, list[str]]:
        git = shutil.which("git")
        self.assertIsNotNone(git, "Existing Git/Bash required; no installation fallback")
        bash = (
            Path(git).resolve().parent.parent / "bin/bash.exe"
            if os.name == "nt"
            else Path("/bin/bash")
        )
        bash_executable = existing_executable(bash, "bash")
        block = required_job("pr91-focused-qualification", "python-focused")
        piece = block.split("      - name: " + label + "\n", 1)[1].split("      - name:", 1)[0]
        body = piece.split("        run: |\n", 1)[1]
        script = "\n".join(line[10:] for line in body.splitlines()) + "\n"
        with tempfile.TemporaryDirectory(prefix="ocr-v3-command-selector-") as directory:
            root = Path(directory)
            for name in ORIGINAL_NINE + SHARED_SEVEN + ["tests/unit/test_entity.py", *OCR_V3_TESTS]:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# empty synthetic command-selection input\n")
            (root / "evidence").mkdir()
            filename = root / "type.sh"
            fixture = (
                'python() { printf "%s\\n" "$@" > "$ARGV_FILE"; return "$MOCK_MYPY_EXIT"; }\n'
                + script
            )
            filename.write_text(fixture, encoding="utf-8")
            environment = checked_bash_environment(
                dict(
                    os.environ,
                    SCOPE_MODE=OCR_V3_MODE,
                    EVIDENCE_DIR="evidence",
                    ARGV_FILE="argv.txt",
                    MOCK_MYPY_EXIT=mock_exit,
                )
            )
            child = subprocess.run(  # noqa: S603 - installed Bash, owned reviewed fragment
                [
                    bash_executable,
                    "--noprofile",
                    "--norc",
                    checked_fixture_script(filename, root, fixture),
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                shell=False,
                timeout=10,
                check=False,
            )
            self.assertLessEqual(len(child.stdout) + len(child.stderr), 65536)
            return child.returncode, (root / "argv.txt").read_text().splitlines()

    def test_ocr_v3_every_aggregate_accepts_mode_and_reports_omitted_jobs_as_pending(self):
        security_selected = {"codeql", "filesystem-and-iac", "ip-privilege-guard"}
        for workflow, job, ids, selected, joined, extra in (
            ("ci", "affected-scope", CI_JOBS, set(), "false", {}),
            ("model-ci", "affected-scope", MODEL_JOBS, set(), "false", {}),
            ("security", "affected-scope", SECURITY_JOBS, security_selected, "false", {}),
            (
                "security",
                "affected-scope",
                SECURITY_JOBS,
                security_selected - {"codeql"},
                "false",
                {"GHAS_AVAILABLE": "false"},
            ),
            ("joined-e2e", "affected-scope", ["joined-e2e"], {"joined-e2e"}, "true", {}),
            ("joined-e2e", "affected-scope", ["joined-e2e"], set(), "false", {}),
            (
                "pr91-focused-qualification",
                "focused-qualification",
                FOCUSED_JOBS,
                {"python-focused"},
                "false",
                {},
            ),
        ):
            with self.subTest(workflow=workflow, selected=sorted(selected), extra=extra):
                code = gate_code(workflow, job)
                self.assertIn("every job in pending_debt is open debt, not a pass", code)
                needs = outcomes(ids, OCR_V3_MODE, selected)
                needs["scope"]["outputs"]["joined"] = joined
                result, report = run_gate(code, OCR_V3_MODE, needs, **extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(report["full_qualified"])
                self.assertNotEqual(report["qualification"], "full-current-run")
                self.assertEqual(report["pending_debt"], sorted(set(ids) - selected))
                for name in ids:
                    self.assertEqual(
                        report["outcomes"][name]["execution"],
                        "executed-current-run" if name in selected else "not-executed",
                    )
                legacy = outcomes(ids, "parser-entity-delta", selected)
                legacy["scope"]["outputs"]["joined"] = joined
                result, previous = run_gate(code, "parser-entity-delta", legacy, **extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("pending_debt", previous)
                for broken in ("selected-skipped", "omitted-success", "scope-failure", "mismatch"):
                    bad = json.loads(json.dumps(needs))
                    if broken == "selected-skipped":
                        if not selected:
                            continue
                        bad[sorted(selected)[0]]["result"] = "skipped"
                    elif broken == "omitted-success":
                        omitted = set(ids) - selected
                        if not omitted:
                            continue
                        bad[sorted(omitted)[0]]["result"] = "success"
                    elif broken == "scope-failure":
                        bad["scope"]["result"] = "failure"
                    else:
                        bad["scope"]["outputs"]["mode"] = "parser-entity-delta"
                    failed, receipt = run_gate(code, OCR_V3_MODE, bad, **extra)
                    self.assertEqual(failed.returncode, 1, broken)
                    self.assertIsNone(receipt)

    def test_ocr_v3_joined_flag_is_required_and_entity_only_rule_is_unchanged(self):
        code = gate_code("joined-e2e")
        for flag in (None, "", "TRUE", "unreviewed"):
            with self.subTest(flag=flag):
                needs = outcomes(["joined-e2e"], OCR_V3_MODE, set())
                if flag is None:
                    del needs["scope"]["outputs"]["joined"]
                else:
                    needs["scope"]["outputs"]["joined"] = flag
                result, report = run_gate(code, OCR_V3_MODE, needs)
                self.assertEqual(result.returncode, 1)
                self.assertIsNone(report)
        block = required_job("joined-e2e", "joined-e2e")
        condition = re.findall(r"^    if: ([^\n]+)$", block, re.M)
        self.assertEqual(len(condition), 1)
        for result in ("success", "failure", "cancelled", None):
            for joined in ("true", "false", "invalid", None):
                self.assertEqual(
                    joined_condition_selected(condition[0], result, OCR_V3_MODE, joined),
                    result == "success" and joined == "true",
                    (result, joined),
                )

    def test_ocr_v3_focused_python_runs_ocr_tests_product_core_mypy_and_shared(self):
        classifier = self.classifier()
        self.assertEqual(list(classifier.OCR_V3_REQUIRED_TESTS), OCR_V3_TESTS)
        self.assertEqual(classifier.OCR_V3_MODE, OCR_V3_MODE)
        block = required_job("pr91-focused-qualification", "python-focused")
        self.assertIn(f"needs.scope.outputs.mode == '{OCR_V3_MODE}'", block)
        self.assertIn("if: needs.scope.outputs.mode != 'entity-delta'", block)
        for label in (
            "Collect the selected test tree (no execution)",
            "Ruff on the Python paths this PR changes",
        ):
            step = block.split("      - name: " + label + "\n", 1)[1].split("      - name:", 1)[0]
            self.assertIn(f'"$SCOPE_MODE" == "{OCR_V3_MODE}" ]]; then', step)
            self.assertIn(f'"parser-entity-delta", "{OCR_V3_MODE}"}}', step)
        code, argv = self.step_argv("Run only the PR91-affected test files")
        self.assertEqual(code, 0)
        self.assertEqual(
            [x for x in argv if x.startswith(("tests/", "services/"))],
            [*ORIGINAL_NINE, "tests/unit/test_entity.py", *OCR_V3_TESTS],
        )
        code, argv = self.step_argv("Run shared parser pipeline and affected routing contracts")
        self.assertEqual(code, 0)
        self.assertEqual([x for x in argv if x.startswith("tests/")], SHARED_SEVEN)
        for mock_exit in ("0", "23"):
            code, argv = self.step_argv("Type check affected compiler and CIR packages", mock_exit)
            self.assertEqual(code, int(mock_exit))
            self.assertEqual(
                argv,
                [
                    "-m",
                    "uv",
                    "run",
                    "--locked",
                    "--extra",
                    "dev",
                    "mypy",
                    "packages/compiler-runtime/src",
                    "packages/cir-python/src",
                    "packages/product-core/src",
                ],
            )

    def test_ocr_v3_omitted_image_web_db_model_jobs_stay_full_only(self):
        for workflow, ids in (
            ("ci", CI_JOBS),
            ("model-ci", MODEL_JOBS),
            ("pr91-focused-qualification", FOCUSED_JOBS[1:]),
            ("security", ["dependency-review", "dependency-audit", "application-images"]),
        ):
            for job in ids:
                with self.subTest(workflow=workflow, job=job):
                    block = required_job(workflow, job)
                    self.assertIn("needs.scope.outputs.mode == 'full'", block)
                    self.assertNotIn(OCR_V3_MODE, block)
        for workflow in ("ci", "security", "model-ci"):
            block = required_job(workflow, "full-qualification")
            self.assertNotIn(OCR_V3_MODE, block)
