#!/usr/bin/env python3
"""Generate the counsel-flag register and the unsupported-breadth ledger.

Both are views over material that already exists in `CLAIM_AMENDMENTS.yaml` and
`ELEMENT_SUPPORT_BINDINGS.yaml`. They are generated rather than written because a
hand-maintained copy of a register drifts from it, and the drift is invisible
exactly when it matters -- a counsel flag answered in one file and not the other
reads as still open in one and closed in the other.

Neither document decides anything. A counsel flag is a question this programme is
not permitted to answer, and an unsupported-breadth row is a construction the
claim's own binding says the evidence does not reach.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
AMENDMENTS = ROOT / "docs" / "ip" / "CLAIM_AMENDMENTS.yaml"
BINDINGS = ROOT / "docs" / "ip" / "ELEMENT_SUPPORT_BINDINGS.yaml"
FLAGS_OUT = ROOT / "docs" / "ip" / "COUNSEL_FLAGS_2026-08-20.md"
BREADTH_OUT = ROOT / "docs" / "ip" / "UNSUPPORTED_BREADTH_LEDGER_2026-08-20.md"
RECEIPT = ROOT / "docs" / "ip" / "receipts" / "counsel-and-breadth-2026-08-20.json"

NONE_MARKERS = ("none identified", "none.")


def load(path: Path, key: str) -> list[dict[str, Any]]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(key) or []


def one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def build_flags(
    amendments: list[dict[str, Any]], bindings: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for a in amendments:
        if a.get("counsel_flag"):
            rows.append({
                "source": "amendment",
                "id": a.get("id"),
                "claim": a.get("claim"),
                "element": a.get("element"),
                "context": one_line(a.get("what")),
                "question": one_line(a.get("counsel_question")) or "(no question recorded)",
            })
    for b in bindings:
        if b.get("counsel_flag"):
            rows.append({
                "source": "element binding",
                "id": f"{b.get('claim')}/{b.get('element')}",
                "claim": b.get("claim"),
                "element": b.get("element"),
                "context": one_line(b.get("limitation"))[:400],
                "question": one_line(b.get("counsel_question")) or "(no question recorded)",
            })

    unanswered = [r for r in rows if r["question"].startswith("(no question")]
    lines = [
        "# Counsel flags — open questions this programme may not answer",
        "",
        "**Generated** by `tools/ip/build_counsel_and_breadth.py` from",
        "`CLAIM_AMENDMENTS.yaml` and `ELEMENT_SUPPORT_BINDINGS.yaml`. Do not edit: an",
        "answer written here and not in the register would be invisible to every audit",
        "that reads the register.",
        "",
        "A counsel flag is not a defect and not unfinished work. It marks a place where",
        "the technical facts are settled and the remaining choice is prosecution",
        "strategy — restore a limitation, prosecute the broader claim, sequence claims",
        "differently, file now or hold for a continuation. Those are counsel's calls and",
        "the founder's, and this programme records them rather than making them.",
        "",
        f"**{len(rows)} flags open.** None is answered here.",
        "",
        "| # | source | id | claim | question |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, start=1):
        lines.append(f"| {i} | {r['source']} | `{r['id']}` | {r['claim']} | {r['question']} |")
    lines += ["", "## Context for each flag", ""]
    for i, r in enumerate(rows, start=1):
        head = f"### {i}. `{r['id']}` — claim {r['claim']}"
        if r.get("element") is not None:
            head += f", element {r['element']}"
        lines += [
            head,
            "",
            f"**What happened.** {r['context']}",
            "",
            f"**What counsel is asked.** {r['question']}",
            "",
        ]
    if unanswered:
        lines += [
            "## Flags carrying no question",
            "",
            "A flag without a question cannot be answered and is a register defect rather",
            "than a decision point. These are listed so they are fixed rather than skipped:",
            "",
        ]
        lines += [f"- `{r['id']}`" for r in unanswered]
        lines.append("")
    return "\n".join(lines), rows


def build_breadth(bindings: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for b in bindings:
        text = one_line(b.get("unsupported_breadth"))
        if not text or text.lower().startswith(NONE_MARKERS):
            continue
        rows.append({
            "claim": b.get("claim"),
            "element": b.get("element"),
            "support": b.get("support"),
            "evidence_class": b.get("evidence_class"),
            "breadth": text,
        })

    lines = [
        "# Unsupported-breadth ledger",
        "",
        "**Generated** by `tools/ip/build_counsel_and_breadth.py` from",
        "`ELEMENT_SUPPORT_BINDINGS.yaml`. Do not edit.",
        "",
        "Each row is a construction a claim limitation **reads onto** that its evidence",
        "does not reach. This is not a list of defects: a claim is allowed to be broader",
        "than one measurement, and a limitation with no recorded breadth is more often a",
        "limitation nobody examined than a limitation that is perfectly bounded.",
        "",
        "The ledger exists so a breadth is written down **before** an examiner or a",
        "reviewer finds it, and so no argument is later built on a construction this file",
        "already says the evidence does not support.",
        "",
        f"**{len(rows)} recorded breadths** across {len({r['claim'] for r in rows})} claims.",
        "",
        "| claim | element | support | evidence class | the breadth |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['claim']} | {r['element']} | {r['support']} | {r['evidence_class']} "
            f"| {r['breadth']} |"
        )
    lines += [
        "",
        "## Rows with no recorded breadth",
        "",
        "The following bindings record `none identified`. **That is a statement about the",
        "record, not a guarantee.** Each was amended on 2026-08-20 to recite what its",
        "receipt contains, and a construction nobody has thought of is not excluded by",
        "anyone having failed to think of it.",
        "",
    ]
    clean = [
        b for b in bindings
        if one_line(b.get("unsupported_breadth")).lower().startswith(NONE_MARKERS)
    ]
    lines += [f"- {b.get('claim')} element {b.get('element')}" for b in clean] or ["- (none)"]
    lines.append("")
    return "\n".join(lines), rows


def main() -> int:
    amendments = load(AMENDMENTS, "amendments")
    bindings = load(BINDINGS, "bindings")

    flags_md, flag_rows = build_flags(amendments, bindings)
    breadth_md, breadth_rows = build_breadth(bindings)
    FLAGS_OUT.write_text(flags_md, encoding="utf-8")
    BREADTH_OUT.write_text(breadth_md, encoding="utf-8")

    receipt: dict[str, Any] = {
        "schema": "tavonel.counsel-and-breadth.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": {
            "amendments": AMENDMENTS.relative_to(ROOT).as_posix(),
            "bindings": BINDINGS.relative_to(ROOT).as_posix(),
        },
        "counsel_flags": len(flag_rows),
        "counsel_flags_without_a_question": sum(
            1 for r in flag_rows if r["question"].startswith("(no question")
        ),
        "recorded_breadths": len(breadth_rows),
        "bindings_total": len(bindings),
        "note": (
            "Both documents are views. Neither answers a flag, resolves a breadth, or "
            "decides claim scope."
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(
            receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"counsel flags:      {len(flag_rows)}"
        f" ({receipt['counsel_flags_without_a_question']} carry no question)"
    )
    print(f"recorded breadths:  {len(breadth_rows)} of {len(bindings)} bindings")
    print(f"wrote {FLAGS_OUT.relative_to(ROOT).as_posix()}")
    print(f"wrote {BREADTH_OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
