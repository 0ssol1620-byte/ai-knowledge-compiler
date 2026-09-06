#!/usr/bin/env python3
"""SOURCE_FACT_IR_HELDOUT_V1 (SFI1) — parallel acquisition and IR extraction.

Parallel read/compute workers, one deterministic reducer, one writer. The shape
is the one the VBC2 executor established and SFH1 reused, and it is here for the
same reason: completion order correlates with latency, payload size and provider
health, so admitting in arrival order would make the cohort a function of the
network. Results are re-sorted into the frozen sampling order before a single
admission decision is taken.

A worker sees one lineage and one payload callable. It does not know the family
quotas, the admitted count, any other lineage's result, or any extraction
outcome but its own.

What this tool deliberately does not do
---------------------------------------
It does not score, gate or write a receipt. SFH1 and its predecessor lost their
held-out status because an execution against real cohort lineages produced and
exposed outcome metrics before the protocol was frozen, and a smoke run is an
execution. So:

* `--dry-run` reports the FRAME — which lineages are eligible, the quotas, the
  family composition, the digests — and acquires nothing. Frame composition is
  not an outcome; a classification count is.
* the acquire path refuses to start unless the protocol file exists, so it
  cannot be run before the freeze;
* the acquire path refuses to start unless extractors are registered. An empty
  extractor set would find no source facts and score every document clean,
  which is the worst failure available to this study;
* the artifact it writes carries per-lineage facts and admission codes. Verdict,
  gates and summary belong to the scoring tool that runs against the frozen
  protocol, not here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "endpoint", "compiler"):
    sys.path.insert(0, str(NS / _sub))
#: NS itself, not NS/source_fact_ir: the IR must be imported as
#: `source_fact_ir.ir` and never as a bare `ir`, or a lane that registers through
#: the package name and a lane that registers through the bare name end up with
#: two module objects and two registries, and each sees the other's kinds as
#: unclaimed.
sys.path.insert(0, str(NS))

import sources_sfi1 as frame_module  # noqa: E402

#: Lanes 2/3/4 are writing the extractors concurrently, so the IR may not import
#: yet. Defensive here, fatal at the point of use: a missing extractor set is a
#: refusal, never a quiet run with nothing registered.
try:
    from source_fact_ir import ir
except Exception as _error:  # pragma: no cover - exercised only mid-integration
    ir = None  # type: ignore[assignment]
    _IR_IMPORT_ERROR: str | None = f"{type(_error).__name__}: {_error}"
else:
    _IR_IMPORT_ERROR = None

PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V1.yaml"
CACHE = NS / "artifacts" / "development" / "sfi1_cache"
OUT = NS / "artifacts" / "development" / "sfi1"

USER_AGENT = "tavonel-eval-v2 source-fact-ir (research; contact via repository)"

LISTING_FAIL = "LISTING_FAILED"
TOO_FEW = "TOO_FEW_REVISIONS"
NO_DIFF = "NO_RAW_DIFFERENCE"
PAYLOAD_FAIL = "PAYLOAD_UNAVAILABLE"
TOO_LARGE = "PAYLOAD_TOO_LARGE_TO_CLASSIFY"
EMPTY_CANON = "CANONICALISATION_EMPTY"
NO_FACTS = "NO_SOURCE_FACTS_EXTRACTED"
BEYOND_QUOTA = "BEYOND_FAMILY_QUOTA"

#: Lineages evaluated between reductions. Only affects how many extra lineages
#: are looked at past the stopping point; those are BEYOND_FAMILY_QUOTA and
#: cannot change an admission.
CHUNK = 96


class ExtractorsMissing(RuntimeError):
    """No extractor is registered, so nothing would be looked for."""


# --- preconditions ------------------------------------------------------------


def extractor_state() -> dict[str, Any]:
    """What the IR registry currently offers. Reported, never assumed."""
    if ir is None:
        return {
            "importable": False,
            "error": _IR_IMPORT_ERROR,
            "registered_kinds": [],
            "unclaimed_kinds": [],
        }
    return {
        "importable": True,
        "error": None,
        "registered_kinds": list(ir.registered_kinds()),
        "unclaimed_kinds": list(ir.unclaimed_kinds()),
    }


def require_extractors() -> dict[str, Any]:
    """Refuse rather than run empty.

    An unregistered kind is a declared gap and is fine — `unclaimed_kinds()`
    exists to report it. An empty registry is different: every document would
    yield zero source facts, every scope would look complete, and the run would
    report a clean pass for a build that looks for nothing.
    """
    #: Importing an extractor module is what registers it, and nothing else in
    #: this process imports them. Without this the registry is empty at the
    #: moment it is checked, and the refusal below fires on a build that has
    #: every extractor it needs — a false negative guarding against a false
    #: pass. `load_lanes` is the single place that knows which modules exist and
    #: raises if the core one does not.
    try:
        from source_fact_ir.compile import load_lanes

        load_lanes()
    except ImportError as error:
        raise ExtractorsMissing(
            f"the extractor lanes did not import ({error}). SFI1 cannot run "
            "without them; a run with an empty registry scores every document "
            "clean, which is a false pass rather than a result."
        ) from error

    state = extractor_state()
    if not state["importable"]:
        raise ExtractorsMissing(
            "source_fact_ir.ir did not import (" + str(state["error"]) + "). "
            "SFI1 cannot run without the IR contract."
        )
    if not state["registered_kinds"]:
        raise ExtractorsMissing(
            "no extractor is registered with source_fact_ir.ir. A run with an empty "
            "registry finds no source facts and scores every document clean; that is a "
            "false pass, not a result. Register the lane 2/3/4 extractors first."
        )
    return state


def require_frozen_protocol(protocol: Path = PROTOCOL) -> None:
    """Acquisition may not precede the protocol freeze.

    This is the guard that the two demoted studies did not have. It is cheap and
    it is the whole difference between a smoke run and a spent corpus.
    """
    if not protocol.exists():
        raise RuntimeError(
            f"{protocol} does not exist. SFI1 acquisition runs after the protocol freeze, "
            "never before: an execution against real cohort lineages spends their held-out "
            "property whether or not its numbers are kept."
        )


# --- worker -------------------------------------------------------------------


def _default_revisions_for(lineage: dict[str, Any]) -> list[dict[str, str]]:
    #: Imported inside the call so this module can be imported, and its reducer
    #: tested, without pulling in the acquisition stack or touching a network.
    import run_vbc2_acquire as serial

    return serial.ENUMERATORS[lineage["family"]](lineage)


def _default_document_for(
    lineage: dict[str, Any], revision: dict[str, str], raw: bytes
) -> dict[str, Any]:
    from canonical_document import canonical_document

    return canonical_document(
        source_family=lineage["family"],
        source_id=lineage["lineage_id"],
        version_id=revision["version"],
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at=revision.get("known_at"),
        valid_from=revision.get("known_at"),
        licence=lineage.get("licence", "unknown"),
    )


def evaluate(
    lineage: dict[str, Any],
    payload_for: Callable[[dict[str, Any], dict[str, str]], tuple[bytes, str]],
    *,
    revisions_for: Callable[[dict[str, Any]], list[dict[str, str]]] | None = None,
    document_for: Callable[..., dict[str, Any]] | None = None,
    extract: Callable[..., list[Any]] | None = None,
) -> dict[str, Any]:
    """One lineage: the newest adjacent revision pair whose raw bytes differ.

    The three callables are injectable so a fixture can drive this without a
    network and without the canonicalisation stack. Their defaults are the
    frozen enumerators the predecessor studies used — a second enumeration
    implementation is exactly the defect INC-V2-007 and INC-V2-009 record.
    """
    revisions_for = revisions_for or _default_revisions_for
    document_for = document_for or _default_document_for
    if extract is None:
        require_extractors()
        extract = ir.extract_all  # type: ignore[union-attr]

    try:
        revisions = revisions_for(lineage)
    except Exception as error:
        return {"code": LISTING_FAIL, "detail": type(error).__name__}
    if len(revisions) < 2:
        return {"code": TOO_FEW, "revisions_seen": len(revisions)}

    seen: dict[str, tuple[bytes, str]] = {}

    def payload(revision: dict[str, str]) -> tuple[bytes, str]:
        if revision["version"] not in seen:
            seen[revision["version"]] = payload_for(lineage, revision)
        return seen[revision["version"]]

    for index in range(len(revisions) - 1):
        after, before = revisions[index], revisions[index + 1]
        try:
            after_raw, after_digest = payload(after)
            before_raw, before_digest = payload(before)
        except Exception as error:
            return {"code": PAYLOAD_FAIL, "detail": type(error).__name__}
        if after_digest == before_digest:
            continue
        largest = max(len(after_raw), len(before_raw))
        if largest > frame_module.MAX_PAYLOAD_BYTES:
            #: reported, never silently skipped. The count is part of the result.
            return {"code": TOO_LARGE, "bytes": largest}
        return _extract_pair(lineage, after, before, after_raw, before_raw, document_for, extract)
    return {"code": NO_DIFF, "revisions_seen": len(revisions)}


def _extract_pair(
    lineage: dict[str, Any],
    after: dict[str, str],
    before: dict[str, str],
    after_raw: bytes,
    before_raw: bytes,
    document_for: Callable[..., dict[str, Any]],
    extract: Callable[..., list[Any]],
) -> dict[str, Any]:
    after_document = document_for(lineage, after, after_raw)
    before_document = document_for(lineage, before, before_raw)
    if not after_document.get("units") and not before_document.get("units"):
        return {"code": EMPTY_CANON, "after": after["version"], "before": before["version"]}

    after_facts = extract(raw=after_raw, document=after_document)
    before_facts = extract(raw=before_raw, document=before_document)
    if not after_facts and not before_facts:
        #: The extractors ran and found nothing. Distinct from an empty registry,
        #: which never reaches here, and distinct from a clean document, which
        #: would still yield CONTENT_TEXT facts.
        return {"code": NO_FACTS, "after": after["version"], "before": before["version"]}

    return {
        "code": None,
        "family": lineage["family"],
        "lineage_id": lineage["lineage_id"],
        "suffix": lineage["suffix"],
        "after_version": after["version"],
        "before_version": before["version"],
        "adjacent": True,
        "after_bytes": len(after_raw),
        "before_bytes": len(before_raw),
        "facts": {
            "after": [fact.as_dict() for fact in after_facts],
            "before": [fact.as_dict() for fact in before_facts],
        },
    }


# --- reducer ------------------------------------------------------------------


def reduce_results(
    lineages: list[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Frozen order in, deterministic admission out. Arrival order never reaches here.

    The loop walks `lineages`, never `results`, so the reduction is a pure
    function of the frame order and the per-lineage results. Shuffling the
    insertion order of `results` cannot move an admission, and
    `reduction_digest` is the check that says so.
    """
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    per_family: dict[str, int] = {family: 0 for family in frame_module.FAMILY_QUOTA}
    considered = 0

    for lineage in lineages:
        found = results.get(lineage["lineage_id"])
        if found is None:
            continue
        considered += 1
        if found.get("code") is not None:
            rejected.append(
                {
                    "lineage_id": lineage["lineage_id"],
                    "family": lineage["family"],
                    "code": found["code"],
                }
            )
            continue
        family = lineage["family"]
        if per_family.get(family, 0) >= frame_module.FAMILY_QUOTA.get(family, 0):
            rejected.append(
                {"lineage_id": lineage["lineage_id"], "family": family, "code": BEYOND_QUOTA}
            )
            continue
        per_family[family] = per_family.get(family, 0) + 1
        admitted.append(found)

    return {
        "admitted": admitted,
        "rejected": rejected,
        "by_family": per_family,
        "considered": considered,
        "quota_met": all(
            per_family.get(family, 0) >= quota
            for family, quota in frame_module.FAMILY_QUOTA.items()
        ),
    }


def reduction_digest(reduced: dict[str, Any]) -> str:
    """Pins the cohort composition — who was admitted, who was coded out, why.

    Over admission structure only. No fact, no state count and no verdict enters
    it, so it is reproducible from a rerun that admitted the same lineages and
    it is not an outcome.
    """
    payload = {
        "admitted": [row["lineage_id"] for row in reduced["admitted"]],
        "rejected": sorted((row["lineage_id"], row["code"]) for row in reduced["rejected"]),
        "by_family": dict(sorted(reduced["by_family"].items())),
        "considered": reduced["considered"],
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def rejected_by_code(reduced: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in reduced["rejected"]:
        counts[row["code"]] = counts.get(row["code"], 0) + 1
    return dict(sorted(counts.items()))


# --- frame report (acquires nothing) ------------------------------------------


def declaration_report() -> dict[str, Any]:
    """Everything the frame declares before the lineage expansion is sealed.

    The roots, the quotas, the bounds and the size of the spent exclusion are
    all fixed by declaration, so they can be read — and frozen — before a single
    lineage identity has been enumerated. This is the honest report for the
    window between "the frame module exists" and "the freeze step has run": it
    does not guess a lineage count, and it says which one it is missing.
    """
    spent = frame_module.spent_lineages()
    return {
        "protocol_id": frame_module.PROTOCOL_ID,
        "protocol_frozen": PROTOCOL.exists(),
        "lineage_expansion": {
            "sealed": frame_module.FRAME.exists(),
            "path": str(frame_module.FRAME),
            "reason": (
                "expansion needs the network and runs after the protocol freeze; this "
                "lane may not run it"
            ),
        },
        "roots": {
            "git_docs": len(frame_module.GIT_ROOTS),
            "regulation_ecfr": len(frame_module.ECFR_ROOTS),
            "encyclopedia_wikipedia": len(frame_module.WIKIPEDIA_CATEGORY_ROOTS),
            "sec_edgar": len(frame_module.SEC_ROOTS),
        },
        "spent_exclusion": {
            "lineages": len(spent),
            "derived_from": list(frame_module.SPENT_SOURCES),
        },
        "forensic_excluded": list(frame_module.FORENSIC_LINEAGES),
        "quota_digest": frame_module.quota_digest(),
        "family_quota": dict(frame_module.FAMILY_QUOTA),
        "family_share": dict(frame_module.FAMILY_SHARE),
        "primary_target": frame_module.PRIMARY_TARGET,
        "floor": frame_module.FLOOR,
        "families_required": frame_module.FAMILIES_REQUIRED,
        "unexercised_families": dict(frame_module.UNEXERCISED_FAMILIES),
        "quota_basis": dict(frame_module.QUOTA_BASIS),
        "history_bounds": dict(frame_module.HISTORY),
        "payload_bound": _payload_bound(),
        "order": f"ascending sha256 of (lineage_id + {frame_module.ORDER_SALT!r})",
        "extractors": extractor_state(),
        "note": "declaration only; nothing here was fetched, canonicalised or classified",
    }


def _payload_bound() -> dict[str, Any]:
    return {
        "max_payload_bytes": frame_module.MAX_PAYLOAD_BYTES,
        "basis": frame_module.MAX_PAYLOAD_BASIS,
        "insensitive_range_bytes": list(frame_module.MAX_PAYLOAD_INSENSITIVE_RANGE),
        "excluded_fraction_in_sfh1": frame_module.MAX_PAYLOAD_EXCLUDED_FRACTION_IN_SFH1,
        "explicitly_not_basis": frame_module.MAX_PAYLOAD_NOT_BASIS,
    }


def frame_report(source: Path | None = None) -> dict[str, Any]:
    """The frame, and only the frame. No fetch, no canonical document, no fact.

    Everything here is a property of the declaration: which lineages are
    eligible, how they are ordered, what the quotas are and what the spent
    exclusion removed. None of it can be produced by acquiring anything, which
    is why it is safe to look at before the freeze.
    """
    built = frame_module.build_frame(source)
    lineages = built["lineages"]
    dropped_by_code: dict[str, int] = {}
    for row in built["dropped"]:
        dropped_by_code[row["code"]] = dropped_by_code.get(row["code"], 0) + 1
    return {
        "protocol_id": frame_module.PROTOCOL_ID,
        "protocol_frozen": PROTOCOL.exists(),
        "source": built["source"],
        "eligible": len(lineages),
        "family_composition": frame_module.family_composition(lineages),
        "dropped_by_code": dict(sorted(dropped_by_code.items())),
        "frame_digest": frame_module.frame_digest(lineages),
        "quota_digest": frame_module.quota_digest(),
        "family_quota": dict(frame_module.FAMILY_QUOTA),
        "family_share": dict(frame_module.FAMILY_SHARE),
        "primary_target": frame_module.PRIMARY_TARGET,
        "floor": frame_module.FLOOR,
        "families_required": frame_module.FAMILIES_REQUIRED,
        "unexercised_families": dict(frame_module.UNEXERCISED_FAMILIES),
        "quota_basis": dict(frame_module.QUOTA_BASIS),
        "history_bounds": dict(frame_module.HISTORY),
        "payload_bound": _payload_bound(),
        "order": f"ascending sha256 of (lineage_id + {frame_module.ORDER_SALT!r})",
        "extractors": extractor_state(),
        "note": "frame composition only; nothing here was fetched, canonicalised or classified",
    }


# --- driver -------------------------------------------------------------------


def acquire(
    lineages: list[dict[str, Any]],
    payload_for: Callable[[dict[str, Any], dict[str, str]], tuple[bytes, str]],
    *,
    workers: int,
    chunk: int = CHUNK,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Parallel evaluation, reduced after every chunk so a long run is observable."""
    results: dict[str, dict[str, Any]] = {}
    reduced = reduce_results(lineages, results)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for start in range(0, len(lineages), chunk):
            batch = lineages[start : start + chunk]
            futures = {
                lineage["lineage_id"]: executor.submit(evaluate, lineage, payload_for)
                for lineage in batch
            }
            for lineage_id, future in futures.items():
                try:
                    results[lineage_id] = future.result()
                except Exception as error:
                    results[lineage_id] = {
                        "code": PAYLOAD_FAIL,
                        "detail": f"{type(error).__name__}: {error}",
                    }
            reduced = reduce_results(lineages, results)
            progress(
                f"considered {reduced['considered']}  admitted {len(reduced['admitted'])}  "
                f"{reduced['by_family']}"
            )
            if reduced["quota_met"]:
                break
    return reduced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the frame and exit. Acquires nothing and classifies nothing.",
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--chunk", type=int, default=CHUNK)
    parser.add_argument("--limit", type=int, default=None)
    arguments = parser.parse_args(argv)

    if arguments.dry_run:
        try:
            report = frame_report()
        except frame_module.FrameNotFrozen:
            #: Not a fallback: the declaration report says, in its own output,
            #: that the lineage expansion is missing and refuses to invent a
            #: count for it. The non-zero exit keeps the unsealed state visible
            #: to whatever ran this.
            print(json.dumps(declaration_report(), indent=2, ensure_ascii=False))
            return 3
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    #: Both guards before anything is fetched. Order matters: the protocol guard
    #: is the one that protects the corpus, so it goes first.
    require_frozen_protocol()
    extractors = require_extractors()

    import fetch_p4c_corpus as p4c
    import fetch_p4g_corpus as p4g
    import run_vbc2_acquire as serial
    from common import now, rel, sha_file
    from http_pool import HttpPool, install
    from payload_cache import PayloadCache

    OUT.mkdir(parents=True, exist_ok=True)
    started = now()
    clock = time.time()

    pool = HttpPool()
    install(pool, p4c, p4g, USER_AGENT)
    cache = PayloadCache(CACHE, sha_file(NS / "source_fact_ir" / "ir.py"))

    def payload_for(lineage: dict[str, Any], revision: dict[str, str]) -> tuple[bytes, str]:
        return cache.payload(revision["url"], lambda _url: serial._payload(lineage, revision))

    lineages = frame_module.frame()
    if arguments.limit:
        lineages = lineages[: arguments.limit]

    reduced = acquire(lineages, payload_for, workers=arguments.workers, chunk=arguments.chunk)

    #: Cohort and facts, no verdict. Scoring runs against the frozen protocol in
    #: its own tool and writes the receipt; splitting them is what keeps an
    #: acquisition run from being able to publish a result.
    body = {
        "schema": "tavonel.v2.source_fact_ir_heldout.acquisition.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "split": "held_out",
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "frame": {
            "source": rel(frame_module.FRAME),
            "candidates": len(lineages),
            "digest": frame_module.frame_digest(lineages),
            "quota_digest": frame_module.quota_digest(),
            "order": f"ascending sha256 of (lineage_id + {frame_module.ORDER_SALT!r})",
        },
        "extractors": extractors,
        "lineages_considered": reduced["considered"],
        "by_family": reduced["by_family"],
        "rejected": sorted(reduced["rejected"], key=lambda row: (row["code"], row["lineage_id"])),
        "rejected_by_code": rejected_by_code(reduced),
        "reduction_digest": reduction_digest(reduced),
        "admitted": reduced["admitted"],
        "http": pool.stats(),
        "cache": cache.stats(),
    }
    target = OUT / "sfi1_acquisition.json"
    target.write_text(
        json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"written": rel(target), "sha256": sha_file(target)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
