"""One lineage in, one immutable result out. The worker knows nothing else.

What a worker can see is deliberately tiny: the lineage it was handed, the frozen
history bounds and the frozen `ValueFact` extractor. It cannot see the global
quota, the admitted count, any other lineage's result, any coverage or retrieval
figure, or anything a model produced. That is not tidiness — a worker that could
see the admitted count could behave differently depending on how full the cohort
already was, and the selection would stop being a function of the source.

Within a lineage, revision payloads may be fetched in parallel, but they are
*evaluated* newest-to-oldest in frozen order and the first qualifying transition
wins. Prefetching changes when bytes arrive, never which pair is chosen.

The predicate itself is imported, never reimplemented: `qualifying` and
`observations` are the same functions the serial walk used.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "tools"))
sys.path.insert(0, str(HERE.parents[0] / "endpoint"))

import run_vbc2_acquire as serial  # noqa: E402

#: How many revisions of one lineage may be in flight at once. Bounded because a
#: lineage's revisions all live on one host, and the point of the host semaphore
#: is defeated by a worker that queues twelve requests against it at once.
REVISION_PREFETCH = 3


def evaluate(
    lineage: dict[str, Any],
    *,
    payload_for: Callable[[dict[str, Any], dict[str, str]], tuple[bytes, str]],
    state_for: Callable[[dict[str, Any], bytes, str], dict[str, Any]],
) -> dict[str, Any]:
    """The newest qualifying adjacent transition for this lineage, or a code.

    ``payload_for`` and ``state_for`` are injected so the worker itself performs
    no I/O policy: the coordinator supplies a cache-backed, pool-paced fetcher
    and the same frozen parser. The worker owns the *order*, which is the part
    that decides the result.
    """
    try:
        revisions = serial.ENUMERATORS[lineage["family"]](lineage)
    except Exception as error:
        return {
            "lineage_id": lineage["lineage_id"],
            "family": lineage["family"],
            "code": serial.LISTING_FAILED,
            "error": type(error).__name__,
        }
    if len(revisions) < 2:
        return {
            "lineage_id": lineage["lineage_id"],
            "family": lineage["family"],
            "code": serial.TOO_FEW,
            "revisions_seen": len(revisions),
        }

    payloads: dict[str, bytes] = {}
    digests: dict[str, str] = {}
    states: dict[str, dict[str, Any]] = {}
    inspected = 0

    def load(revision: dict[str, str]) -> None:
        if revision["version"] in payloads:
            return
        body, digest = payload_for(lineage, revision)
        payloads[revision["version"]] = body
        digests[revision["version"]] = digest
        states[revision["version"]] = state_for(lineage, body, digest)

    try:
        for index in range(len(revisions) - 1):
            after, before = revisions[index], revisions[index + 1]
            # prefetch a bounded window ahead; evaluation order is untouched
            window = revisions[index : index + 1 + REVISION_PREFETCH]
            pending = [rev for rev in window if rev["version"] not in payloads]
            if pending:
                with ThreadPoolExecutor(max_workers=min(len(pending), REVISION_PREFETCH)) as pool:
                    list(pool.map(load, pending))
                inspected += len(pending)
            load(after)
            load(before)
            transitions = serial.qualifying(
                states[after["version"]], states[before["version"]]
            )
            if transitions:
                return {
                    "lineage_id": lineage["lineage_id"],
                    "family": lineage["family"],
                    "code": None,
                    "after": after,
                    "before": before,
                    "adjacency_index": index,
                    "revisions_seen": len(revisions),
                    "revisions_inspected": inspected,
                    "transitions": transitions,
                    "payload_digests": {
                        "after": digests[after["version"]],
                        "before": digests[before["version"]],
                    },
                }
    except Exception as error:
        return {
            "lineage_id": lineage["lineage_id"],
            "family": lineage["family"],
            "code": serial.PAYLOAD_UNAVAILABLE,
            "error": type(error).__name__,
        }

    return {
        "lineage_id": lineage["lineage_id"],
        "family": lineage["family"],
        "code": serial.NO_TRANSITION,
        "revisions_seen": len(revisions),
        "revisions_inspected": inspected,
    }
