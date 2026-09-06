#!/usr/bin/env python3
"""Where the 14 SFI2 selective stale escapes actually diverge. Observation only.

`SOURCE_FACT_IR_HELDOUT_V2` is a frozen FAIL. E5 confirmed 14 selective stale
escapes over 158 gate-power pairs; E6 found 14 divergences over 190
judged-supported pairs; the two sets are the same 14 lineages; and the typed
cross-check on those same 191 pairs was clean -- 0 under-invalidated over the
artifacts that had entered its denominator.

That 191/191 stands, and it does not mean what it was first read to mean. The
cross-check established completeness only over the artifacts and units that had
already entered its downstream denominator; it did not establish completeness of
the upstream change detector or the seeding stage. A unit the detector never
called changed is not an under-invalidation the cross-check could count -- it is
a member the defect removed from the set before the counting began. So the
correct reading is not "the delta knew and the executor disobeyed" but "the
delta's own denominator was downstream of the defect". This tool replays each of the 14
cases through the real production modules -- `akc_cir.semantic_diff`,
`akc_cir.recompilation`, `compiler.selective_build` -- and records, stage by
stage, the first point at which the required-to-rebuild artifact stops being
required.

**It does not infer the stage from the final stale artifact.** That an artifact
ended up carried forward and stale is the symptom the frozen receipt already
reports; asking "what does the final state look like" answers nothing new. This
tool instead calls the production functions in pipeline order and asks, at each
one, whether the artifact this case names is still marked as needing a rebuild:

    typed delta            `akc_cir.semantic_diff.diff_documents` --
                            is the unit's logical id in `changed_logical_ids`?
    dependency expansion    `DependencyGraph.impact_of` over that seed set --
                            is the artifact reached?
    rebuild request         `RecompilationPlan.to_rebuild` --
                            is the artifact in it?
    rebuild execution /
    carry-forward           `selective_build.run_pair`'s per-artifact branch --
                            rebuilt, or carried from `prior_state`?

Two stages named in the founder's pipeline description do not exist as
independent gates in this executor, and that absence is itself recorded rather
than papered over with a synthetic result: `rebuild_order` (the scheduler) only
reorders `plan.to_rebuild`, so it cannot remove a member from the set once
`plan_recompilation` has decided it; and `recompilation.verify_equivalence` (the
only thing that could serve as "candidate verification") is never called
anywhere on the production path -- `run_pair` writes `final[artifact]` straight
from the rebuild/carry-forward decision, so there is no activation step
distinct from that decision either.

**Read-only.** Nothing here edits `compiler/selective_build.py` or
`compiler/rebuild_equivalence.py`; the executor is called exactly as production
calls it and observed from outside. Nothing here is fetched: every payload comes
from `artifacts/development/sfi2_cache/`, content-addressed and already present,
and a case whose payload is not cached is reported as unresolved rather than
silently fetched or silently dropped.

**Scope.** The SFI2 cohort is spent. This tool may replay the 14 already-frozen
cases as many times as needed for diagnosis; nothing it finds may be used to
re-score SFI2 or to widen its cohort. It writes an immutable receipt under the
`sfi2-execution-forensic` stem and nothing else.
"""

from __future__ import annotations

import hashlib
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import selective_build as engine  # noqa: E402
from akc_cir.recompilation import StructuralPolicy, plan_recompilation  # noqa: E402
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402
from common import now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from payload_cache import PayloadCache  # noqa: E402
from provenance_document import provenance_document  # noqa: E402

SCHEMA = "tavonel.v2.forensic_sfi2_execution.v1"
STEM = "sfi2-execution-forensic"

RECEIPTS = NS / "receipts"
LINEAGES = NS / "artifacts" / "development" / "sfi2_lineages.json"
CACHE_ROOT = NS / "artifacts" / "development" / "sfi2_cache"
THIS_TOOL = Path(__file__).resolve()

#: The pipeline stages named in the task, in order. Only the first four are
#: independent gates in this executor -- see the module docstring for why the
#: last two are recorded as structurally absent rather than measured.
PIPELINE_STAGES: tuple[str, ...] = (
    "typed_delta",
    "dependency_expansion",
    "rebuild_request",
    "scheduler",
    "rebuild_execution",
    "carry_forward",
    "candidate_verification",
    "activation",
)

#: `scheduler` cannot remove a member from `plan.to_rebuild`, and
#: `candidate_verification` / `activation` are never reached by the production
#: path at all (see module docstring). They are excluded from "first divergence
#: point" search, not because they are exempt, but because they have no
#: independent required/not-required signal to observe.
GATED_STAGES: tuple[str, ...] = (
    "typed_delta",
    "dependency_expansion",
    "rebuild_request",
    "rebuild_execution",
)


class CacheMiss(RuntimeError):
    """A revision this case needs is not in the local content-addressed cache."""


class UnsupportedFamily(RuntimeError):
    """A lineage family this tool does not know how to reconstruct a URL for."""


def _git_url(lineage: dict[str, Any], version: str) -> str:
    return "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        lineage["owner"], lineage["repo"], version, lineage["path"]
    )


def _ecfr_url(lineage: dict[str, Any], version: str) -> str:
    return "https://www.ecfr.gov/api/versioner/v1/full/{}/title-{}.xml?part={}&section={}".format(
        version, lineage["title"], lineage["part"], lineage["identifier"]
    )


#: Mirrors `tools/run_vbc2_acquire.py`'s URL construction for the two families
#: the 14 cases actually use, so a cache hit is looked up under the same key
#: acquisition wrote it under. Not imported from there: that module enumerates
#: revisions over the network to build these URLs, and this tool must not touch
#: the network at all.
URL_BUILDERS = {
    "git_docs": _git_url,
    "regulation_ecfr": _ecfr_url,
}


def load_lineages() -> dict[str, dict[str, Any]]:
    import json

    rows = json.loads(LINEAGES.read_text(encoding="utf-8"))["lineages"]
    return {row["lineage_id"]: row for row in rows}


def load_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The 14 E5-confirmed cases, from the most recent frozen SFI2 receipt.

    The receipt is read for its `rebuild` block only. Nothing here reruns SFI2
    or changes any of its counts.
    """
    import json

    candidates = sorted(RECEIPTS.glob("sfi2-native-provenance--*.json"))
    if not candidates:
        raise RuntimeError("no sfi2-native-provenance--*.json receipt exists to trace cases from")
    source = candidates[-1]
    body = json.loads(source.read_text(encoding="utf-8"))
    rebuild = body["rebuild"]
    e5 = rebuild["E5_confirmed_selective_stale_escape"]["confirmed"]
    e6 = rebuild["E6_exact_selective_vs_clean_equivalence"]["divergent"]
    meta = {
        "source_receipt": rel(source),
        "source_receipt_sha256": sha_file(source),
        "e5_confirmed_count": len(e5),
        "e6_divergent_count": len(e6),
        "e5_lineages": sorted(row["lineage_id"] for row in e5),
        "e6_lineages": sorted(row["lineage_id"] for row in e6),
        "e5_and_e6_are_the_same_lineage_set": (
            {row["lineage_id"] for row in e5} == {row["lineage_id"] for row in e6}
        ),
        "typed_cross_check": rebuild.get("typed_cross_check"),
    }
    return e5, meta


def fetch_payload(cache: PayloadCache, lineage: dict[str, Any], version: str) -> bytes:
    family = lineage["family"]
    builder = URL_BUILDERS.get(family)
    if builder is None:
        raise UnsupportedFamily(
            f"no cache-only URL builder for family {family!r} (lineage {lineage['lineage_id']!r})"
        )
    url = builder(lineage, version)

    def _refuse(_url: str) -> bytes:
        raise CacheMiss(
            f"{lineage['lineage_id']!r} @ {version!r} is not in {rel(CACHE_ROOT)}: {url}"
        )

    body, _digest = cache.payload(url, _refuse)
    return body


def build_document(lineage: dict[str, Any], version: str, raw: bytes) -> dict[str, Any]:
    return provenance_document(
        source_family=lineage["family"],
        source_id=lineage["lineage_id"],
        version_id=version,
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at=None,
        valid_from=None,
        licence=lineage.get("licence", "unknown"),
    )


def _first_divergence_sample(before: str, after: str, width: int = 60) -> dict[str, Any]:
    """Where the two raw texts first part company, with a little context."""
    limit = min(len(before), len(after))
    cut = next((index for index in range(limit) if before[index] != after[index]), limit)
    low = max(0, cut - 20)
    seg_before = before[low : low + width]
    seg_after = after[low : low + width]
    return {
        "at": cut,
        "before": seg_before,
        "after": seg_after,
        "before_non_ascii_names": [
            unicodedata.name(c, f"U+{ord(c):04X}") for c in seg_before if not c.isascii()
        ],
        "after_non_ascii_names": [
            unicodedata.name(c, f"U+{ord(c):04X}") for c in seg_after if not c.isascii()
        ],
    }


def trace_case(
    lineage: dict[str, Any], case: dict[str, Any], cache: PayloadCache
) -> dict[str, Any]:
    """Replay one case through the real production stages and record each one.

    Every stage below calls the production function directly -- nothing about
    `diff_documents`, `plan_recompilation` or `run_pair` is reimplemented or
    patched. The only thing this function adds is recording, at each stage,
    whether the artifact this case names is still marked as needing a rebuild.
    """
    lineage_id = case["lineage_id"]
    before_version = case["before_version"]
    after_version = case["after_version"]
    artifacts = list(case.get("artifacts") or case.get("keys") or [])

    try:
        before_raw = fetch_payload(cache, lineage, before_version)
        after_raw = fetch_payload(cache, lineage, after_version)
    except (CacheMiss, UnsupportedFamily) as error:
        return {
            "lineage_id": lineage_id,
            "before_version": before_version,
            "after_version": after_version,
            "artifacts": artifacts,
            "resolved": False,
            "unresolved_reason": f"{type(error).__name__}: {error}",
            "first_divergence_stage": None,
        }

    before = build_document(lineage, before_version, before_raw)
    after = build_document(lineage, after_version, after_raw)

    before_deps, _ = engine.inventory_and_dependencies(before)
    after_deps, _ = engine.inventory_and_dependencies(after)
    before_units, before_shape = engine.snapshots(before)
    after_units, after_shape = engine.snapshots(after)

    #: stage 1 -- typed delta. The real `diff_documents`, called once.
    diff = diff_documents(
        before_sha256=before["source_digest"],
        after_sha256=after["source_digest"],
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=after["source_id"],
    )

    #: stage 2 -- dependency expansion, and stage 3 -- rebuild request. Both
    #: come out of the one real `plan_recompilation` call; `to_rebuild` is the
    #: rebuild request, and the graph traversal it performs internally is the
    #: dependency expansion. The graph is rebuilt here the same way
    #: `selective_build.run_pair` builds it, from the same two inventories.
    graph = engine.graph_for(before_deps, after_deps)
    union_inventory = sorted({*before_deps, *after_deps})
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=union_inventory,
        structural_policy=StructuralPolicy.PRECISE,
    )

    #: stage 4 -- rebuild execution / carry-forward. The real `run_pair`,
    #: called once, exactly as `judge_pair` and `score_sfi2` call it.
    selective = engine.run_pair(before, after)
    rebuilt_set = set(selective["selective_rebuild_set"])
    carried_set = set(selective["carried_forward_set"])

    clean_before = engine.build_all(before)
    clean_after = engine.build_all(after)

    per_artifact: list[dict[str, Any]] = []
    case_first_stage: str | None = None
    case_first_evidence: dict[str, Any] | None = None

    for artifact in artifacts:
        logical = artifact.split("section:", 1)[-1] if artifact.startswith("section:") else None
        moved = clean_before.get(artifact) != clean_after.get(artifact)

        before_text = next((u.text for u in before_units if u.logical_id == logical), None)
        after_text = next((u.text for u in after_units if u.logical_id == logical), None)
        text_differs = (
            before_text is not None and after_text is not None and before_text != after_text
        )
        identity_before = next(
            (u.identity_text for u in before_units if u.logical_id == logical), None
        )
        identity_after = next(
            (u.identity_text for u in after_units if u.logical_id == logical), None
        )

        modified_claim = any(
            change.kind.value == "modified_claim" and change.logical_id == logical
            for change in diff.changes
        )

        plan_target = next((t for t in plan.targets if t.artifact_id == artifact), None)
        #: `plan_recompilation` folds "reached by the graph traversal" straight
        #: into a STALE or UNRESOLVED target with no filter in between, so
        #: dependency_expansion and rebuild_request read the same underlying
        #: state here -- that identity is itself part of the finding: this
        #: executor has no separate gate between "the graph says it is
        #: affected" and "the plan says rebuild it".
        reached_by_traversal = plan_target is not None and plan_target.state.value != "current"
        stage_required = {
            "typed_delta": logical is not None and logical in diff.changed_logical_ids,
            "dependency_expansion": reached_by_traversal,
            "rebuild_request": artifact in plan.to_rebuild,
            "rebuild_execution": artifact in rebuilt_set,
        }

        first_stage = None
        if moved:
            for stage in GATED_STAGES:
                if not stage_required[stage]:
                    first_stage = stage
                    break

        row: dict[str, Any] = {
            "artifact": artifact,
            "logical_id": logical,
            "clean_before_moved_from_clean_after": moved,
            "raw_text_differs": text_differs,
            "identity_text_equal": (
                identity_before == identity_after if identity_before is not None else None
            ),
            "modified_claim_emitted": modified_claim,
            "stage_marks_required_to_rebuild": stage_required,
            "plan_target_state": plan_target.state.value if plan_target else None,
            "plan_target_reason": plan_target.reason if plan_target else None,
            "carried_forward": artifact in carried_set,
            "rebuilt": artifact in rebuilt_set,
            "first_divergence_stage": first_stage,
        }
        if text_differs and before_text is not None and after_text is not None:
            row["first_text_divergence"] = _first_divergence_sample(before_text, after_text)
        per_artifact.append(row)

        if first_stage is not None and case_first_stage is None:
            case_first_stage = first_stage
            case_first_evidence = row

    return {
        "lineage_id": lineage_id,
        "before_version": before_version,
        "after_version": after_version,
        "artifacts": per_artifact,
        "resolved": True,
        "unresolved_reason": None,
        "diff_content_changed": diff.content_changed,
        "diff_change_id": diff.change_id,
        "diff_structural_change_present": diff.structural_change_present,
        "diff_unresolved_count": len(diff.unresolved),
        "first_divergence_stage": case_first_stage,
        "first_divergence_evidence": case_first_evidence,
    }


def main() -> int:
    started = now()
    clock = time.perf_counter()

    cases, meta = load_cases()
    lineages = load_lineages()
    cache = PayloadCache(CACHE_ROOT, "cache-only-forensic-replay")

    rows: list[dict[str, Any]] = []
    for case in cases:
        lineage = lineages.get(case["lineage_id"])
        if lineage is None:
            rows.append(
                {
                    "lineage_id": case["lineage_id"],
                    "before_version": case["before_version"],
                    "after_version": case["after_version"],
                    "artifacts": case.get("artifacts") or case.get("keys") or [],
                    "resolved": False,
                    "unresolved_reason": "lineage_id not present in sfi2_lineages.json",
                    "first_divergence_stage": None,
                }
            )
            continue
        rows.append(trace_case(lineage, case, cache))

    resolved = [row for row in rows if row["resolved"]]
    unresolved = [row for row in rows if not row["resolved"]]

    distribution: dict[str, int] = {}
    for row in resolved:
        stage = row["first_divergence_stage"]
        key = stage if stage is not None else "no_divergence_found"
        distribution[key] = distribution.get(key, 0) + 1

    body: dict[str, Any] = {
        "schema": SCHEMA,
        "what_this_is": (
            "a stage-by-stage replay of the 14 SFI2 E5-confirmed selective stale "
            "escapes through the real production functions (diff_documents, "
            "plan_recompilation, run_pair), recording the first pipeline stage at "
            "which each required-to-rebuild artifact stops being marked as such."
        ),
        "what_this_is_not": [
            "a rescore of SOURCE_FACT_IR_HELDOUT_V2. That receipt's counts stand "
            "exactly as executed and are read here, not recomputed.",
            "an inference from the final stale artifact. Every row below is a "
            "direct observation of an intermediate stage's output.",
            "usable to widen or re-admit the SFI2 cohort. The cohort is spent; "
            "these 14 cases are development fixtures from this point forward.",
        ],
        "pipeline_stages_named_in_the_task": list(PIPELINE_STAGES),
        "pipeline_stages_gated_in_this_executor": list(GATED_STAGES),
        "pipeline_stages_not_independent_gates": {
            "scheduler": (
                "rebuild_order() only reorders plan.to_rebuild for dependency-safe "
                "execution order; it cannot remove or add a member, so it cannot be "
                "the first point of divergence"
            ),
            "candidate_verification": (
                "recompilation.verify_equivalence() exists but is never called on "
                "the production path (selective_build.run_pair does not call it, "
                "nor does rebuild_equivalence.judge_pair); there is no verification "
                "step between rebuild/carry-forward and the final state"
            ),
            "activation": (
                "run_pair writes final[artifact] directly from the rebuild/"
                "carry-forward branch in the same loop iteration; there is no "
                "separate activation step to diverge at"
            ),
        },
        "cases_source": meta,
        "cases_considered": len(cases),
        "cases_resolved": len(resolved),
        "cases_unresolved": len(unresolved),
        "unresolved": unresolved,
        "first_divergence_stage_distribution": distribution,
        "single_root_cause": len(distribution) == 1,
        "cases": rows,
        "cache_stats": cache.stats(),
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.perf_counter() - clock, 3),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(STEM, body, tool=THIS_TOOL, protocol=None)
    print(
        f"cases considered={len(cases)} resolved={len(resolved)} "
        f"unresolved={len(unresolved)} distribution={distribution}"
    )
    print(f"written: {written['receipt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
