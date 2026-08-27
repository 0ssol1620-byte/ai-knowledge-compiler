#!/usr/bin/env python3
"""SFI3 acquisition: the held-out cohort, rebuilt, with E8 and E9 carried out.

The V3 sibling of `sfi2_worker.py`, and deliberately a thin one. Everything that
can decide an admission or a verdict is IMPORTED:

    admission order, per-lineage evaluation,
    deterministic reduction, rejection codes      -> sfi1_worker  (via sfi2_worker)
    canonical document with native provenance     -> sfi2_worker.document_for
    per-pair judging                              -> sfi2_worker.RebuildJudge
    E5/E6/E8/E9 aggregation                       -> rebuild_equivalence.summarise

What this module owns is the four things that genuinely differ between V2 and
V3: which protocol must be frozen, which frame is drawn from, where the artifact
lands, and the refusal to write that artifact twice.

**Why nothing is reimplemented.** INC-V2-007 and INC-V2-009 record what a second
enumeration implementation costs, and INC-V2-035 records what happens when a
producer and a consumer hold two spellings of one contract. A study that reached
a different cohort than the one it declared would be undetectable from its own
receipt, because the receipt is written from the same code that reached it.

**What is new in V3 relative to V2.** V2 answered E5 and E6. V3 additionally
answers E8 (the mandatory carry-forward veto, observed at both declared stages)
and E9 (every detected typed change creates a rebuild request, expected side
from the declarative dependency contract). Neither needed a change here:
`selective_build.run_pair` already emits `carry_observations` and
`e9_channel_closure` per pair, `judge_pair` carries both onto the verdict, and
`summarise` aggregates them into the two blocks `score_sfi3.EXECUTOR_BLOCKS`
names. This module simply does not drop them on the floor.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import rebuild_equivalence as reb  # noqa: E402
import sfi1_worker as base  # noqa: E402
import sfi2_worker as driver  # noqa: E402
import sources_sfi3 as frame_module  # noqa: E402
import verify_sfi3_reservation_binding as reservation_binding  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V3.yaml"
CACHE = NS / "artifacts" / "development" / "sfi3_cache"
OUT = NS / "artifacts" / "development" / "sfi3"
ARTIFACT_NAME = "sfi3_acquisition.json"

#: The stem `tools/freeze_sfi3_protocol.py` writes. Imported rather than spelled
#: again would be better still, but importing the gate here would make the gate
#: import the worker (its execution-readiness check reads this module's path),
#: so the coupling is asserted in `tests/test_sfi3_worker.py` instead.
FREEZE_STEM = "sfi3-protocol-freeze"

USER_AGENT = "tavonel-eval-v2 source-fact-ir-v3 (research; contact via repository)"


class NotFrozen(RuntimeError):
    """Acquiring against an unfrozen protocol spends the corpus for nothing."""


class AlreadyWritten(RuntimeError):
    """A second acquisition artifact would make the scored result ambiguous."""


def require_frozen_protocol() -> dict[str, Any]:
    """The freeze receipt, or a refusal, before one fresh lineage is read.

    Checked here rather than in the scorer for the reason the corpus is
    irreplaceable: by the time the scorer runs, it has already been spent. The
    protocol's own hash is compared against the frozen one, so a protocol edited
    after its freeze refuses rather than quietly governing a run under rules
    nobody sealed.
    """
    from common import sha_file

    freezes = sorted((NS / "receipts").glob(f"{FREEZE_STEM}--*.json"))
    if not freezes:
        raise NotFrozen(
            f"no {FREEZE_STEM} receipt exists. The protocol is frozen before "
            "acquisition, not after it"
        )
    body = json.loads(freezes[-1].read_text(encoding="utf-8"))
    actual = sha_file(PROTOCOL)
    if body.get("protocol_sha256") != actual:
        raise NotFrozen(
            f"the protocol has moved since it was frozen: {actual} is not "
            f"{body.get('protocol_sha256')}. A run under edited rules is not the "
            "run that was authorised"
        )
    return body


def require_shared_admission_constants() -> None:
    """The imported driver decides admission from V1's frame module. Check it.

    `sfi1_worker.evaluate` bounds payloads and `sfi1_worker.reduce_results` fills
    family quotas from `sfi1_worker.frame_module`, which is `sources_sfi1`. V3
    carries both across unchanged, so reusing the driver is correct exactly as
    long as they are still equal — and that is checked here rather than trusted.
    If they diverged, the run would collect one cohort while every declaration
    named another, and nothing downstream could see the difference.
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


def require_single_writer(target: Path) -> None:
    """Refuse to overwrite an existing acquisition artifact.

    The declared order is `freeze -> acquire -> reduce -> score exactly once`.
    Two artifacts at one path, or one path written twice, makes it impossible to
    say afterwards which run the score describes — and the second run cannot be
    a repeat, because the first one spent the corpus. Refusing is the only
    honest option: there is no correct way to acquire this cohort again.
    """
    if target.exists():
        raise AlreadyWritten(
            f"{target} already exists. The held-out corpus is spent by the run "
            "that produced it; a second acquisition would neither reproduce it "
            "nor be scoreable alongside it"
        )


def build_summary(judge: Any, reduced: dict[str, Any]) -> dict[str, Any]:
    """Aggregate the judged pairs over the admitted cohort, and only it.

    A verdict for a lineage the reduction rejected describes a pair that is not
    in the study. Counting one would let a rejected pair make an endpoint met,
    which is the denominator defect this programme keeps rediscovering — so the
    pairs judged outside the admitted cohort are reported as a number rather
    than silently dropped.
    """
    admitted_ids = {row["lineage_id"] for row in reduced["admitted"]}
    scored = [row for row in judge.verdicts if row.lineage_id in admitted_ids]
    summary = reb.summarise(scored)
    summary["pairs_judged_outside_the_admitted_cohort"] = len(judge.verdicts) - len(scored)
    summary["rebuild_errors"] = sorted(judge.errors, key=lambda row: row["lineage_id"])
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--handoff",
        type=Path,
        default=None,
        help="exact immutable V2R4/SFI3 reservation-handoff receipt",
    )
    parser.add_argument(
        "--handoff-sha256",
        default=None,
        help="exact file sha256 of --handoff, including the sha256: prefix",
    )
    parser.add_argument(
        "--declare",
        action="store_true",
        help="report the frame declaration and exit; fetches nothing",
    )
    arguments = parser.parse_args(argv)

    if arguments.declare:
        #: Safe before the freeze: every field is a property of the declaration
        #: and none of it can be produced by acquiring anything. In particular
        #: this reads no revision content, so running it does not open the
        #: held-out corpus.
        print(
            json.dumps(
                {
                    "protocol_id": frame_module.PROTOCOL_ID,
                    "protocol_frozen": bool(
                        sorted((NS / "receipts").glob(f"{FREEZE_STEM}--*.json"))
                    ),
                    "family_quota": dict(frame_module.FAMILY_QUOTA),
                    "quota_digest": frame_module.quota_digest(),
                    "floor": frame_module.FLOOR,
                    "families_required": frame_module.FAMILIES_REQUIRED,
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

    #: Order matters. The reservation binding is verified from one exact path and
    #: digest before the worker imports a fetcher or reads any frozen lineage.
    #: The single-writer guard is also before any fetch because discovering it
    #: afterwards would mean the corpus was spent to produce an artifact that
    #: cannot be written.
    if arguments.handoff is None or not arguments.handoff_sha256:
        raise reservation_binding.BindingRefused(
            "worker requires --handoff and --handoff-sha256; there is no default, "
            "glob, or newest-wins reservation binding"
        )
    binding = reservation_binding.verify_binding(
        handoff_receipt=arguments.handoff,
        handoff_sha256=arguments.handoff_sha256,
    )
    require_frozen_protocol()
    require_shared_admission_constants()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / ARTIFACT_NAME
    require_single_writer(target)
    extractors = base.require_extractors()

    import fetch_p4c_corpus as p4c
    import fetch_p4g_corpus as p4g
    import ir
    import run_vbc2_acquire as serial
    from common import now, rel, sha_file
    from http_pool import HttpPool, install
    from payload_cache import PayloadCache

    started = now()
    clock = time.time()

    pool = HttpPool()
    install(pool, p4c, p4g, USER_AGENT)
    cache = PayloadCache(CACHE, sha_file(NS / "source_fact_ir" / "ir.py"))

    def payload_for(lineage: dict[str, Any], revision: dict[str, str]) -> tuple[bytes, str]:
        return cache.payload(revision["url"], lambda _url: serial._payload(lineage, revision))

    judge = driver.RebuildJudge(ir.extract_all)

    lineages = frame_module.frame()
    if arguments.limit:
        lineages = lineages[: arguments.limit]

    reduced = driver.acquire(
        lineages,
        payload_for,
        workers=arguments.workers,
        chunk=arguments.chunk,
        document_for=driver.document_for,
        extract=judge,
    )

    rebuild = build_summary(judge, reduced)

    #: Cohort, facts and rebuild — no verdict. Scoring runs against the frozen
    #: protocol in its own tool; splitting them is what keeps an acquisition run
    #: from being able to publish a result about itself.
    body = {
        "schema": "tavonel.v2.source_fact_ir_heldout.acquisition.v3",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "split": "held_out",
        "reservation_binding": binding,
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

    #: Re-checked immediately before the write. The guard above ran before a
    #: long network walk, and a concurrent second worker could have landed in
    #: between — which is exactly the single-writer property being asserted.
    require_single_writer(target)
    target.write_text(
        json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"written": rel(target), "sha256": sha_file(target)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
