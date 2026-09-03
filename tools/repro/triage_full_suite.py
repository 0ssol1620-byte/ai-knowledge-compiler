#!/usr/bin/env python3
"""Cluster every full-suite failure by root cause, from the run outputs.

P0 forbade calling failures "probably pre-existing" and required each one
classified. It also required them treated as root-cause clusters rather than as N
independent problems, because 24 assertions with one cause is one defect wearing
24 costumes.

**The root cause, established causally rather than inferred.** The parser sandbox
launches its child with `-I`. That implies `-s`, which excludes user
site-packages. Under the global interpreter this repository's dependencies live
there, so the child cannot import them, exits non-zero, and the worker raises
`PARSER_PROCESS_CRASH`. Every downstream assertion then observes an analysis task
still `queued`.

The causal step is isolating `-s` from the rest of `-I`:

    python -E -P    -m akc_worker_document.sandbox_runner   -> imports cleanly
    python -E -P -s -m akc_worker_document.sandbox_runner   -> ModuleNotFoundError
    .venv python -I -c "import akc_worker_document.sandbox_runner"  -> IMPORT OK

**`-I` is the sandbox boundary for hostile documents and is not relaxed.**
Trading a security invariant for a green number is not an available repair.

Counts and cluster membership are read from the run outputs. Nothing is typed in,
and no count is carried over from a previous run.
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

ROOT = Path(__file__).resolve().parents[2]

TAXONOMY = {
    "A": "REGRESSION_INTRODUCED_THIS_PROGRAM",
    "B": "REAL_PRODUCT_DEFECT",
    "C": "STALE_TEST_EXPECTATION",
    "D": "ENVIRONMENT_DEPENDENT",
    "E": "OPTIONAL_DEPENDENCY",
    "F": "INTENTIONAL_CONTRACT_CHANGE",
    "G": "TEST_HARNESS_DEFECT",
    "H": "UNKNOWN",
}

SUMMARY = re.compile(r"(\d+) (passed|failed|skipped|error|errors)")
COLLECTED = re.compile(r"collected (\d+) items?")
FAILED = re.compile(r"^FAILED (\S+)", re.M)
TBLINE = re.compile(r"^(?:[A-Za-z]:)?[\\/].*[\\/]([\w.-]+\.py):(\d+): (.*)$", re.M)

ADDR = re.compile(r"0x[0-9a-fA-F]+")
QUOTED = re.compile(r"'[^']*'")


def normalise(sig: str) -> str:
    """Collapse a message to its shape, so equivalent failures cluster."""
    s = ADDR.sub("0xADDR", sig)
    s = re.sub(r"<[\w.]+ object at 0xADDR>", "<OBJ>", s)
    return re.sub(r"\s+", " ", s).strip()[:160]


#: Run outputs are captured to a session scratchpad that does not survive the
#: session. A receipt citing a path nobody can open is not a receipt, so the raw
#: output is copied under docs/repro/runs/ and both copies are hashed.
RUNS = ROOT / "docs" / "repro" / "runs"


def parse_run(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"present": False, "path": str(path)}
    raw = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    RUNS.mkdir(parents=True, exist_ok=True)
    kept = RUNS / path.name
    kept.write_bytes(raw)
    out = parse_text(raw.decode("utf-8", errors="replace"), str(path))
    out["sha256"] = digest
    out["retained_copy"] = kept.relative_to(ROOT).as_posix()
    out["retained_copy_sha256"] = "sha256:" + hashlib.sha256(kept.read_bytes()).hexdigest()
    return out


def parse_text(text: str, origin: str) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "collected": 0}
    lines = [ln for ln in text.splitlines() if SUMMARY.search(ln)]
    if lines:
        for n, kind in SUMMARY.findall(lines[-1]):
            counts["errors" if kind.startswith("error") else kind] = int(n)
    for m in COLLECTED.finditer(text):
        counts["collected"] = int(m.group(1))
    if not counts["collected"]:
        counts["collected"] = sum(counts[k] for k in ("passed", "failed", "skipped", "errors"))

    tests = FAILED.findall(text)
    tb = [(f"{f}:{ln}", msg.strip()) for f, ln, msg in TBLINE.findall(text)]
    # pytest emits FAILURES and the short summary in the same execution order.
    per_test = [
        {"test": t, "site": tb[i][0] if i < len(tb) else None,
         "signature": tb[i][1] if i < len(tb) else None}
        for i, t in enumerate(tests)
    ]
    return {
        "present": True, "path": origin,
        "summary_line": lines[-1].strip() if lines else None,
        **counts, "failed_tests": tests, "failure_details": per_test,
        "signature_alignment": (
            "traceback lines and the short summary are both in execution order and were "
            f"zipped; {len(tb)} traceback lines for {len(tests)} failures"
            + ("" if len(tb) == len(tests) else " -- COUNTS DIFFER, signatures unreliable")
        ),
        "signatures_reliable": len(tb) == len(tests),
    }


ROOT_CAUSE = {
    "id": "CLUSTER-SANDBOX-USERSITE",
    "root_code_path": (
        "workers/cpu-document/src/akc_worker_document/worker.py -- the sandbox child is "
        "launched with `-I`; failure surfaces at worker.py:1510 as "
        "AnalysisAttemptError('PARSER_PROCESS_CRASH')"
    ),
    "root_cause": (
        "`-I` implies `-s`, excluding user site-packages. Under the global interpreter the "
        "dependencies live there, so the child cannot import them and exits non-zero."
    ),
    "category": "D",
    "disposition": (
        "No code change. Run the suite with the project interpreter. `-I` is the sandbox "
        "boundary for hostile documents and is not relaxed; no test was edited, skipped or "
        "marked xfail."
    ),
    "first_responsible_change": (
        "None identifiable in this repository. The condition is where the dependencies were "
        "installed, not a commit here. No git evidence is offered, and the word "
        "'pre-existing' is therefore not used."
    ),
    "regression_coverage": (
        "tools/repro/run_test_scopes.py records the running interpreter and withholds "
        "repository_green when it is not the project one, verified by four controls in the "
        "same execution."
    ),
}


def classify(g: dict[str, Any], v: dict[str, Any]) -> dict[str, Any]:
    g_fail = {d["test"]: d for d in (g.get("failure_details") or [])}
    v_fail = {d["test"]: d for d in (v.get("failure_details") or [])}
    resolved = sorted(set(g_fail) - set(v_fail))
    persisting = sorted(set(g_fail) & set(v_fail))
    new_under_venv = sorted(set(v_fail) - set(g_fail))

    # Sub-signatures within the cluster: distinct assertion shapes, one cause.
    shapes: dict[str, list[str]] = {}
    for test, d in g_fail.items():
        shapes.setdefault(normalise(d["signature"] or "<no signature>"), []).append(test)

    clusters: list[dict[str, Any]] = []
    if resolved:
        clusters.append({
            **ROOT_CAUSE,
            "tests": resolved,
            "test_count": len(resolved),
            "category_name": TAXONOMY[ROOT_CAUSE["category"]],
            "distinct_assertion_shapes": [
                {"shape": s, "tests": t, "count": len(t)}
                for s, t in sorted(shapes.items(), key=lambda kv: -len(kv[1]))
                if set(t) & set(resolved)
            ],
            "why_one_cluster_not_many": (
                "The assertion shapes differ because they are downstream observations of the "
                "same unfinished analysis task, not independent defects. Every one resolves "
                "when the interpreter is corrected and none resolves without it."
            ),
            "evidence": {
                "causal_isolation": [
                    {"command": "python -E -P -m akc_worker_document.sandbox_runner",
                     "result": "imports cleanly"},
                    {"command": "python -E -P -s -m akc_worker_document.sandbox_runner",
                     "result": "ModuleNotFoundError: No module named 'starlette'"},
                    {"command": ".venv python -I -c 'import akc_worker_document.sandbox_runner'",
                     "result": "IMPORT OK"},
                ],
                "differential_run": {
                    "global": g.get("summary_line"),
                    "project_venv": v.get("summary_line"),
                },
            },
        })

    for test in persisting:
        clusters.append({
            "id": f"CLUSTER-UNRESOLVED-{test}",
            "tests": [test], "test_count": 1,
            "category": "H", "category_name": TAXONOMY["H"],
            "root_cause": "not determined",
            "root_code_path": g_fail[test].get("site"),
            "disposition": "requires diagnosis -- the environment mechanism does not explain it",
            "evidence": {"signature": g_fail[test].get("signature")},
        })
    for test in new_under_venv:
        clusters.append({
            "id": f"CLUSTER-NEW-UNDER-VENV-{test}",
            "tests": [test], "test_count": 1,
            "category": "H", "category_name": TAXONOMY["H"],
            "root_cause": "not determined -- fails only under the project interpreter",
            "root_code_path": v_fail[test].get("site"),
            "disposition": "requires diagnosis",
            "evidence": {"signature": v_fail[test].get("signature")},
        })

    unknown = [c for c in clusters if c["category"] == "H"]
    return {
        "clusters": clusters, "unknown": unknown, "resolved": resolved,
        "persisting": persisting, "new_under_venv": new_under_venv,
        "repository_green_allowed": (
            bool(v.get("present")) and v.get("failed", 1) == 0 and not unknown
        ),
    }


#: A triage that cannot produce an UNKNOWN cluster reports the same shape for a
#: clean suite and for one it failed to understand. This feeds the classifier a
#: venv run carrying a failure the environment mechanism does not explain, and
#: requires it to open an H cluster and withhold the green verdict.
CONTROL_VENV_RUN = (
    "collected 2790 items\n"
    r"D:\repo\tests\unit\test_control_probe.py:12: assert 0 == 1" + "\n"
    "FAILED tests/unit/test_control_probe.py::test_synthetic_control\n"
    "1 failed, 2757 passed, 32 skipped in 700.00s\n"
)
CONTROL_CLEAN_RUN = "collected 2790 items\n2758 passed, 32 skipped in 700.00s\n"


def self_control(g: dict[str, Any]) -> dict[str, Any]:
    dirty = classify(g, parse_text(CONTROL_VENV_RUN, "<control:injected>"))
    clean = classify(g, parse_text(CONTROL_CLEAN_RUN, "<control:clean>"))
    separates = (
        len(dirty["unknown"]) == 1
        and not dirty["repository_green_allowed"]
        and not clean["unknown"]
        and clean["repository_green_allowed"]
    )
    return {
        "separates": separates,
        "injected_run_unknown_clusters": len(dirty["unknown"]),
        "injected_run_green_allowed": dirty["repository_green_allowed"],
        "clean_run_unknown_clusters": len(clean["unknown"]),
        "clean_run_green_allowed": clean["repository_green_allowed"],
        "what_it_proves": (
            "the classifier opens an UNKNOWN cluster and withholds the green verdict for a "
            "failure the environment mechanism does not explain, and does neither on an "
            "otherwise identical clean run"
        ),
        "what_it_does_not_prove": (
            "nothing about whether the real clusters' root causes are correctly attributed; "
            "that rests on the causal isolation recorded in each cluster's evidence"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--global-run", required=True)
    ap.add_argument("--venv-run", required=True)
    args = ap.parse_args()

    g = parse_run(Path(args.global_run))
    v = parse_run(Path(args.venv_run))

    result = classify(g, v)
    clusters = result["clusters"]
    unknown = result["unknown"]
    resolved = result["resolved"]
    persisting = result["persisting"]
    new_under_venv = result["new_under_venv"]
    control = self_control(g)
    repo_green_allowed = result["repository_green_allowed"] and control["separates"]

    receipt: dict[str, Any] = {
        "schema": "tavonel.full-suite-triage.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "taxonomy": TAXONOMY,
        "full_suite": {
            "interpreter": "project venv",
            "collected": v.get("collected"),
            "passed": v.get("passed"),
            "failed": v.get("failed"),
            "skipped": v.get("skipped"),
            "exit_code": 0 if v.get("failed") == 0 else 1,
            "summary_line": v.get("summary_line"),
            "source": v.get("path"),
            "source_sha256": v.get("sha256"),
            "retained_copy": v.get("retained_copy"),
        },
        "global_interpreter_run": {
            "collected": g.get("collected"), "passed": g.get("passed"),
            "failed": g.get("failed"), "skipped": g.get("skipped"),
            "summary_line": g.get("summary_line"), "source": g.get("path"),
            "source_sha256": g.get("sha256"), "retained_copy": g.get("retained_copy"),
        },
        "signature_alignment": {"global": g.get("signature_alignment"),
                                "venv": v.get("signature_alignment")},
        "failure_clusters": clusters,
        "cluster_count": len(clusters),
        "resolved_by_correct_interpreter": len(resolved),
        "persisting_under_venv": persisting,
        "new_under_venv": new_under_venv,
        "unknown_clusters": len(unknown),
        "triage_detector_control": control,
        "repository_green_allowed": repo_green_allowed,
        "repository_green_rule": (
            "FULL failed must be 0, no cluster may remain UNKNOWN, and the classifier's own "
            "positive control must separate in the same execution. This field states "
            "whether the phrase is permitted; the phrase itself is emitted only by "
            "tools/repro/run_test_scopes.py, from a scope it actually ran."
        ),
        "second_defect_found_while_diagnosing": {
            "what": (
                "The global interpreter carries _editable_impl_ai_knowledge_compiler.pth "
                "pointing at a SIBLING checkout, "
                "D:/CodexProjects/ai-knowledge-compiler-collection-plane-rehearsal."
            ),
            "consequence": (
                "Under it, `import akc_worker_document` resolves to the other repository. "
                "The test process masks this by inserting this repository's paths first; a "
                "subprocess launched with -I has no such insertion."
            ),
            "category": "D",
            "status": "reported, not repaired -- another checkout's install is the operator's call",
        },
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()

    out = ROOT / "docs" / "repro" / "FULL_SUITE_TRIAGE.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fs = receipt["full_suite"]
    print(f"FULL  collected={fs['collected']} passed={fs['passed']} failed={fs['failed']} "
          f"skipped={fs['skipped']} exit={fs['exit_code']}")
    print(f"global run: {g.get('summary_line')}")
    print(f"clusters: {len(clusters)}  unknown: {len(unknown)}")
    for c in clusters:
        print(f"  {c['id']:<34} {c['category']} {c['category_name']:<32} tests={c['test_count']}")
    print(f"detector control separates: {control['separates']}")
    print(f"repository_green_allowed: {repo_green_allowed}")
    print(f"wrote {out}")
    return 0 if not unknown else 1


if __name__ == "__main__":
    sys.exit(main())
