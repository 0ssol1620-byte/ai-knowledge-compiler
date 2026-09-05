"""The real .dockerignore excludes every forbidden directory, simulated with
a fake tree and the local fnmatch-based matcher (no new dependency, per the
lane brief)."""

from __future__ import annotations

from pathlib import Path

import pytest
from ignore_matcher import is_ignored, load_patterns, parse_pattern

NAMESPACE_ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE_TEXT = (NAMESPACE_ROOT / ".dockerignore").read_text(encoding="utf-8")
PATTERNS = load_patterns(DOCKERIGNORE_TEXT)

# A fake tree standing in for a real checkout: (relpath, must_be_ignored).
FAKE_TREE = (
    ("ARENA_CONTRACT.md", False),
    ("README.md", False),
    ("conftest.py", False),
    ("arena/__init__.py", False),
    ("arena/constants.py", False),
    ("arena/worker/adapter_api.py", False),
    ("runtimes/paddleocr_vl_1_6/Dockerfile", False),
    ("runtimes/paddleocr_vl_1_6/adapter.py", False),
    ("runtimes/paddleocr_vl_1_6/runtime.json", False),
    ("prompt_registry/sha256.json", False),
    ("build/build_plan.json", False),
    ("build/BUILD_PLAN.md", False),
    # Forbidden: benchmark/campaign data that must never enter an image layer.
    ("tests/build/test_dockerignore.py", True),
    ("tests/core/test_receipts.py", True),
    ("runs/paddleocr_vl_1_6/receipts/x.json", True),
    ("runs/paddleocr_vl_1_6/raw/x.raw.txt", True),
    ("frozen_outputs/paddleocr_vl_1_6/manifest.jsonl", True),
    ("frozen_outputs/paddleocr_vl_1_6/FROZEN.json", True),
    ("queue/campaign.sqlite", True),
    ("queue/campaign.sqlite-wal", True),
    ("scores/paddleocr_vl_1_6/omnidoc/summary.json", True),
    ("receipts/events.jsonl", True),
    ("receipts/provider_receipts/catalog-1.json", True),
    ("cost/pod_ledger.jsonl", True),
    ("reports/executive_summary_ko.md", True),
    ("evidence/FINAL_EVIDENCE_MANIFEST.json", True),
    ("failures/errors.jsonl", True),
    ("tavonel/signals/paddleocr_vl_1_6/x.json", True),
    ("tavonel/route_decisions/A/FROZEN.json", True),
    (".private/scratch.txt", True),
    ("source_manifest.jsonl", True),
    ("campaign_manifest.json", True),
    ("canary_selection.json", True),
    ("model_registry.json", True),
    ("evaluator_registry.json", True),
    ("__pycache__/module.cpython-312.pyc", True),
    ("arena/__pycache__/constants.cpython-312.pyc", True),
    (".git/HEAD", True),
    (".git/objects/pack/pack-x.pack", True),
    (".mypy_cache/3.12/arena/constants.data.json", True),
    (".ruff_cache/0.12/cache.bin", True),
    (".pytest_cache/v/cache/lastfailed", True),
    (".venv/Scripts/python.exe", True),
)


@pytest.mark.parametrize("relpath,expected_ignored", FAKE_TREE)
def test_fake_tree_matches_expected_ignore_state(relpath: str, expected_ignored: bool) -> None:
    assert is_ignored(relpath, PATTERNS) is expected_ignored, (
        f"{relpath}: expected ignored={expected_ignored}"
    )


def test_dockerignore_has_no_negation_patterns() -> None:
    """This matcher does not implement '!' negation; the real .dockerignore
    must not need it, or the simulation above would be unsound."""
    for line in DOCKERIGNORE_TEXT.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("!"), "negation patterns are not simulated"


def test_every_forbidden_directory_named_in_the_lane_brief_is_covered() -> None:
    required_dirs = (
        "tests/",
        "runs/",
        "frozen_outputs/",
        "queue/",
        "scores/",
        "receipts/",
        "cost/",
        "reports/",
        "evidence/",
        ".private/",
    )
    for directory in required_dirs:
        probe = f"{directory}some/nested/file.txt"
        assert is_ignored(probe, PATTERNS), f"{directory} must be excluded"


def test_generated_jsonl_and_sqlite_are_excluded_anywhere() -> None:
    assert is_ignored("anything/anywhere/x.jsonl", PATTERNS)
    assert is_ignored("x.jsonl", PATTERNS)
    assert is_ignored("anything/anywhere/x.sqlite", PATTERNS)
    assert is_ignored("x.sqlite-wal", PATTERNS)
    assert is_ignored("x.sqlite-shm", PATTERNS)


def test_parse_pattern_skips_comments_and_blank_lines() -> None:
    assert parse_pattern("") is None
    assert parse_pattern("   ") is None
    assert parse_pattern("# a comment") is None
    assert parse_pattern("runs/") is not None
