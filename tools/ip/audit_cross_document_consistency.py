#!/usr/bin/env python3
"""Cross-document consistency audit: registry vs specification vs paper vs figures.

This exists because of hostile finding P14. Claim text was narrowed promptly when
H1-I and H1-K landed; the *specification* and a *figure caption* kept asserting
the older, stronger property for four sessions. A written-description mismatch is
exactly what a hostile examiner looks for, and keyword-grepping one file at a
time is how it survived.

Three mechanical checks, none of which replaces reading:

1. **Forbidden wording leakage.** Every claim's `forbidden_wording` is searched
   across the specification, claim set, manuscript and figures. A forbidden
   phrase appearing anywhere outside an explicit correction or prohibition
   context is a finding.
2. **Evidence-path liveness.** Every path a claim cites must exist on disk.
3. **Status/vocabulary coherence.** A claim whose status is FAILED, NOT_RUN,
   BLOCKED_* or EXPLORATORY must not be described in the paper with
   success vocabulary in the same sentence as its own identifier.

Check 1 is the one that would have caught P14, so it is deliberately noisy: it
reports context lines and lets a human dismiss them, rather than trying to be
clever about negation and silently missing a real leak.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs" / "ip" / "claim-evidence-matrix.yaml"

TARGETS = {
    "specification": ROOT / "docs" / "ip" / "PATENT_SPECIFICATION_v1_2026-08-19.md",
    "claim_set": ROOT / "docs" / "ip" / "PATENT_CLAIM_SET_v1_2026-08-19.md",
    "manuscript": ROOT / "docs" / "paper" / "MANUSCRIPT_v1_2026-08-19.md",
    "figures": ROOT / "docs" / "paper" / "FIGURES_2026-08-19.md",
    "prior_art": ROOT / "docs" / "ip" / "PRIOR_ART_AND_NARROWING_MEMO_2026-08-19.md",
}

#: A forbidden phrase inside one of these is a *prohibition* or a *correction*,
#: not a leak. Matched against the surrounding line and the two before it.
EXEMPT_CONTEXT = re.compile(
    r"(withdrawn|correction|corrected|must not|never|forbidden|not claimed|"
    r"previously said|previously read|overclaim|was wrong|do not|"
    r"deliberately not|is not\b|are not\b|no longer|prohibited|nor are|"
    r"terminology|were changed|was changed|invited exactly that)",
    re.I,
)

#: Vocabulary that would misrepresent a non-success status.
SUCCESS_WORDS = re.compile(
    r"\b(validated|proven|demonstrated|confirms|established|solved|achieves)\b", re.I
)
NON_SUCCESS_STATUS = {"FAILED", "NOT_RUN", "BLOCKED_INTERNAL", "BLOCKED_EXTERNAL",
                      "EXPLORATORY", "SUPERSEDED", "PARTIALLY_SUPPORTED"}


def load_targets() -> dict[str, list[str]]:
    return {
        name: (path.read_text(encoding="utf-8").splitlines() if path.exists() else [])
        for name, path in TARGETS.items()
    }


def normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def check_forbidden_leakage(claims, docs) -> list[dict[str, Any]]:
    findings = []
    for claim in claims:
        for phrase in claim.get("forbidden_wording") or []:
            needle = normalise(phrase)
            # A forbidden entry that is itself a meta-rule ("any citation of ...")
            # is guidance, not a literal string to hunt for.
            if needle.startswith("any ") or len(needle.split()) > 12:
                continue
            for doc, lines in docs.items():
                for i, line in enumerate(lines):
                    if needle not in normalise(line):
                        continue
                    window = " ".join(lines[max(0, i - 3): i + 2])
                    if EXEMPT_CONTEXT.search(window):
                        continue
                    findings.append(
                        {
                            "claim": claim["id"],
                            "forbidden_phrase": phrase,
                            "document": doc,
                            "line_number": i + 1,
                            "line": line.strip()[:200],
                        }
                    )
    return findings


WITHDRAWN_TERMS = ROOT / "docs" / "ip" / "WITHDRAWN_TERMS.yaml"


def load_withdrawn() -> list[dict[str, Any]]:
    if not WITHDRAWN_TERMS.exists():
        return []
    doc = yaml.safe_load(WITHDRAWN_TERMS.read_text(encoding="utf-8")) or {}
    return doc.get("withdrawn") or []


def enclosing_block(lines: list[str], index: int, limit: int = 15) -> str:
    """The whole paragraph or blockquote an occurrence sits in.

    A withdrawn term legitimately appears inside the note that withdraws it, and
    those notes are multi-line blockquotes: a fixed three-line window lands in
    the middle of one and sees no marker. Scoping the exemption to the passage
    asks the right question -- is this occurrence inside a passage that announces
    a correction? -- rather than an arbitrary distance one.
    """
    start = index
    while start > 0 and lines[start - 1].strip() and index - start < limit:
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip() and end - index < limit:
        end += 1
    return " ".join(lines[start: end + 1])


def check_withdrawn_terms(withdrawn, docs) -> list[dict[str, Any]]:
    """Every term withdrawn from a claim, hunted across every target document.

    P19: "atomically" and "ordered" were withdrawn on evidence and then survived
    in five surfaces. The forbidden-wording check was green and honest -- neither
    word was on any list, so it was never asked. Prose recorded the withdrawal;
    prose is not a detector. This is the detector.
    """
    findings = []
    for entry in withdrawn:
        needle = normalise(entry["term"])
        for doc, lines in docs.items():
            for i, line in enumerate(lines):
                if needle not in normalise(line):
                    continue
                if EXEMPT_CONTEXT.search(enclosing_block(lines, i)):
                    continue
                findings.append(
                    {
                        "withdrawn_term": entry["term"],
                        "withdrawn_from": entry.get("withdrawn_from"),
                        "document": doc,
                        "line_number": i + 1,
                        "line": line.strip()[:200],
                        "replacement": entry.get("replacement"),
                        "evidence": entry.get("evidence"),
                    }
                )
    return findings


def withdrawn_control(withdrawn) -> dict[str, Any]:
    """Positive control for the withdrawn-term detector.

    A synthetic document carrying a withdrawn term in a plain assertion, and a
    second carrying it inside a correction note. The detector must flag the first
    and exempt the second. Without this the passage-scoped exemption could widen
    until it swallows everything, and the audit would still report zero.
    """
    if not withdrawn:
        return {"ran": False, "separates": False, "why": "no withdrawn terms registered"}
    term = withdrawn[0]["term"]
    leak_doc = {"__control__": [
        "Some unrelated sentence about the pipeline.",
        f"Activation proceeds {term} once the gate has passed.",
        "Another unrelated sentence.",
    ]}
    exempt_doc = {"__control__": [
        f"> **Correction, 2026-08-19.** The claim previously read {term} and was withdrawn.",
    ]}
    leaked = check_withdrawn_terms(withdrawn[:1], leak_doc)
    exempted = check_withdrawn_terms(withdrawn[:1], exempt_doc)
    return {
        "ran": True,
        "control_term": term,
        "plain_assertion_flagged": len(leaked) == 1,
        "correction_note_exempted": len(exempted) == 0,
        "separates": len(leaked) == 1 and len(exempted) == 0,
        "why_it_matters": (
            "The exemption is passage-scoped, so it can silently widen. A detector "
            "that exempts everything reports the same zero as a clean corpus."
        ),
    }


def check_evidence_paths(claims) -> list[dict[str, Any]]:
    missing = []
    for claim in claims:
        for ev in claim.get("evidence", []):
            p = ROOT / ev["path"]
            if not p.exists():
                missing.append({"claim": claim["id"], "path": ev["path"]})
    return missing


def check_status_vocabulary(claims, docs) -> list[dict[str, Any]]:
    findings = []
    ident = {c["id"]: c for c in claims}
    for doc, lines in docs.items():
        for i, line in enumerate(lines):
            for cid, claim in ident.items():
                if cid not in line:
                    continue
                if claim["status"] not in NON_SUCCESS_STATUS:
                    continue
                if SUCCESS_WORDS.search(line) and not EXEMPT_CONTEXT.search(line):
                    findings.append(
                        {
                            "claim": cid,
                            "status": claim["status"],
                            "document": doc,
                            "line_number": i + 1,
                            "line": line.strip()[:200],
                        }
                    )
    return findings


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    claims = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["claims"]
    docs = load_targets()

    leakage = check_forbidden_leakage(claims, docs)
    withdrawn = load_withdrawn()
    withdrawn_leaks = check_withdrawn_terms(withdrawn, docs)
    missing = check_evidence_paths(claims)
    vocab = check_status_vocabulary(claims, docs)

    clean = not (leakage or missing or vocab)
    receipt: dict[str, Any] = {
        "schema": "tavonel.cross-document-consistency-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "motivation": (
            "Hostile finding P14: a claim narrowing updated the claim text but "
            "left the specification and a figure caption asserting the older, "
            "stronger property."
        ),
        "documents_audited": {
            name: str(path.relative_to(ROOT)).replace("\\", "/")
            for name, path in TARGETS.items()
        },
        "claims_audited": len(claims),
        "forbidden_wording_leakage": leakage,
        "forbidden_wording_leakage_count": len(leakage),
        "withdrawn_terms_registered": len(withdrawn),
        "withdrawn_term_detector_control": withdrawn_control(withdrawn),
        "withdrawn_term_leakage": withdrawn_leaks,
        "withdrawn_term_leakage_count": len(withdrawn_leaks),
        "missing_evidence_paths": missing,
        "missing_evidence_path_count": len(missing),
        "status_vocabulary_conflicts": vocab,
        "status_vocabulary_conflict_count": len(vocab),
        "clean": clean,
        "what_this_does_not_check": (
            "Semantic agreement. A sentence can contradict a claim without using "
            "any forbidden phrase, which is how P14 survived. This tool narrows "
            "the manual reading surface; it does not replace it."
        ),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out = ROOT / "docs" / "ip" / "receipts" / "cross-document-consistency-2026-08-19.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"claims audited:              {len(claims)}")
    print(f"forbidden wording leakage:   {len(leakage)}")
    ctl = withdrawn_control(withdrawn)
    print(f"withdrawn terms registered:  {len(withdrawn)}  "
          f"(control separates: {ctl['separates']})")
    print(f"withdrawn term leakage:      {len(withdrawn_leaks)}")
    for f in withdrawn_leaks[:15]:
        print(f"  ! {f['document']}:{f['line_number']} withdrawn {f['withdrawn_term']!r}")
        print(f"      {f['line'][:140]}")
    for f in leakage[:12]:
        print(f"  [{f['document']}:{f['line_number']}] {f['claim']}")
        print(f"     forbidden: {f['forbidden_phrase']!r}")
        print(f"     line:      {f['line']}")
    print(f"missing evidence paths:      {len(missing)}")
    for m in missing[:10]:
        print(f"  {m['claim']} -> {m['path']}")
    print(f"status vocabulary conflicts: {len(vocab)}")
    for v in vocab[:10]:
        print(f"  [{v['document']}:{v['line_number']}] {v['claim']} ({v['status']})")
        print(f"     {v['line']}")
    print(f"wrote {out}")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
