#!/usr/bin/env python3
"""Executable checks for six of `freeze_sfi3_protocol.py`'s pre-freeze
conditions that were `UNVERIFIABLE` placeholders.

`UNVERIFIABLE` blocks the freeze exactly as `FAIL` does, and the correct
response to an uncheckable condition is to build the check, never to lower
the bar (see `freeze_sfi3_protocol.py`'s own module docstring, INC-V2-041).
Each function here returns the same `{"verdict": ..., "detail": ..., ...}`
shape `freeze_sfi3_protocol.Check` expects, is wired into that module's
`CONDITION_CHECKS`, and is independently testable: every one accepts the
paths or data it reads as optional keyword arguments so a test can point it
at a small fixture instead of the real, multi-gigabyte repository state.

Every check is read-only. None of them ever open fresh SFI3 revision
content -- checks 5 and 6 read lineage *identity* metadata only, streamed
through `json.load(..., object_hook=...)` the same way
`acquisition/sources_sfi3.py` itself does, because the acquisition artifacts
these checks and that module both read are tens to ~100 MB each and holding
one whole in memory has already produced a `MemoryError` failure in this
suite (see the founder's routing note for this session).

    1. causal_wording_consistency               -- INC-V2-041's four
                                                     generalisations must not
                                                     reappear unqualified.
    2. incident_cross_reference_coherence        -- every INC-V2-NNN cited
                                                     anywhere resolves to a
                                                     ledger heading; no
                                                     unmarked duplicate
                                                     declaration; no gap.
    3. dynamic_include_target_closure            -- every INCLUDE_TARGET
                                                     extractor either routes
                                                     through the frozen
                                                     taxonomy or is excluded
                                                     by an executable scope
                                                     gate.
    4. artifact_facet_fingerprint_propagation    -- for each declared
                                                     channel, does a change to
                                                     only that facet move the
                                                     production artifact
                                                     digest?
    5. fresh_frame_disjointness                  -- declared roots and any
                                                     sealed frame are disjoint
                                                     from the spent set.
    6. sfi2_forensic_lineages_excluded           -- the 14 pinned SFI2 E5/E6
                                                     forensic lineages are all
                                                     in SFI3's spent set.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "acquisition"),
    str(NS / "compiler"),
    str(NS / "canonicalization"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from common import rel  # noqa: E402

#: Matches `freeze_sfi3_protocol.CONDITION_MET` / `CONDITION_FAILED` /
#: `UNVERIFIABLE` by value rather than by import, so this module has no
#: import-time dependency on the gate module (the gate imports this one).
PASS = "PASS"  # noqa: S105 -- a status label, not a credential
FAIL = "FAIL"
UNVERIFIABLE = "UNVERIFIABLE"

__all__ = [
    "causal_wording_consistency",
    "incident_cross_reference_coherence",
    "dynamic_include_target_closure",
    "artifact_facet_fingerprint_propagation",
    "fresh_frame_disjointness",
    "sfi2_forensic_lineages_excluded",
    "receipt_pointer_targets_are_recoverable",
]


# ---------------------------------------------------------------------------
# shared: which files these text-scanning checks read

_SCAN_EXTENSIONS = (".py", ".md", ".yaml", ".yml")

#: Directories that are either frozen historical evidence (receipts,
#: forensic_snapshots), pure data too large to scan as prose (artifacts is
#: ~2.9 GB), or tooling caches. Excluded from both text-scanning checks
#: (causal wording, incident cross-references) for the same reason: none of
#: them is living prose a lane edits, so a reappearance of stale wording
#: there is neither fixable nor meaningful, and scanning `artifacts/` as text
#: would be prohibitively slow for no signal.
_EXCLUDE_DIR_NAMES = frozenset(
    {
        "receipts",
        "artifacts",
        "forensic_snapshots",
        ".hybrid-agent",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "node_modules",
        ".git",
    }
)

#: This module's own source and its test contain the detection patterns and
#: fixture text as literal strings, by necessity -- excluded from a real scan
#: of NS so the checks below can never trip over their own implementation.
_SELF_FILES = frozenset(
    {
        (NS / "tools" / "preflight_checks.py").resolve(),
        (NS / "tests" / "test_preflight_checks.py").resolve(),
    }
)


def _iter_text_files(root: Path) -> list[Path]:
    """Every scannable file under `root`, with excluded directories skipped.

    Exclusions are matched against the path RELATIVE TO `root`, not against its
    absolute parts. Matching absolutely meant a scan rooted anywhere beneath a
    directory whose name is on the exclusion list — `artifacts/`, say — excluded
    every file it was pointed at and returned nothing. The check then reported
    PASS because it had scanned zero files, which is the failure mode this whole
    programme exists to eliminate: a clean answer from an instrument that never
    looked. It also made the check untestable, since any fixture written inside
    the repository tree lands under `artifacts/`.
    """
    if not root.exists():
        return []
    root = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
            continue
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:  # pragma: no cover - rglob cannot leave its root
            continue
        if any(part in _EXCLUDE_DIR_NAMES for part in relative.parts):
            continue
        if path.resolve() in _SELF_FILES:
            continue
        files.append(path)
    return sorted(files)


def _rel_or_str(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# 1. causal wording consistency


#: Phrases from four generalisations INC-V2-037 withdrew, built from the
#: *shape* of the story rather than one fixed sentence: the wording drifted
#: across files ("cross-check was clean" vs. "reported clean", "named every
#: moved artifact" vs. "every moved artifact named"). Matching only one exact
#: sentence would be as narrow and gameable as the `UNVERIFIABLE` placeholder
#: this check replaces.
_STALE_STORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cross_check_was_clean",
        re.compile(r"typed\s+cross-check\s+(?:was|reported)\s+clean", re.IGNORECASE),
    ),
    (
        "named_every_moved_artifact",
        re.compile(
            r"named\s+every\s+moved\s+artifact|every\s+moved\s+artifact\s+named",
            re.IGNORECASE,
        ),
    ),
    (
        "delta_knew_what_had_to_be_rebuilt",
        re.compile(
            r"typed\s+(?:delta|cross-check)\s+knew\s+(?:exactly\s+)?what\s+had\s+to\s+be\s+rebuilt",
            re.IGNORECASE,
        ),
    ),
    (
        "defect_in_execution_not_ir",
        re.compile(r"defect\s+is\s+in\s+execution,?\s+not\s+in\s+the\s+IR", re.IGNORECASE),
    ),
)

#: Any of these appearing in the qualifying window means the sentence is the
#: corrected reading, not the withdrawn one. Drawn from the actual corrections
#: on record (`compiler/execution_invariant.py`, `protocols
#: /SOURCE_FACT_IR_HELDOUT_V3.yaml`, `paper/CLAIM_MATRIX.yaml`,
#: `paper/TAVONEL_PAPER_DRAFT_INTERNAL.md`, `incident_ledger.md` INC-V2-037).
_QUALIFIER_MARKERS: tuple[str, ...] = (
    "only over its own downstream denominator",
    "does not mean",
    "is not evidence",
    "never verifies",
    "downstream of",
    "upstream of",
    "withdrawn",
    "narrower than the obvious",
    "did not name",
)

_LEDGER_NAME = "incident_ledger.md"


def causal_wording_consistency(*, scan_root: Path | None = None) -> dict[str, Any]:
    """The withdrawn causal story must not reappear unqualified.

    `NS/receipts/**` is excluded: it is immutable, historical evidence and is
    never edited in place, so a phrase frozen inside a receipt cannot be
    "corrected" and scanning it would only ever produce an unfixable finding.

    `NS/incident_ledger.md` is NOT excluded, deliberately. It is append-only
    and its historical entries legitimately quote the old wording while
    marking it withdrawn -- excluding the whole file would make this check
    unable to catch a new entry that reintroduces the story without a
    correction. Instead, a match inside the ledger is a violation only if
    none of `_QUALIFIER_MARKERS` appears anywhere in the ledger text AT OR
    AFTER that match: the ledger is append-only, so a correction for an
    earlier entry always comes strictly later in the file, and a genuinely
    new, unmarked violation has nothing after it to exonerate it. A match in
    any other scanned file is a violation only if no marker appears anywhere
    in that same file.
    """
    root = scan_root if scan_root is not None else NS
    violations: list[dict[str, Any]] = []
    scanned = 0

    for path in _iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            violations.append({"file": _rel_or_str(path), "error": f"unreadable: {error}"})
            continue
        scanned += 1
        lower = text.lower()
        is_ledger = path.name == _LEDGER_NAME
        for name, pattern in _STALE_STORY_PATTERNS:
            for match in pattern.finditer(text):
                window = lower[match.start() :] if is_ledger else lower
                if any(marker in window for marker in _QUALIFIER_MARKERS):
                    continue
                line_no = text.count("\n", 0, match.start()) + 1
                snippet = text[max(0, match.start() - 40) : match.end() + 40].replace("\n", " ")
                violations.append(
                    {
                        "file": _rel_or_str(path),
                        "pattern": name,
                        "line": line_no,
                        "snippet": snippet.strip(),
                    }
                )

    return {
        "verdict": FAIL if violations else PASS,
        "detail": (
            f"{len(violations)} unqualified reappearance(s) across {scanned} scanned file(s)"
            if violations
            else f"no unqualified reappearance found across {scanned} scanned file(s)"
        ),
        "violations": violations,
        "excluded": [
            "NS/receipts/** (immutable historical evidence)",
            "this module and its test (self-referential pattern/fixture text)",
        ],
    }


# ---------------------------------------------------------------------------
# 2. incident cross-reference coherence


_INC_REF_RE = re.compile(r"\bINC-V2-(\d+)\b")
_INC_HEADING_RE = re.compile(r"^##\s+INC-V2-(\d+)\b(.*)$", re.MULTILINE)

#: A heading for a number already seen is a legitimate follow-up, not a
#: duplicate declaration, when its own suffix names itself as one -- the real
#: ledger does this repeatedly (e.g. "INC-V2-001 -- update, 2026-08-21: ...",
#: "... -- restoration event, ...").
_LEDGER_CONTINUATION_MARKERS = ("update", "note", "correction", "restoration event")


def incident_cross_reference_coherence(
    *, ledger_path: Path | None = None, scan_root: Path | None = None
) -> dict[str, Any]:
    """Every `INC-V2-NNN` cited anywhere resolves to a ledger heading; no
    unmarked duplicate declaration; the declared numbering has no gap.

    References are searched under the same root and exclusions as
    `causal_wording_consistency` (see that function for why `receipts/` and
    `artifacts/` are out of scope). `STOP-V2-NNN` is a distinct numbering
    series in the same ledger and is not part of this check.
    """
    ledger = ledger_path if ledger_path is not None else (NS / _LEDGER_NAME)
    root = scan_root if scan_root is not None else NS

    if not ledger.exists():
        return {"verdict": FAIL, "detail": f"{_rel_or_str(ledger)} does not exist"}

    ledger_text = ledger.read_text(encoding="utf-8")
    headings = [
        (int(match.group(1)), match.group(2).strip())
        for match in _INC_HEADING_RE.finditer(ledger_text)
    ]
    declared_numbers = sorted({number for number, _ in headings})
    declared_set = set(declared_numbers)

    first_seen: set[int] = set()
    duplicates: list[dict[str, Any]] = []
    for number, suffix in headings:
        if number not in first_seen:
            first_seen.add(number)
            continue
        if not any(marker in suffix.lower() for marker in _LEDGER_CONTINUATION_MARKERS):
            duplicates.append({"number": number, "suffix": suffix})

    gaps = (
        [n for n in range(declared_numbers[0], declared_numbers[-1] + 1) if n not in declared_set]
        if declared_numbers
        else []
    )

    referenced: dict[int, list[str]] = {}
    for path in _iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _INC_REF_RE.finditer(text):
            referenced.setdefault(int(match.group(1)), []).append(_rel_or_str(path))

    unresolved = [
        {"number": number, "referenced_from": sorted(set(files))[:5]}
        for number, files in sorted(referenced.items())
        if number not in declared_set
    ]

    failed = bool(duplicates or gaps or unresolved)
    return {
        "verdict": FAIL if failed else PASS,
        "detail": (
            f"{len(declared_numbers)} distinct INC-V2 number(s) declared; "
            f"{len(duplicates)} unmarked duplicate declaration(s), {len(gaps)} numbering "
            f"gap(s), {len(unresolved)} unresolved reference(s)"
        ),
        "duplicate_declarations": duplicates,
        "numbering_gaps": gaps,
        "unresolved_references": unresolved,
        "declared_numbers": declared_numbers,
    }


# ---------------------------------------------------------------------------
# 3. dynamic include-target closure


_INCLUDE_TARGET_TAXONOMY_ENTRYPOINT = "classify_include_expression"

#: The two SourceFact-constructor names `source_fact_ir/reference.py`'s
#: extractors call to emit a fact -- see `_fact`/`_target_fact` there.
_FACT_CONSTRUCTOR_NAMES = frozenset({"_fact", "_target_fact"})


def _include_target_constructs(reference_path: Path) -> dict[str, bool]:
    """Every INCLUDE_TARGET *construct id* `reference_path`'s extractors can
    produce (the string literal `reference.py` itself passes as the second
    argument to `_fact(INCLUDE_TARGET, "html-include-src", ...)` /
    `_target_fact(...)` -- the same id `source_fact_ir.scope_gate` keys its
    `CONSTRUCT_SCOPES` by), mapped to whether that construct routes through
    the frozen taxonomy (`classify_include_expression` called anywhere in the
    enclosing function).

    Found by parsing the module's AST rather than hardcoding today's four
    construct ids, so a fifth construct added later is picked up without
    editing this file.
    """
    tree = ast.parse(reference_path.read_text(encoding="utf-8"), filename=str(reference_path))
    result: dict[str, bool] = {}
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef) or not func.name.startswith("_extract_"):
            continue
        names_in_func = {child.id for child in ast.walk(func) if isinstance(child, ast.Name)}
        routed = _INCLUDE_TARGET_TAXONOMY_ENTRYPOINT in names_in_func
        for call in ast.walk(func):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if call.func.id not in _FACT_CONSTRUCTOR_NAMES or len(call.args) < 2:
                continue
            kind_arg, construct_arg = call.args[0], call.args[1]
            if not (isinstance(kind_arg, ast.Name) and kind_arg.id == "INCLUDE_TARGET"):
                continue
            if isinstance(construct_arg, ast.Constant) and isinstance(construct_arg.value, str):
                construct = construct_arg.value
                result[construct] = routed or result.get(construct, False)
    return result


def _load_scope_gate_module(gate_path: Path) -> Any:
    """Import `gate_path` as a module.

    When `gate_path` is the real, on-disk `source_fact_ir/scope_gate.py`,
    this is a normal package import, so its own `from source_fact_ir import
    ir` absolute imports resolve exactly as they do for every other importer
    of that package. For a test fixture at a different path, falls back to
    `importlib.util.spec_from_file_location` -- registering the module in
    `sys.modules` under its own spec name *before* `exec_module`, which a
    module defining a `@dataclass` needs: `dataclasses._is_type` looks the
    class's defining module up in `sys.modules` by name, and an
    unregistered module fails there with an `AttributeError` that has
    nothing to do with this check's own logic.
    """
    real_path = (NS / "source_fact_ir" / "scope_gate.py").resolve()
    if gate_path.resolve() == real_path:
        import source_fact_ir.scope_gate as real_module

        return real_module

    spec = importlib.util.spec_from_file_location("_preflight_scope_gate_probe", gate_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{gate_path} could not be loaded as a module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def dynamic_include_target_closure(
    *, scope_gate_path: Path | None = None, reference_path: Path | None = None
) -> dict[str, Any]:
    """Every production INCLUDE_TARGET construct routes through
    `source_fact_ir.include_target.classify_include_expression`, or is
    proven safe another way by the executable scope gate at
    `source_fact_ir/scope_gate.py`.

    That module (built by another lane; read here, never edited) does not
    "exclude" a construct from scoring -- every declared construct really is
    in the scored path (its own `is_in_scored_path` proves that
    behaviourally). What it proves instead, per unrouted construct, is that a
    computed-or-malformed input can never reach a `REPRESENTED` fact anyway,
    by a fixture battery or a structural argument. This check therefore
    treats an unrouted construct as covered only if (a) the gate declares a
    scope claim for it in `INCLUDE_TARGET_CONSTRUCTS` and (b) the gate's own
    `prove_scope()` -- which raises on any failed proof rather than
    swallowing one into a summary row -- completes without raising and
    includes that construct in its result.

    If `source_fact_ir/scope_gate.py` does not exist at all, absence is a
    definite negative, not `UNVERIFIABLE`: "no gate exists" is a fully
    decided fact, unlike "what would the gate decide".
    """
    gate_path = (
        scope_gate_path
        if scope_gate_path is not None
        else (NS / "source_fact_ir" / "scope_gate.py")
    )
    ref_path = (
        reference_path if reference_path is not None else (NS / "source_fact_ir" / "reference.py")
    )

    if not ref_path.exists():
        return {"verdict": FAIL, "detail": f"{_rel_or_str(ref_path)} does not exist"}

    constructs = _include_target_constructs(ref_path)
    unrouted = sorted(name for name, routed in constructs.items() if not routed)

    if not constructs:
        #: An existing module that yields no construct at all means the AST scan
        #: watched nothing, not that the module is clean. Passing here would make
        #: this check green in exactly the case where it has stopped working.
        return {
            "verdict": FAIL,
            "detail": (
                f"{_rel_or_str(ref_path)} exists but yielded no INCLUDE_TARGET construct; "
                f"the scan covered nothing, which is not the same as covering nothing unsafe"
            ),
            "constructs": constructs,
            "unrouted": unrouted,
        }

    if not unrouted:
        #: Every construct routes through the frozen taxonomy, so a
        #: computed-or-malformed target already fails closed there. The scope
        #: gate exists only to cover constructs that do NOT route; with none to
        #: cover, its absence decides nothing. Asked BEFORE the existence branch
        #: below, which would otherwise block on a missing gate that has no work.
        return {
            "verdict": PASS,
            "detail": (
                f"all {len(constructs)} INCLUDE_TARGET construct(s) route through "
                f"{_INCLUDE_TARGET_TAXONOMY_ENTRYPOINT}; no scope gate is needed"
            ),
            "constructs": constructs,
            "unrouted": unrouted,
        }

    if not gate_path.exists():
        return {
            "verdict": FAIL,
            "detail": (
                f"{_rel_or_str(gate_path)} does not exist. Absence is a definite negative: "
                f"{len(unrouted)} INCLUDE_TARGET construct(s) do not route through "
                f"{_INCLUDE_TARGET_TAXONOMY_ENTRYPOINT} and nothing proves them safe another way"
            ),
            "constructs": constructs,
            "unrouted": unrouted,
        }

    try:
        module = _load_scope_gate_module(gate_path)
    except Exception as error:  # noqa: BLE001 -- a broken gate module blocks, never passes
        return {
            "verdict": FAIL,
            "detail": f"{_rel_or_str(gate_path)} raised on import: {type(error).__name__}: {error}",
            "constructs": constructs,
            "unrouted": unrouted,
        }

    declared = set(getattr(module, "INCLUDE_TARGET_CONSTRUCTS", ()))
    uncovered = sorted(set(unrouted) - declared)
    if uncovered:
        return {
            "verdict": FAIL,
            "detail": (
                f"{_rel_or_str(gate_path)} declares no scope claim for: " + ", ".join(uncovered)
            ),
            "constructs": constructs,
            "unrouted": unrouted,
            "declared_by_gate": sorted(declared),
        }

    prove_scope = getattr(module, "prove_scope", None)
    if prove_scope is None:
        return {
            "verdict": FAIL,
            "detail": f"{_rel_or_str(gate_path)} exposes no prove_scope() entry point",
            "constructs": constructs,
            "unrouted": unrouted,
        }

    try:
        proof = prove_scope()
    except Exception as error:  # noqa: BLE001 -- a failed proof blocks, it does not pass
        return {
            "verdict": FAIL,
            "detail": (
                f"{_rel_or_str(gate_path)}.prove_scope() raised: {type(error).__name__}: {error}"
            ),
            "constructs": constructs,
            "unrouted": unrouted,
        }

    unproven = sorted(construct for construct in unrouted if construct not in proof)
    return {
        "verdict": FAIL if unproven else PASS,
        "detail": (
            f"{len(unrouted)} unrouted construct(s); not covered by "
            f"{_rel_or_str(gate_path)}'s own proof: " + ", ".join(unproven)
            if unproven
            else f"all {len(unrouted)} unrouted construct(s) proven safe by {_rel_or_str(gate_path)}"
        ),
        "constructs": constructs,
        "unrouted": unrouted,
        "proof": dict(proof),
    }


# ---------------------------------------------------------------------------
# 4. artifact facet/fingerprint propagation


_CHANNEL_CASE_NAMES: tuple[str, ...] = (
    "semantic_case",
    "structural_case",
    "referential_case",
    "temporal_case",
    "descriptive_case",
)


def artifact_facet_fingerprint_propagation() -> dict[str, Any]:
    """For each of the five declared channels, does a change to only that
    facet move the artifact digest `compiler.selective_build.build_all`
    actually computes?

    Reuses `compiler.channel_cases`' own case builders -- real production
    `build_all`, called on the same document pairs the executor's own
    adversarial suite uses -- rather than asserting today's known answer, so
    this measures the property and turns `PASS` on its own once another
    lane's repair lands. Today `build_all`'s `section:` artifact spec reads
    only `{"logical_id", "semantic_text"}` (see `compiler/selective_build.py`
    `build_all`), so REFERENTIAL/LOCATOR, TEMPORAL and DESCRIPTIVE/METADATA
    changes leave the digest untouched even though the channel is real and
    detected -- each case's own `note` field says so.
    """
    import compiler.channel_cases as cc

    channels: list[dict[str, Any]] = []
    for name in _CHANNEL_CASE_NAMES:
        case = getattr(cc, name)()
        moved = case.prior_value != case.rebuilt_value
        channels.append(
            {
                "case": name,
                "ir_channel": case.ir_channel,
                "target_artifact": case.target_artifact,
                "digest_moved": moved,
                "prior_value": case.prior_value,
                "rebuilt_value": case.rebuilt_value,
            }
        )

    failing = [row["ir_channel"] for row in channels if not row["digest_moved"]]
    return {
        "verdict": FAIL if failing else PASS,
        "detail": (
            "artifact digest did not move for: " + ", ".join(failing)
            if failing
            else "artifact digest moved for every declared channel"
        ),
        "channels": channels,
    }


# ---------------------------------------------------------------------------
# 5. fresh-frame disjointness (identity metadata only)


def fresh_frame_disjointness(
    *, spent: frozenset[str] | None = None, frame_path: Path | None = None
) -> dict[str, Any]:
    """The declared SFI3 roots, and any sealed lineage expansion, are
    disjoint from every predecessor spent set.

    Reads lineage identity only, never revision content. Git and eCFR roots
    are checked by lineage-id prefix directly against
    `sources_sfi3.spent_lineages()` (already the union of everything SFI1,
    SFI2, SFH1, VBC2 and the forensic sets spent -- reused, not
    reimplemented). Wikipedia category roots have no lineage-id-shaped prefix
    before expansion -- a category expands to many article lineages over the
    network, which this check must not do -- so they are checked only once
    `artifacts/development/sfi3_lineages.json` is sealed, by streaming its
    lineage ids the same way `sources_sfi3._lineage_ids_from_acquisition`
    reads the ~80 MB SFI2 acquisition artifact: `json.load` with an
    `object_hook` that trims every row to `{"lineage_id": ...}` as soon as it
    is parsed, so the full row (extracted facts and all) is never held.
    """
    import sources_sfi3 as sfi3

    spent_set = spent if spent is not None else sfi3.spent_lineages()
    frame = frame_path if frame_path is not None else sfi3.FRAME

    violations: list[dict[str, Any]] = []

    for git_root in sfi3.GIT_ROOTS:
        prefix = f"git:{git_root['owner']}/{git_root['repo']}:"
        hits = sorted(candidate for candidate in spent_set if candidate.startswith(prefix))
        if hits:
            violations.append(
                {
                    "kind": "git_root",
                    "root": f"{git_root['owner']}/{git_root['repo']}",
                    "spent_hit_count": len(hits),
                    "spent_hits_sample": hits[:5],
                }
            )

    for title, part, _description in sfi3.ECFR_ROOTS:
        prefix = f"ecfr:{title}:{part}:"
        hits = sorted(candidate for candidate in spent_set if candidate.startswith(prefix))
        if hits:
            violations.append(
                {
                    "kind": "ecfr_root",
                    "root": f"{title}:{part}",
                    "spent_hit_count": len(hits),
                    "spent_hits_sample": hits[:5],
                }
            )

    frame_sealed = frame.exists()
    expanded_overlap: tuple[str, ...] = ()
    if frame_sealed:
        expanded_ids = sfi3._lineage_ids_from_acquisition(frame)  # noqa: SLF001 -- reused for
        # its streaming technique; NS/acquisition/sources_sfi3.py is read/import-only here.
        expanded_overlap = tuple(sorted(expanded_ids & spent_set))
        if expanded_overlap:
            violations.append(
                {
                    "kind": "expanded_frame_overlap",
                    "overlap_count": len(expanded_overlap),
                    "overlap_sample": expanded_overlap[:20],
                }
            )

    return {
        "verdict": FAIL if violations else PASS,
        "detail": (
            f"{len(violations)} disjointness violation(s) against a spent set of "
            f"{len(spent_set)} lineage id(s); frame_sealed={frame_sealed}"
        ),
        "violations": violations,
        "frame_sealed": frame_sealed,
        "scope_note": (
            "Wikipedia category roots are not lineage-id-shaped before network expansion and "
            "are checked only once the frame is sealed, via expanded_frame_overlap above"
        ),
    }


# ---------------------------------------------------------------------------
# 6. all 14 spent SFI2 forensic lineages explicitly excluded


#: The immutable receipt the founder named, read directly rather than through
#: `receipts/latest/sfi2-native-provenance.json` -- that pointer already
#: resolves to this exact file (`points_to`), but citing the immutable path
#: means this check does not depend on the pointer never being repointed.
_SFI2_FORENSIC_RECEIPT = (
    NS / "receipts" / "sfi2-native-provenance--20260823T085006Z-e53cc8aaeb7d.json"
)


def sfi2_forensic_lineages_excluded(
    *, receipt_path: Path | None = None, spent: frozenset[str] | None = None
) -> dict[str, Any]:
    """The 14 lineages SFI2's E5/E6 rebuild used to confirm the selective
    stale escape are all present in SFI3's spent set.

    A case used to diagnose a defect cannot certify its repair -- this check
    proves the diagnostic cases are excluded, not that the repair works.
    """
    path = receipt_path if receipt_path is not None else _SFI2_FORENSIC_RECEIPT
    if not path.exists():
        return {"verdict": FAIL, "detail": f"{_rel_or_str(path)} does not exist"}

    body = json.loads(path.read_text(encoding="utf-8"))
    try:
        confirmed = body["rebuild"]["E5_confirmed_selective_stale_escape"]["confirmed"]
    except (KeyError, TypeError) as error:
        return {
            "verdict": FAIL,
            "detail": (
                f"{_rel_or_str(path)} has no "
                f"rebuild.E5_confirmed_selective_stale_escape.confirmed: {error}"
            ),
        }

    pinned = sorted({row["lineage_id"] for row in confirmed})
    if len(pinned) != 14:
        return {
            "verdict": FAIL,
            "detail": f"expected 14 confirmed forensic lineages, found {len(pinned)}",
            "pinned_lineage_ids": pinned,
        }

    if spent is not None:
        spent_set = spent
    else:
        import sources_sfi3 as sfi3

        spent_set = sfi3.spent_lineages()

    missing = sorted(set(pinned) - spent_set)
    return {
        "verdict": FAIL if missing else PASS,
        "detail": (
            "all 14 pinned SFI2 E5/E6 forensic lineages are in SFI3's spent set"
            if not missing
            else f"{len(missing)} of 14 pinned forensic lineage(s) are missing from the spent set"
        ),
        "pinned_receipt": _rel_or_str(path),
        "pinned_lineage_ids": pinned,
        "missing_from_spent_set": missing,
    }


# ---------------------------------------------------------------------------
# INC-V2-097: a mutable pointer must name bytes git can return


def receipt_pointer_targets_are_recoverable(
    *, pointer_dir: Path | None = None, repo_root: Path | None = None
) -> dict[str, Any]:
    """Every `receipts/latest/*.json` pointer names a file that is on disk AND
    committed at HEAD.

    A pointer is not evidence and says so in its own `note`, but it is the only
    published handle on the receipt it names -- so a pointer whose target git
    cannot return is a citation into nothing. That is INC-V2-089's failure at a
    smaller scale: a name for bytes, without the bytes.

    Both halves are required and they fail differently. Absent from disk means
    the receipt is gone from this checkout; present on disk but absent at HEAD
    means it is gone from every OTHER checkout, which is the harder failure to
    notice because everything works locally. `ad99d18` committed exactly one
    pointer of the second kind having never committed its target, and no test
    then existed that would have said so.

    `UNVERIFIABLE` rather than `FAIL` when git cannot be consulted: not knowing
    whether a file is committed is a different fact from knowing it is not, and
    reporting the first as the second would make this check fire in any export
    that has no git directory.
    """
    directory = pointer_dir if pointer_dir is not None else (NS / "receipts" / "latest")
    root = repo_root if repo_root is not None else ROOT

    if not directory.is_dir():
        return {"verdict": FAIL, "detail": f"{_rel_or_str(directory)} does not exist"}

    try:
        committed = set(
            subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", "HEAD"],  # noqa: S607
                capture_output=True,
                text=True,
                cwd=root,
                check=True,
            ).stdout.split("\n")
        )
    except (OSError, subprocess.CalledProcessError) as error:
        return {
            "verdict": UNVERIFIABLE,
            "detail": f"git could not be consulted for HEAD membership: {error}",
        }

    absent_from_disk: list[dict[str, str]] = []
    digest_mismatched: list[dict[str, str]] = []
    absent_at_head: list[dict[str, str]] = []
    checked = 0
    for pointer in sorted(directory.glob("*.json")):
        try:
            body = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return {
                "verdict": FAIL,
                "detail": f"{_rel_or_str(pointer)} is unreadable as JSON: {error}",
            }
        target = body.get("points_to")
        if not isinstance(target, str) or not target:
            continue
        checked += 1
        row = {"pointer": pointer.name, "points_to": target}
        resolved = root / target
        if not resolved.is_file():
            absent_from_disk.append(row)
        elif target not in committed:
            absent_at_head.append(row)
        else:
            # Every pointer in this tree states its target's digest. Until this
            # ran, nothing compared it -- and at least one reader follows
            # `points_to` without checking it: `sources_sfi3.py` derives the
            # fourteen SFI2 E5/E6 forensic lineages, the cases that must NOT
            # certify their own repair, by following this kind of pointer at
            # import time. Its own docstring says "a forensic set that quietly
            # shrinks re-admits a diagnostic case", and it guards the pointer
            # being MISSING but not the pointer having MOVED.
            #
            # That file is pinned by frozen receipts and is not currently in
            # frozen_drift, so editing it would newly break a frozen instrument
            # and grow the preserved historical FAIL. The check therefore lives
            # here, outside the frozen file, where it costs no drift and covers
            # all 102 pointers rather than the one reader.
            declared = body.get("points_to_file_sha256")
            if isinstance(declared, str) and declared:
                actual = "sha256:" + hashlib.sha256(resolved.read_bytes()).hexdigest()
                if actual != declared:
                    digest_mismatched.append({**row, "declared": declared, "actual": actual})

    unrecoverable = absent_from_disk + absent_at_head + digest_mismatched
    return {
        "verdict": PASS if not unrecoverable else FAIL,
        "detail": (
            f"{checked} pointer(s) checked; "
            f"{len(absent_from_disk)} target(s) absent from disk, "
            f"{len(absent_at_head)} present on disk but not committed at HEAD, "
            f"{len(digest_mismatched)} not matching the digest the pointer states"
        ),
        "pointers_checked": checked,
        "absent_from_disk": absent_from_disk,
        "absent_at_head": absent_at_head,
        "digest_mismatched": digest_mismatched,
    }
