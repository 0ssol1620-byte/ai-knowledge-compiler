"""The demo Personal workspace: real markdown and code a spine can compile.

Every file here earns its place in the mission brief: a launch date that
answers questions, one authority conflict the resolver settles (an informal
note losing to an owned plan), one superseded fact, one future effective
date, and one dependency chain (spec -> plan -> governance policy) long
enough to show transitive invalidation.

The prose is engineered for the identity resolver's §N15.4 bands, on purpose:
a date swap ("October 15" -> "November 3") must keep enough shared tokens to
stay a MATCHED continuation, while a full rewrite of a line must fall into
the review band so fail-closed quarantine is reachable from realistic edits.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["DEMO_FILES", "write_demo_workspace"]

DEMO_FILES: dict[str, str] = {
    # ------------------------------------------------------------------
    "projects/launch-plan.md": """\
# Project Phoenix - Launch Plan

## Launch date

The current confirmed launch date for Project Phoenix is October 15, 2026.

## Dependencies

- Depends on: policies/launch-governance.md - readiness gate compliance.

## Scope

The plan covers the go-to-market workstream for the Phoenix platform.
""",
    # ------------------------------------------------------------------
    "policies/launch-governance.md": """\
# Launch Governance

## Readiness gate

The launch readiness gate requires sign-off from legal and finance before any public announcement.
""",
    # ------------------------------------------------------------------
    "specs/launch-spec.md": """\
# Launch Readiness Spec

## Dependencies

- Depends on: projects/launch-plan.md - dates and scope.

## Go or no-go criteria

Go criterion: the marketing site must be live one week before day one.
""",
    # ------------------------------------------------------------------
    "meetings/2026-09-30-kickoff.md": """\
Date: 2026-09-30

# Kickoff meeting, September 30

## Decisions

Tentative launch date slides to November 3 pending board approval.
""",
    # ------------------------------------------------------------------
    "policies/warranty-policy.md": """\
# Warranty Policy

## Coverage

Devices ship with a two-year limited warranty from first activation.
""",
    # ------------------------------------------------------------------
    "notes/pricing-note.md": """\
# Pricing notes

## Warranty

- The three-year extended warranty commitment is superseded by policies/warranty-policy.md.
""",
    # ------------------------------------------------------------------
    "policies/support-policy.md": """\
# Support Policy

## Support hours

Current support coverage is Monday through Friday from nine to five until December 31, 2026.

- Effective January 1, 2027: support coverage extends to weekends.
""",
    # ------------------------------------------------------------------
    "notes/roadmap-hints.md": """\
# Roadmap hints

## Later

The companion mobile app is planned for next quarter.
""",
    # ------------------------------------------------------------------
    "tools/freeze_check.py": '''\
"""Freeze checklist helpers for release documentation."""

FREEZE_OFFSET_DAYS = 3


def main() -> None:
    # The documentation freeze starts three days before day one.
    print("freeze window computed")
''',
}

#: Lines used by the acceptance scenarios when they mutate the workspace.
LAUNCH_PLAN = "projects/launch-plan.md"
GOVERNANCE_POLICY = "policies/launch-governance.md"
ROADMAP_HINTS = "notes/roadmap-hints.md"
LAUNCH_DELAY_MEMO = "projects/launch-delay-memo.md"

MEMO_CONTENT = """\
# Launch delay memo

## Launch date

The current confirmed launch date for Project Phoenix is November 3, 2026.
"""


def write_demo_workspace(target: Path | str) -> list[Path]:
    """Write the demo corpus under ``target``; returns the files written."""
    root = Path(target)
    written: list[Path] = []
    for rel_path, content in DEMO_FILES.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written
