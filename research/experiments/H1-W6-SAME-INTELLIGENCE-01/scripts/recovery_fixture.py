#!/usr/bin/env python3
"""W6 §2B -- tiny fixture proving the recovery semantics the static audit inferred.

The audit at `receipts/acquisition-resume-audit-2026-08-19.json` read the
acquisition code and concluded the writes are non-atomic, unconditional and
uncheckpointed. That is a reading. This file *demonstrates* it on the same write
pattern, so the recovery decision rests on a measurement rather than on my
interpretation of someone's source.

No network. No Wikipedia call. The fetcher is a local stub, because what is under
test is the write/kill/restart behaviour, not the transport.

The pattern under test is transcribed from `acquire_w6_v3.py:351-386`:

    directory.mkdir(parents=True, exist_ok=True)
    before_path.write_text(before_content)
    after_path.write_text(after_content)
    ... metadata.json written last ...

`acquire_w6_v3.py` is NOT imported or executed: it self-checks its own sha256
against the frozen title manifest and would refuse to run, and running it would
require the network. Transcribing the three write calls is the point -- if the
transcription were wrong the fixture would prove nothing, so it is quoted above
and the line range is cited.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Killed(Exception):
    """Stands in for the process dying between two writes."""


def write_pair(directory: Path, before: str, after: str, meta: dict,
               *, kill_after: str | None = None) -> None:
    """The transcribed write pattern, with an injectable kill point."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "before.wikitext").write_text(before, encoding="utf-8")
    if kill_after == "before":
        raise Killed("died after before.wikitext")
    (directory / "after.wikitext").write_text(after, encoding="utf-8")
    if kill_after == "after":
        raise Killed("died after after.wikitext, before metadata.json")
    (directory / "metadata.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def state_of(directory: Path) -> dict[str, Any]:
    names = sorted(p.name for p in directory.iterdir()) if directory.exists() else []
    return {
        "files": names,
        "complete": names == ["after.wikitext", "before.wikitext", "metadata.json"],
        "before_sha256": _sha(directory / "before.wikitext"),
        "after_sha256": _sha(directory / "after.wikitext"),
    }


def _sha(p: Path) -> str | None:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def test_overwrite_of_existing_pair(root: Path) -> dict[str, Any]:
    """Does a re-run overwrite an already-acquired pair? The audit says yes."""
    d = root / "overwrite" / "00000-abc"
    write_pair(d, "ORIGINAL before", "ORIGINAL after", {"v": 1})
    first = state_of(d)
    write_pair(d, "REPLACEMENT before", "REPLACEMENT after", {"v": 2})
    second = state_of(d)
    return {
        "question": "does a second run overwrite an existing complete pair?",
        "audit_predicted": "YES",
        "observed_overwrite": first["before_sha256"] != second["before_sha256"],
        "before_first": first["before_sha256"],
        "before_second": second["before_sha256"],
        "confirms_audit": first["before_sha256"] != second["before_sha256"],
    }


def test_partial_pair_after_kill(root: Path) -> dict[str, Any]:
    """Killed between the two writes: what survives?"""
    rows = []
    for kill_point in ("before", "after"):
        d = root / f"kill_{kill_point}" / "00000-abc"
        try:
            write_pair(d, "B", "A", {"v": 1}, kill_after=kill_point)
        except Killed as exc:
            rows.append({"kill_after": kill_point, "error": str(exc),
                         **state_of(d)})
    return {
        "question": "what is on disk after a kill mid-pair?",
        "audit_predicted": "an incomplete directory with no metadata.json",
        "rows": rows,
        "all_incomplete": all(not r["complete"] for r in rows),
        "metadata_absent_in_all": all(
            "metadata.json" not in r["files"] for r in rows
        ),
    }


def test_metadata_as_completion_marker(root: Path) -> dict[str, Any]:
    """Is metadata.json a sound completion marker for a future resume rule?"""
    complete = root / "marker" / "complete"
    write_pair(complete, "B", "A", {"v": 1})
    partial = root / "marker" / "partial"
    with contextlib.suppress(Killed):
        write_pair(partial, "B", "A", {"v": 1}, kill_after="before")
    c, p = state_of(complete), state_of(partial)
    return {
        "question": "does metadata.json distinguish a complete pair from a partial one?",
        "complete_dir": c,
        "partial_dir": p,
        "marker_is_sound": c["complete"] and not p["complete"],
        "caveat": (
            "Sound as a marker only because metadata.json is written last. It is "
            "NOT written atomically either, so a kill during the metadata write "
            "itself would leave a truncated marker. A resume rule would have to "
            "parse it, not merely stat it."
        ),
    }


def test_truncation_is_invisible(root: Path) -> dict[str, Any]:
    """A short write leaves a valid-looking file. Nothing detects it."""
    d = root / "truncate" / "00000-abc"
    write_pair(d, "FULL CONTENT " * 100, "FULL CONTENT " * 100, {"v": 1})
    good = _sha(d / "before.wikitext")
    (d / "before.wikitext").write_text("FULL CONT", encoding="utf-8")
    return {
        "question": "is a truncated wikitext file distinguishable without a stored hash?",
        "full_sha256": good,
        "truncated_sha256": _sha(d / "before.wikitext"),
        "metadata_still_present": (d / "metadata.json").exists(),
        "detectable_only_via_metadata_hash": True,
        "note": (
            "metadata.json records before_sha256/after_sha256, so a resume rule "
            "CAN detect truncation -- but only by re-hashing and comparing, which "
            "no existing code path does."
        ),
    }


def test_fresh_dir_isolation(root: Path) -> dict[str, Any]:
    """Option B's safety property: does writing into v6 touch v5 at all?"""
    v5 = root / "corpus-v5" / "00000-abc"
    write_pair(v5, "V5 before", "V5 after", {"v": 5})
    before_state = state_of(v5)
    v6 = root / "corpus-v6" / "00000-abc"
    write_pair(v6, "V6 before", "V6 after", {"v": 6})
    after_state = state_of(v5)
    return {
        "question": "does acquiring into a fresh corpus dir modify the old one?",
        "v5_unchanged": before_state == after_state,
        "v5_before_sha256": after_state["before_sha256"],
        "supports_option_b": before_state == after_state,
    }


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = Path(__file__).resolve().parents[1]
    out = exp / "receipts" / "recovery-fixture-2026-08-19.json"
    tmp = Path(tempfile.mkdtemp(prefix="w6-recovery-fixture-"))
    try:
        results = {
            "overwrite": test_overwrite_of_existing_pair(tmp),
            "partial_after_kill": test_partial_pair_after_kill(tmp),
            "completion_marker": test_metadata_as_completion_marker(tmp),
            "truncation": test_truncation_is_invisible(tmp),
            "fresh_dir_isolation": test_fresh_dir_isolation(tmp),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    confirms = {
        "overwrite_confirmed": results["overwrite"]["confirms_audit"],
        "partial_state_confirmed": results["partial_after_kill"]["all_incomplete"],
        "no_marker_on_partial": results["partial_after_kill"]["metadata_absent_in_all"],
        "marker_sound_when_present": results["completion_marker"]["marker_is_sound"],
        "fresh_dir_isolated": results["fresh_dir_isolation"]["supports_option_b"],
    }
    all_confirmed = all(confirms.values())

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-recovery-fixture.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Demonstrate, rather than infer, the recovery semantics of the "
            "acquisition write pattern, so the corpus-v6 decision rests on a "
            "measurement."
        ),
        "method": (
            "The three write calls at acquire_w6_v3.py:351-386 are transcribed "
            "into a local fixture with an injectable kill point. The real script "
            "is neither imported nor executed: it self-checks its own sha256 "
            "against the frozen manifest and would refuse to run, and it requires "
            "the network."
        ),
        "transcription_risk": (
            "If the transcription is wrong the fixture proves nothing. The "
            "pattern is quoted in the module docstring with its line range so the "
            "transcription is checkable by eye."
        ),
        "results": results,
        "audit_predictions_confirmed": confirms,
        "all_audit_predictions_confirmed": all_confirmed,
        "recovery_decision": "B_FRESH_CORPUS_V6",
        "decision_now_rests_on": (
            "measurement: a re-run overwrites an existing complete pair, a kill "
            "leaves an incomplete directory, and writing into a fresh corpus "
            "directory provably does not touch the old one"
        ),
        "still_required_before_network_run": [
            "a frozen recovery protocol naming corpus-v6, the same 6,987-title "
            "manifest and the same cutoffs",
            "confirmation that corpus-v5 is retained untouched as failed-run evidence",
        ],
        "corpus_v5_modified": False,
        "network_access": False,
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for k, v in confirms.items():
        print(f"  {k:<32} {v}")
    print(f"all audit predictions confirmed: {all_confirmed}")
    print(f"wrote {out}")
    return 0 if all_confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
