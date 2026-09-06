#!/usr/bin/env python3
"""Read the built package and check that it is what it says it is.

Separate from the builder on purpose. The builder reports what it intended to
write; this opens the directory it produced and looks. Every check below has a
way to fail, and `--control` shows that each one does.

1. every expected file is present
2. every manifest hash is valid, checked independently of the manifest writer
3. no content file is missing from the manifest
4. the README's counts match the directory
5. every PDF opens and has at least one page
6. the rendered figure count matches the figure registry
7. no zero-byte artifact
8. no unresolved relative link between package files
9. no TODO / TBD / FIXME / placeholder on a filing or submission surface
10. no forbidden comparative wording near the W6 boundary
11. no withdrawn patent assertion on a claim surface

Checks 10 and 11 are scoped to the documents that go to a venue or to counsel --
see `CLAIM_SURFACES` for which, and why the registers and the red-team documents
are deliberately not among them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "submission" / "TAVONEL_FINAL_SUBMISSION_PACKAGE_2026-08-20"
MANIFEST = PACKAGE / "HASH_MANIFEST.sha256"

EXPECTED = [
    "SUBMISSION_README.md",
    "FINAL_EXTERNAL_ACTIONS.md",
    "HASH_MANIFEST.sha256",
    "paper/MANUSCRIPT.md",
    "paper/TABLES.md",
    "paper/TAVONEL_MANUSCRIPT_GENERIC.pdf",
    "paper/submission-source/00_MANUSCRIPT_BODY.md",
    "paper/submission-source/01_REFERENCES.md",
    "paper/submission-source/02_APPENDICES.md",
    "paper/submission-source/03_TABLES.md",
    "paper/submission-source/04_FIGURES.md",
    "paper/submission-source/05_REPRODUCIBILITY.md",
    "patent/CLAIM_SET.md",
    "patent/SPECIFICATION.md",
    "patent/ABSTRACT_AND_DRAWINGS.md",
    "patent/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf",
    "patent/drawings/TAVONEL_PATENT_DRAWINGS.pdf",
    "figures/FIGURES.md",
    "figures/FIGURE_REGISTRY.json",
    "human-review/HUMAN_PASS_A_PACKET.md",
]

PLACEHOLDER = re.compile(
    r"\bTODO\b|\bTBD\b|\bFIXME\b|\bXXX\b|<placeholder|\[insert |\bLOREM\b", re.I)

#: The surfaces checks 10 and 11 apply to: the documents that go to a venue or
#: to counsel, and the sources the three built PDFs are assembled from. This is
#: the same set `tools/ip/audit_cross_document_consistency.py` scans upstream,
#: named here as package paths.
#:
#: Deliberately not the whole package. `red-team/` exists to state the attacks a
#: reviewer or examiner would make, so it quotes comparative wording on purpose.
#: The registers -- the evidence matrix, the amendment log, the counsel flags,
#: the withdrawn-term registry itself -- are the *record* of each withdrawal and
#: necessarily contain the withdrawn wording. Scanning them would report the
#: correction as the defect it corrected, and a check that cries wolf on its own
#: rulebook gets switched off.
#:
#: This is the P32 boundary, and it cuts both ways: a register is not a surface
#: until a document starts printing it. Every document below is checked; if a
#: future build renders a register into one of them, the register's text is
#: checked at that moment, in the surface that prints it.
CLAIM_SURFACES = (
    "paper/MANUSCRIPT.md",
    "paper/TABLES.md",
    "paper/submission-source/",
    "figures/FIGURES.md",
    "patent/CLAIM_SET.md",
    "patent/SPECIFICATION.md",
    "patent/ABSTRACT_AND_DRAWINGS.md",
    "patent/PRIOR_ART_AND_FTO_MEMO.md",
)

#: Surfaces that go to counsel or a venue. A placeholder here is a placeholder
#: someone outside the programme reads.
FILING_SURFACES = ("paper/", "patent/", "figures/", "human-review/",
                   "FINAL_EXTERNAL_ACTIONS.md", "SUBMISSION_README.md")

COMPARATIVE = re.compile(
    r"\b(outperform\w*|better than|superior to|beats)\b", re.I)

#: Copied verbatim from `tools/ip/audit_cross_document_consistency.py`. The
#: withdrawn-term rule is that tool's, and this applies the same rule to the
#: built package instead of to the sources. A second, looser rule here would
#: disagree with the audit that the package cites as clean.
EXEMPT_CONTEXT = re.compile(
    r"(withdrawn|correction|corrected|must not|never|forbidden|not claimed|"
    r"previously said|previously read|overclaim|was wrong|do not|"
    r"deliberately not|is not\b|are not\b|no longer|prohibited|nor are|"
    r"terminology|were changed|was changed|invited exactly that)",
    re.I,
)

#: An identifier is a record, not an assertion. `B-ATOMIC-PROMOTION-CONTRACT`
#: names the experiment that caused the withdrawal, and renaming it to satisfy
#: a text scan would break every receipt that cites it.
IDENTIFIER = re.compile(r"[A-Z0-9]+(?:[-_][A-Z0-9]+){2,}")

TEXT_SUFFIXES = {".md", ".yaml", ".json", ".sha256", ".txt", ".mmd"}
LINK = re.compile(r"\]\((?!https?:|mailto:|#)([^)#\s]+)")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def enclosing_block(lines: list[str], index: int, limit: int = 15) -> str:
    """The whole paragraph or blockquote an occurrence sits in.

    Same scoping as the upstream audit: a withdrawn term legitimately appears
    inside the note that withdraws it, and those notes are multi-line
    blockquotes, so a fixed window lands in the middle of one and sees no
    marker.
    """
    start = index
    while start > 0 and lines[start - 1].strip() and index - start < limit:
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip() and end - index < limit:
        end += 1
    return " ".join(lines[start : end + 1])


def withdrawn_terms(package: Path) -> list[str]:
    """The withdrawn terms, read from the registry that ships in the package.

    Hard-coding them here would let the registry and the check drift apart, and
    the drift would be invisible: the check would keep passing on the terms it
    remembered while a newly withdrawn one leaked.
    """
    import yaml

    path = package / "patent" / "WITHDRAWN_TERMS.yaml"
    if not path.is_file():
        return []
    doc = yaml.safe_load(read(path)) or {}
    return [e["term"] for e in (doc.get("withdrawn") or []) if e.get("term")]


def negation_context(text: str, at: int) -> bool:
    """Is this match inside a prohibition list or an explicit negation?

    The package documents its own forbidden wording, so the literal strings
    appear in it legitimately. A check that cannot tell a prohibition from a
    claim reports the rulebook as a violation and gets switched off.
    """
    window = text[max(0, at - 320) : at + 160].lower()
    markers = ("never", "not claim", "no comparative", "forbidden", "prohibited",
               "withdrawn", "must not", "does not appear", "we do not",
               "is not claimed", "never claimed", "not supported", "avoid",
               "would be", "rather than", "instead of", "not a claim")
    return any(m in window for m in markers)


def checks(package: Path) -> list[str]:
    problems: list[str] = []
    if not package.is_dir():
        return [f"package directory absent: {package}"]

    manifest = package / "HASH_MANIFEST.sha256"

    # 1 -- expected files present
    for rel in EXPECTED:
        if not (package / rel).is_file():
            problems.append(f"1 missing expected file: {rel}")

    # 2 -- manifest hashes valid
    listed: set[str] = set()
    if not manifest.is_file():
        problems.append("2 no hash manifest")
    else:
        raw = manifest.read_bytes()
        if b"\r\n" in raw:
            problems.append("2 manifest uses CRLF; sha256sum -c would fail every line")
        for line in raw.decode("utf-8").splitlines():
            digest, _, rel = line.partition("  ")
            listed.add(rel)
            target = package / rel
            if not target.is_file():
                problems.append(f"2 manifest names a file that is not here: {rel}")
            elif sha(target) != digest:
                problems.append(f"2 hash mismatch: {rel}")

    # 3 -- no content file outside the manifest
    on_disk = {p.relative_to(package).as_posix() for p in package.rglob("*")
               if p.is_file() and p.name != "HASH_MANIFEST.sha256"}
    for rel in sorted(on_disk - listed):
        problems.append(f"3 content file not in the manifest: {rel}")

    # 4 -- README counts match the directory
    readme = package / "SUBMISSION_README.md"
    if readme.is_file():
        text = read(readme)
        total = len(on_disk) + 1
        top = sorted(p.name for p in package.iterdir() if p.is_dir())
        for label, want in (("Package content files hashed", len(on_disk)),
                            ("Total files on disk", total),
                            ("Top-level content directories", len(top))):
            m = re.search(rf"\| {re.escape(label)} \| (\d+) \|", text)
            if not m:
                problems.append(f"4 README does not state {label!r}")
            elif int(m.group(1)) != want:
                problems.append(f"4 README says {label} = {m.group(1)}, "
                                f"directory has {want}")
        if "excludes itself" not in text:
            problems.append("4 README does not state that the manifest excludes itself")

    # 5 -- every PDF opens
    from pypdf import PdfReader
    pdfs = sorted(package.rglob("*.pdf"))
    if not pdfs:
        problems.append("5 the package contains no PDF")
    for pdf in pdfs:
        try:
            pages = len(PdfReader(str(pdf)).pages)
        except Exception as exc:
            problems.append(f"5 pdf will not open: "
                            f"{pdf.relative_to(package).as_posix()}: {exc}")
        else:
            if pages < 1:
                problems.append(f"5 pdf has no pages: "
                                f"{pdf.relative_to(package).as_posix()}")

    # 6 -- rendered figure count matches the registry
    reg_path = package / "figures" / "FIGURE_REGISTRY.json"
    if reg_path.is_file():
        reg = json.loads(read(reg_path))
        for group, subdir, prefix in (("paper", "figures/paper", "FIG"),
                                      ("patent", "figures/patent", "SHEET")):
            want = {f"{f['stem']}{ext}" for f in reg[group]
                    for ext in (".svg", ".pdf", ".png")}
            have = {p.name for p in (package / subdir).glob(f"{prefix}*")
                    if p.suffix in (".svg", ".pdf", ".png")}
            if want != have:
                problems.append(f"6 {subdir}: registry expects {len(want)} assets, "
                                f"directory has {len(have)}; "
                                f"missing {sorted(want - have)}, "
                                f"extra {sorted(have - want)}")
    else:
        problems.append("6 no figure registry in the package")

    # 7 -- no zero-byte artifact
    for rel in sorted(on_disk):
        if (package / rel).stat().st_size == 0:
            problems.append(f"7 zero-byte file: {rel}")

    # 8 -- relative links resolve
    for rel in sorted(on_disk):
        path = package / rel
        if path.suffix not in TEXT_SUFFIXES:
            continue
        for target in LINK.findall(read(path)):
            if not (path.parent / target).exists():
                problems.append(f"8 unresolved link in {rel}: {target}")

    # 9 -- no placeholders on a filing or submission surface
    for rel in sorted(on_disk):
        if not rel.startswith(FILING_SURFACES):
            continue
        path = package / rel
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = read(path)
        for m in PLACEHOLDER.finditer(text):
            if negation_context(text, m.start()):
                continue
            problems.append(f"9 placeholder {m.group(0)!r} in {rel}")

    # 10 -- no comparative wording near the W6 boundary
    for rel in sorted(on_disk):
        if not rel.startswith(CLAIM_SURFACES):
            continue
        path = package / rel
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = read(path)
        for m in COMPARATIVE.finditer(text):
            window = text[max(0, m.start() - 400) : m.end() + 400]
            if ("W6" in window or "NOT_MEASURED" in window) and not negation_context(
                    text, m.start()):
                problems.append(f"10 comparative wording {m.group(0)!r} beside the "
                                f"W6 boundary in {rel}")

    # 11 -- no withdrawn patent assertion
    terms = withdrawn_terms(package)
    if not terms:
        problems.append("11 no withdrawn-term registry in the package; the "
                        "withdrawn-assertion check has nothing to look for")
    for rel in sorted(on_disk):
        if not rel.startswith(CLAIM_SURFACES):
            continue
        path = package / rel
        if path.suffix not in TEXT_SUFFIXES:
            continue
        lines = read(path).splitlines()
        for term in terms:
            needle = term.lower()
            for i, line in enumerate(lines):
                if needle not in line.lower():
                    continue
                if EXEMPT_CONTEXT.search(enclosing_block(lines, i)):
                    continue
                if any(needle in ident.lower().replace("-", " ").replace("_", " ")
                       for ident in IDENTIFIER.findall(line)):
                    continue
                problems.append(f"11 withdrawn assertion {term!r} in {rel}:{i + 1}: "
                                f"{line.strip()[:90]}")
    return problems


def control(package: Path) -> int:
    """Show that the checks fail when the package is broken.

    A self-test that has only ever returned zero is indistinguishable from one
    that returns zero unconditionally.
    """
    import shutil
    import tempfile

    fired: dict[str, bool] = {}
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / package.name
        shutil.copytree(package, copy)

        (copy / "paper" / "MANUSCRIPT.md").unlink()
        fired["1 missing file"] = any(p.startswith("1 ") for p in checks(copy))
        shutil.copy2(package / "paper" / "MANUSCRIPT.md", copy / "paper" / "MANUSCRIPT.md")

        target = copy / "paper" / "TABLES.md"
        target.write_text(read(target) + "\n<!-- mutated -->\n", encoding="utf-8")
        fired["2 hash mismatch"] = any(p.startswith("2 ") for p in checks(copy))
        shutil.copy2(package / "paper" / "TABLES.md", target)

        (copy / "figures" / "STRAY.md").write_text("stray\n", encoding="utf-8")
        fired["3 unlisted file"] = any(p.startswith("3 ") for p in checks(copy))
        (copy / "figures" / "STRAY.md").unlink()

        readme = copy / "SUBMISSION_README.md"
        readme.write_text(
            read(readme).replace("| Total files on disk |", "| Total files on disk |", 1)
            .replace("Package content files hashed | ", "Package content files hashed | 9", 1),
            encoding="utf-8")
        fired["4 README count"] = any(p.startswith("4 ") for p in checks(copy))
        shutil.copy2(package / "SUBMISSION_README.md", readme)

        pdf = copy / "patent" / "drawings" / "TAVONEL_PATENT_DRAWINGS.pdf"
        pdf.write_bytes(b"not a pdf")
        fired["5 broken pdf"] = any(p.startswith("5 ") for p in checks(copy))
        shutil.copy2(package / "patent" / "drawings" / "TAVONEL_PATENT_DRAWINGS.pdf", pdf)

        stray = copy / "figures" / "paper" / "FIG01.svg"
        stray.unlink()
        fired["6 figure count"] = any(p.startswith("6 ") for p in checks(copy))
        shutil.copy2(package / "figures" / "paper" / "FIG01.svg", stray)

        empty = copy / "paper" / "EMPTY.md"
        empty.write_bytes(b"")
        fired["7 zero-byte"] = any(p.startswith("7 ") for p in checks(copy))
        empty.unlink()

        target = copy / "figures" / "FIGURES.md"
        original = read(target)
        target.write_text(original + "\n[gone](./no-such-file.md)\n", encoding="utf-8")
        fired["8 broken link"] = any(p.startswith("8 ") for p in checks(copy))
        target.write_text(original, encoding="utf-8")

        # Probes 9-11 go into a file of their own rather than being appended to
        # a real document. Appending puts the probe a few lines below prose that
        # already says "never" and "rather than", and the exemption -- correctly
        # -- suppresses it. The probe would then report a check as dead when
        # what it had actually demonstrated was the exemption working.
        probe = copy / "paper" / "submission-source" / "99_CONTROL_PROBE.md"
        term = withdrawn_terms(copy)[0]

        probe.write_text("# Control\n\nTODO: finish this section.\n", encoding="utf-8")
        fired["9 placeholder"] = any(p.startswith("9 ") for p in checks(copy))

        probe.write_text(
            "# Control\n\nOn the W6 endpoint our compiled context outperforms the "
            "comparator by a clear margin.\n", encoding="utf-8")
        fired["10 comparative"] = any(p.startswith("10 ") for p in checks(copy))

        probe.write_text(
            f"# Control\n\nThe world state is published {term} once every check "
            f"has passed.\n", encoding="utf-8")
        fired["11 withdrawn"] = any(p.startswith("11 ") for p in checks(copy))
        probe.unlink()

        # And the other half of the same question: the exemption must still
        # exempt. A probe that fires on the correction note as well would mean
        # check 11 had simply stopped reading context.
        probe.write_text(
            f"# Control\n\n> **Correction, 2026-08-19.** The claim previously read "
            f"{term} and that wording was withdrawn on the evidence.\n",
            encoding="utf-8")
        fired["11 exemption still holds"] = not any(
            p.startswith("11 ") for p in checks(copy))
        probe.unlink()

    for name, ok in fired.items():
        print(f"  control {name:20} separates: {ok}")
    dead = [n for n, ok in fired.items() if not ok]
    if dead:
        print(f"CONTROLS THAT DID NOT FIRE: {dead}")
        return 1
    print("all controls fire")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true",
                    help="mutate a copy of the package and show each check firing")
    args = ap.parse_args()

    if args.control:
        return control(PACKAGE)

    problems = checks(PACKAGE)
    total = sum(1 for p in PACKAGE.rglob("*") if p.is_file())
    print(f"package: {PACKAGE.relative_to(ROOT).as_posix()}")
    print(f"Package content files hashed: {total - 1}")
    print("Hash manifest file: 1")
    print(f"Total files on disk: {total}")
    print(f"Top-level content directories: "
          f"{sum(1 for p in PACKAGE.iterdir() if p.is_dir())}")
    print(f"PROBLEMS: {len(problems)}")
    for p in problems[:60]:
        print(f"  - {p}")
    if len(problems) > 60:
        print(f"  ... and {len(problems) - 60} more")

    receipt: dict[str, Any] = {
        "schema": "tavonel.package-selftest.v1",
        "package": PACKAGE.name,
        "content_files_hashed": total - 1,
        "total_files_on_disk": total,
        "problems": problems,
    }
    out = ROOT / "docs" / "ip" / "receipts" / "package-selftest-2026-08-20.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
