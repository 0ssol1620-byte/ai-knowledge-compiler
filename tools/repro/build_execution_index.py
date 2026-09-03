#!/usr/bin/env python3
"""Build an honest per-experiment reproduction/execution index.

Current reproduction templates are not silently promoted to historical commands.
Exact historical invocations are recovered only when repository artifacts record
an invocation-like field. Commands executed in the current continuation are
listed explicitly as current-session records.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "repro" / "EXPERIMENT_MANIFEST.json"
SESSION_LOG = ROOT / "docs" / "repro" / "SESSION_EXECUTION_LOG_2026-08-19.md"
EXCLUSIONS = ROOT / "docs" / "repro" / "EXCLUSION_RULES_2026-08-19.md"
OUTPUT = ROOT / "docs" / "repro" / "EXECUTION_INDEX_2026-08-19.json"

CURRENT_SESSION_EXACT: dict[str, list[str]] = {
    # 2026-08-19 continuation. These five take no arguments, so the invocation is
    # fully determined and is recorded rather than left as a template. Where a run
    # was superseded, the superseding invocation is the one listed: the earlier
    # receipts are retained but the command that produced the authoritative
    # receipt is what a reproducer needs.
    "H1-I-GATE-ORDERING-01": [
        "python research/experiments/H1-I-GATE-ORDERING-01/scripts/"
        "permute_gate_order.py",
    ],
    "H1-J-GOVERNANCE-FILTER-ABLATION-01": [
        "python research/experiments/H1-J-GOVERNANCE-FILTER-ABLATION-01/scripts/"
        "ablate_governance_filters.py",
    ],
    "H1-K-LEGACY-INVARIANT-EXTRACTION-01": [
        "python research/experiments/H1-K-LEGACY-INVARIANT-EXTRACTION-01/scripts/"
        "probe_legacy_invariants.py",
        "python research/experiments/H1-K-LEGACY-INVARIANT-EXTRACTION-01/scripts/"
        "audit_candidates_semanticity.py",
        "python research/experiments/H1-K-LEGACY-INVARIANT-EXTRACTION-01/scripts/"
        "audit_pruning_ceiling_lemma.py",
    ],
    "H1-L-CERTIFIED-SPARSE-MATCHER-01": [
        "python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/"
        "run_exactness.py",
        "python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/"
        "run_h1e_topologies.py",
        "python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/"
        "run_future_path.py",
        "python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/"
        "run_full_contract.py",
    ],
    "H1-W6-SAME-INTELLIGENCE-01": [
        "python research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/"
        "recovery_fixture.py",
    ],
    "H1-E2-TIE-PATH-DEPENDENCE-01": [
        ".venv\\Scripts\\python.exe research\\experiments\\"
        "H1-E2-TIE-PATH-DEPENDENCE-01\\scripts\\tie_path_dependence.py freeze "
        "--output research\\experiments\\H1-E2-TIE-PATH-DEPENDENCE-01\\receipts\\"
        "seal-amend1-2026-08-19.json",
        ".venv\\Scripts\\python.exe research\\experiments\\"
        "H1-E2-TIE-PATH-DEPENDENCE-01\\scripts\\tie_path_dependence.py run "
        "--seal research\\experiments\\H1-E2-TIE-PATH-DEPENDENCE-01\\receipts\\"
        "seal-amend1-2026-08-19.json --output research\\experiments\\"
        "H1-E2-TIE-PATH-DEPENDENCE-01\\receipts\\path-dependence-amend1-2026-08-19.json",
    ],
    "H1-F-REAL-CORPUS-EQUIV-01": [
        ".venv\\Scripts\\python.exe research\\experiments\\H1-F-REAL-CORPUS-EQUIV-01\\"
        "scripts\\run_real_corpus_equivalence.py freeze --output research\\experiments\\"
        "H1-F-REAL-CORPUS-EQUIV-01\\receipts\\seal-2026-08-19.json",
        ".venv\\Scripts\\python.exe research\\experiments\\H1-F-REAL-CORPUS-EQUIV-01\\"
        "scripts\\run_real_corpus_equivalence.py run --seal research\\experiments\\"
        "H1-F-REAL-CORPUS-EQUIV-01\\receipts\\seal-2026-08-19.json --output "
        "research\\experiments\\H1-F-REAL-CORPUS-EQUIV-01\\receipts\\"
        "all-stored-real-corpus-2026-08-19.json",
    ],
    "H1-A12-01": [
        ".venv\\Scripts\\pytest.exe -q research\\experiments\\H1-A12-01\\tests\\"
        "test_analyze_policy_divergence.py benchmark\\tests\\v6\\test_identity_and_registry.py",
        ".venv\\Scripts\\python.exe research\\experiments\\H1-A12-01\\scripts\\"
        "audit_runtime_readiness.py",
    ],
}

INVOCATION_KEYS = {
    "argv",
    "command",
    "command_line",
    "commandline",
    "cmd",
    "invocation",
    "invoked_as",
}


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _is_invocation(child: Any) -> bool:
    """Is this value actually a recorded command, rather than an empty field?

    Two shapes count and nothing else: a non-blank string, or a non-empty list
    of strings (an argv). An empty string or an empty list is a field that was
    declared and never filled, and recording it as a recovered invocation would
    manufacture provenance that does not exist.
    """
    if isinstance(child, str):
        return bool(child.strip())
    return bool(child) and isinstance(child, list) and all(isinstance(x, str) for x in child)


def extract_invocations(value: Any, pointer: str = "") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{key}"
            if key.casefold() in INVOCATION_KEYS and _is_invocation(child):
                found.append({"pointer": child_pointer, "value": child})
            found.extend(extract_invocations(child, child_pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(extract_invocations(child, f"{pointer}/{index}"))
    return found


def historical_invocations(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    for receipt in receipts:
        path = ROOT / receipt["path"]
        if path.suffix.lower() != ".json":
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        for item in extract_invocations(document):
            recovered.append(
                {
                    "receipt_path": receipt["path"],
                    "receipt_sha256": receipt["sha256"],
                    **item,
                }
            )
    return recovered


def file_hash_if_present(name: str) -> dict[str, Any]:
    path = ROOT / name
    if not path.exists():
        return {"path": name, "present": False}
    return {"path": name, "present": True, "sha256": sha256_file(path)}


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    experiments = []
    historical_recovered_count = 0
    for experiment in manifest["experiments"]:
        recovered = historical_invocations(experiment["receipts"])
        historical_recovered_count += int(bool(recovered))
        templates = experiment.get("commands", [])
        exact_current = CURRENT_SESSION_EXACT.get(experiment["experiment"], [])
        experiments.append(
            {
                "experiment": experiment["experiment"],
                "protocols": experiment["protocols"],
                "scripts": experiment["scripts"],
                "receipts": [
                    {
                        key: receipt[key]
                        for key in (
                            "path",
                            "sha256",
                            "schema",
                            "generated_at",
                            "self_hash_recomputes",
                        )
                        if key in receipt
                    }
                    for receipt in experiment["receipts"]
                ],
                "current_reproduction": {
                    "status": (
                        "EXACT_CURRENT_SESSION_COMMANDS_RECORDED"
                        if exact_current
                        else ("TEMPLATE_ONLY" if templates else "NO_RUNNER_DISCOVERED")
                    ),
                    "exact_current_session_commands": exact_current,
                    "templates": templates,
                    "cwd": str(ROOT),
                    "warning": (
                        "Templates are conveniences derived from current scripts and are not "
                        "evidence of the historical invocation."
                    ),
                },
                "historical_exact_invocation": {
                    "status": (
                        "RECOVERED_FROM_REPOSITORY_ARTIFACT"
                        if recovered
                        else "NOT_RECOVERABLE_FROM_REPOSITORY"
                    ),
                    "recovered_records": recovered,
                    "warning": (
                        "No command is invented from argparse/help text when the historical "
                        "invocation is absent."
                    ),
                },
            }
        )

    exact_current_count = sum(
        bool(CURRENT_SESSION_EXACT.get(item["experiment"])) for item in experiments
    )
    body: dict[str, Any] = {
        "schema": "tavonel.execution-index.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Per-experiment separation of current reproducibility from historical exact "
            "invocation recovery; closes X8 without fabricating missing commands."
        ),
        "manifest_path": rel(MANIFEST),
        "manifest_file_sha256": sha256_file(MANIFEST),
        "manifest_self_sha256": manifest.get("manifest_sha256"),
        "exclusion_rules_path": rel(EXCLUSIONS),
        "exclusion_rules_sha256": sha256_file(EXCLUSIONS),
        "session_execution_log_path": rel(SESSION_LOG),
        "session_execution_log_sha256": sha256_file(SESSION_LOG),
        "environment_at_index_build": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "git_commit": git_commit(),
            "warning": (
                "This is the environment at index-build time. It is not asserted to be the "
                "historical environment of older receipts."
            ),
            "dependency_files": [
                file_hash_if_present("pyproject.toml"),
                file_hash_if_present("uv.lock"),
            ],
            "manifest_environment": manifest.get("environment"),
        },
        "summary": {
            "experiment_count": len(experiments),
            "experiments_with_repository_recovered_"
            "historical_invocation": historical_recovered_count,
            "experiments_without_recoverable_historical_invocation": (
                len(experiments) - historical_recovered_count
            ),
            "experiments_with_exact_current_session_commands": exact_current_count,
            "historical_invocation_completeness": "PARTIAL",
            "interpretation": (
                "A current reproduction route exists for many experiments, but the repository "
                "does not preserve every older exact command. Missing history remains explicit."
            ),
        },
        "experiments": experiments,
    }
    body["index_sha256"] = canonical_sha256(body)
    OUTPUT.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"experiments: {len(experiments)}")
    print(f"historical exact invocation recovered: {historical_recovered_count}")
    print(f"historical invocation missing: {len(experiments) - historical_recovered_count}")
    print(f"exact current-session command sets: {exact_current_count}")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
