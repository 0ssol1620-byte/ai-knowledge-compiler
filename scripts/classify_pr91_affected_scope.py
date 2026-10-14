"""Fail-closed PR91 routing over exact Git evidence, without executing checks.

The narrow route describes the reviewed parser successor and finite joined source delta.
A classification is never evidence that a test, audit, image build or release prerequisite passed.
This helper never fetches, changes Git state or calls an external service.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

ANCHOR_COMMIT = "621b7d692d21ca73e133010e7e234cc0ffe28086"
ANCHOR_TREE = "be7d4a6a5166b4b6a31372d1496fa3d7a26e65c8"
REVIEWED_TREE_REFERENCE = "397210e9e91fd398165988ef533f29b3ff283d36"
REPOSITORY = "0ssol1620-byte/ai-knowledge-compiler"
# This private tree need not exist in published history. Bind its six payload
# files individually; never manufacture a remotely published successor commit.
PINNED_PAYLOAD = {
    "packages/compiler-runtime/src/akc_compiler_runtime/extraction.py":
        "fb9e0edb665d5da1d83dbee82f1232a60dbdc22e",
    "packages/compiler-runtime/src/akc_compiler_runtime/pipeline.py":
        "84848dffcafe288ee80430c1b3036f3e71ab1389",
    "scripts/prepare_parser_upgrade_fixtures.py": "efe51ff99b2824c210ee21996139240d517300d5",
    "tests/integration/test_document_parser_policy_upgrade.py":
        "e0e93397ad4ac68fa1bae5332c2b4d0ffb193416",
    "tests/unit/test_document_remaining_state_extraction.py":
        "f02f4d9b6866d3a41f62b681da84dffa4614dee0",
    "tests/unit/test_parser_upgrade_ci_contract.py": "4d486de75a9c314ac6f4442758b3f27055c1dfeb",
}
# K15 is a separately reviewed finite pair, never an arbitrary Python prefix.
ENTITY_PAYLOAD = {
    "packages/cir-python/src/akc_cir/entity.py": "7536ab16f28be68d2d6d43aa261702f5bb491349",
    "tests/unit/test_entity.py": "aeddade75b55a00b70ffe0a7aed05a89a3123839",
}
ENTITY_REQUIRED_TESTS = (
    "tests/unit/test_entity.py",
    "tests/unit/test_pr91_affected_scope.py",
    "tests/unit/test_pr91_affected_workflow_contract.py",
)
NARROW_MODES = {"parser-delta", "entity-delta", "parser-entity-delta"}
# Exact repository source registration; no prefix/wildcard or runtime qualification.
JOINED_SOURCE_PATHS = (
    "tests/e2e/joined/g1-11-runtime-producer.mjs",
    "tests/e2e/joined/g1-11-runtime-producer.test.mjs",
    "tests/e2e/joined/g1-11-producer-review-correction.test.mjs",
    "tests/e2e/joined/HOOKS-AND-REVIEW.md",
    "tests/e2e/joined/g1-11-seven-member-scenario.mjs",
    "tests/e2e/joined/g1-11-seven-member-scenario.test.mjs",
    "tests/e2e/joined/joined-e2e.mjs",
    "tests/e2e/joined/materialize-g1-11-contract-fixture.mjs",
)
REQUIRED_JOINED_TESTS = (
    "tests/e2e/joined/g1-11-runtime-producer.test.mjs",
    "tests/e2e/joined/g1-11-producer-review-correction.test.mjs",
    "tests/e2e/joined/g1-11-seven-member-scenario.test.mjs",
)
CI_CONTROL_PATHS = {
    "scripts/classify_pr91_affected_scope.py",
    "tests/unit/test_pr91_affected_scope.py",
    ".github/workflows/ci.yml",
    ".github/workflows/pr91-focused-qualification.yml",
    ".github/workflows/security.yml",
    ".github/workflows/model-ci.yml",
    ".github/workflows/joined-e2e.yml",
    ".github/workflows/release-gates.yml",
    "tests/unit/test_pr91_affected_workflow_contract.py",
    "docs/audit/PR91_AFFECTED_SCOPE.md",
}
UNCHANGED_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "pnpm-lock.yaml",
    "package.json",
    "pnpm-workspace.yaml",
    ".dockerignore",
    "services/api/Dockerfile",
    "services/scheduler/Dockerfile",
    "workers/cpu-document/Dockerfile",
    "apps/web/Dockerfile",
    "infra/product-core/Dockerfile",
    "workers/gpu-parser/Dockerfile",
    "workers/gpu-knowledge/Dockerfile",
    "workers/gpu-hpd/Dockerfile",
    "workers/gpu-unlimited/Dockerfile",
    "workers/gpu-common/pyproject.toml",
    "workers/gpu-common/uv.lock",
)
REQUIRED_TESTS = (
    "tests/unit/test_hwpx_structured_parser.py",
    "tests/unit/test_nonpdf_structured_parsers.py",
    "tests/unit/test_product_core_native_cir.py",
    "tests/unit/test_product_core_native_world_manifest.py",
    "tests/unit/test_document_remaining_state_extraction.py",
    "tests/integration/test_document_parser_policy_upgrade.py",
    "tests/unit/test_parser_upgrade_ci_contract.py",
    "tests/security/test_security_boundaries.py",
    "services/api/tests/test_native_nonpdf_worker_e2e.py",
    "tests/integration/test_core_parser_cache.py",
    "tests/integration/test_core_runtime_history_safety_claude.py",
    "tests/integration/test_core_semantic_incremental_runtime.py",
    "tests/unit/test_answer_compiler.py",
    "tests/unit/test_core_semantic_incremental_fixtures.py",
    "tests/unit/test_pr91_affected_scope.py",
    "tests/unit/test_pr91_affected_workflow_contract.py",
)
WORKFLOW_KINDS = {"ci", "focused", "security", "model", "joined"}
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class EvidenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _git(repo: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise EvidenceError("missing-git", "Git evidence is unavailable")
    environment = dict(os.environ)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        # Fixed operations, verified hexadecimal revisions, no shell or fetch.
        return subprocess.run(  # noqa: S603
            [executable, "-C", str(repo), *arguments],
            env=environment,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise EvidenceError("missing-git-evidence", "Required local Git evidence failed") from exc


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise EvidenceError("invalid-identity", f"{field} must be an exact hexadecimal commit SHA")
    return value


def _entries(repo: Path, revision: str, paths: tuple | dict | set) -> dict:
    raw = _git(repo, "ls-tree", "-r", "-z", revision, "--", *sorted(paths))
    entries = {}
    for item in raw.split(b"\0"):
        if item:
            metadata, path = item.decode("utf-8").split("\t", 1)
            mode, kind, blob = metadata.split()
            entries[path] = {"mode": mode, "kind": kind, "blob": blob}
    return entries


def _changes(repo: Path, base: str, head: str) -> list[dict]:
    raw = _git(
        repo,
        "diff",
        "--raw",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        "--abbrev=40",
        "-z",
        base,
        head,
    )
    parts = raw.split(b"\0")
    records = []
    for index in range(0, len(parts) - 1, 2):
        if index + 1 >= len(parts) - 1:
            raise EvidenceError("invalid-diff", "Incomplete raw Git change evidence")
        metadata = parts[index].decode("ascii").split()
        if len(metadata) != 5 or not metadata[0].startswith(":"):
            raise EvidenceError("invalid-diff", "Unsupported raw Git change evidence")
        path = parts[index + 1].decode("utf-8")
        if "\n" in path or "\r" in path:
            raise EvidenceError("invalid-path", "Unsupported path line breaks")
        records.append(
            {
                "path": path,
                "status": metadata[4],
                "old_mode": metadata[0][1:],
                "new_mode": metadata[1],
                "old_blob": metadata[2],
                "new_blob": metadata[3],
            }
        )
    return records


def _selection(mode: str, joined: bool = False) -> dict:
    accepted = mode == "full" or mode in NARROW_MODES
    full = mode == "full"
    return {
        "python": accepted,
        "images": full,
        "web": full,
        "db": full,
        "model": full,
        "joined": full or (mode in {"parser-delta", "parser-entity-delta"} and joined),
        "security_core": accepted,
        "dependency_audit": full,
        "codeql_languages": ["python", "javascript-typescript"] if full else ["python"],
    }


def classify(repo: Path, event: dict, event_name: str, workflow_kind: str) -> dict:
    report = {
        "mode": "broad-required",
        "full_qualification": False,
        "selection": _selection("broad-required"),
        "reason_codes": [],
        "reasons": [],
        "identity": {
            "event_name": event_name,
            "workflow_kind": workflow_kind,
            "anchor_commit": ANCHOR_COMMIT,
            "anchor_tree": ANCHOR_TREE,
        },
        "delta": None,
        "cumulative_pr_diff": None,
        "unchanged_inputs": None,
        "required_tests": list(REQUIRED_TESTS),
        "required_joined_tests": [],
        "joined_sources": None,
        "entity_sources": None,
        "qualification_semantics": "Selection only; no test/audit/image/release pass is inherited",
        "reviewed_payload_tree_reference": REVIEWED_TREE_REFERENCE,
    }
    joined_active = False
    try:
        if workflow_kind not in WORKFLOW_KINDS:
            raise EvidenceError("invalid-workflow", "Unknown workflow kind")
        if not isinstance(event, dict) or not isinstance(event.get("repository"), dict):
            raise EvidenceError("invalid-event", "Repository event evidence is missing")
        repository = event["repository"].get("full_name")
        if not isinstance(repository, str) or not repository:
            raise EvidenceError("invalid-event", "Repository identity is missing")
        head = _sha(_git(repo, "rev-parse", "HEAD^{commit}").decode().strip(), "checkout HEAD")
        tree = _sha(_git(repo, "rev-parse", "HEAD^{tree}").decode().strip(), "checkout tree")
        report["identity"].update(head_commit=head, head_tree=tree)
        if event_name == "pull_request":
            pull = event["pull_request"]
            if not isinstance(pull, dict):
                raise EvidenceError("invalid-event", "Pull-request identity is malformed")
            number = event.get("number", pull.get("number"))
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise EvidenceError("invalid-identity", "Missing pull-request number")
            if "number" in pull and pull["number"] != number:
                raise EvidenceError("invalid-identity", "Conflicting pull-request numbers")
            expected_head = _sha(pull["head"]["sha"], "event PR head")
            base = _sha(pull["base"]["sha"], "event PR base")
            if expected_head != head:
                raise EvidenceError("head-mismatch", "Checkout is not the event's exact PR head")
            merge_base = _sha(
                _git(repo, "merge-base", base, head).decode().strip(), "PR merge base"
            )
            report["identity"].update(
                pr_number=number,
                pr_base_commit=base,
                pr_merge_base=merge_base,
                cumulative_diff_basis="PR merge-base to event head; never the delta routing basis",
            )
            report["cumulative_pr_diff"] = {
                "base_commit": base,
                "merge_base": merge_base,
                "head_commit": head,
                "paths": _changes(repo, merge_base, head),
            }
            if number != 91:
                mode = "full"
            else:
                if repository != REPOSITORY or pull["head"]["repo"]["full_name"] != repository:
                    raise EvidenceError(
                        "fork-or-missing-repo", "PR91 narrow routing requires same repo"
                    )
                actual_anchor = _git(repo, "rev-parse", f"{ANCHOR_COMMIT}^{{tree}}")
                if actual_anchor.decode().strip() != ANCHOR_TREE:
                    raise EvidenceError(
                        "anchor-tree-mismatch", "Fixed historical anchor tree differs"
                    )
                _git(repo, "merge-base", "--is-ancestor", ANCHOR_COMMIT, head)
                changes = _changes(repo, ANCHOR_COMMIT, head)
                report["delta"] = {
                    "base_commit": ANCHOR_COMMIT,
                    "head_commit": head,
                    "paths": changes,
                    "python_paths": sorted(
                        item["path"]
                        for item in changes
                        if item["path"].endswith(".py") and item["new_mode"] == "100644"
                    ),
                }
                allowed = (
                    PINNED_PAYLOAD.keys()
                    | ENTITY_PAYLOAD.keys()
                    | CI_CONTROL_PATHS
                    | set(JOINED_SOURCE_PATHS)
                )
                if not changes:
                    raise EvidenceError("empty-delta", "No reviewed parser successor delta")
                for item in changes:
                    if item["path"] not in allowed:
                        raise EvidenceError("unknown-path", f"Unclassified path: {item['path']}")
                    if item["status"] not in {"A", "M"} or item["new_mode"] != "100644":
                        raise EvidenceError(
                            "unsupported-change", "Deletion/rename/type/mode not admitted"
                        )
                    if item["old_mode"] not in {"000000", "100644"}:
                        raise EvidenceError(
                            "unsupported-change", "Historical source mode not admitted"
                        )
                entity_changes = [item for item in changes if item["path"] in ENTITY_PAYLOAD]
                parser_active = any(item["path"] in PINNED_PAYLOAD for item in changes)
                # Original parser route always requires its frozen six payloads. An entity-only
                # route instead requires those parser files to remain exactly at the anchor.
                expected_payload = (
                    {
                        path: {"mode": "100644", "kind": "blob", "blob": blob}
                        for path, blob in PINNED_PAYLOAD.items()
                    }
                    if parser_active or not entity_changes
                    else _entries(repo, ANCHOR_COMMIT, PINNED_PAYLOAD)
                )
                payload = _entries(repo, head, PINNED_PAYLOAD)
                if payload != expected_payload:
                    raise EvidenceError(
                        "payload-mismatch",
                        "Reviewed parser payload or unchanged anchor entry set differs",
                    )
                before = _entries(repo, ANCHOR_COMMIT, UNCHANGED_INPUTS)
                after = _entries(repo, head, UNCHANGED_INPUTS)
                if before != after or set(before) != set(UNCHANGED_INPUTS):
                    raise EvidenceError(
                        "build-input-mismatch", "Declared build/dependency input differs"
                    )
                project = tomllib.loads(
                    _git(repo, "show", f"{ANCHOR_COMMIT}:pyproject.toml").decode()
                )
                wheel_packages = project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
                if any("compiler-runtime" in package for package in wheel_packages):
                    raise EvidenceError(
                        "wheel-scope-mismatch", "Compiler runtime enters packaged wheel"
                    )
                report["unchanged_inputs"] = {
                    "entries": before,
                    "wheel_packages": wheel_packages,
                    "qualification": (
                        "Static anchor/head equality only; no current audit or build pass"
                    ),
                    "image_boundary": (
                        "Builder COPY cache changes; frozen wheel excludes compiler-runtime. "
                        "No image execution or equivalence result is inherited."
                    ),
                }
                required = list(REQUIRED_TESTS)
                if entity_changes:
                    entity_sources = _entries(repo, head, ENTITY_PAYLOAD)
                    for path, blob in ENTITY_PAYLOAD.items():
                        if entity_sources.get(path) != {
                            "mode": "100644",
                            "kind": "blob",
                            "blob": blob,
                        }:
                            raise EvidenceError(
                                "entity-payload-mismatch", f"Reviewed K15 payload differs: {path}"
                            )
                    report["entity_sources"] = {
                        "changed_paths": sorted(item["path"] for item in entity_changes),
                        "entries": entity_sources,
                        "qualification": (
                            "Pinned source only; no entity accuracy, test or image equivalence pass"
                        ),
                    }
                    required = (
                        list(dict.fromkeys([*REQUIRED_TESTS, *ENTITY_REQUIRED_TESTS]))
                        if parser_active
                        else list(ENTITY_REQUIRED_TESTS)
                    )
                    report["required_tests"] = required
                    report["unchanged_inputs"]["image_boundary"] = (
                        "Build configuration equality only; CIR source changes "
                        "are not image equivalence. "
                        "Images are omitted by bounded routing; full image/release "
                        "qualification remains unrun."
                    )
                tests = _entries(repo, head, required)
                if any(
                    tests.get(path, {}).get("mode") != "100644"
                    or tests.get(path, {}).get("kind") != "blob"
                    for path in required
                ):
                    raise EvidenceError(
                        "required-test-missing", "Mandatory related test source unavailable"
                    )
                control = _entries(repo, head, ("scripts/classify_pr91_affected_scope.py",))
                classifier_source = control.get("scripts/classify_pr91_affected_scope.py", {})
                if classifier_source.get("mode") != "100644":
                    raise EvidenceError(
                        "required-control-missing", "Classifier source unavailable at head"
                    )
                joined_changes = [item for item in changes if item["path"] in JOINED_SOURCE_PATHS]
                if joined_changes:
                    if entity_changes and not parser_active:
                        raise EvidenceError(
                            "unsupported-combination",
                            "Entity-only route cannot activate joined sources",
                        )
                    joined_sources = _entries(repo, head, JOINED_SOURCE_PATHS)
                    if any(
                        joined_sources.get(path, {}).get("mode") != "100644"
                        or joined_sources.get(path, {}).get("kind") != "blob"
                        for path in JOINED_SOURCE_PATHS
                    ):
                        raise EvidenceError(
                            "joined-source-missing",
                            "Finite joined source set must be regular and complete",
                        )
                    joined_active = True
                    report["required_joined_tests"] = list(REQUIRED_JOINED_TESTS)
                    report["joined_sources"] = {
                        "changed_paths": sorted(item["path"] for item in joined_changes),
                        "entries": joined_sources,
                        "qualification": (
                            "Regular source presence only; no Node or runtime pass is inherited"
                        ),
                    }
                mode = (
                    ("parser-entity-delta" if parser_active else "entity-delta")
                    if entity_changes
                    else "parser-delta"
                )
        elif event_name == "push":
            if (
                event.get("ref") != "refs/heads/main"
                or _sha(event.get("after"), "push after") != head
            ):
                raise EvidenceError("invalid-push", "Full push policy requires exact main head")
            mode = "full"
        elif event_name in {"workflow_dispatch", "schedule"}:
            mode = "full"
        else:
            raise EvidenceError("unsupported-event", "No original full policy for this event")
        report.update(
            mode=mode,
            full_qualification=mode == "full",
            selection=_selection(mode, joined=joined_active),
        )
        report["reason_codes"] = [
            ("reviewed-" + mode) if mode in NARROW_MODES else "original-full-policy"
        ]
        report["reasons"] = [
            "Run only mandatory related checks"
            if mode in NARROW_MODES
            else "Preserve original full workflow policy"
        ]
    except EvidenceError as exc:
        report["reason_codes"].append(exc.code)
        report["reasons"].append(str(exc))
    except (KeyError, TypeError, ValueError, OSError) as exc:
        report["reason_codes"].append("insufficient-evidence")
        report["reasons"].append(
            f"Malformed or unavailable classification evidence ({type(exc).__name__})"
        )
    if report["mode"] == "broad-required":
        report["entity_sources"] = None
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--workflow-kind", choices=sorted(WORKFLOW_KINDS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    arguments = parser.parse_args()
    try:
        event = json.loads(arguments.event_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        event = {}
    report = classify(arguments.repo, event, arguments.event_name, arguments.workflow_kind)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["mode"] == "broad-required":
        print("Broad qualification required: " + "; ".join(report["reason_codes"]))
        return 1
    if arguments.github_output is not None:
        outputs = {
            "mode": report["mode"],
            "full_qualification": report["full_qualification"],
            **report["selection"],
        }
        with arguments.github_output.open("a", encoding="utf-8", newline="\n") as handle:
            for key, value in outputs.items():
                encoded = json.dumps(value) if not isinstance(value, str) else value
                handle.write(f"{key}={encoded}\n")
    print(report["mode"] + ": selection only; checks have not run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
