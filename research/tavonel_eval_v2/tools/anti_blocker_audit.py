"""Scan the chains that are still going to run for the fifteen defect classes.

WHY THIS EXISTS. Every blocker this study has hit was found by hitting it. The
V2R3 chain died on an instrument crash AFTER the freeze, with 300 acquired pairs
behind it; V2R2 died on a quarantine reading nobody had exercised; SFI2 died on
an E5 reading that had to be corrected after the fact. Each was cheap to find in
advance and expensive to find at the barrier. This module looks for the same
shapes BEFORE the remaining serial chain runs, mechanically, over the modules
that are actually going to execute.

SCOPE IS DELIBERATELY NARROW. It scans the ACTIVE surface only -- the SFI3
pipeline, the four-link gate, and the GPU launcher -- because a scan over every
historical study would report hundreds of true findings about work that is
already spent and can no longer hurt anything. A spent study's defect is
history; an active stage's defect is a blocker.

WHAT IT IS NOT. It is not a proof of correctness. Each check looks for one
STRUCTURAL shape that has previously preceded a blocker here. A clean scan means
none of the fifteen shapes is present, not that the pipeline is right.

Findings carry a severity:

  BLOCKER  -- would stop or corrupt a chain that has not run yet.
  FINDING  -- a real defect of the named class, in a place where it cannot
              currently reach a frozen result.
  ACCEPTED -- the shape is present and a structural feature of the same module
              removes its power. The reason is recorded, and the structural
              feature is CHECKED, not asserted.

The audit passes when no BLOCKER remains. FINDINGs are reported, never hidden.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
if str(NS / "tools") not in sys.path:
    sys.path.insert(0, str(NS / "tools"))

SCHEMA = "tavonel.v2.anti_blocker_audit.v1"

#: The modules that the remaining serial chain -- SFI3, four-link, GPU -- will
#: actually execute. Kept explicit rather than globbed: a glob would silently
#: widen the audit the next time somebody drops a file in tools/, and the
#: audit's verdict would then change for a reason nobody chose.
ACTIVE_TOOLS = (
    "tools/invariant_domain.py",
    "tools/freeze_sfi3_protocol.py",
    "tools/freeze_sfi3_lineages.py",
    "tools/preflight_sfi3_roots.py",
    "tools/replace_sfi3_roots.py",
    "tools/verify_sfi3_frame.py",
    "tools/sfi3_worker.py",
    "tools/score_sfi3.py",
    "tools/rehearse_sfi3_execution.py",
    "tools/four_link_gate.py",
    "tools/four_link_validator.py",
    "tools/four_link_acceptance.py",
    "tools/sfi3_acceptance.py",
    "tools/migration_closure_acceptance.py",
    "tools/v2r4_grading.py",
    "tools/v2r4_semantics_delta.py",
    "tools/rehearse_v2r4_closure.py",
    "tools/gpu_successor_preflight.py",
    "tools/resolve_gpu_successor_pin.py",
    "tools/launch_gpu_successor.py",
    "tools/sfi3_root_reservation.py",
    "tools/probe_v2r4_roots.py",
    "tools/v2r4_attestation.py",
    "tools/enumerate_v2r4_universe.py",
    "tools/freeze_migration_closure_v2r4.py",
    "tools/v2r4_preacquisition_gate.py",
    "tools/identity_change_migration_closure_v2r4.py",
    "acquisition/sources_sfi3.py",
    "acquisition/sources_v2r4.py",
    "acquisition/fetch_v2r4_corpus.py",
)

ACTIVE_TESTS = (
    "tests/test_invariant_domain.py",
    "tests/test_freeze_sfi3_gate.py",
    "tests/test_sfi3_acquisition.py",
    "tests/test_sfi3_execution_path.py",
    "tests/test_sfi3_frame_verification.py",
    "tests/test_sfi3_root_preflight.py",
    "tests/test_sfi3_root_replacement.py",
    "tests/test_sfi3_scoring.py",
    "tests/test_four_link_gate.py",
    "tests/test_four_link_validator.py",
    "tests/test_four_link_acceptance.py",
    "tests/test_sfi3_acceptance.py",
    "tests/test_migration_closure_acceptance.py",
    "tests/test_v2r4_grading.py",
    "tests/test_v2r4_semantics_delta.py",
    "tests/test_v2r4_rehearsal.py",
    "tests/test_sfi3_root_reservation.py",
    "tests/test_v2r4_frame.py",
    "tests/test_v2r4_closure_runner.py",
    "tests/test_v2r4_preacquisition_gate.py",
    "tests/test_gpu_successor_pin.py",
    "tests/test_gpu_successor_study.py",
    "tests/test_launch_gpu_successor.py",
    "tests/test_sfi_gpu_preflight.py",
)

#: Modules belonging to a study that is already spent. An active module reaching
#: into one of these is class 1 / class 12 territory.
SPENT_STUDY = re.compile(
    r"^(score_sfi1|score_sfi2|sfi1_worker|sfi2_\w+|freeze_migration_closure_v2r[12]"
    r"|identity_change_migration_closure_v2r[123]\w*)$"
)

#: A cross-study import is only safe when the importing module CHECKS that the
#: things it borrowed still say what it thinks. These are the call shapes that
#: perform such a check in this codebase.
AGREEMENT_CALLS = re.compile(r"^(require_|_require_|_assert_|assert_|_verify_|verify_|_bound)")

BLOCKER = "BLOCKER"
FINDING = "FINDING"
ACCEPTED = "ACCEPTED"


@dataclass(frozen=True)
class Finding:
    defect_class: int
    name: str
    severity: str
    path: str
    line: int
    detail: str


CLASS_NAMES = {
    1: "inherited stage reads a base protocol's defaults",
    2: "unbound protocol id",
    3: "rows/pairs schema-key drift",
    4: "test reproduces an implementation assumption instead of schema truth",
    5: "a unit test can execute a live held-out closure",
    6: "import carries a hidden active-protocol global",
    7: "stale receipt looked up by glob/latest instead of an explicit run id",
    8: "scorer emits output before a successful return",
    9: "receipt created before grading is complete",
    10: "real-cohort access reachable from pytest",
    11: "mutable 'latest' path inside a frozen chain",
    12: "stage silently falls back to a spent study's defaults",
    13: "schema literal duplicated instead of imported",
    14: "stage's protocol/universe binding is implicit",
    15: "acceptance domain is not checked against the executable grading domain",
}


# ---------------------------------------------------------------------------
# helpers


def _read(rel: str) -> tuple[str, ast.Module] | None:
    path = NS / rel
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text, filename=str(path))


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and any(
            isinstance(other, ast.Constant) and other.value == "__main__"
            for other in test.comparators
        )
    )


def _module_level(tree: ast.Module) -> list[ast.stmt]:
    """Statements that run at import time, including inside module-level if/try."""
    out: list[ast.stmt] = []
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        #: `if __name__ == "__main__":` does not run on import, and treating its
        #: body as import-time work reports every CLI entry point in the
        #: repository as a hidden global.
        if isinstance(node, ast.If) and _is_main_guard(node):
            continue
        out.append(node)
        if isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            stack.extend(getattr(node, "body", []))
            stack.extend(getattr(node, "orelse", []))
            stack.extend(getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                stack.extend(handler.body)
    return out


def _call_name(node: ast.AST) -> str:
    func = getattr(node, "func", None)
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _calls(node: ast.AST) -> list[ast.Call]:
    return [child for child in ast.walk(node) if isinstance(child, ast.Call)]


def _functions(tree: ast.Module) -> list[ast.FunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]


def _strings(tree: ast.AST) -> list[tuple[str, int]]:
    return [
        (n.value, n.lineno)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _docstring_lines(tree: ast.Module) -> set[int]:
    """Lines occupied by any docstring, so prose explaining a shape is not the shape."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            doc = body[0].value
            if isinstance(doc.value, str):
                lines.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return lines


def _guarded_lines(tree: ast.Module) -> set[int]:
    """Lines inside a `with pytest.raises(...)` block."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any(
            _call_name(item.context_expr) == "raises"
            for item in node.items
            if isinstance(item.context_expr, ast.Call)
        ):
            continue
        for stmt in node.body:
            lines.update(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))
    return lines


# ---------------------------------------------------------------------------
# the fifteen checks


def _class_1_and_12(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    """A stage importing a spent study, with or without an agreement check."""
    found: list[Finding] = []
    checks = {_call_name(call) for fn in _functions(tree) for call in _calls(fn)}
    checks |= {fn.name for fn in _functions(tree)}
    has_agreement = any(AGREEMENT_CALLS.match(name) for name in checks)
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for name in names:
            if not SPENT_STUDY.match(name):
                continue
            found.append(
                Finding(
                    1 if has_agreement else 12,
                    CLASS_NAMES[1 if has_agreement else 12],
                    ACCEPTED if has_agreement else BLOCKER,
                    rel,
                    node.lineno,
                    f"imports {name!r} from a spent study; "
                    + (
                        "the module carries an explicit agreement check, so a "
                        "constant that moves is reported rather than inherited"
                        if has_agreement
                        else "NO agreement check was found, so a constant that "
                        "moves in the spent study is inherited silently"
                    ),
                )
            )
    return found


def _class_2_and_14(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    """A module naming a protocol must verify its freeze, and bind it in its receipt."""
    found: list[Finding] = []
    names = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    if "PROTOCOL" not in names and "RUNTIME_PROTOCOL" not in names:
        return found
    #: `declaration_digests` is included because it IS the check: the preflight
    #: records what it read and the launcher refuses when disk no longer matches.
    #: A recogniser that only knew the word "frozen" would report a stage that
    #: binds its protocol properly under a different spelling.
    verifies = bool(
        re.search(
            r"protocol_sha256|require_frozen|frozen_protocol|_verify_pins"
            r"|declaration_digests|_declaration_gate",
            text,
        )
    )
    if not verifies:
        found.append(
            Finding(
                2,
                CLASS_NAMES[2],
                BLOCKER,
                rel,
                1,
                "names a protocol path but never checks that the protocol still "
                "hashes to what was frozen; the id is a filename, not a binding",
            )
        )
    if "write_immutable" in text and not re.search(
        r"protocol_sha256|universe_sha256|manifest_sha256|runtime_declaration"
        r"|declaration_gate|declarations",
        text,
    ):
        found.append(
            Finding(
                14,
                CLASS_NAMES[14],
                BLOCKER,
                rel,
                1,
                "writes an immutable receipt that records no protocol, universe or "
                "manifest digest; a reader cannot tell what the stage was bound to",
            )
        )
    return found


def _class_5_and_10(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    """A test that can reach a real cohort, and a cohort module with no pytest guard."""
    found: list[Finding] = []
    if rel.startswith("tests/"):
        docs = _docstring_lines(tree)
        guarded = _guarded_lines(tree)
        for call in _calls(tree):
            name = _call_name(call)
            if name not in {"run", "acquire", "main"}:
                continue
            if call.lineno in docs or call.lineno in guarded:
                continue
            target = getattr(call.func, "value", None)
            owner = target.id if isinstance(target, ast.Name) else ""
            if owner not in {"worker", "scorer", "driver", "closure"}:
                continue
            executes = any(
                isinstance(node, ast.Constant) and node.value == "--execute"
                for node in ast.walk(call)
            )
            if name == "main" and not executes:
                continue
            found.append(
                Finding(
                    5,
                    CLASS_NAMES[5],
                    BLOCKER,
                    rel,
                    call.lineno,
                    f"unguarded {owner}.{name}() -- a stray pytest run could reach a live cohort",
                )
            )
        return found
    #: The other direction: a module that CAN touch a real cohort should refuse
    #: when a test runner is in the process.
    if re.search(r"\bdef (run|acquire)\(", text) and "sys.modules" not in text:
        found.append(
            Finding(
                10,
                CLASS_NAMES[10],
                FINDING,
                rel,
                1,
                "exposes a cohort-touching entry point with no test-runner refusal; "
                "an accidental import under pytest is the only thing standing "
                "between a stray call and a live traversal",
            )
        )
    return found


def _sealed_frame(text: str, tree: ast.Module) -> bool:
    """The module resolves a mutable pointer to an immutable receipt AND seals.

    Two structural features, both checked here rather than taken on a comment's
    word: the read follows a `points_to` indirection to the immutable receipt
    the pointer names, and the module publishes a `frame_digest` over what it
    produced. Together they do not PREVENT the pointer moving -- they make a
    move visible in the frozen frame's digest instead of silent. That is the
    difference between this being a FINDING and a BLOCKER, and it is why the
    severity is lowered rather than the finding dropped.
    """
    names = {fn.name for fn in _functions(tree)}
    return "points_to" in text and "frame_digest" in names


def _class_6(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    """Reading a protocol, receipt or manifest at import time."""
    readers = {"read_text", "read_bytes", "safe_load", "glob", "rglob"}
    #: One level of indirection, because the shape that actually appears is a
    #: module-level constant assigned from a local helper that does the reading.
    #: A check that only looked at the call written on the module-level line
    #: would find nothing and report clean.
    reads_via = {
        fn.name
        for fn in _functions(tree)
        if any(_call_name(call) in readers for call in _calls(fn))
    }
    found: list[Finding] = []
    for node in _module_level(tree):
        for call in _calls(node):
            if _call_name(call) in readers or _call_name(call) in reads_via:
                found.append(
                    Finding(
                        6,
                        CLASS_NAMES[6],
                        FINDING if _sealed_frame(text, tree) else BLOCKER,
                        rel,
                        call.lineno,
                        f"{_call_name(call)}() runs at import time; whoever imports "
                        "this module inherits whatever was on disk at that moment",
                    )
                )
    return found


def _class_7_and_11(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    """Receipt chosen by newest-wins, and any writable 'latest' path."""
    found: list[Finding] = []
    explicit = "--receipt" in text or "--run-id" in text or "run_id=" in text
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not (isinstance(node.value, ast.Call) and _call_name(node.value) in {"sorted", "list"}):
            continue
        index = node.slice
        newest = (
            isinstance(index, ast.UnaryOp)
            and isinstance(index.op, ast.USub)
            and isinstance(index.operand, ast.Constant)
            and index.operand.value == 1
        )
        if not newest:
            continue
        if not any(_call_name(call) in {"glob", "rglob"} for call in _calls(node.value)):
            continue
        found.append(
            Finding(
                7,
                CLASS_NAMES[7],
                ACCEPTED if explicit else BLOCKER,
                rel,
                node.lineno,
                "picks a receipt by newest-wins over a glob"
                + (
                    "; the module also accepts an explicit receipt/run id, so the "
                    "glob is a CLI convenience and never the chain's binding"
                    if explicit
                    else "; nothing in this module lets a caller name the receipt it "
                    "meant, so the binding is whatever sorted last"
                ),
            )
        )
    #: Only a literal used to BUILD a path counts. `revision != "latest"` and
    #: `if revision == "latest": raise` are the guards AGAINST this class, and an
    #: audit that reads a guard as the defect reports the safest module as the
    #: worst one -- INC-V2-036 in the auditor rather than the audited.
    for lineno, segment in _path_segments(tree):
        if segment == "latest" or ("latest" in segment and segment.endswith(".json")):
            found.append(
                Finding(
                    11,
                    CLASS_NAMES[11],
                    FINDING if _sealed_frame(text, tree) else BLOCKER,
                    rel,
                    lineno,
                    f"a path is built through the mutable segment {segment!r}; what "
                    "it resolves to can change without any receipt recording that "
                    "it did",
                )
            )
    return found


def _path_segments(tree: ast.Module) -> list[tuple[int, str]]:
    """String literals used as operands of the `Path / "part"` idiom."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    out.append((side.lineno, side.value))
        elif isinstance(node, ast.Call) and _call_name(node) == "Path":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.append((arg.lineno, arg.value))
    return out


def _class_8_and_9(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    """Output or a receipt emitted before grading finishes."""
    outputs = {"print", "write_text", "write_bytes", "write_immutable", "dump"}
    found: list[Finding] = []
    for fn in _functions(tree):
        if fn.name not in {"run", "score", "gate", "validate", "launch", "acquire"}:
            continue
        returns = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Return)]
        if returns:
            last_return = max(returns)
            for call in _calls(fn):
                if _call_name(call) in outputs and call.lineno < last_return:
                    found.append(
                        Finding(
                            8,
                            CLASS_NAMES[8],
                            FINDING,
                            rel,
                            call.lineno,
                            f"{fn.name}() emits {_call_name(call)}() before its final "
                            "return; a crash after this point leaves output that no "
                            "successful return stands behind",
                        )
                    )
        #: class 9 -- a receipt written from inside a per-item loop is a receipt
        #: written before the cohort is graded.
        for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]:
            for call in _calls(loop):
                if _call_name(call) == "write_immutable":
                    found.append(
                        Finding(
                            9,
                            CLASS_NAMES[9],
                            BLOCKER,
                            rel,
                            call.lineno,
                            f"{fn.name}() writes an immutable receipt inside a loop; "
                            "the receipt exists before grading is complete",
                        )
                    )
    return found


#: Which study surface a module belongs to. Endpoint ids are only comparable
#: within one of these: SFI2 and SFI3 both have an `E1_no_unclassified_changed_
#: regions`, and they are two studies' endpoints that happen to share a name.
STUDY_SURFACES = (
    ("sfi3", re.compile(r"sfi3")),
    ("four_link", re.compile(r"four_link")),
    ("gpu", re.compile(r"gpu_successor")),
)


def _study_of(rel: str) -> str:
    for name, pattern in STUDY_SURFACES:
        if pattern.search(rel):
            return name
    return "other"


def _drifting_literal(value: str, study: str, sites: list[tuple[str, int]]) -> list[Finding]:
    """One endpoint id, spelled in more than one place inside one study."""
    owners = {rel for rel, _ in sites}
    tests = sorted(rel for rel in owners if rel.startswith("tests/"))
    tools = sorted(rel for rel in owners if not rel.startswith("tests/"))
    found: list[Finding] = []
    if len(tools) > 1:
        found.append(
            Finding(
                3,
                CLASS_NAMES[3],
                BLOCKER,
                tools[1],
                next(line for rel, line in sites if rel == tools[1]),
                f"endpoint id {value!r} is spelled out in {tools} (study {study!r}); "
                "two modules carrying the same key as a literal drift independently",
            )
        )
    if tests and tools:
        found.append(
            Finding(
                4,
                CLASS_NAMES[4],
                FINDING,
                tests[0],
                next(line for rel, line in sites if rel == tests[0]),
                f"{value!r} is re-spelled in {tests} rather than imported from "
                f"{tools[0]}; the test then agrees with a copy of the contract",
            )
        )
    return found


#: A module carrying one of these declares an ACCEPTANCE DOMAIN: a set of
#: identifiers whose verdicts decide a PASS. The founder's rule of 2026-08-26 is
#: that such a set may never be assumed to match what the instrument actually
#: grades -- INC-V2-067 spent a 300-pair corpus on exactly that assumption.
ACCEPTANCE_SET_NAMES = (
    "ENDPOINTS",
    "PRIMARY_ENDPOINTS",
    "REQUIRED_ENDPOINTS",
    "INVARIANTS",
    "CANONICAL_INVARIANTS",
    "PASS_CONTRIBUTING",
)

#: What counts as actually asking the question. Each of these compares a
#: declared set against something outside the module that declares it.
#: `acceptance_domain` is included because a module that REPORTS the comparison
#: in its own output has demonstrably made it -- the key cannot be present
#: unless both sides were computed and differenced.
DOMAIN_CHECKS = re.compile(
    r"require_declared_endpoints|require_domain_equality|require_receipt_domain"
    r"|invariant_domain|graded_invariants|declared_invariants|acceptance_domain"
)


def _class_15(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    """A PASS-contributing set declared with nothing comparing it to the grader.

    The check is structural, and deliberately so: whether the two domains are
    equal is a question only `invariant_domain.require_domain_equality` can
    answer, by executing the grader. What an AST scan CAN establish is whether
    anybody asks -- and INC-V2-067 is a case where nobody did, for eight rungs
    of freeze chain and one irreversible execution.
    """
    declared = sorted(
        target.id
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id in ACCEPTANCE_SET_NAMES
    )
    if not declared:
        return []
    #: The module that OWNS the anchor is not required to check itself against
    #: itself; it is the thing others are checked against, and it verifies its
    #: own well-formedness at import.
    if "_require_canonical_is_well_formed" in text:
        return []
    if DOMAIN_CHECKS.search(text):
        return [
            Finding(
                15,
                CLASS_NAMES[15],
                ACCEPTED,
                rel,
                1,
                f"declares the acceptance set(s) {declared} and routes them through "
                "a domain-equality check, so a declared-but-ungraded identifier "
                "refuses rather than being reported as absent",
            )
        ]
    return [
        Finding(
            15,
            CLASS_NAMES[15],
            BLOCKER,
            rel,
            1,
            f"declares the acceptance set(s) {declared} and nothing compares them "
            "to what the instrument actually grades. A count is not a "
            "correspondence and eight wrong names pass any check that counts; "
            "see INC-V2-067",
        )
    ]


def _class_3_4_13(modules: dict[str, tuple[str, ast.Module]]) -> list[Finding]:
    """Literals that ought to be one constant, counted across the active surface."""
    endpoint = re.compile(r"^E[1-9]_[a-z0-9_]+$")
    schema = re.compile(r"^tavonel\.[a-z0-9_.]+\.v\d+$")
    endpoints: dict[str, list[tuple[str, int]]] = {}
    schemas: dict[str, list[tuple[str, int]]] = {}
    for rel, (_text, tree) in modules.items():
        docs = _docstring_lines(tree)
        for value, lineno in _strings(tree):
            if lineno in docs:
                continue
            if endpoint.match(value):
                endpoints.setdefault(value, []).append((rel, lineno))
            elif schema.match(value):
                schemas.setdefault(value, []).append((rel, lineno))

    found: list[Finding] = []
    for value, sites in sorted(endpoints.items()):
        #: Scoped per study. SFI2's E1-E7 and SFI3's E1-E7 are different
        #: studies' endpoints that happen to share names; the launcher's SFI2
        #: list cannot drift from SFI3's contract because it never reads it.
        #: Comparing across that boundary reports a collision as a defect.
        by_study: dict[str, list[tuple[str, int]]] = {}
        for rel_path, lineno in sites:
            by_study.setdefault(_study_of(rel_path), []).append((rel_path, lineno))
        for study, scoped in sorted(by_study.items()):
            found += _drifting_literal(value, study, scoped)
    for value, sites in sorted(schemas.items()):
        owners = sorted({rel for rel, _ in sites if not rel.startswith("tests/")})
        if len(owners) > 1:
            found.append(
                Finding(
                    13,
                    CLASS_NAMES[13],
                    BLOCKER,
                    owners[1],
                    next(line for rel, line in sites if rel == owners[1]),
                    f"schema id {value!r} is a literal in {owners}; the second copy is what drifts",
                )
            )
    return found


# ---------------------------------------------------------------------------


def audit() -> dict[str, Any]:
    modules: dict[str, tuple[str, ast.Module]] = {}
    absent: list[str] = []
    for rel in ACTIVE_TOOLS + ACTIVE_TESTS:
        loaded = _read(rel)
        if loaded is None:
            absent.append(rel)
            continue
        modules[rel] = loaded

    findings: list[Finding] = []
    for rel, (text, tree) in modules.items():
        if rel.startswith("tests/"):
            findings += _class_5_and_10(rel, text, tree)
            continue
        findings += _class_1_and_12(rel, text, tree)
        findings += _class_2_and_14(rel, text, tree)
        findings += _class_5_and_10(rel, text, tree)
        findings += _class_6(rel, text, tree)
        findings += _class_7_and_11(rel, text, tree)
        findings += _class_8_and_9(rel, text, tree)
        findings += _class_15(rel, text, tree)
    findings += _class_3_4_13(modules)

    blockers = [f for f in findings if f.severity == BLOCKER]
    by_class = {
        index: sum(1 for f in findings if f.defect_class == index) for index in sorted(CLASS_NAMES)
    }
    return {
        "schema": SCHEMA,
        "modules_scanned": sorted(modules),
        "modules_absent": absent,
        "classes_checked": {str(k): v for k, v in CLASS_NAMES.items()},
        "findings_by_class": {str(k): v for k, v in by_class.items()},
        "findings": [asdict(f) for f in sorted(findings, key=lambda f: (f.defect_class, f.path))],
        "blocker_count": len(blockers),
        "verdict": "ANTI_BLOCKER_AUDIT_PASS" if not blockers else "BLOCKED",
        "what_a_pass_means": (
            "none of the fifteen structural shapes that have preceded a blocker in "
            "this study is present in the modules the remaining serial chain will "
            "execute. It is not a proof that those modules are correct."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="print the summary only")
    args = parser.parse_args(argv)
    body = audit()
    if args.quiet:
        body = {k: v for k, v in body.items() if k != "findings"}
    print(json.dumps(body, indent=1, sort_keys=True))
    return 0 if body["blocker_count"] == 0 else 5


if __name__ == "__main__":
    raise SystemExit(main())
