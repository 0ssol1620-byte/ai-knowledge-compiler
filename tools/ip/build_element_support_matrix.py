#!/usr/bin/env python3
"""Which claim element is supported by which evidence, element by element.

The claim-evidence matrix binds an evidence claim to a patent *family* in a
free-text `patent` field. That is the right granularity for a paper and the wrong
one for prosecution: an examiner reads limitations, and a §112 objection lands on
an element, not on a family.

This parses each claim's elements and each claim's `**Evidence:**` block, and
reports per element: which evidence claims name it, their status, and whether any
does. An element no evidence claim names is reported `UNSUPPORTED` -- which is a
statement about the *record*, not a statement that the element is unsupportable.
Support may well exist and be unwritten; that is exactly the thing worth knowing
before a filing.

Dependent claims carry a single `**Evidence:**` line covering the claim as a
whole; they are single-limitation claims and are treated as one element.

**What this does not do.** It does not read the evidence and judge whether it
actually supports the limitation. It reports whether a binding was *written
down*, which is the mechanical half. The judgement half is a human read and is
recorded as such.
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
CLAIM_SET = ROOT / "docs" / "ip" / "PATENT_CLAIM_SET_v1_2026-08-19.md"
MATRIX = ROOT / "docs" / "ip" / "claim-evidence-matrix.yaml"
BINDINGS = ROOT / "docs" / "ip" / "ELEMENT_SUPPORT_BINDINGS.yaml"

#: Support states an explicit binding may declare. Ordered weakest-first so a
#: reader can see that IMPLEMENTED_ONLY is not a synonym for supported.
BINDING_STATES = ("SPEC_SUPPORT_NEEDED", "IMPLEMENTED_ONLY", "PARTIALLY_SUPPORTED",
                  "ELEMENT_BOUND")
REQUIRED_BINDING_FIELDS = ("claim_language", "specification", "implementation",
                           "evidence_class", "limitation", "unsupported_breadth",
                           "support")
OUTPUT = ROOT / "docs" / "ip" / "receipts" / "element-support-matrix-2026-08-19.json"

CLAIM_HEAD = re.compile(r"^#{2,4}\s+Claim\s+([AB]\d+)\b(.*)$", re.M)
ELEMENT = re.compile(r"^(\d+)\.\s+(.+?)(?=^\d+\.\s|\Z)", re.M | re.S)
# A hyphen is required. Every evidence-claim id and every experiment id carries
# one; bare uppercase words in backticks are code literals -- `AMBIGUOUS` is a
# classification value the claim recites, not a citation, and was being counted
# as a dangling evidence reference.
EVIDENCE_REF = re.compile(r"`([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)`")
ELEMENT_REF = re.compile(r"elements?\s+([\d,\s and]+?)(?=:|\s*[-—])", re.I)


#: Prose that binds an element to the implementation rather than to a measured
#: evidence claim. It is a real and openly stated evidence class -- an
#: embodiment-supported dependent claim -- and reporting it as unevidenced
#: overstates the gap.
EMBODIMENT = re.compile(r"implemented and unit-tested|embodiment-supported", re.I)


def load_bindings() -> tuple[dict[tuple[str, int], dict[str, Any]], list[dict[str, Any]]]:
    """Explicit element-level bindings, validated rather than believed.

    A binding that names a specification section, an implementation path or an
    evidence path that does not exist is a claim about the record that the record
    does not support -- which is the whole defect this pass exists to catch, so it
    is rejected here rather than counted as a binding.
    """
    if not BINDINGS.exists():
        return {}, []
    doc = yaml.safe_load(BINDINGS.read_text(encoding="utf-8")) or {}
    out: dict[tuple[str, int], dict[str, Any]] = {}
    problems: list[dict[str, Any]] = []
    for row in doc.get("bindings") or []:
        key = (str(row.get("claim")), int(row.get("element", 0)))
        missing = [f for f in REQUIRED_BINDING_FIELDS if not row.get(f)]
        if missing:
            problems.append({"kind": "BINDING_INCOMPLETE", "claim": key[0],
                             "element": key[1], "missing_fields": missing,
                             "why": "an incomplete binding is not a binding"})
            continue
        if row["support"] not in BINDING_STATES:
            problems.append({"kind": "BINDING_BAD_SUPPORT_STATE", "claim": key[0],
                             "element": key[1], "value": row["support"],
                             "allowed": list(BINDING_STATES)})
            continue
        impl = str(row["implementation"]).split(" (")[0]
        if not (ROOT / impl).exists():
            problems.append({"kind": "BINDING_IMPLEMENTATION_PATH_ABSENT", "claim": key[0],
                             "element": key[1], "path": impl})
            continue
        ev = row.get("evidence")
        if ev and not (ROOT / ev).exists():
            problems.append({"kind": "BINDING_EVIDENCE_PATH_ABSENT", "claim": key[0],
                             "element": key[1], "path": ev})
            continue
        if row["support"] == "ELEMENT_BOUND" and not ev:
            problems.append({
                "kind": "BINDING_CLAIMS_ELEMENT_BOUND_WITHOUT_EVIDENCE",
                "claim": key[0], "element": key[1],
                "why": ("ELEMENT_BOUND asserts a receipt records this limitation's own "
                        "observable. With no evidence path the correct state is "
                        "IMPLEMENTED_ONLY or SPEC_SUPPORT_NEEDED.")})
            continue
        out[key] = row
    return out, problems


def experiment_exists(ident: str) -> bool:
    """A citation into the experiment namespace, exact or by family prefix.

    `H1-E-IDENTITY-SCALABILITY-01` names a directory. `H1-K` and `H1-L` name
    experiment *families* in prose. Neither is an evidence-claim id and neither
    is dangling; treating them as dangling turned legitimate citations into
    findings.
    """
    base = ROOT / "research" / "experiments"
    if (base / ident).is_dir():
        return True
    return any(d.name.startswith(ident + "-") for d in base.iterdir() if d.is_dir())


def sections(text: str) -> list[tuple[str, str, str]]:
    """(claim id, heading tail, body up to the next claim heading)."""
    heads = list(CLAIM_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((m.group(1), m.group(2), text[m.end() : end]))
    return out


def parse_elements(body: str) -> list[dict[str, Any]]:
    stop = body.find("**Evidence:**")
    recital = body[:stop] if stop != -1 else body
    found = [
        {"n": int(m.group(1)), "text": re.sub(r"\s+", " ", m.group(2)).strip()[:240]}
        for m in ELEMENT.finditer(recital)
    ]
    if found:
        return found
    return [{"n": 1, "text": re.sub(r"\s+", " ", recital).strip()[:240], "single": True}]


def parse_support(body: str) -> tuple[dict[int, list[str]], list[str]]:
    """Element number -> evidence ids, plus ids named without an element."""
    start = body.find("**Evidence:**")
    if start == -1:
        return {}, []
    block = body[start:]
    end = block.find("\n\n> ")
    if end != -1:
        block = block[:end]

    # Split on bullets, not on physical lines: a bullet wraps, and reading line by
    # line stranded the second id of "elements 7, 8, 9: `A`, and `B`" as unscoped.
    bullets, buf = [], []
    for line in block.splitlines():
        if line.lstrip().startswith("- "):
            if buf:
                bullets.append(" ".join(buf))
            buf = [line.strip()]
        elif buf:
            buf.append(line.strip())
        else:
            bullets.append(line.strip())
    if buf:
        bullets.append(" ".join(buf))

    per_element: dict[int, list[str]] = {}
    unscoped: list[str] = []
    for bullet in bullets:
        ids = EVIDENCE_REF.findall(bullet)
        if not ids:
            continue
        m = ELEMENT_REF.search(bullet)
        if m:
            for n in (int(x) for x in re.findall(r"\d+", m.group(1))):
                per_element.setdefault(n, []).extend(ids)
        else:
            unscoped.extend(ids)
    return per_element, unscoped


def main() -> int:
    text = CLAIM_SET.read_text(encoding="utf-8")
    bindings, binding_problems = load_bindings()
    matrix = yaml.safe_load(MATRIX.read_text(encoding="utf-8")) or {}
    status_of = {c.get("id"): c.get("status") for c in (matrix.get("claims") or [])}

    findings: list[dict[str, Any]] = []
    claims_out: list[dict[str, Any]] = []

    for cid, tail, body in sections(text):
        reserved = "RESERVED" in tail or "NOT SUPPORTED" in tail
        elements = parse_elements(body)
        per_element, unscoped = parse_support(body)
        multi = len(elements) > 1

        rows = []
        for e in elements:
            explicit = bindings.get((cid, e["n"]))
            own = sorted(set(per_element.get(e["n"], [])))
            # Three states, not two. A multi-element claim whose Evidence block
            # names ids without scoping them to elements has bound the claim as a
            # whole -- weaker than an element binding for Sec.112, and not the
            # same as no evidence. Calling that UNSUPPORTED reported seven of A1's
            # elements as unevidenced when the claim carries a CONFIRMATORY result.
            if own:
                support = "ELEMENT_BOUND"
                ids = own
            elif unscoped:
                support = "CLAIM_LEVEL_ONLY" if multi else "ELEMENT_BOUND"
                ids = sorted(set(unscoped))
            elif EMBODIMENT.search(body[body.find("**Evidence:**"):]) if (
                "**Evidence:**" in body
            ) else False:
                support = "EMBODIMENT_ONLY"
                ids = []
            else:
                support = "UNSUPPORTED"
                ids = []
            unknown = [i for i in ids if i not in status_of and not experiment_exists(i)]
            experiments = [i for i in ids if i not in status_of and experiment_exists(i)]
            rows.append({
                "element": e["n"], "recital": e["text"],
                "evidence": ids,
                "evidence_status": {i: status_of.get(i) for i in ids},
                "support": support,
                "experiment_references": experiments,
                "evidence_not_in_matrix": unknown,
            })
            if explicit:
                # An explicit binding overrides the parse -- in both directions.
                # It can raise a CLAIM_LEVEL_ONLY row to ELEMENT_BOUND when a
                # receipt really does record that limitation, and it can lower a
                # row the parser thought was bound. Lowering is the point: the
                # instruction was to classify down where support is absent, not
                # to relabel claim-level evidence as element evidence.
                support = explicit["support"]
                rows[-1].update({
                    "support": support,
                    "explicit_binding": True,
                    "specification": explicit["specification"],
                    "implementation": explicit["implementation"],
                    "bound_evidence": explicit.get("evidence"),
                    "evidence_class": explicit["evidence_class"],
                    "limitation": explicit["limitation"],
                    "unsupported_breadth": explicit["unsupported_breadth"],
                    "counsel_flag": bool(explicit.get("counsel_flag")),
                })
                if support != "ELEMENT_BOUND":
                    findings.append({
                        "kind": f"ELEMENT_{support}",
                        "claim": cid, "element": e["n"],
                        "recital": e["text"][:160],
                        "why": explicit["limitation"],
                        "unsupported_breadth": explicit["unsupported_breadth"],
                        "counsel_flag": bool(explicit.get("counsel_flag")),
                        # A RESERVED claim declaring IMPLEMENTED_ONLY is doing what
                        # the vocabulary asks of it. It is not in the filing core, so
                        # there is no work owed before filing -- calling it
                        # MAJOR_BEFORE_FILING made the disclosure look like a blocker
                        # and buried the rows that really are one. The finding stays
                        # visible; only its severity reflects that it is a held claim.
                        "severity": (
                            "DISCLOSED_RESERVED_NOT_IN_FILING_CORE" if reserved
                            else ("MAJOR_BEFORE_FILING"
                                  if support in ("SPEC_SUPPORT_NEEDED", "IMPLEMENTED_ONLY")
                                  else "MINOR_EVIDENCE_CLASS")
                        ),
                        "reserved": reserved,
                    })
                continue

            if support == "EMBODIMENT_ONLY":
                findings.append({
                    "kind": "ELEMENT_SUPPORTED_BY_EMBODIMENT_ONLY",
                    "claim": cid, "element": e["n"], "recital": e["text"][:160],
                    "why": (
                        "the Evidence block cites the implementation and its unit tests "
                        "rather than a measured evidence claim. That is a stated and "
                        "legitimate class for a dependent claim, and it is a weaker record "
                        "than a bound receipt -- recorded so the difference is visible "
                        "before filing, not asserted as a defect."
                    ),
                    "severity": "MINOR_EVIDENCE_CLASS",
                })
            if support == "CLAIM_LEVEL_ONLY":
                findings.append({
                    "kind": "ELEMENT_BOUND_ONLY_AT_CLAIM_LEVEL",
                    "claim": cid, "element": e["n"], "recital": e["text"][:160],
                    "evidence": ids,
                    "why": (
                        "the Evidence block names evidence for the claim without scoping it "
                        "to elements. An examiner objects to a limitation, and a claim-level "
                        "citation does not say which limitation the evidence reaches."
                    ),
                    "severity": "MINOR_RECORD_GRANULARITY",
                })
            if support == "UNSUPPORTED" and not reserved:
                findings.append({
                    "kind": "ELEMENT_WITHOUT_NAMED_EVIDENCE",
                    "claim": cid, "element": e["n"], "recital": e["text"][:160],
                    "why": (
                        "the claim's Evidence block names no evidence for this element. "
                        "That is a statement about the record, not about the element: "
                        "support may exist and be unwritten. An examiner reads limitations, "
                        "so an unwritten binding is where a Sec.112 objection lands."
                    ),
                    "severity": "MAJOR_BEFORE_FILING",
                })
            for i in unknown:
                findings.append({
                    "kind": "EVIDENCE_ID_NOT_IN_MATRIX",
                    "claim": cid, "element": e["n"], "evidence": i,
                    "why": (
                        "the claim set cites this identifier, the claim-evidence matrix does "
                        "not carry it, and no experiment directory of that name exists, so "
                        "its status and limitations are unbound"
                    ),
                })

        claims_out.append({
            "claim": cid, "reserved": reserved, "elements": len(elements),
            "multi_element": multi, "unscoped_evidence": sorted(set(unscoped)),
            "rows": rows,
            "explicitly_bound": sum(1 for r in rows if r.get("explicit_binding")),
            "element_bound": sum(1 for r in rows if r["support"] == "ELEMENT_BOUND"),
            "embodiment_only": sum(1 for r in rows if r["support"] == "EMBODIMENT_ONLY"),
            "claim_level_only": sum(1 for r in rows if r["support"] == "CLAIM_LEVEL_ONLY"),
            "unsupported": sum(1 for r in rows if r["support"] == "UNSUPPORTED"),
        })

    control = self_control(status_of)
    findings.extend(binding_problems)
    total = sum(c["elements"] for c in claims_out)
    unsupported = sum(c["unsupported"] for c in claims_out)

    receipt: dict[str, Any] = {
        "schema": "tavonel.element-support-matrix.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "claim_set_sha256": "sha256:" + hashlib.sha256(CLAIM_SET.read_bytes()).hexdigest(),
        "claims": claims_out,
        "elements_total": total,
        "elements_unsupported": unsupported,
        "coverage_note": (
            "Coverage is over bindings that were written down in the claim set's Evidence "
            "blocks. It is not a judgement that the named evidence supports the limitation "
            "-- that reading is not automatable and is not claimed here."
        ),
        "detector_control": control,
        "detector_is_live": control["separates"],
        "findings": findings,
        "finding_count": len(findings),
        "state": (
            "NOT_RUN" if not control["separates"]
            else ("CLEAN" if not findings else "FINDINGS")
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for c in claims_out:
        flag = "" if not c["unsupported"] else f"  <-- {c['unsupported']} unsupported"
        print(f"  {c['claim']:<4} elements={c['elements']:<2} "
              f"element_bound={c['element_bound']} claim_level={c['claim_level_only']}{flag}")
    print(f"control separates: {control['separates']}")
    for f in findings[:20]:
        print(f"  {f['kind']:<32} {f['claim']} element {f.get('element')}")
    print(f"elements: {total}  unsupported: {unsupported}  state: {receipt['state']}")
    print(f"wrote {OUTPUT.relative_to(ROOT).as_posix()}")
    return 0 if receipt["state"] == "CLEAN" else 1


def self_control(status_of: dict[str, Any]) -> dict[str, Any]:
    """The parser must find support where it exists and miss it where it does not."""
    supported = (
        "1. doing a thing;\n2. doing another thing;\n\n"
        "**Evidence:**\n- elements 1, 2: `B-EQUIV-FRESH-HOLDOUT` — controlled\n"
    )
    partial = (
        "1. doing a thing;\n2. doing another thing;\n\n"
        "**Evidence:**\n- element 1: `B-EQUIV-FRESH-HOLDOUT` — controlled\n"
    )
    a, _ = parse_support(supported)
    b, _ = parse_support(partial)
    return {
        "separates": sorted(a) == [1, 2] and sorted(b) == [1],
        "both_elements_bound": sorted(a),
        "one_element_bound": sorted(b),
        "what_it_proves": (
            "the Evidence-block parser attributes an id to every element a line names and "
            "to no element it does not, so an UNSUPPORTED row means the binding is absent "
            "rather than unparsed"
        ),
        "what_it_does_not_prove": (
            "nothing about whether the named evidence supports the limitation, and nothing "
            "about support written somewhere other than the Evidence block"
        ),
    }


if __name__ == "__main__":
    sys.exit(main())
