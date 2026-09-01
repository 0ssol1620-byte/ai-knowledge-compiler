"""Check the manuscript against audit section 28-F's required elements.

28-F asks for figures, tables, methods, limitations, related work, a
threat-to-validity section, and appendix/protocols. This checks the draft for
each, and -- more usefully -- checks that the claims established in this
session are actually reachable from the prose rather than sitting in the
matrix unreferenced.

A claim registered in CLAIM_MATRIX.yaml but never cited in the draft is a
silent gap: the evidence exists and the paper does not use it. This reports
those explicitly.

Read-only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CANON = Path(r"D:\CodexProjects\ai-knowledge-compiler")
PAPER = CANON / "research" / "tavonel_eval_v2" / "paper"
DRAFT = PAPER / "TAVONEL_PAPER_DRAFT_INTERNAL.md"
MATRIX = PAPER / "CLAIM_MATRIX.yaml"
GENERATED = PAPER / "generated"

REQUIRED_SECTIONS = {
    "methods": [r"##\s*\d*\.?\s*Method", r"freezing, receipts"],
    "limitations": [r"##\s*\d*\.?\s*Limitations", r"Discussion and limitations"],
    "related work": [r"Related work"],
    "threat to validity": [r"[Tt]hreat", r"validity"],
    "appendix/protocols": [r"##\s*Appendix"],
    "conclusion": [r"##\s*\d*\.?\s*Conclusion"],
    "references": [r"##\s*References"],
    "reproducibility": [r"Reproducibility"],
}


def main() -> int:
    text = DRAFT.read_text(encoding="utf-8")
    problems: list[str] = []

    print("=" * 66)
    print("MANUSCRIPT COMPLETENESS -- audit section 28-F")
    print("=" * 66)

    print("\nRequired elements:")
    for label, patterns in REQUIRED_SECTIONS.items():
        found = any(re.search(p, text) for p in patterns)
        print(f"  [{'PASS' if found else 'MISSING'}] {label}")
        if not found:
            problems.append(f"missing section: {label}")

    print("\nTables and figures:")
    tables = sorted(GENERATED.glob("table*.json"))
    figures = sorted(GENERATED.glob("figure*"))
    print(f"  generated tables : {len(tables)}")
    for t in tables:
        print(f"      {t.name}")
    print(f"  generated figures: {len(figures)}")
    for f in figures:
        print(f"      {f.name}")
    if not tables:
        problems.append("no generated tables")

    # Markdown tables written directly in the prose.
    inline_tables = len(re.findall(r"^\|.+\|$", text, flags=re.M))
    print(f"  inline table rows: {inline_tables}")

    print("\nClaim reachability (registered but never cited is a silent gap):")
    import yaml

    data = yaml.safe_load(MATRIX.read_text(encoding="utf-8"))
    claims = [c["id"] for c in data["claims"]]
    findings = [n["id"] for n in data["negative_findings"]]

    uncited_claims = [c for c in claims if c not in text]
    uncited_findings = [n for n in findings if n not in text]

    print(f"  claims registered  : {len(claims)}")
    print(f"  claims cited       : {len(claims) - len(uncited_claims)}")
    if uncited_claims:
        print(f"  NOT cited          : {', '.join(uncited_claims)}")
    print(f"  findings registered: {len(findings)}")
    print(f"  findings cited     : {len(findings) - len(uncited_findings)}")
    if uncited_findings:
        print(f"  NOT cited          : {', '.join(uncited_findings)}")

    # This session's claims must be reachable.
    for cid in ("C-36", "C-37", "N-18", "N-19"):
        cited = cid in text
        print(f"  [{'PASS' if cited else 'FAIL'}] {cid} reachable from the prose")
        if not cited:
            problems.append(f"{cid} registered but never cited in the draft")

    print("\n" + "=" * 66)
    if problems:
        print(f"RESULT: {len(problems)} gap(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("RESULT: 28-F elements present and this session's claims are cited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
