#!/usr/bin/env python3
"""SFIR7's live Git census: SFIR4's science over an externally selected frame.

`probe_sfir4_capacity.probe_capacity` cannot run this. It enumerates
`sources.FAMILIES` and reads `sources.SOURCE_POOLS` directly, and it re-hashes
itself against SFIR4's charter before it starts, so it is neither parameterisable
nor editable. SFIR6 was able to reuse it because SFIR6 changed an adapter and
kept the roots; SFIR7 changes the roots and keeps everything else.

**What is reused, and how.** The traversal is not reimplemented: it lives in
`LiveMetadataTransport._git`, which takes its repository set from the *request*,
so SFIR7 supplies its own pool and gets the identical non-recursive BFS, the
identical bounds and the identical traversal proof. What is written here is the
enumeration loop around it -- retry handling, disposition validation, candidate
assembly -- and one function SFIR4's version could not be reused for.

**That one function is the risk, so it is bound rather than trusted.**
`_candidate` refuses any repository outside SFIR4's twenty, which is every SFIR7
root. `sfir7_candidate` therefore exists, and
`test_the_candidate_builder_agrees_with_sfir4_for_a_shared_repository` runs both
over the same item and requires identical output, field for field. A candidate
builder that is *almost* SFIR4's produces lineage ids that look right and do not
match, and no downstream check would catch it.

**The bound that is expected to bite.** INC-V2-115: the inherited global Git
request cap is 4,800, and fifty roots at SFIR4's frozen per-root plan want
12,000. When the cap is reached, `GitRequestBoundExceeded` escapes the very first
fetch of a root, and that root is recorded `EXCLUDED_INCOMPLETE_ROOT_DISPOSITION`
with reason `GLOBAL_GIT_REQUEST_BOUND`. It is never recorded as a root with zero
candidates: SFIR4's own comment on that distinction predates this study, and
conflating them would turn a budget exhaustion into a finding about content.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import live_cohort_guard  # noqa: E402
import probe_sfir4_capacity as probe4  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
import sfir4_response_evidence as evidence  # noqa: E402
import sfir7_roots as roots  # noqa: E402
import sfir7_transport as t7  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

SCHEMA = "tavonel.sfir7.capacity_metadata_census.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"
FAMILY = "git_docs"

VALID_STATES = frozenset(
    {
        "COMPLETE",
        "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
        "UNAVAILABLE_ROOT_DISPOSITION",
        "ZERO_CANDIDATE_ROOT_DISPOSITION",
    }
)


class SFIR7CensusRefused(RuntimeError):
    """The census cannot be trusted to describe what it claims to describe."""


def sfir7_candidate(item: Mapping[str, Any], pool: Mapping[str, Any]):
    """SFIR4's Git candidate, with the frozen-root check reading SFIR7's pool.

    Every derived identity -- lineage, container, payload refs, the salted
    capability draw -- is computed exactly as `probe4._candidate` computes it,
    from the same constants read live. The only difference is which repository
    set counts as frozen, which is the whole reason a second function exists.
    """
    repo, path = item.get("repository"), item.get("path")
    if repo not in pool["repositories"] or not isinstance(path, str):
        raise SFIR7CensusRefused("Git item escaped SFIR7's frozen roots")
    root = discovery = sources.discovery_root_id(FAMILY, repo)
    lineage = f"git:{repo}:{path}"
    container = f"git:{repo}:document:{path}"
    ids = probe4._pair(item.get("commit_before"), item.get("commit_after"), FAMILY)
    refs = {key: f"github://{repo}/blob/{ids[key]}/{path}" for key in ids}
    timestamps = probe4._pair(item.get("timestamp_before"), item.get("timestamp_after"), FAMILY)
    if ids["before"] == ids["after"] or timestamps["before"] >= timestamps["after"]:
        return None
    bits = hashlib.sha256((sources.SELECTION_SALT + "\0" + lineage).encode()).digest()[0]
    row = {
        "discovery_root_id": discovery,
        "root_container_id": root,
        "lineage_id": lineage,
        "family": FAMILY,
        "container_id": container,
        "alias_ids": [],
        "payload_ref": refs,
        "revision_id": ids,
        "revision_timestamp": timestamps,
        "capability_exercise": {
            "E5": not bool(bits & 1),
            "E6": not bool(bits & 2),
            "E9": not bool(bits & 4),
        },
    }
    return row, set()


def require_well_formed_response(
    response: Mapping[str, Any], expected: str
) -> tuple[Mapping[str, Any], list[Any]]:
    """Every structural check the loop makes on a transport answer, in one place.

    Extracted for the reason INC-V2-113 records: the census refuses to run under
    a test harness, so a check living inside its loop has no call site any
    control can reach, and deleting it stays green. Here it is reachable, and
    each branch has a control that goes red when it is removed.

    The third check is the one worth naming. A root that did not complete must
    not carry candidates: an incomplete traversal that emitted rows would be
    reporting a partial tree as if it were a whole one, which is the shape of
    every silently-undercounted corpus in this programme's history.
    """
    disposition = response.get("root_disposition")
    if (
        not isinstance(disposition, Mapping)
        or disposition.get("discovery_root_id") != expected
    ):
        raise SFIR7CensusRefused("git root disposition malformed")
    if disposition.get("state") not in VALID_STATES:
        raise SFIR7CensusRefused(
            f"git root disposition state {disposition.get('state')!r} is not one "
            f"SFIR4 defines; its seal would refuse it"
        )
    items = response.get("items")
    if not isinstance(items, list) or (disposition["state"] != "COMPLETE" and items):
        raise SFIR7CensusRefused("incomplete root emitted candidates")
    return disposition, items


def bound_excluded_disposition(
    expected: str, repository: str, transport: Any
) -> dict[str, Any]:
    """A root the global request bound stopped before it began.

    Extracted so it can be driven by a control rather than described by one: the
    census itself refuses to run under a test harness, so a guard buried in its
    loop would otherwise be asserted about in prose and never exercised.

    The state is `EXCLUDED_INCOMPLETE_ROOT_DISPOSITION` and never
    `ZERO_CANDIDATE_ROOT_DISPOSITION`. A budget exhausted and a tree that held
    nothing are different observations; reporting the first as the second turns
    an accounting event into a finding about content.
    """
    return {
        "discovery_root_id": expected,
        "state": "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
        "reason": "GLOBAL_GIT_REQUEST_BOUND",
        "traversal_proof": {
            "algorithm": "IMMUTABLE_NONRECURSIVE_TREE_BFS",
            "api_requests": 0,
            "global_api_requests": getattr(transport, "_global_git_request_count", -1),
            "bound": sources.MAX_GIT_API_REQUESTS_GLOBAL,
        },
        "snapshot_ref": f"github:{repository}:not-reached",
        "response_refs": [],
    }


def build_census_body(
    *,
    transport: Any,
    declared: tuple[str, ...],
    candidates: dict[str, dict[str, Any]],
    dispositions: list[dict[str, Any]],
    snapshots: list[str],
    response_refs: list[str],
    retries: int,
    transport_retries: int,
    total_wait_seconds: int,
    bound_excluded: int,
    started: float,
) -> dict[str, Any]:
    """Assemble the census receipt.

    Separated from the loop for one reason, and it is not tidiness. The first
    live run of this census traversed every frozen root, spent the whole request
    budget, and then died on the last statement -- `import evidence` had bound a
    module of that name in `tools/` rather than `sfir4_response_evidence`, so
    `evidence.ResponseLedger` did not exist. Every measurement was lost to a name
    collision in code that had never once been executed, because `census` refuses
    to run under a test harness and nothing else reached its tail (INC-V2-117).

    Here it is reachable. `preflight_receipt_path` runs it end to end, against a
    real destination, BEFORE the first request leaves the machine.
    """
    ledger = getattr(transport, "ledger", None)
    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "science_carried_from": protocol.PROTOCOL_ID,
        "families": {
            FAMILY: {
                "authority": sources.FAMILY_AUTHORITIES[FAMILY],
                "snapshot_refs": snapshots,
                "response_refs": response_refs,
                "root_dispositions": dispositions,
                "pagination": {
                    "roots_processed": len(declared),
                    "exhausted": True,
                    "rate_limit_retries": retries - transport_retries,
                    "transport_retries": transport_retries,
                    "retries_total": retries,
                    "rate_limit_wait_seconds": total_wait_seconds,
                    "cap_reached": bound_excluded > 0,
                },
                "candidates": sorted(candidates.values(), key=lambda row: row["lineage_id"]),
            }
        },
        "frame": {
            "roster_fingerprint": json.loads(
                roots.FREEZE_PATH.read_text(encoding="utf-8")
            )["roster_fingerprint"],
            "roots_frozen": len(declared),
            "inherited_bounds": roots.inherited_bounds(),
        },
        "bound_exclusions": {
            "roots_excluded_by_the_global_git_bound": bound_excluded,
            "bound": sources.MAX_GIT_API_REQUESTS_GLOBAL,
            "registered_in_advance_as": "INC-V2-115",
            "what_a_bound_exclusion_is_not": (
                "a root with zero candidates. A budget exhausted and a tree that "
                "held nothing are different observations, and a census that "
                "conflated them would report a content finding for an "
                "accounting event."
            ),
            "direction_of_bias": (
                "an excluded root can only lower measured capacity, never raise it"
            ),
        },
        "identity_attestation": transport.identity_attestation()
        if hasattr(transport, "identity_attestation")
        else None,
        "wall_clock_seconds": round(time.monotonic() - started, 3),
        "capacity_criterion_evaluated_here": False,
        "payload_opened": False,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "response_evidence": ledger.proof()
        if isinstance(ledger, evidence.ResponseLedger)
        else evidence.ResponseLedger().proof(),
    }


def preflight_receipt_path(destination: Path) -> None:
    """Write a receipt before spending anything, and refuse if it cannot be written.

    The cheap step runs before the expensive one. An import that does not
    resolve, a schema violation, a directory that does not exist or a disk that
    is full all cost one temporary file here and a whole census budget if they
    are found afterwards.

    It uses the real assembly and the real writer against a real path -- a
    preflight that exercised a stub would prove the stub works.
    """
    import tempfile

    class _Empty:
        ledger = None

        def identity_attestation(self):
            return {"roots_attested": 0, "roots_frozen": len(roots.declared_roots())}

    body = build_census_body(
        transport=_Empty(),
        declared=roots.declared_roots(),
        candidates={},
        dispositions=[],
        snapshots=[],
        response_refs=[],
        retries=0,
        transport_retries=0,
        total_wait_seconds=0,
        bound_excluded=0,
        started=time.monotonic(),
    )
    protocol._assert_metadata_only(body)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        protocol.write_immutable(Path(directory) / destination.name, body)


def census(
    root: Path,
    spent_ref: Mapping[str, Any],
    destination: Path,
    transport: Any,
) -> Path:
    """Visit every frozen root in frozen order. Measure. Refuse nothing quietly."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        live_cohort_guard.refuse_under_test("probe_sfir7_capacity.census")

    #: Cheap before expensive. The receipt path is proven writable before the
    #: first request leaves the machine (INC-V2-117).
    preflight_receipt_path(destination)

    spent = protocol.verify_spent(root, spent_ref)
    spent_ids = set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    pool = roots.git_pool()
    declared = roots.declared_roots()

    candidates: dict[str, dict[str, Any]] = {}
    dispositions: list[dict[str, Any]] = []
    snapshots: list[str] = []
    response_refs: list[str] = []
    retries = 0
    transport_retries = 0
    total_wait_seconds = 0
    bound_excluded = 0
    started = time.monotonic()

    for index, repository in enumerate(declared):
        expected = sources.discovery_root_id(FAMILY, repository)
        current_retries = 0
        while True:
            request: dict[str, Any] = {
                "cursor": str(index),
                "pool": pool,
                "metadata_only": True,
                "expected_discovery_root_id": expected,
                "repository": repository,
            }
            try:
                response = transport(FAMILY, request)
            except probe4.GitRequestBoundExceeded:
                #: The global cap reached on a root's very first fetch, which
                #: `_git` cannot convert into a disposition because it has not
                #: begun. Recorded as bound-excluded, never as zero candidates.
                bound_excluded += 1
                dispositions.append(
                    bound_excluded_disposition(expected, repository, transport)
                )
                break
            protocol._assert_metadata_only(response)
            interrupted = response.get("transport_interrupted") is True
            if response.get("rate_limited") is True or interrupted:
                current_retries += 1
                retries += 1
                if interrupted:
                    transport_retries += 1
                if current_retries > sources.PAGINATION_CONTRACT["maximum_retries_per_request"]:
                    raise SFIR7CensusRefused(
                        "git transport retry budget exhausted"
                        if interrupted
                        else "git rate-limit retry budget exhausted"
                    )
                delay = response.get("retry_after_seconds")
                if (
                    not isinstance(delay, int)
                    or delay < 1
                    or delay > sources.MAX_RATE_LIMIT_WAIT_SECONDS
                    or total_wait_seconds + delay > sources.MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS
                ):
                    raise SFIR7CensusRefused("git retry wait exceeds frozen fail-safe bound")
                time.sleep(delay)
                total_wait_seconds += delay
                continue

            disposition, items = require_well_formed_response(response, expected)
            accepted = 0
            for item in items:
                if not isinstance(item, Mapping):
                    raise SFIR7CensusRefused("candidate metadata is not an object")
                made = sfir7_candidate(item, pool)
                if made is None:
                    continue
                row, aliases = made
                identities = {
                    row["root_container_id"],
                    row["container_id"],
                    row["lineage_id"],
                    *aliases,
                }
                if identities & spent_ids:
                    continue
                if row["lineage_id"] in candidates:
                    raise SFIR7CensusRefused("duplicate lineage")
                candidates[row["lineage_id"]] = row
                accepted += 1
            if accepted > pool["max_candidates_per_repository"]:
                raise SFIR7CensusRefused("git per-root candidate cap exceeded")
            snapshot = response.get("snapshot_id")
            refs = response.get("response_refs")
            if (
                not isinstance(snapshot, str)
                or not snapshot
                or not isinstance(refs, list)
                or not refs
            ):
                raise SFIR7CensusRefused("git root lacks exact response evidence")
            dispositions.append(
                {**dict(disposition), "snapshot_ref": snapshot, "response_refs": list(refs)}
            )
            snapshots.append(snapshot)
            response_refs.extend(refs)
            break

    if len(candidates) > pool["max_total_candidates"]:
        raise SFIR7CensusRefused("git candidate cap exceeded")

    body = build_census_body(
        transport=transport,
        declared=declared,
        candidates=candidates,
        dispositions=dispositions,
        snapshots=snapshots,
        response_refs=response_refs,
        retries=retries,
        transport_retries=transport_retries,
        total_wait_seconds=total_wait_seconds,
        bound_excluded=bound_excluded,
        started=started,
    )
    protocol._assert_metadata_only(body)
    return protocol.write_immutable(destination, body)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=NS.parents[1])
    parser.add_argument("--spent", type=Path, required=True)
    parser.add_argument("--census-destination", type=Path, required=True)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args(argv)

    transport = t7.SFIR7Transport()
    try:
        path = census(
            args.root,
            protocol.exact_ref(args.root, args.spent),
            args.census_destination,
            transport,
        )
    except t7.RepositoryIdentityRefused as error:
        print(
            json.dumps({"state": "IDENTITY_REFUSED", "why": str(error)}, indent=2),
            file=sys.stderr,
        )
        return 7
    except (SFIR7CensusRefused, protocol.SFIR4Refused, roots.SFIR7RootsRefused) as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4
    body = json.loads(path.read_text(encoding="utf-8"))
    block = body["families"][FAMILY]
    print(
        json.dumps(
            {
                "state": "CENSUS_WRITTEN",
                "roots": len(block["root_dispositions"]),
                "candidates": len(block["candidates"]),
                "bound_excluded": body["bound_exclusions"][
                    "roots_excluded_by_the_global_git_bound"
                ],
                "renames": body["identity_attestation"]["rename_count"],
                "census": path.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
