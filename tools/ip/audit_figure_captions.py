#!/usr/bin/env python3
"""Check figure captions against the evidence boundary their claims carry.

P14 was a caption problem before it was a claim problem: claim text was narrowed
promptly and a figure caption kept asserting the older, stronger property for
four sessions. A caption is the part of a paper a reader trusts without checking,
which is exactly why it drifts unnoticed.

Three checks over the figure set:

1. **Withdrawn terms.** Any term registered in `WITHDRAWN_TERMS.yaml` appearing
   in a caption outside a correction context. Figure 3 is the live example: it
   draws the gate's checks in implementation order and must never be captioned as
   though the order controls the outcome.
2. **Strength words without a boundary.** A caption using `exact`, `safe`,
   `independent`, `atomic`, `general`, `validated`, `proven` or `guaranteed`
   must carry a scope qualifier in the same figure block -- the corpus, the
   condition, or an explicit negation. A bare superlative is the drift.
3. **Numbers not bound to a receipt.** A caption number that appears in no live
   receipt.

`--self-test` runs the positive control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIGURES = ROOT / "docs" / "paper" / "FIGURES_2026-08-19.md"
WITHDRAWN = ROOT / "docs" / "ip" / "WITHDRAWN_TERMS.yaml"
OUTPUT = ROOT / "docs" / "ip" / "receipts" / "figure-caption-audit-2026-08-19.json"

STRENGTH = re.compile(
    r"\b(exact|exactly|safe|independent(?:ly)?|atomic(?:ally)?|general(?:ly)?|"
    r"validated|proven|guaranteed|always|never fails|complete(?:ly)?)\b",
    re.I,
)

#: A strength word is acceptable when the same figure block states its boundary.
BOUNDARY = re.compile(
    r"(on the tested|tested corpus|constructed|controlled|does not establish|"
    r"not claimed|only|within|under the|limitation|scope|withdrawn|corpus of|"
    r"is not\b|are not\b|no claim|retrospective|single source|not a benchmark|"
    r"must never|do not caption|deliberately|measured over|denominator)",
    re.I,
)

EXEMPT = re.compile(
    r"(withdrawn|correction|corrected|must not|must never|never|do not caption|"
    r"not claimed|was wrong|no longer|forbidden|is not\b|are not\b)",
    re.I,
)

NUMBER = re.compile(r"(?<![\w./-])(\d{1,3}(?:,\d{3})+|\d{2,})(?![\w./%-])")
YEARISH = re.compile(r"^(19|20)\d{2}$")
HEXISH = re.compile(r"^[0-9a-f]{16,}$", re.I)
#: Mermaid/CSS styling lines -- colours and widths, never claims.
CSSISH = re.compile(r"(style\s+\w+|fill:|stroke:|stroke-width|linkStyle|classDef)", re.I)


def receipt_numbers() -> set[str]:
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            seen.add(str(node))
            seen.add(f"{node:,}")
        elif isinstance(node, float):
            seen.add(str(node))
        elif isinstance(node, str):
            if len(node) > 200 or HEXISH.match(node.removeprefix("sha256:")):
                return
            for raw in re.findall(r"(?<![\w.])\d[\d,]*(?![\w.])", node):
                tok = raw.replace(",", "")
                if tok.isdigit() and len(tok) <= 9:
                    seen.add(tok)
                    seen.add(f"{int(tok):,}")
        elif isinstance(node, dict):
            for k, v in node.items():
                if "sha256" in k.lower() or "hash" in k.lower():
                    continue
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for rel in ("research/experiments", "docs/ip/receipts", "docs/repro"):
        for path in (ROOT / rel).rglob("*.json"):
            # Never read this tool's own output. The first run recorded its unbound
            # numbers in its receipt; the second run then found them "bound" -- in a
            # file it had written itself -- and reported clean. A detector that
            # launders its own findings into evidence is worse than no detector.
            if path.resolve() == OUTPUT.resolve():
                continue
            try:
                walk(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
    return seen


def load_withdrawn() -> list[str]:
    if not WITHDRAWN.exists():
        return []
    doc = yaml.safe_load(WITHDRAWN.read_text(encoding="utf-8")) or {}
    return [e["term"] for e in (doc.get("withdrawn") or [])]


def blocks(text: str) -> list[tuple[str, int, str]]:
    """Split the figure set into (figure title, start line, block text)."""
    out, title, start, buf = [], None, 0, []
    for i, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            if title:
                out.append((title, start, "\n".join(buf)))
            title, start, buf = line[3:].strip(), i, []
        else:
            buf.append(line)
    if title:
        out.append((title, start, "\n".join(buf)))
    return out


def scan(text: str, withdrawn: list[str], known: set[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for title, start, body in blocks(text):
        has_boundary = bool(BOUNDARY.search(body))

        for term in withdrawn:
            for m in re.finditer(re.escape(term), body, re.I):
                line = body[: m.start()].count("\n")
                context = body.splitlines()[max(0, line - 2): line + 3]
                if EXEMPT.search(" ".join(context)):
                    continue
                findings.append(
                    {"kind": "WITHDRAWN_TERM_IN_FIGURE", "figure": title,
                     "line": start + line + 1, "term": term,
                     "why": "a term withdrawn from a claim, asserted in a figure"}
                )

        for m in STRENGTH.finditer(body):
            if has_boundary:
                continue
            line = body[: m.start()].count("\n")
            findings.append(
                {"kind": "STRENGTH_WORD_WITHOUT_BOUNDARY", "figure": title,
                 "line": start + line + 1, "term": m.group(0),
                 "why": ("a strength word with no scope qualifier anywhere in the figure "
                         "block. Name the corpus, the condition, or what is not claimed.")}
            )

        # Mermaid style directives carry hex colours (`stroke:#090`), which are not
        # claims about anything. Strip them before looking for numbers, or every
        # styled figure reports a phantom finding.
        prose = "\n".join(ln for ln in body.splitlines() if not CSSISH.search(ln))
        unbound = sorted({
            n.replace(",", "") for n in NUMBER.findall(prose)
            if not YEARISH.match(n.replace(",", ""))
            and n.replace(",", "") not in known and n not in known
        })
        if unbound:
            findings.append(
                {"kind": "FIGURE_NUMBER_NOT_IN_ANY_RECEIPT", "figure": title,
                 "line": start, "unbound_numbers": unbound,
                 "why": "a figure number that appears in no live receipt"}
            )
    return findings


def self_test(withdrawn: list[str], known: set[str]) -> dict[str, Any]:
    term = withdrawn[0] if withdrawn else "atomically"
    leak = f"## Figure X — control\n\nActivation proceeds {term} after the gate.\n"
    strong = "## Figure Y — control\n\nThe matcher is exact.\n"
    ok = ("## Figure Z — control\n\nThe matcher is exact on the tested corpus, and "
          "this does not establish general exactness.\n")
    return {
        "withdrawn_in_figure_detected": any(
            f["kind"] == "WITHDRAWN_TERM_IN_FIGURE" for f in scan(leak, withdrawn, known)
        ),
        "unbounded_strength_detected": any(
            f["kind"] == "STRENGTH_WORD_WITHOUT_BOUNDARY" for f in scan(strong, withdrawn, known)
        ),
        "bounded_strength_passes": not any(
            f["kind"] == "STRENGTH_WORD_WITHOUT_BOUNDARY" for f in scan(ok, withdrawn, known)
        ),
        "separates": (
            any(f["kind"] == "WITHDRAWN_TERM_IN_FIGURE" for f in scan(leak, withdrawn, known))
            and any(f["kind"] == "STRENGTH_WORD_WITHOUT_BOUNDARY"
                    for f in scan(strong, withdrawn, known))
            and not any(f["kind"] == "STRENGTH_WORD_WITHOUT_BOUNDARY"
                        for f in scan(ok, withdrawn, known))
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    withdrawn, known = load_withdrawn(), receipt_numbers()
    control = self_test(withdrawn, known)
    findings = []
    if not args.self_test and FIGURES.exists():
        findings = scan(FIGURES.read_text(encoding="utf-8"), withdrawn, known)

    receipt: dict[str, Any] = {
        "schema": "tavonel.figure-caption-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "closes": (
            "P14 was a caption drift before it was a claim drift. A caption is the part a "
            "reader trusts without checking."
        ),
        "figures_document": str(FIGURES.relative_to(ROOT)),
        "withdrawn_terms_checked": withdrawn,
        "positive_control": control,
        "detector_is_live": control["separates"],
        "findings": findings,
        "finding_count": len(findings),
        "clean": not findings,
        "scope_limitation": (
            "Lexical and block-scoped. A boundary anywhere in a figure block satisfies the "
            "strength check, so a qualifier attached to the wrong sentence would pass. It "
            "narrows the manual surface; it does not replace reading the figure."
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    out = OUTPUT
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"detector live: {control['separates']}")
    print(f"findings: {len(findings)}")
    for f in findings[:25]:
        print(f"  ! {f['kind']} [{f['figure'][:45]}] line {f['line']} "
              f"{f.get('term') or f.get('unbound_numbers')}")
    return 0 if control["separates"] else 1


if __name__ == "__main__":
    sys.exit(main())
