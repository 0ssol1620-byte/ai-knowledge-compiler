#!/usr/bin/env python3
"""SFI2 acquisition: native provenance documents, and a rebuild for E5 and E6.

Two things make this different from `sfi1_worker.py`, and both come straight
from the founder's ruling of 2026-08-23.

**Documents come from the native canonicaliser.** `provenance_document` records
the source span of every unit as it emits the text, so a witness survives markup
stripping, whitespace normalisation, entity decoding and block composition by
construction. Nothing searches canonical text back inside raw bytes anywhere
below this line; `_locate` is gone from the extractor entirely.

**Every pair is rebuilt while its bytes are in hand.** V1 failed partly because
E5 and E6 reported SKIPPED_NEVER_EXERCISED — nothing in that run rebuilt an
artifact, so the two questions INC-V2-028 raised had no held-out evidence in
either direction. The ruling forbids that outcome, and the only place a rebuild
is cheap is here, where the raw payloads and both documents already exist. A
separate later pass would have to re-materialise them, which means either
another network walk or a second enumeration implementation, and INC-V2-007 and
INC-V2-009 record what a second enumeration implementation costs.

This module is a driver, not a fork. **Admission is imported** — the frozen
order, the per-lineage evaluation (`base.evaluate`), the deterministic reduction
(`base.reduce_results`) and the rejection codes are `sfi1_worker`'s, used
unchanged. Two implementations of the admission rule would diverge with nothing
to detect it, which is the outcome being avoided.

What is rewritten here is the thread-pool loop, and only because
`sfi1_worker.acquire` calls `evaluate` positionally and offers no way to pass a
canonicaliser or an extractor. That loop owns scheduling, chunk size and
progress printing; none of the three can move an admission. `acquire` below
says what was considered instead and why it was rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import rebuild_equivalence as reb  # noqa: E402
import sfi1_worker as base  # noqa: E402
import sources_sfi2 as frame_module  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V2.yaml"
CACHE = NS / "artifacts" / "development" / "sfi2_cache"
OUT = NS / "artifacts" / "development" / "sfi2"

USER_AGENT = "tavonel-eval-v2 source-fact-ir-v2 (research; contact via repository)"


class NotFrozen(RuntimeError):
    """Acquiring against an unfrozen protocol spends the corpus for nothing."""


def require_frozen_protocol() -> dict[str, Any]:
    """The freeze receipt, or a refusal, before one fresh lineage is read.

    The founder's ordering is explicit: *integrate deterministically, freeze
    SOURCE_FACT_IR_HELDOUT_V2 before reading any fresh lineage, then score once.*
    Checking it here rather than in the scorer is what makes it enforceable — by
    the time the scorer runs the corpus has already been spent.
    """
    freezes = sorted((NS / "receipts").glob("sfi2-protocol-freeze--*.json"))
    if not freezes:
        raise NotFrozen(
            "no sfi2-protocol-freeze receipt exists. The protocol is frozen before "
            "acquisition, not after it"
        )
    from common import sha_file

    body = json.loads(freezes[-1].read_text(encoding="utf-8"))
    actual = sha_file(PROTOCOL)
    if body.get("protocol_sha256") != actual:
        raise NotFrozen(
            f"the protocol has moved since it was frozen: {actual} is not "
            f"{body.get('protocol_sha256')}"
        )
    return body


def require_shared_admission_constants() -> None:
    """The imported driver decides admission from V1's frame module. Check it.

    `sfi1_worker.evaluate` bounds payloads and `sfi1_worker.reduce_results` fills
    family quotas from `sfi1_worker.frame_module`, which is `sources_sfi1`. V2
    carries both across deliberately unchanged — quotas moved to fit an observed
    yield are not quotas — so reusing the driver is correct exactly as long as
    they are still equal.

    That is a real coupling and it is checked rather than trusted. If the two
    ever diverged the run would collect one cohort while every declaration named
    another, and nothing downstream could see the difference. Rebinding the
    driver's module global instead would be worse: a mutated import is the shape
    of defect INC-V2-029 records, and it would be invisible in the receipt.
    """
    mismatches = [
        (name, theirs, ours)
        for name, theirs, ours in (
            (
                "MAX_PAYLOAD_BYTES",
                base.frame_module.MAX_PAYLOAD_BYTES,
                frame_module.MAX_PAYLOAD_BYTES,
            ),
            (
                "FAMILY_QUOTA",
                dict(base.frame_module.FAMILY_QUOTA),
                dict(frame_module.FAMILY_QUOTA),
            ),
        )
        if theirs != ours
    ]
    if mismatches:
        raise RuntimeError(
            "the imported acquisition driver decides admission from constants this "
            "study does not share: "
            + "; ".join(
                f"{name}: driver {theirs!r} vs study {ours!r}" for name, theirs, ours in mismatches
            )
            + ". The driver decides admission, so the declaration would be "
            "describing a cohort that was never collected"
        )


def document_for(lineage: dict[str, Any], revision: dict[str, str], raw: bytes) -> dict[str, Any]:
    """A canonical document with a witness for every unit."""
    from provenance_document import provenance_document

    return provenance_document(
        source_family=lineage["family"],
        source_id=lineage["lineage_id"],
        version_id=revision["version"],
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at=revision.get("known_at"),
        valid_from=revision.get("known_at"),
        licence=lineage.get("licence", "unknown"),
    )


class RebuildJudge:
    """Judges each pair for E5 and E6 as its second side is extracted.

    `sfi1_worker._extract_pair` extracts the after side and then the before side,
    consecutively and on one thread. Wrapping the extractor is therefore enough
    to see a whole pair without touching the driver: the first call buffers, the
    second judges and clears.

    The buffer is thread-local because the driver is threaded, and it holds at
    most one half-pair per thread. Documents are dropped as soon as a verdict
    exists — a rebuild produces artifacts far larger than the verdict about them,
    and keeping them would put the run's memory in the hands of the corpus.
    """

    def __init__(self, extract) -> None:
        self._extract = extract
        self._local = threading.local()
        self._lock = threading.Lock()
        self.verdicts: list[reb.RebuildVerdict] = []
        self.errors: list[dict[str, str]] = []

    def __call__(self, *, raw: bytes, document: dict[str, Any]) -> list[Any]:
        facts = self._extract(raw=raw, document=document)
        pending = getattr(self._local, "pending", None)
        if pending is None:
            #: the after side. Held until its partner arrives.
            self._local.pending = (raw, document, facts)
            return facts

        self._local.pending = None
        after_raw, after_document, after_facts = pending
        try:
            verdict = reb.judge_pair(
                before_document=document,
                after_document=after_document,
                before_raw=raw,
                after_raw=after_raw,
                before_facts=facts,
                after_facts=after_facts,
            )
        except Exception as error:  # the endpoint is lost, the extraction is not
            #: A rebuild that raised is recorded and the facts are still
            #: returned. Losing the pair's facts because the rebuild failed
            #: would turn a gap in one endpoint into a gap in five.
            with self._lock:
                self.errors.append(
                    {
                        "lineage_id": str(document.get("source_id", "")),
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
            return facts
        with self._lock:
            self.verdicts.append(verdict)
        return facts

    def reset(self) -> None:
        """Drop a half-pair left over from a lineage that ended mid-extraction."""
        self._local.pending = None


def acquire(
    lineages: list[dict[str, Any]],
    payload_for,
    *,
    workers: int,
    chunk: int,
    document_for,
    extract,
    progress=print,
) -> dict[str, Any]:
    """The chunked thread pool, with the two injection points wired through.

    `sfi1_worker.acquire` calls `evaluate(lineage, payload_for)` positionally and
    exposes no way to pass a canonicaliser or an extractor, so V2 cannot reach it
    through that door. Three ways in were considered and two rejected:

    * adding an optional parameter to `sfi1_worker.acquire` — additive and
      behaviour-preserving, but it edits a tool whose path a frozen study's
      receipt names, for the convenience of a later study.
    * rebinding `base.evaluate` — the mutated-import shape INC-V2-029 records,
      and invisible in the receipt afterwards.

    So the loop is written here instead. What is NOT written here is the part
    that matters: **admission is still `base.evaluate` and `base.reduce_results`,
    imported and unchanged.** This function owns thread scheduling, chunk size
    and progress printing, none of which can move an admission. The rule stays
    single-implementation, which was the whole point of importing the driver.
    """
    results: dict[str, dict[str, Any]] = {}
    reduced = base.reduce_results(lineages, results)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for start in range(0, len(lineages), chunk):
            batch = lineages[start : start + chunk]
            futures = {
                lineage["lineage_id"]: executor.submit(
                    base.evaluate,
                    lineage,
                    payload_for,
                    document_for=document_for,
                    extract=extract,
                )
                for lineage in batch
            }
            for lineage_id, future in futures.items():
                try:
                    results[lineage_id] = future.result()
                except Exception as error:
                    results[lineage_id] = {
                        "code": base.PAYLOAD_FAIL,
                        "detail": f"{type(error).__name__}: {error}",
                    }
            reduced = base.reduce_results(lineages, results)
            progress(
                f"considered {reduced['considered']}  admitted {len(reduced['admitted'])}  "
                f"{reduced['by_family']}"
            )
            if reduced["quota_met"]:
                break
    return reduced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--declare",
        action="store_true",
        help="report the frame declaration and exit; fetches nothing",
    )
    arguments = parser.parse_args(argv)

    if arguments.declare:
        #: Safe before the freeze: every field is a property of the declaration
        #: and none of it can be produced by acquiring anything.
        print(
            json.dumps(
                {
                    "protocol_id": frame_module.PROTOCOL_ID,
                    "protocol_frozen": PROTOCOL.exists(),
                    "family_quota": dict(frame_module.FAMILY_QUOTA),
                    "quota_digest": frame_module.quota_digest(),
                    "primary_target": frame_module.PRIMARY_TARGET,
                    "floor": frame_module.FLOOR,
                    "families_required": frame_module.FAMILIES_REQUIRED,
                    "unexercised_families": dict(frame_module.UNEXERCISED_FAMILIES),
                    "quota_basis": dict(frame_module.QUOTA_BASIS),
                    "max_payload_bytes": frame_module.MAX_PAYLOAD_BYTES,
                    "frame_sealed": frame_module.FRAME.exists(),
                    "note": (
                        "declaration only; nothing here was fetched, canonicalised or classified"
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    #: Both guards before anything is fetched, and the protocol guard first
    #: because it is the one that protects the corpus.
    require_frozen_protocol()
    require_shared_admission_constants()
    extractors = base.require_extractors()

    import fetch_p4c_corpus as p4c
    import fetch_p4g_corpus as p4g
    import ir
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

    judge = RebuildJudge(ir.extract_all)

    lineages = frame_module.frame()
    if arguments.limit:
        lineages = lineages[: arguments.limit]

    reduced = acquire(
        lineages,
        payload_for,
        workers=arguments.workers,
        chunk=arguments.chunk,
        document_for=document_for,
        extract=judge,
    )

    #: E5 and E6 are answered over the admitted cohort only. A verdict for a
    #: lineage the reduction rejected describes a pair that is not in the study,
    #: and counting it would let a rejected pair make an endpoint met.
    admitted_ids = {row["lineage_id"] for row in reduced["admitted"]}
    scored = [row for row in judge.verdicts if row.lineage_id in admitted_ids]
    rebuild = reb.summarise(scored)
    rebuild["pairs_judged_outside_the_admitted_cohort"] = len(judge.verdicts) - len(scored)
    rebuild["rebuild_errors"] = sorted(judge.errors, key=lambda row: row["lineage_id"])

    #: Cohort, facts and rebuild — no verdict. Scoring runs against the frozen
    #: protocol in its own tool; splitting them is what keeps an acquisition run
    #: from being able to publish a result.
    body = {
        "schema": "tavonel.v2.source_fact_ir_heldout.acquisition.v2",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "split": "held_out",
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "canonicaliser": {
            "module": "canonicalization/provenance_document.py",
            "provenance": "native span-map recorded at emission",
            "searching": "none. `_locate` was removed rather than widened",
        },
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
        "rejected_by_code": base.rejected_by_code(reduced),
        "reduction_digest": base.reduction_digest(reduced),
        "admitted": reduced["admitted"],
        "rebuild": rebuild,
        "http": pool.stats(),
        "cache": cache.stats(),
    }
    target = OUT / "sfi2_acquisition.json"
    target.write_text(
        json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"written": rel(target), "sha256": sha_file(target)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
