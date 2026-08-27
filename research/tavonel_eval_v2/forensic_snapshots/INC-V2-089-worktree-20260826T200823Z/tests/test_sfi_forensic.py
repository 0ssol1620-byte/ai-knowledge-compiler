"""forensic_four_divergences_v2 — pure logic, no network.

Exercises the comparison function directly (`compare_case`), the NOT_EXERCISED
degradation path, and the shape of the immutable receipt a real run produces.
Nothing here fetches bytes: `evaluate` and `main` do the fetching and are left
to a manual run, exactly as the sibling forensic tools are.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools",):
    sys.path.insert(0, str(NS / _sub))

import forensic_four_divergences_v2 as tool  # noqa: E402

# ---------------------------------------------------------------------------
# compare_case — the pure comparison


def test_named_artifact_is_a_catch():
    result = tool.compare_case(
        confirmed_stale_artifacts=["section:u:abc"],
        typed_invalidated=["section:u:abc", "document-index:doc"],
        moved_facts=[
            {
                "kind": "CONTENT_TEXT",
                "channel": "SEMANTIC",
                "dependency_keys": ["section:u:abc", "document-index:doc"],
            }
        ],
    )
    assert result["conclusion"] == tool.WOULD_HAVE_NAMED
    assert result["per_artifact"]["section:u:abc"]["named_by_typed_delta"] is True
    assert result["per_artifact"]["section:u:abc"]["via_fact_kind_and_channel"] == [
        ["CONTENT_TEXT", "SEMANTIC"]
    ]


def test_unnamed_artifact_is_a_miss():
    """The exact shape of the four confirmed escapes: moved but not invalidated."""
    result = tool.compare_case(
        confirmed_stale_artifacts=["topic-bucket:doc:0"],
        typed_invalidated=["section:u:abc"],  # something else moved, not this
        moved_facts=[
            {"kind": "CONTENT_TEXT", "channel": "SEMANTIC", "dependency_keys": ["section:u:abc"]}
        ],
    )
    assert result["conclusion"] == tool.WOULD_NOT_HAVE_NAMED
    assert result["per_artifact"]["topic-bucket:doc:0"]["named_by_typed_delta"] is False
    assert result["per_artifact"]["topic-bucket:doc:0"]["via_fact_kind_and_channel"] == []


def test_partial_naming_of_several_stale_artifacts_is_still_a_miss():
    """Every confirmed-stale artifact must be named, or the case did not catch it.

    A conclusion that called this a catch because *one* of two stale artifacts
    was named would be exactly the kind of averaging-away-the-weakness this
    tool's own `what_this_is_not` forbids at the case level too.
    """
    result = tool.compare_case(
        confirmed_stale_artifacts=["section:u:one", "section:u:two"],
        typed_invalidated=["section:u:one"],
        moved_facts=[
            {"kind": "CONTENT_TEXT", "channel": "SEMANTIC", "dependency_keys": ["section:u:one"]}
        ],
    )
    assert result["conclusion"] == tool.WOULD_NOT_HAVE_NAMED


def test_no_confirmed_stale_artifacts_is_not_a_catch():
    """An empty input must not default to a pass. `all([])` is True; guard it."""
    result = tool.compare_case(
        confirmed_stale_artifacts=[],
        typed_invalidated=["section:u:abc"],
        moved_facts=[],
    )
    assert result["conclusion"] == tool.WOULD_NOT_HAVE_NAMED


def test_via_fact_kind_and_channel_only_reports_facts_that_reach_the_artifact():
    """A moved fact that does not list the artifact in its dependency_keys is
    not evidence for that artifact, even though something moved somewhere."""
    result = tool.compare_case(
        confirmed_stale_artifacts=["section:u:abc"],
        typed_invalidated=["section:u:abc"],
        moved_facts=[
            {"kind": "CONTENT_TEXT", "channel": "SEMANTIC", "dependency_keys": ["section:u:abc"]},
            {"kind": "LANGUAGE", "channel": "DESCRIPTIVE", "dependency_keys": ["section:u:other"]},
        ],
    )
    assert result["per_artifact"]["section:u:abc"]["via_fact_kind_and_channel"] == [
        ["CONTENT_TEXT", "SEMANTIC"]
    ]


# ---------------------------------------------------------------------------
# NOT_EXERCISED — must never be indistinguishable from a pass


def test_not_exercised_conclusion_is_never_a_pass():
    """The literal guarantee: NOT_EXERCISED is a distinct value from WOULD_HAVE_NAMED."""
    assert tool.NOT_EXERCISED != tool.WOULD_HAVE_NAMED
    assert tool.NOT_EXERCISED not in {tool.WOULD_HAVE_NAMED}


def test_evaluate_reports_not_exercised_when_core_extractor_missing():
    """`evaluate` must degrade to NOT_EXERCISED, not attempt extraction, when the
    core lane failed to import — before it ever tries to fetch anything."""
    case = {
        "lineage_id": "wikipedia:en:Fixture",
        "family": "encyclopedia_wikipedia",
        "after_version": "2",
        "before_version": "1",
        "confirmed_stale_artifacts": ["section:u:fixture"],
    }
    lineage = {"lineage_id": "wikipedia:en:Fixture", "family": "encyclopedia_wikipedia"}
    lane_report = {
        "core_extractor": {
            "imported": False,
            "reason": "ModuleNotFoundError: no module named core_extractor",
        },
        "fingerprint": {
            "imported": False,
            "reason": "ModuleNotFoundError: no module named fingerprint",
        },
    }
    result = tool.evaluate(
        case, lineage, ir_module=None, fingerprint_module=None, lane_report=lane_report
    )
    assert result["conclusion"] == tool.NOT_EXERCISED
    assert "core_extractor" in result["why"]
    assert "fingerprint" in result["why"]


def test_evaluate_not_exercised_path_never_touches_the_network():
    """No `run_vbc2_acquire` import, no HTTP: the missing-module check must be
    the very first thing `evaluate` does for this to hold at all."""
    case = {
        "lineage_id": "git:pnpm/pnpm.io:docs/cli/change.md",
        "family": "git_docs",
        "after_version": "after",
        "before_version": "before",
        "confirmed_stale_artifacts": ["topic-bucket:doc:0"],
    }
    lineage = {"lineage_id": "git:pnpm/pnpm.io:docs/cli/change.md", "family": "git_docs"}
    lane_report = {"core_extractor": {"imported": False, "reason": "ImportError: x"}}
    # if this reached the network path it would raise (no HttpPool installed,
    # no real lineage shape) rather than return cleanly
    result = tool.evaluate(
        case, lineage, ir_module=None, fingerprint_module=None, lane_report=lane_report
    )
    assert result["conclusion"] == tool.NOT_EXERCISED


# ---------------------------------------------------------------------------
# conclusion vocabulary cannot express a rate


def test_conclusion_vocabulary_is_closed_and_qualitative():
    """Every conclusion value is one of four fixed labels — none of them numeric,
    none of them a fraction, none of them nameable as a percentage or a count."""
    assert {
        tool.WOULD_HAVE_NAMED,
        tool.WOULD_NOT_HAVE_NAMED,
        tool.NOT_EXERCISED,
        tool.UNREPRODUCIBLE,
    } == tool.CONCLUSIONS
    for value in tool.CONCLUSIONS:
        assert isinstance(value, str)
        # no digits anywhere in the label — a rate would need one
        assert not any(character.isdigit() for character in value)
        assert "%" not in value
        assert "/" not in value


def test_compare_case_conclusion_is_always_one_of_the_closed_vocabulary():
    for confirmed, invalidated in (
        (["a"], ["a"]),
        (["a"], []),
        ([], []),
        (["a", "b"], ["a"]),
    ):
        result = tool.compare_case(confirmed, invalidated, [])
        assert result["conclusion"] in {tool.WOULD_HAVE_NAMED, tool.WOULD_NOT_HAVE_NAMED}


# ---------------------------------------------------------------------------
# a real receipt, if one exists — guarded, since a run needs the network


RECEIPTS = NS / "receipts"
_existing = (
    sorted(RECEIPTS.glob("forensic-four-divergences-v2--*.json")) if RECEIPTS.exists() else []
)
_SKIP_REASON = "no forensic-four-divergences-v2 receipt has been written yet"


@pytest.mark.skipif(not _existing, reason=_SKIP_REASON)
def test_latest_real_receipt_has_the_declared_shape():
    body = json.loads(_existing[-1].read_text(encoding="utf-8"))
    assert body["schema"] == "tavonel.v2.forensic_four_divergences_v2.v1"
    assert isinstance(body["what_this_is_not"], list)
    assert len(body["what_this_is_not"]) >= 3
    joined = " ".join(body["what_this_is_not"]).lower()
    assert "rate" in joined
    assert "rescore" in joined
    assert "held-out" in joined or "held out" in joined
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
    assert body["provenance"]["immutable"] is True
    for row in body["cases"]:
        assert row["conclusion"] in tool.CONCLUSIONS
        # a case that was not exercised must not carry a naming verdict
        if row["conclusion"] == tool.NOT_EXERCISED:
            assert "per_artifact" not in row
