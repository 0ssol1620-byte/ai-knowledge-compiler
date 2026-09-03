#!/usr/bin/env python3
# ruff: noqa: E501, RUF001 -- this module carries a markdown README template.
# A markdown table row cannot be wrapped without changing the rendered table, and
# the en dashes are deliberate prose that matches every other document in the
# package. Both rules are correct for code and wrong for the embedded document.
"""Assemble the hand-over package into one directory, with a hash manifest.

Everything here already exists under `docs/` and `research/`. This tool copies,
never authors: a document that appears in the package and nowhere else would be a
document no audit reads. The one exception is the split of the manuscript into
`paper/submission-source/`, which is a mechanical slice of the manuscript at its
own headings -- no text is written, moved or reworded, and each slice is checked
back against the source byte for byte before it is written.

**The package inherits `docs/ip/`'s privilege control.** The claim set and
specification are git-ignored under a fail-closed allowlist (founder instruction,
2026-08-11), so the package directory is written with its own fail-closed
`.gitignore`. Copying privileged material into a tracked directory would defeat
the control by accident, which is exactly the failure the allowlist exists to
prevent.

**Counting.** The package reports four numbers because three of them are
routinely confused: the number of content files, the manifest that covers them,
the total on disk, and the number of top-level content directories. An earlier
build reported a single "files copied" figure that counted copy operations, and
it disagreed with the directory it described.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "submission" / "TAVONEL_FINAL_SUBMISSION_PACKAGE_2026-08-20"
MANUSCRIPT = ROOT / "docs" / "paper" / "MANUSCRIPT_v1_2026-08-19.md"

#: destination subdirectory -> [(source path, destination filename)]
LAYOUT: dict[str, list[tuple[str, str]]] = {
    "paper": [
        ("docs/paper/MANUSCRIPT_v1_2026-08-19.md", "MANUSCRIPT.md"),
        ("docs/paper/TABLES_2026-08-19.md", "TABLES.md"),
        ("docs/paper/TAVONEL_MANUSCRIPT_GENERIC.pdf", "TAVONEL_MANUSCRIPT_GENERIC.pdf"),
    ],
    "figures": [
        ("docs/paper/FIGURES_2026-08-19.md", "FIGURES.md"),
        ("docs/paper/figures/FIGURE_REGISTRY.json", "FIGURE_REGISTRY.json"),
    ],
    "patent": [
        ("docs/ip/FILING_README_2026-08-20.md", "FILING_README.md"),
        ("docs/ip/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf", "TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf"),
        ("docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md", "CLAIM_SET.md"),
        ("docs/ip/PATENT_ABSTRACT_AND_DRAWINGS_2026-08-20.md", "ABSTRACT_AND_DRAWINGS.md"),
        ("docs/ip/COUNSEL_FLAGS_2026-08-20.md", "COUNSEL_FLAGS.md"),
        ("docs/ip/UNSUPPORTED_BREADTH_LEDGER_2026-08-20.md", "UNSUPPORTED_BREADTH_LEDGER.md"),
        ("docs/ip/PATENT_SPECIFICATION_v1_2026-08-19.md", "SPECIFICATION.md"),
        ("docs/ip/CLAIM_EVIDENCE_MATRIX.md", "CLAIM_EVIDENCE_MATRIX.md"),
        ("docs/ip/claim-evidence-matrix.yaml", "claim-evidence-matrix.yaml"),
        ("docs/ip/ELEMENT_SUPPORT_BINDINGS.yaml", "ELEMENT_SUPPORT_BINDINGS.yaml"),
        ("docs/ip/CLAIM_AMENDMENTS.yaml", "CLAIM_AMENDMENTS.yaml"),
        ("docs/ip/ASSERTION_REGISTRY.yaml", "ASSERTION_REGISTRY.yaml"),
        ("docs/ip/WITHDRAWN_TERMS.yaml", "WITHDRAWN_TERMS.yaml"),
        ("docs/ip/PRIOR_ART_AND_NARROWING_MEMO_2026-08-19.md", "PRIOR_ART_AND_FTO_MEMO.md"),
        ("docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml", "TECHNOLOGY_INTAKE_REGISTER.yaml"),
        ("docs/ip/V4_DISCLOSURE_REGISTRY.yaml", "DISCLOSURE_REGISTRY.yaml"),
        ("docs/ip/receipts/element-support-matrix-2026-08-19.json", "element-support-matrix.json"),
        ("docs/ip/receipts/amendment-coverage-2026-08-19.json", "amendment-coverage.json"),
        ("docs/ip/receipts/submission-pdf-build-2026-08-20.json", "submission-pdf-build.json"),
        ("docs/ip/receipts/submission-pdf-check-2026-08-20.json", "submission-pdf-check.json"),
    ],
    "patent/drawings": [
        ("docs/ip/drawings/TAVONEL_PATENT_DRAWINGS.pdf", "TAVONEL_PATENT_DRAWINGS.pdf"),
    ],
    "red-team": [
        ("docs/ip/EXAMINER_RED_TEAM_2026-08-19.md", "EXAMINER_RED_TEAM.md"),
        ("docs/ip/EXAMINER_RED_TEAM_STATUTORY_2026-08-20.md", "EXAMINER_RED_TEAM_STATUTORY.md"),
        ("docs/ip/W6_V8_EXAMINER_RED_TEAM_2026-08-20.md", "EXAMINER_RED_TEAM_W6.md"),
        ("docs/audit/REVIEWER_RED_TEAM_2026-08-19.md", "REVIEWER_RED_TEAM.md"),
        ("docs/audit/W6_V8_REVIEWER_RED_TEAM_2026-08-20.md", "REVIEWER_RED_TEAM_W6.md"),
        ("docs/audit/HOSTILE_REVIEW_2026-08-19.md", "HOSTILE_REVIEW.md"),
    ],
    "evidence": [
        ("docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md", "CAMPAIGN_RESULTS.md"),
        ("docs/evidence/FAILED_AND_SUPERSEDED_LEDGER.md", "FAILED_AND_SUPERSEDED_LEDGER.md"),
        (
            "research/experiments/H1-W6-SAME-INTELLIGENCE-01/W6_V8_FINAL_STATE_2026-08-20.md",
            "W6_FINAL_STATE.md",
        ),
        ("docs/audit/ABLATION_COVERAGE_2026-08-19.md", "ABLATION_COVERAGE.md"),
    ],
    "reproducibility": [
        ("docs/repro/EXPERIMENT_MANIFEST.json", "EXPERIMENT_MANIFEST.json"),
        ("docs/repro/EXECUTION_INDEX_2026-08-19.json", "EXECUTION_INDEX.json"),
        ("docs/repro/HISTORICAL_DRIFT_REGISTER.yaml", "HISTORICAL_DRIFT_REGISTER.yaml"),
        ("docs/repro/EXCLUSION_RULES_2026-08-19.md", "EXCLUSION_RULES.md"),
        ("docs/repro/TEST_SCOPE_STATUS.json", "TEST_SCOPE_STATUS.json"),
    ],
    "supplement": [
        ("docs/audit/CONVERGENCE_PROTOCOL_2026-08-19.md", "CONVERGENCE_PROTOCOL.md"),
        ("docs/audit/STANDING_BOUNDS.yaml", "STANDING_BOUNDS.yaml"),
        ("docs/SUBMISSION_PACKAGE_INDEX_2026-08-19.md", "SUBMISSION_PACKAGE_INDEX.md"),
        ("research/PROGRAM_STATUS_2026-08-19.md", "PROGRAM_STATUS.md"),
    ],
    "human-review": [
        ("docs/submission/HUMAN_PASS_A_PACKET.md", "HUMAN_PASS_A_PACKET.md"),
        ("docs/ip/INVENTOR_REVIEW_CHECKLIST_2026-08-20.md", "INVENTOR_REVIEW_CHECKLIST.md"),
    ],
}

#: (source directory, destination subdirectory, glob) for the rendered assets.
#: `figures/` is the one home for every rendered figure; `patent/drawings/`
#: carries the combined print-ready PDF a filing agent asks for and points at
#: `figures/patent/` for the per-sheet files rather than holding a second copy.
ASSET_TREES = [
    ("docs/paper/figures/source", "figures/source", "*.mmd"),
    ("docs/paper/figures/source", "figures/source", "*.json"),
    ("docs/ip/drawings/source", "figures/source", "*.mmd"),
    ("docs/paper/figures", "figures/paper", "FIG*.*"),
    ("docs/ip/drawings", "figures/patent", "SHEET*.*"),
]

TOP_LEVEL = [
    ("docs/submission/FINAL_EXTERNAL_ACTIONS.md", "FINAL_EXTERNAL_ACTIONS.md"),
]

#: Written to `submission/`, the PARENT of the package, not to the package itself.
#: A rule that lives only inside the generated directory disappears with it: the
#: file is ignored by its own `*`, so it is never tracked, so on any other clone
#: the rule does not exist and the next generated package is unprotected. Placing
#: it one level up -- and un-ignoring itself, as docs/ip/.gitignore does -- means
#: the control is in version control and covers every package generated here.
GITIGNORE = """# Hand-over packages — fail-closed, inherited from docs/ip/.gitignore.
#
# These directories contain copies of privileged claim-level material. docs/ip/ is
# git-ignored under a fail-closed allowlist (founder instruction, 2026-08-11);
# copying that material here and tracking it would defeat the control by
# accident, which is precisely the failure the allowlist exists to prevent.
#
# Only this file is tracked. Regenerate a package with
# `python tools/release/build_submission_package.py`, whose sources are the
# canonical documents under docs/ and research/.
*
!.gitignore
"""

DRAWINGS_README = """# Patent drawing sheets

`TAVONEL_PATENT_DRAWINGS.pdf` is the combined print-ready copy: six sheets, one
per page, each labelled `FIG. N` with its description beneath.

The per-sheet vector masters and rasters — `SHEET01.svg` … `SHEET06.svg`, the
individual `.pdf` sheets and the 300 dpi `.png` previews — are in
`../../figures/patent/`, and the `.mmd` sources they were rendered from are in
`../../figures/source/`. They live there rather than being duplicated here, so
that every asset has one copy in the package and one line in the manifest.

**Monochrome line art with three-digit reference numerals.** Nothing on these
sheets appears outside the specification and the claim set. Jurisdiction-specific
formalities — sheet size and margins, the header block, numeral fonts, the
drawing-page numbering scheme — are counsel's and are not applied here.
"""

SUBMISSION_SOURCE_README = """# Generic paper submission source

A mechanical split of `../MANUSCRIPT.md` at its own headings, for assembling a
venue-formatted build. **No text was written, reworded or moved between
sections** — each file is a verbatim slice, and the builder checks each slice back
against the manuscript before writing it.

| file | manuscript section |
|---|---|
| `00_MANUSCRIPT_BODY.md` | title through §8 Conclusion |
| `01_REFERENCES.md` | §9 References |
| `02_APPENDICES.md` | Appendix A and Appendix B |
| `03_TABLES.md` | the table set, verbatim from `../TABLES.md` |
| `04_FIGURES.md` | the figure specifications, verbatim from `../../figures/FIGURES.md` |
| `05_REPRODUCIBILITY.md` | §6 Reproducibility, extracted so that a venue's artifact-availability field can be filled from one file |

Rendered figure assets are in `../../figures/paper/` — `FIG01` … `FIG08` as SVG
vector masters, PDF vector copies and 300 dpi PNG previews.

`../TAVONEL_MANUSCRIPT_GENERIC.pdf` is the built copy: A4, single column, no
venue template. Choosing a venue and applying its template is an external action.
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_round() -> dict[str, Any]:
    rounds = sorted((ROOT / "docs" / "audit" / "convergence-rounds").glob("round-*.json"))
    if not rounds:
        return {}
    return json.loads(rounds[-1].read_text(encoding="utf-8"))


def slice_at(text: str, start: str, end: str | None) -> str:
    """The manuscript from one heading up to (not including) another.

    Raises if an anchor is missing or the slice comes out trivially short. A
    split that silently produced an empty file would hand a venue build a
    references section with no references in it.
    """
    i = text.index(start)
    j = text.index(end, i) if end else len(text)
    out = text[i:j].rstrip() + "\n"
    if len(out) < 40:
        raise RuntimeError(f"slice {start!r}..{end!r} came out empty")
    return out


def write_submission_source(dest: Path) -> list[tuple[str, str]]:
    dest.mkdir(parents=True, exist_ok=True)
    text = MANUSCRIPT.read_text(encoding="utf-8")

    parts = {
        "00_MANUSCRIPT_BODY.md": slice_at(text, "# Compiling organizational",
                                          "## 9. References"),
        "01_REFERENCES.md": slice_at(text, "## 9. References", "## Appendix A"),
        "02_APPENDICES.md": slice_at(text, "## Appendix A", None),
        "05_REPRODUCIBILITY.md": slice_at(text, "## 6. Reproducibility",
                                          "## 7. Discussion"),
    }
    written: list[tuple[str, str]] = []
    for name, body in parts.items():
        # Every slice must be findable in the manuscript byte for byte. This is
        # what makes "no text was reworded" a statement about the files rather
        # than about the intent of the code that produced them.
        if body.rstrip() not in text:
            raise RuntimeError(f"{name} is not a verbatim slice of the manuscript")
        (dest / name).write_text(body, encoding="utf-8")
        written.append((MANUSCRIPT.relative_to(ROOT).as_posix(),
                        f"paper/submission-source/{name}"))

    for name, src in (("03_TABLES.md", "docs/paper/TABLES_2026-08-19.md"),
                      ("04_FIGURES.md", "docs/paper/FIGURES_2026-08-19.md")):
        shutil.copy2(ROOT / src, dest / name)
        written.append((src, f"paper/submission-source/{name}"))

    (dest / "README.md").write_text(SUBMISSION_SOURCE_README, encoding="utf-8")
    written.append(("(generated)", "paper/submission-source/README.md"))
    return written


def content_files() -> list[Path]:
    """Every file the manifest covers: the package minus the manifest itself."""
    return sorted(p for p in PACKAGE.rglob("*")
                  if p.is_file() and p.name != "HASH_MANIFEST.sha256")


def main() -> int:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    PACKAGE.mkdir(parents=True)
    (PACKAGE.parent / ".gitignore").write_text(GITIGNORE, encoding="utf-8")

    copied: list[tuple[str, str]] = []
    missing: list[str] = []

    for subdir, items in LAYOUT.items():
        (PACKAGE / subdir).mkdir(parents=True, exist_ok=True)
        for src, dst in items:
            source = ROOT / src
            if not source.is_file():
                missing.append(src)
                continue
            shutil.copy2(source, PACKAGE / subdir / dst)
            copied.append((src, f"{subdir}/{dst}"))

    for src_dir, dst_dir, pattern in ASSET_TREES:
        source = ROOT / src_dir
        if not source.is_dir():
            missing.append(src_dir)
            continue
        (PACKAGE / dst_dir).mkdir(parents=True, exist_ok=True)
        for path in sorted(source.glob(pattern)):
            if not path.is_file():
                continue
            shutil.copy2(path, PACKAGE / dst_dir / path.name)
            copied.append((f"{src_dir}/{path.name}", f"{dst_dir}/{path.name}"))

    (PACKAGE / "patent" / "drawings" / "README.md").write_text(
        DRAWINGS_README, encoding="utf-8")
    copied.append(("(generated)", "patent/drawings/README.md"))

    copied += write_submission_source(PACKAGE / "paper" / "submission-source")

    for src, dst in TOP_LEVEL:
        source = ROOT / src
        if not source.is_file():
            missing.append(src)
            continue
        shutil.copy2(source, PACKAGE / dst)
        copied.append((src, dst))

    # Convergence round copied last, so the copy reflects the latest recorded one.
    rounds = sorted((ROOT / "docs" / "audit" / "convergence-rounds").glob("round-*.json"))
    if rounds:
        shutil.copy2(rounds[-1], PACKAGE / "supplement" / f"CONVERGENCE_{rounds[-1].name}")
        copied.append(
            (
                str(rounds[-1].relative_to(ROOT)).replace("\\", "/"),
                f"supplement/CONVERGENCE_{rounds[-1].name}",
            )
        )

    top_dirs = sorted(p.name for p in PACKAGE.iterdir() if p.is_dir())
    # The README states the counts, so it must be written before the manifest --
    # and counted with the +1 it will itself add.
    write_readme(copied, missing, len(content_files()) + 1 + 1, top_dirs)

    files = content_files()
    lines_out = [f"{sha(p)}  {p.relative_to(PACKAGE).as_posix()}" for p in files]

    # newline="" so Python does not translate to CRLF on Windows. `sha256sum -c`
    # treats a trailing \r as part of the filename and reports every line as a
    # missing file -- a manifest that verifies nothing while looking complete.
    manifest = PACKAGE / "HASH_MANIFEST.sha256"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines_out) + "\n")

    # Verify what was just written rather than trusting that it was written. A
    # hash manifest is the one file in the package whose correctness cannot be
    # inferred from the code that produced it.
    bad = []
    for entry in manifest.read_text(encoding="utf-8").splitlines():
        digest, _, rel = entry.partition("  ")
        target = PACKAGE / rel
        if not target.is_file() or sha(target) != digest:
            bad.append(rel)
    if bad:
        raise RuntimeError(f"manifest does not verify against the package: {bad[:5]}")

    total_on_disk = sum(1 for p in PACKAGE.rglob("*") if p.is_file())
    print(f"package: {PACKAGE.relative_to(ROOT).as_posix()}")
    print(f"Package content files hashed: {len(lines_out)}")
    print("Hash manifest file: 1")
    print(f"Total files on disk: {total_on_disk}")
    print(f"Top-level content directories: {len(top_dirs)}  ({', '.join(top_dirs)})")
    print(f"copy operations: {len(copied)}")
    if len(lines_out) + 1 != total_on_disk:
        raise RuntimeError(
            f"content files ({len(lines_out)}) plus the manifest do not account "
            f"for everything on disk ({total_on_disk})")
    if missing:
        print(f"MISSING: {len(missing)}")
        for m in missing:
            print(f"  - {m}")
    return 2 if missing else 0


def write_readme(copied: list[tuple[str, str]], missing: list[str],
                 total_on_disk: int, top_dirs: list[str]) -> None:
    rnd = latest_round()
    scope = ROOT / "docs" / "repro" / "TEST_SCOPE_STATUS.json"
    green = (
        json.loads(scope.read_text(encoding="utf-8")).get("repository_green")
        if (scope.is_file())
        else None
    )
    element = json.loads(
        (ROOT / "docs/ip/receipts/element-support-matrix-2026-08-19.json").read_text(
            encoding="utf-8"
        )
    )
    figures = json.loads(
        (ROOT / "docs/paper/figures/FIGURE_REGISTRY.json").read_text(encoding="utf-8")
    )
    pdfs = json.loads(
        (ROOT / "docs/ip/receipts/submission-pdf-build-2026-08-20.json").read_text(
            encoding="utf-8"
        )
    )
    limitations = len(
        re.findall(
            r"^\d+\. ",
            MANUSCRIPT.read_text(encoding="utf-8")
            .split("## 5. Limitations")[1]
            .split("## 5.1")[0],
            re.M,
        )
    )
    hashed = total_on_disk - 1

    body = f"""# TAVONEL — submission package, 2026-08-20

**Nothing here has been submitted or filed.** `PATENT_FILING = NOT FILED`; no
paper is under review at any venue. This is the state of the work at the point
where the remaining actions require a person, a licence or a legal judgement, and
those are listed in `FINAL_EXTERNAL_ACTIONS.md`.

Generated by `tools/release/build_submission_package.py` from the canonical
documents under `docs/` and `research/`. **Every file here is a copy**, apart from
this README, `patent/drawings/README.md`, `paper/submission-source/README.md`, and
the verbatim manuscript slices in `paper/submission-source/`. If a copy and its
source disagree, the source is authoritative and this tool was not re-run.

---

## What is in this package, by count

| | |
|---|---|
| Package content files hashed | {hashed} |
| Hash manifest file | 1 |
| Total files on disk | {total_on_disk} |
| Top-level content directories | {len(top_dirs)} |

`HASH_MANIFEST.sha256` covers every content file and **excludes itself** — a file
cannot contain its own digest — which is why the hashed count is exactly one less
than the total on disk. To check the package:

```
cd TAVONEL_FINAL_SUBMISSION_PACKAGE_2026-08-20
sha256sum -c HASH_MANIFEST.sha256
```

Expect {hashed} `OK` lines and no failures. There is no `.gitignore` inside the
package: the fail-closed rule that protects generated packages lives one level up,
in `submission/.gitignore`, so that the rule itself is under version control.

---

## Status at generation time

| | |
|---|---|
| paper package | complete — manuscript, references, figures, tables, limitations, reproducibility, prebuttal, built PDF |
| patent package | complete — claim set, specification, matrix, bindings, amendments, red teams, FTO memo, drawing sheets, built review PDF |
| rendered figures | {figures["paper_figure_count"]} paper figures and {figures["patent_sheet_count"]} patent sheets, each as SVG, PDF and 300 dpi PNG |
| built documents | `paper/TAVONEL_MANUSCRIPT_GENERIC.pdf` ({pdfs["paper"]["pages"]} pp) · `patent/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf` ({pdfs["patent"]["pages"]} pp) · `patent/drawings/TAVONEL_PATENT_DRAWINGS.pdf` ({pdfs["drawings"]["pages"]} pp) |
| element support | {element["elements_total"]} elements, {len(element["findings"])} findings, all `DISCLOSED_RESERVED_NOT_IN_FILING_CORE` |
| agent-side convergence | {rnd.get("agent_convergence_complete")} (passes B–K) |
| Pass A | {rnd.get("pass_a_state", "EXTERNAL_HUMAN_REVIEW_REQUIRED")} |
| convergence declared | {rnd.get("convergence_declared")} |
| full suite | repository_green = {green} |
| actual submission | **not performed** |

`agent_convergence_complete` is **not** convergence. It covers passes B–K only.
Pass A is a human read, it has not been performed, and while that is true no
round counts toward the protocol's two-consecutive-clean stop rule.

---

## Layout

| directory | what is in it |
|---|---|
| `paper/` | manuscript, tables, the built generic PDF, and `submission-source/` — a verbatim split for a venue build |
| `figures/` | `FIGURES.md` and the figure registry; `source/` mermaid and table sources; `paper/` rendered `FIG01`–`FIG08`; `patent/` rendered `SHEET01`–`SHEET06` |
| `patent/` | claim set, specification, evidence matrix, element bindings, amendment register, assertion registry, FTO intake, the built review PDF, and `drawings/` with the combined print-ready sheet PDF |
| `red-team/` | examiner passes (general, statutory, W6), reviewer passes, the hostile review with its full incident log |
| `evidence/` | campaign results, the failed-and-superseded ledger, W6's final state, ablation coverage |
| `reproducibility/` | experiment manifest, execution index, drift register, exclusion rules, test-scope receipt |
| `supplement/` | convergence protocol, standing bounds, the latest round record, the package index, programme status |
| `human-review/` | the Pass A packet — the one thing here that needs a person |

Every rendered figure has one copy and one hash. `patent/drawings/` holds the
combined sheet PDF and points at `figures/patent/` for the per-sheet files rather
than carrying a second copy of them.

## Where to start

1. `FINAL_EXTERNAL_ACTIONS.md` — what is left, and who owns each item.
2. `human-review/HUMAN_PASS_A_PACKET.md` — 60–90 minutes, and it blocks everything else.
3. `paper/TAVONEL_MANUSCRIPT_GENERIC.pdf` — the paper as built, with the figures in place.
4. `patent/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf` — title, abstracts, specification, claims and drawing sheets in one file.
5. `red-team/HOSTILE_REVIEW.md` Part 4 — eleven attacks with their answers, six conceded.
6. `paper/MANUSCRIPT.md` §5 — {limitations} limitations. Read these before the results.

## What is deliberately absent

- **Venue formatting.** The paper PDF is A4, single column, no template. ACM,
  IEEE and NeurIPS styles are applied after a venue is chosen.
- **Jurisdiction filing form.** Claim numbering, dependency form, sheet margins
  and header blocks are counsel's.
- **A comparative same-intelligence result.** W6's confirmatory run stopped at a
  pre-arm gate; the endpoint is `NOT_MEASURED`, not failed and not tied. The
  cohort is spent.
- **A prior-art search.** None has been run by a professional searcher, and every
  §102/§103 position is drafting discipline rather than a search result.
- **Inventor names and applicant entity.** A legal determination, not a
  derivation from commit authorship.
- **A convergence claim.** See the status table.

{"" if not missing else chr(10).join(["## Missing sources", ""] + [f"- `{m}`" for m in missing]) + chr(10)}
---

Copy operations in this build: {len(copied)}. Regenerate with:

```
python tools/release/render_figures.py
python tools/release/build_pdfs.py
python tools/release/build_submission_package.py
```
"""
    (PACKAGE / "SUBMISSION_README.md").write_text(body, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
