#!/usr/bin/env python3
"""The gate that proves SFIR9 does not stand on the failed historical chain.

Fifty-nine frozen attestations in this repository no longer match the bytes they
attest to. The founder ruling preserves all of them: they are the evidence of a
reproducibility chain that failed, and repairing them would destroy the record of
the failure. SFIR9's job is not to fix that chain. It is to be a new one that
does not depend on it.

**"Does not depend on it" has to be machine-checkable, or it is a promise.** So
this gate takes SFIR9's declared components and its declared historical inputs
and refuses unless the separation holds:

- no drift-affected receipt is a scientific prerequisite of an SFIR9 gate
- no historical expected SHA certifies a current SFIR9 source file
- no historical frozen attestation stands behind a fresh cohort
- no `latest` / newest-file / glob lookup chooses a scientific authority
- no historical SFI/SFIR spent manifest supplies a fresh held-out cohort

**A drifted filename is not banned forever, and the distinction matters.** If
`tools/root_identity.py` is what SFIR9 needs and it survives a hostile audit,
its *current bytes* can be newly frozen under SFIR9 with a new digest against a
current Git blob. What may not be claimed is continuity: this is not "the old
`root_identity` restored", it is "the current implementation newly frozen for
SFIR9", and the gate records the second phrasing and refuses the first.

**Historical material may still be read, for four purposes and no others** --
background, failure taxonomy, spent-identity exclusion, development fixture --
and each such input must declare its purpose, its digest, that it is not
value-bearing, and why it is not scientific authority.

**The two integrity states are reported side by side and never merged.**
Historical integrity stays FAIL with its drift count and `PRESERVED_FAIL`; SFIR9
integrity is evaluated independently. A historical FAIL does not block an SFIR9
freeze, and an SFIR9 PASS does not repair the historical chain.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V9"
SCHEMA = "tavonel.sfir9.historical_isolation.v1"

REFUSAL = "REFUSED_HISTORICAL_DRIFT_AUTHORITY"

#: The only purposes for which a historical artifact may be read at all. Each
#: one is a use that cannot influence what SFIR9 concludes.
ALLOWED_HISTORICAL_PURPOSES = frozenset(
    {
        "background",
        "failure_taxonomy",
        "spent_identity_exclusion",
        "development_fixture",
    }
)

#: Lookups that choose an artifact by recency or shape rather than by name and
#: digest. Every one of these makes the authority a run selected depend on the
#: state of a directory, which is not something a frozen protocol can pin.
_NONDETERMINISTIC_LOOKUPS = (
    (re.compile(r"\.glob\("), "glob lookup"),
    (re.compile(r"\.rglob\("), "recursive glob lookup"),
    (re.compile(r"\bst_mtime\b"), "newest-by-modification-time lookup"),
    (re.compile(r"""["']latest["']"""), "a 'latest' pointer"),
    (re.compile(r"\bmax\([^)]*key\s*=\s*os\.path\.getmtime"), "newest-file lookup"),
)


class IsolationRefused(RuntimeError):
    """SFIR9 would have rested on the failed historical chain."""

    def __init__(self, message: str) -> None:
        super().__init__(f"{REFUSAL}: {message}")


@dataclass(frozen=True, slots=True)
class HistoricalInput:
    """A historical artifact SFIR9 reads, and the reason that is permissible."""

    path: str
    sha256: str
    purpose: str
    why_not_scientific_authority: str
    value_bearing: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "purpose": self.purpose,
            "value_bearing": self.value_bearing,
            "why_not_scientific_authority": self.why_not_scientific_authority,
        }


@dataclass
class DriftRecord:
    """What the preserved historical-integrity receipt says, read-only."""

    receipt_path: Path
    receipt_sha256: str
    frozen_drift_count: int
    advisory_drift_count: int
    affected_paths: frozenset[str]
    affected_receipts: frozenset[str]
    expected_digests: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "historical_integrity_receipt": self.receipt_path.as_posix(),
            "historical_integrity_receipt_sha256": self.receipt_sha256,
            "historical_frozen_drift_count": self.frozen_drift_count,
            "historical_advisory_drift_count": self.advisory_drift_count,
            "historical_status": "PRESERVED_FAIL",
            "preserved": True,
            "this_gate_never_writes_to_it": (
                "the drift receipt is read for failure taxonomy and exclusion only. "
                "Repairing it would destroy the record of the reproducibility failure "
                "it exists to document."
            ),
        }


def read_drift(receipt_path: Path) -> DriftRecord:
    """Load the preserved drift receipt. Read-only, always."""
    raw = Path(receipt_path).read_bytes()
    body = json.loads(raw.decode("utf-8"))
    frozen = body.get("frozen_drift") or []
    advisory = body.get("advisory_drift") or []
    entries = list(frozen) + list(advisory)
    return DriftRecord(
        receipt_path=Path(receipt_path),
        receipt_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        frozen_drift_count=len(frozen),
        advisory_drift_count=len(advisory),
        affected_paths=frozenset(e["path"] for e in entries if "path" in e),
        affected_receipts=frozenset(e["receipt"] for e in entries if e.get("receipt")),
        expected_digests=frozenset(
            e["expected"] for e in entries if e.get("expected")
        ),
    )


@dataclass
class Sfir9Declaration:
    """What SFIR9 says it is made of, before the gate is allowed to believe it."""

    #: Component name -> source path. Every gate-bearing part of SFIR9.
    components: dict[str, str]
    #: Historical artifacts read, each with a declared non-scientific purpose.
    historical_inputs: list[HistoricalInput] = field(default_factory=list)
    #: Receipts SFIR9 names as scientific prerequisites of its own gates.
    scientific_prerequisites: list[str] = field(default_factory=list)
    #: Digests SFIR9 uses to certify its own source. Must be freshly computed.
    source_digests: dict[str, str] = field(default_factory=dict)
    #: Set true only to claim an SFIR9 component continues a historical pin.
    claims_continuity_with_historical_pin: bool = False


#: The minimum closure. Ten, not eight.
#:
#: The first version omitted the selection rule and this gate itself, which
#: meant the code that decides *which repositories are studied* and the code
#: that decides *whether the study leans on the failed historical chain* could
#: both be changed without the closure noticing. A closure that does not contain
#: its own judgement is not a closure; it is a list of things somebody else
#: checks.
REQUIRED_COMPONENTS = (
    "protocol",
    "execution_closure",
    "historical_isolation_gate",
    "selection_rule",
    "scorer",
    "acceptance",
    "cohort_roster",
    "transport",
    "identity_logic",
    "checkpoint_chain",
)


def evaluate(
    declaration: Sfir9Declaration, drift: DriftRecord, *, root: Path
) -> dict[str, Any]:
    """Refuse, or produce the isolation proof that goes into the freeze receipt."""
    _require_every_component(declaration)
    _require_no_drifted_receipt_as_authority(declaration, drift)
    _require_no_historical_digest_certifies_current_source(declaration, drift)
    _require_no_continuity_claim(declaration)
    _require_historical_inputs_are_declared_non_authoritative(declaration)
    findings = _scan_for_nondeterministic_authority_lookup(declaration, root)
    if findings:
        raise IsolationRefused(
            "an SFIR9 component selects an artifact by recency or shape rather than "
            "by name and digest, so which authority a run uses would depend on the "
            f"state of a directory: {'; '.join(findings)}"
        )
    return proof(declaration, drift)


def _require_every_component(declaration: Sfir9Declaration) -> None:
    missing = [name for name in REQUIRED_COMPONENTS if name not in declaration.components]
    if missing:
        raise IsolationRefused(
            f"the declaration does not name {', '.join(missing)}. A component the "
            "gate never sees is a component whose historical dependencies were "
            "never checked."
        )


def _require_no_drifted_receipt_as_authority(
    declaration: Sfir9Declaration, drift: DriftRecord
) -> None:
    for prerequisite in declaration.scientific_prerequisites:
        name = Path(prerequisite).name
        if name in drift.affected_receipts or prerequisite in drift.affected_paths:
            raise IsolationRefused(
                f"{prerequisite} is named as a scientific prerequisite of an SFIR9 "
                "gate, and it is affected by the preserved historical drift. The "
                "property it would establish must be proven freshly by SFIR9 "
                "instead; the historical receipt is not edited to let it pass."
            )


def _require_no_historical_digest_certifies_current_source(
    declaration: Sfir9Declaration, drift: DriftRecord
) -> None:
    for path, digest in declaration.source_digests.items():
        normalized = digest if digest.startswith("sha256:") else f"sha256:{digest}"
        if normalized in drift.expected_digests:
            raise IsolationRefused(
                f"{path} is certified with {normalized}, which is a historical "
                "*expected* digest from the drift record rather than a digest of the "
                "bytes on disk now. Certifying current source with a historical pin "
                "is how a chain claims a continuity it does not have."
            )


def _require_no_continuity_claim(declaration: Sfir9Declaration) -> None:
    if declaration.claims_continuity_with_historical_pin:
        raise IsolationRefused(
            "the declaration claims continuity with a historical pin. Current bytes "
            "may be newly frozen for SFIR9 -- that is 'the current implementation "
            "newly frozen for SFIR9', not 'the old component restored' -- but the "
            "old pin's authority does not transfer to them."
        )


def _require_historical_inputs_are_declared_non_authoritative(
    declaration: Sfir9Declaration,
) -> None:
    for entry in declaration.historical_inputs:
        if entry.value_bearing:
            raise IsolationRefused(
                f"{entry.path} is declared value-bearing. Historical material may be "
                "read for background, failure taxonomy, spent-identity exclusion or "
                "as a development fixture, and may not bear value."
            )
        if entry.purpose not in ALLOWED_HISTORICAL_PURPOSES:
            raise IsolationRefused(
                f"{entry.path} declares purpose {entry.purpose!r}, which is not one of "
                f"{sorted(ALLOWED_HISTORICAL_PURPOSES)}."
            )
        if not entry.why_not_scientific_authority.strip():
            raise IsolationRefused(
                f"{entry.path} does not say why it is not scientific authority. An "
                "unexplained exemption is the shape every later exemption copies."
            )
        if not entry.sha256.startswith("sha256:"):
            raise IsolationRefused(
                f"{entry.path} is declared without a digest, so which bytes were read "
                "is not recoverable."
            )


#: The name whose assignment holds the patterns above. The scan blanks that one
#: assignment before searching, because this module is itself one of the ten
#: components it scans and the patterns' own definition is not a use of them.
_PATTERN_DEFINITION = "_NONDETERMINISTIC_LOOKUPS"


def _without_the_pattern_definition(text: str) -> str:
    """Blank the assignment that defines the patterns, and nothing else.

    Located structurally, by parsing for a module-level assignment to that one
    name -- not by a marker comment. A comment-based exemption would be a
    mechanism anyone could sprinkle over a real offending line, which is the
    opposite of what a scan is for. This can only ever silence the single
    statement that declares the patterns, in whichever file declares them.

    The lines are replaced with blanks rather than removed so that any line
    number this scan reports still refers to the real file.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    lines = text.splitlines(keepends=True)
    for node in tree.body:
        targets = getattr(node, "targets", [])
        if not isinstance(node, ast.Assign) or not targets:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == _PATTERN_DEFINITION
            for target in targets
        ):
            continue
        for index in range(node.lineno - 1, min(node.end_lineno, len(lines))):
            lines[index] = "\n"
    return "".join(lines)


def _scan_for_nondeterministic_authority_lookup(
    declaration: Sfir9Declaration, root: Path
) -> list[str]:
    """Static scan. Honest about being static.

    This reads source text; it does not prove absence at runtime. It catches the
    shapes that have actually caused this class of failure before, and a
    component that finds a novel way to select an authority by recency will pass
    it. That limitation is recorded in the proof rather than left implied.

    One statement is excluded: the assignment declaring the patterns themselves,
    because this module is one of the ten components it scans and would otherwise
    refuse itself for describing what it looks for.
    """
    findings: list[str] = []
    for name, relative in sorted(declaration.components.items()):
        path = Path(root) / relative
        if not path.is_file():
            raise IsolationRefused(
                f"component {name!r} points at {relative}, which is not a file. A "
                "component that cannot be read cannot be checked."
            )
        text = _without_the_pattern_definition(path.read_text(encoding="utf-8"))
        for pattern, description in _NONDETERMINISTIC_LOOKUPS:
            if pattern.search(text):
                findings.append(f"{name} ({relative}) uses {description}")
    return findings


def proof(declaration: Sfir9Declaration, drift: DriftRecord) -> dict[str, Any]:
    """The block that goes into the SFIR9 freeze receipt."""
    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "HISTORICAL_INSTRUMENT_INTEGRITY": {
            "state": "FAIL",
            **drift.as_dict(),
        },
        "SFIR9_PROSPECTIVE_INTEGRITY": {
            "state": "INDEPENDENTLY_EVALUATED",
            "sfir9_historical_authority_dependencies": [],
            "components": dict(sorted(declaration.components.items())),
            "sfir9_source_hashes": dict(sorted(declaration.source_digests.items())),
            "historical_inputs": [e.as_dict() for e in declaration.historical_inputs],
        },
        "the_two_states_are_not_merged": (
            "historical integrity is FAIL and preserved; SFIR9 integrity is evaluated "
            "on its own evidence. A historical FAIL does not block an SFIR9 freeze, "
            "and an SFIR9 PASS does not repair the historical V2R4/SFIR1/2/3/SFI "
            "chain. Reporting one number for both would hide whichever is worse."
        ),
        "what_this_gate_does_not_establish": (
            "the lookup scan is static: it reads source text for the shapes that have "
            "caused this failure before and cannot prove that no component selects an "
            "authority by recency at runtime. It is a control, not a proof."
        ),
        "the_one_statement_the_scan_excludes": (
            "the assignment that declares the patterns themselves. This gate is one "
            "of the ten components it scans, and without that exclusion it would "
            "refuse itself for naming the shapes it looks for. The exclusion is "
            "located by parsing for that single module-level assignment, not by a "
            "marker comment -- a comment-based exemption would be a mechanism anyone "
            "could put on a real offending line."
        ),
    }
