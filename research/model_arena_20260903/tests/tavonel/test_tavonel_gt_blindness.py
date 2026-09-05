"""The lane must not be able to see an answer key, by source and at runtime.

Masterplan section 2.1 lists what an inference/route plane may never touch.
Two independent checks here: a scan of this package's source for the
vocabulary of ground truth, and the runtime guard that refuses to open a path
under a forbidden root.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from arena.constants import ACQUIRED_PUBLIC_CORE_ROOT, EVALUATOR_CACHE_ROOT, REPO_ROOT
from arena.tavonel import guards
from arena.tavonel.errors import GtBoundaryViolation

PACKAGE = Path(guards.__file__).parent

# The oracle is the one module allowed to consume scoring output, and it says
# so in its own name and in every record it writes.
ALLOWED_MODULES = {"oracle.py"}

# Path fragments and field names that would mean this lane had reached into the
# evaluator plane. Prose that *names* the boundary is fine; a path is not.
FORBIDDEN_TOKENS = (
    "acquired/public-core",
    "acquired\\public-core",
    "benchmark/cache",
    "benchmark\\cache",
    "omnidocbench.json",
    "olmocr-bench.jsonl",
    "parsebench_gt",
    "ground_truth",
    "groundtruth",
    "answer_key",
    "expected_text",
    "expected_output",
    "gt_paths",
    "gt.jsonl",
)


def test_no_module_outside_the_oracle_names_ground_truth() -> None:
    offenders: list[str] = []
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name in ALLOWED_MODULES:
            continue
        text = path.read_text(encoding="utf-8").casefold()
        offenders.extend(
            f"{path.name}: {token}" for token in FORBIDDEN_TOKENS if token in text
        )
    assert offenders == []


def test_the_scan_would_actually_catch_a_violation(tmp_path: Path) -> None:
    """A guard that cannot fail is not a guard: prove the scan trips."""
    planted = tmp_path / "leaky.py"
    planted.write_text('GT = "benchmark/cache/omnidoc"\n', encoding="utf-8")
    text = planted.read_text(encoding="utf-8").casefold()
    assert [token for token in FORBIDDEN_TOKENS if token in text] == ["benchmark/cache"]


@pytest.mark.parametrize(
    "forbidden",
    [
        ACQUIRED_PUBLIC_CORE_ROOT / "omnidoc" / "answers.json",
        EVALUATOR_CACHE_ROOT / "omnidoc" / "eval.py",
        REPO_ROOT / "research" / "tavonel_eval_v2" / "runtime" / "state.json",
        REPO_ROOT / "docs" / "evidence" / "FOLYNTA_CAMPAIGN_RESULTS.md",
        REPO_ROOT / "docs" / "ip" / "V4_DISCLOSURE_REGISTRY.yaml",
    ],
)
def test_runtime_guard_refuses_forbidden_roots(forbidden: Path) -> None:
    with pytest.raises(GtBoundaryViolation):
        guards.assert_readable(forbidden)


def test_runtime_guard_refuses_through_every_reader(tmp_path: Path) -> None:
    target = EVALUATOR_CACHE_ROOT / "omnidoc" / "gt.jsonl"
    for reader in (guards.read_text_guarded, guards.read_json_guarded):
        with pytest.raises(GtBoundaryViolation):
            reader(target, what="probe")
    with pytest.raises(GtBoundaryViolation):
        list(guards.iter_jsonl_guarded(target, what="probe"))


def test_runtime_guard_allows_the_campaign_tree(tmp_path: Path) -> None:
    allowed = tmp_path / "runs" / "model" / "canonical" / "case.md"
    assert guards.assert_readable(allowed) == allowed.resolve()
