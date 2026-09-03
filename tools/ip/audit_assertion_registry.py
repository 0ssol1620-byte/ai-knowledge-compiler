#!/usr/bin/env python3
"""Audit the package's surfaces against assertion STATUS, not against a word list.

The term-level detector in `audit_cross_document_consistency.py` asks whether a
withdrawn word survived. This asks a different question: does any surface still
assert a proposition the registry says was narrowed or withdrawn, and does every
surface that is supposed to carry an active assertion still carry it?

Two failure directions, both real:

**Leak.** An assertion is narrowed or withdrawn, and a surface still states the
broad form. That is how "atomically" and "ordered" survived in five surfaces
after both were withdrawn on our own receipts.

**Silent disappearance.** An assertion is ACTIVE and declares the surfaces it
must appear on, and it is not on one of them. A claim that quietly vanishes from
the specification while the manuscript still relies on it is a defect in the same
family, and a leak detector cannot see it.

**The control is the point of this file.** A registry audit that cannot fail
reports the same clean result whether propagation worked or was never attempted.
`withdrawal_propagation_control()` marks a synthetic assertion WITHDRAWN, leaves
its wording in a synthetic surface, and requires a finding; then it re-runs with
that assertion absent and requires none. If the two do not separate, the audit
reports NOT_RUN and no result of this tool may be cited.
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
REGISTRY = ROOT / "docs" / "ip" / "ASSERTION_REGISTRY.yaml"
OUTPUT = ROOT / "docs" / "ip" / "receipts" / "assertion-registry-audit-2026-08-19.json"

EVIDENCE_CLASSES = (
    "MEASURED", "STATIC_CODE_AUDIT", "DERIVED", "INFERRED",
    "EXPECTED", "EXTERNAL", "NOT_MEASURED",
)
STATUSES = ("ACTIVE", "NARROWED", "WITHDRAWN")

#: An occurrence inside a passage that is correcting, prohibiting or recording the
#: withdrawal is the fix, not the defect. Scoped to the enclosing block so the
#: exemption cannot be earned by a disclaimer elsewhere in the file.
EXEMPT = re.compile(
    r"withdraw|no longer|superseded|must not|may not|never (?:write|recite|claim)|"
    r"forbidden|previously (?:stated|recited|claimed)|was narrowed|not supported|"
    r"corrected from|earlier wording|does not (?:establish|entail|claim)|"
    r"do(?:es)? not recite|initially wrote|overclaim|was headed|invited|"
    r"is not claimed|were (?:both )?changed",
    re.I,
)
# Deliberately NOT exempt: "never as a distributed transaction guarantee" and
# "*not* distributed atomicity". Disclaiming the distributed reading is not
# permission to keep the withdrawn label -- a caption headed "Atomic promotion"
# asserts it in the heading and retracts it in the fine print, which is the
# construction the withdrawal existed to remove. Those two sites are repaired,
# not exempted.

#: A hyphenated all-caps token is an artifact or experiment identifier --
#: `B-ATOMIC-PROMOTION-CONTRACT` names the audit that *disproved* the broad
#: reading. Backticked text is code or a path. Neither asserts anything, and
#: reading them as assertions is how a detector earns its findings by counting
#: its own evidence pointers. `ATOMIC ACTIVATION` in a figure node is not
#: exempt: it has no hyphen joining it into an identifier.
IDENTIFIER = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)+$")

#: Mention versus use, decided within the sentence rather than the block.
#: "not distributed crash atomicity" names what is *not* claimed and is the
#: disclaimer working. "Atomic promotion contract" as a table heading uses the
#: withdrawn label as the document's own vocabulary and retracts it in the fine
#: print -- the exact construction the withdrawal removed. A block-level
#: exemption cannot tell these apart, because both blocks contain a negation.
NEGATED = re.compile(
    r"(?:\*{0,2}not\*{0,2}|never|no|rather than|instead of|does not|is not|are not)"
    r"[ *_,]{1,4}(?:\w+[ *_-]{1,3}){0,3}$",
    re.I,
)


def is_negated_mention(block: str, start: int) -> bool:
    line_start = block.rfind("\n", 0, start) + 1
    return bool(NEGATED.search(block[line_start:start]))


def is_identifier_context(block: str, start: int, end: int) -> bool:
    line_start = block.rfind("\n", 0, start) + 1
    line_end = block.find("\n", end)
    line = block[line_start : line_end if line_end != -1 else len(block)]
    # Inline-code parity is counted within the line. Counting across the block
    # made a ```mermaid fence open a code span that never closed, so every node
    # label in every diagram read as code and two real leaks went silent.
    if block[line_start:start].count("`") % 2 == 1:
        return True
    left = line.rfind(" ", 0, start - line_start) + 1
    right = line.find(" ", end - line_start)
    token = line[left : right if right != -1 else len(line)].strip()
    return bool(IDENTIFIER.match(token.strip("`*_.,;:()[]{}\"")))


def blocks(text: str) -> list[tuple[int, str]]:
    """Paragraph-ish blocks with their starting line number.

    A markdown table row is emitted as its own block. A table is one paragraph
    to a blank-line splitter, so a `may not` in one row exempted every other row
    in the same table -- which silenced a real partial statement six rows away.
    Rows are independent statements and are scoped independently.
    """
    out, buf, start = [], [], 1
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("|"):
            if buf:
                out.append((start, "\n".join(buf)))
                buf = []
            out.append((i, line))
            continue
        if line.strip():
            if not buf:
                start = i
            buf.append(line)
        elif buf:
            out.append((start, "\n".join(buf)))
            buf = []
    if buf:
        out.append((start, "\n".join(buf)))
    return out


def scan(assertion: dict[str, Any], surfaces: dict[str, str]) -> list[dict[str, Any]]:
    """Findings for one assertion against already-loaded surface text."""
    findings: list[dict[str, Any]] = []
    status = assertion.get("status")
    aid = assertion.get("id")

    if status in ("NARROWED", "WITHDRAWN"):
        for pattern in assertion.get("forbidden_wording") or []:
            rx = re.compile(pattern, re.I)
            for name, text in surfaces.items():
                for line_no, block in blocks(text):
                    m = rx.search(block)
                    if not m or EXEMPT.search(block):
                        continue
                    if is_identifier_context(block, m.start(), m.end()):
                        continue
                    if is_negated_mention(block, m.start()):
                        continue
                    findings.append({
                        "kind": "ASSERTION_LEAK",
                        "assertion": aid, "status": status, "surface": name,
                        "line": line_no + block[: m.start()].count("\n"),
                        "pattern": pattern, "matched": m.group(0),
                        "why": (
                            f"{aid} is {status}; this surface still states the "
                            "form the registry forbids, and the enclosing block "
                            "is not a correction or prohibition"
                        ),
                        "required_wording": (
                            assertion.get("statement") if status == "NARROWED"
                            else "no replacement -- the assertion was withdrawn outright"
                        ),
                    })

    # A narrowed assertion can be stated in part. "eight residual tied assignments
    # were path-dependent" is true and is half the narrowing: it omits that each
    # is a classification flip and that AMBIGUOUS carries no logical identifier,
    # which is what makes the divergence permanent rather than cosmetic. Presence
    # anywhere in the file satisfies must_appear_in, so the abstract can carry the
    # weak form indefinitely while the file passes. This requires the completion
    # to appear in the same block as the partial form.
    for rule in assertion.get("partial_forms") or []:
        partial = re.compile(rule["partial"], re.I)
        completion = re.compile(rule["completed_by"], re.I)
        for name, text in surfaces.items():
            for line_no, block in blocks(text):
                m = partial.search(block)
                if not m or EXEMPT.search(block):
                    continue
                if completion.search(re.sub(r"\s+", " ", block)):
                    continue
                findings.append({
                    "kind": "ASSERTION_STATED_IN_PART",
                    "assertion": aid, "status": status, "surface": name,
                    "line": line_no + block[: m.start()].count("\n"),
                    "matched": m.group(0), "missing": rule["completed_by"],
                    "why": rule.get("why", ""),
                    "required_wording": assertion.get("statement"),
                })

    # Presence is required of NARROWED assertions too, not only ACTIVE ones. A
    # narrowing leaves an assertion standing in its narrower form; if that form
    # is nowhere in a document that relies on it, the assertion was not narrowed,
    # it was lost. Only WITHDRAWN assertions are exempt -- being absent is what
    # withdrawal means.
    if status in ("ACTIVE", "NARROWED"):
        for name in assertion.get("must_appear_in") or []:
            text = surfaces.get(name)
            if text is None:
                continue
            # Markdown hard-wraps prose, so "invariant to evaluation order" is
            # three lines in the claim set and a literal phrase search misses it.
            flat = re.sub(r"\s+", " ", text)
            marks = assertion.get("appears_as") or []
            if marks and not any(
                re.search(re.sub(r"\s+", r"\\s+", m), flat, re.I) for m in marks
            ):
                findings.append({
                    "kind": "ASSERTION_MISSING",
                    "assertion": aid, "status": status, "surface": name,
                    "why": (
                        f"{aid} is ACTIVE and declares this surface, but none of its "
                        "identifying wording appears there. An assertion that quietly "
                        "left a document it is relied on in is a defect a leak "
                        "detector cannot see."
                    ),
                    "looked_for": marks,
                })
    return findings


def hygiene(assertions: list[dict[str, Any]], surface_names: set[str]) -> list[dict[str, Any]]:
    """Defects in the registry itself, which no surface scan would reveal."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in assertions:
        aid = a.get("id") or "<missing id>"
        if aid in seen:
            out.append({"kind": "REGISTRY_DUPLICATE_ID", "assertion": aid,
                        "why": "two entries share a canonical id"})
        seen.add(aid)
        if a.get("status") not in STATUSES:
            out.append({"kind": "REGISTRY_BAD_STATUS", "assertion": aid,
                        "value": a.get("status"), "allowed": list(STATUSES)})
        if a.get("evidence_class") not in EVIDENCE_CLASSES:
            out.append({"kind": "REGISTRY_BAD_EVIDENCE_CLASS", "assertion": aid,
                        "value": a.get("evidence_class"), "allowed": list(EVIDENCE_CLASSES)})
        ev = a.get("evidence")
        if a.get("evidence_class") in ("MEASURED", "STATIC_CODE_AUDIT"):
            if not ev:
                out.append({"kind": "REGISTRY_EVIDENCE_MISSING", "assertion": aid,
                            "why": "a MEASURED or STATIC_CODE_AUDIT assertion must name evidence"})
            elif not (ROOT / ev).exists():
                out.append({"kind": "REGISTRY_EVIDENCE_PATH_ABSENT", "assertion": aid,
                            "path": ev,
                            "why": "the named evidence directory is not in the repository"})
        for name in a.get("must_appear_in") or []:
            if name not in surface_names:
                out.append({"kind": "REGISTRY_UNKNOWN_SURFACE", "assertion": aid,
                            "surface": name, "why": "not declared in the surfaces map"})
        if a.get("status") in ("NARROWED", "WITHDRAWN") and not a.get("forbidden_wording"):
            out.append({"kind": "REGISTRY_NO_FORBIDDEN_WORDING", "assertion": aid,
                        "why": ("a narrowed or withdrawn assertion with no forbidden wording "
                                "is undetectable; the status would be decorative")})
        if a.get("status") == "NARROWED" and not a.get("narrowed_from"):
            out.append({"kind": "REGISTRY_NO_PRIOR_FORM", "assertion": aid,
                        "why": "a narrowing must record what it narrowed from"})
    return out


CONTROL_SURFACE = {
    "control_surface": (
        "Section 3. Results\n\n"
        "The system performs quorum-certified rollback across every replica, and "
        "the certification holds under arbitrary partition.\n\n"
        "Section 4. Discussion\n\nUnrelated text.\n"
    )
}
CONTROL_ASSERTION = {
    "id": "ASSERT_CONTROL_PROBE",
    "statement": "synthetic; exists only to make this detector falsifiable",
    "status": "WITHDRAWN",
    "evidence_class": "NOT_MEASURED",
    "forbidden_wording": ["quorum-certified rollback"],
    "must_appear_in": [],
}


def withdrawal_propagation_control() -> dict[str, Any]:
    """Mark an assertion withdrawn, leave its wording behind, require a finding.

    Then remove the assertion and require the same surface to come back clean.
    One direction alone proves nothing: a detector that always fires separates as
    poorly as one that never does.
    """
    withdrawn = scan(CONTROL_ASSERTION, CONTROL_SURFACE)
    absent = scan({**CONTROL_ASSERTION, "status": "ACTIVE", "forbidden_wording": []},
                  CONTROL_SURFACE)
    exempted = scan(CONTROL_ASSERTION, {
        "control_surface": (
            "Section 3. Results\n\n"
            "This disclosure must not recite quorum-certified rollback; the "
            "assertion was withdrawn and no replica-level guarantee is claimed.\n"
        )
    })
    separates = len(withdrawn) == 1 and not absent and not exempted
    return {
        "separates": separates,
        "withdrawn_leaves_wording_findings": len(withdrawn),
        "assertion_absent_findings": len(absent),
        "wording_inside_a_prohibition_findings": len(exempted),
        "what_it_proves": (
            "the audit fails when an assertion is marked WITHDRAWN and its wording is left "
            "in a surface, does not fire when no such assertion is registered, and does not "
            "fire on the sentence that records the prohibition"
        ),
        "what_it_does_not_prove": (
            "nothing about whether the registry's own statuses are correct, or whether a "
            "surface asserts a withdrawn proposition in wording the registry never listed. "
            "That remains a human read."
        ),
    }


#: The wording B1 element 7 actually carried before 2026-08-19, and what replaced
#: it. A pattern added in the same change that repairs the text it was written
#: for has never been shown to fire, and this programme has shipped three
#: detectors that could not. This runs the registry's live ASSERT_GATE_ORDER
#: patterns against both and requires them to separate.
HISTORICAL_GATE_WORDING = {
    "before": (
        "7. verifying the candidate knowledge state, before activation, by a sequence of\n"
        "   **candidate-state predicates whose conjunctive acceptance result is invariant\n"
        "   to evaluation order**, comprising: that every classified change is accounted\n"
        "   for by the affected set;\n"
    ),
    "after": (
        "7. verifying the candidate knowledge state, before activation, by a conjunction of\n"
        "   **candidate-state predicates whose conjunctive acceptance result is invariant\n"
        "   to evaluation order**, comprising: that every classified change is accounted\n"
        "   for by the affected set;\n"
    ),
}


#: The abstract's own wording before and after 2026-08-19. The first states half
#: the narrowing -- true, and missing the half that makes it consequential.
HISTORICAL_PARTIAL_WORDING = {
    "before": (
        "removed the measured runtime/memory ceiling, but eight residual tied assignments\n"
        "were path-dependent across a later revision, so that faster matcher was not\n"
        "promoted.\n"
    ),
    "after": (
        "removed the measured runtime/memory ceiling, but its eight residual divergences\n"
        "were each a `NEW`/`AMBIGUOUS` classification flip, and all eight were measured\n"
        "path-dependent into the following revision.\n"
    ),
}


def partial_form_control(assertions: list[dict[str, Any]]) -> dict[str, Any]:
    a = next((x for x in assertions if x.get("id") == "ASSERT_IDENTITY_EQUIVALENCE"), None)
    if a is None or not a.get("partial_forms"):
        return {"separates": False, "why": "no partial_forms rule to exercise"}
    probe = {**a, "must_appear_in": [], "forbidden_wording": []}
    before = scan(probe, {"manuscript": HISTORICAL_PARTIAL_WORDING["before"]})
    after = scan(probe, {"manuscript": HISTORICAL_PARTIAL_WORDING["after"]})
    return {
        "separates": len(before) == 1 and not after,
        "findings_on_partial_wording": len(before),
        "findings_on_completed_wording": len(after),
        "what_it_proves": (
            "the audit fails on the abstract's own superseded sentence, which contains no "
            "withdrawn term and states the narrowing in part, and passes on the sentence "
            "that replaced it"
        ),
        "what_it_does_not_prove": (
            "nothing about partial statements of assertions that carry no partial_forms "
            "rule -- each has to be written down, and only one is"
        ),
    }


def historical_wording_control(assertions: list[dict[str, Any]]) -> dict[str, Any]:
    gate = next((a for a in assertions if a.get("id") == "ASSERT_GATE_ORDER"), None)
    if gate is None:
        return {"separates": False, "why": "ASSERT_GATE_ORDER is not in the registry"}
    before = scan(gate, {"claim_set": HISTORICAL_GATE_WORDING["before"]})
    after = scan(gate, {"claim_set": HISTORICAL_GATE_WORDING["after"]})
    return {
        "separates": len(before) >= 1 and not after,
        "findings_on_superseded_wording": len(before),
        "findings_on_current_wording": len(after),
        "matched": [f.get("matched", "")[:60] for f in before],
        "what_it_proves": (
            "the registry's live patterns fire on the wording the claim set actually "
            "carried and not on the wording that replaced it -- measured on the real text, "
            "not on a synthetic string chosen to match"
        ),
        "what_it_does_not_prove": (
            "nothing about wording variants neither text contains"
        ),
    }


def main() -> int:
    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    surface_map: dict[str, str] = doc.get("surfaces") or {}
    assertions: list[dict[str, Any]] = doc.get("assertions") or []

    surfaces, missing_surfaces = {}, []
    for name, rel in surface_map.items():
        path = ROOT / rel
        if path.exists():
            surfaces[name] = path.read_text(encoding="utf-8")
        else:
            missing_surfaces.append({"surface": name, "path": rel})

    control = withdrawal_propagation_control()
    historical = historical_wording_control(assertions)
    partial = partial_form_control(assertions)
    findings = hygiene(assertions, set(surface_map))
    for a in assertions:
        findings += scan(a, surfaces)
    for ms in missing_surfaces:
        findings.append({"kind": "SURFACE_MISSING", **ms,
                         "why": "declared in the registry and not on disk"})

    by_status: dict[str, int] = {}
    for a in assertions:
        by_status[str(a.get("status"))] = by_status.get(str(a.get("status")), 0) + 1

    receipt: dict[str, Any] = {
        "schema": "tavonel.assertion-registry-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "registry": REGISTRY.relative_to(ROOT).as_posix(),
        "registry_sha256": "sha256:" + hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
        "surfaces_scanned": sorted(surfaces),
        "surfaces_missing": missing_surfaces,
        "assertions": len(assertions),
        "assertions_by_status": by_status,
        "assertion_ids": [a.get("id") for a in assertions],
        "withdrawal_propagation_control": control,
        "historical_wording_control": historical,
        "partial_form_control": partial,
        "detector_is_live": (
            control["separates"] and historical["separates"] and partial["separates"]
        ),
        "findings": findings,
        "finding_count": len(findings),
        "state": (
            "NOT_RUN" if not (
                control["separates"] and historical["separates"] and partial["separates"]
            )
            else ("CLEAN" if not findings else "FINDINGS")
        ),
        "why_status_not_strings": (
            "The term-level audit asks whether a withdrawn word survived. This asks whether "
            "a surface still asserts something the registry says was narrowed or withdrawn, "
            "and whether an active assertion is still where it is relied on. A surface can "
            "pass the first and fail the second."
        ),
        "scope": (
            "Automated structural and lexical comparison against a declared registry. It "
            "does not read for meaning: a withdrawn proposition restated in wording the "
            "registry never listed passes this audit and is a human read's job."
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"assertions: {len(assertions)}  {by_status}")
    print(f"partial-form control separates: {partial['separates']} "
          f"(partial={partial['findings_on_partial_wording']}, "
          f"completed={partial['findings_on_completed_wording']})")
    print(f"historical wording control separates: {historical['separates']} "
          f"(superseded={historical['findings_on_superseded_wording']}, "
          f"current={historical['findings_on_current_wording']})")
    print(f"control separates: {control['separates']} "
          f"(withdrawn={control['withdrawn_leaves_wording_findings']}, "
          f"absent={control['assertion_absent_findings']}, "
          f"exempted={control['wording_inside_a_prohibition_findings']})")
    for f in findings[:40]:
        loc = f.get("surface", "-")
        line = f":{f['line']}" if "line" in f else ""
        print(f"  {f['kind']:<32} {f.get('assertion', '-'):<28} {loc}{line} "
              f"{f.get('matched', '')}")
    print(f"findings: {len(findings)}  state: {receipt['state']}")
    print(f"wrote {OUTPUT.relative_to(ROOT).as_posix()}")
    return 0 if receipt["state"] == "CLEAN" else 1


if __name__ == "__main__":
    sys.exit(main())
