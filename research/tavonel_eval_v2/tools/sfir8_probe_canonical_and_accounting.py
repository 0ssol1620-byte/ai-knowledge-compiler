#!/usr/bin/env python3
"""Development probe: canonical addressing, and where the provider's counter lands.

Two SFIR8 questions in one live window, because both need the same requests and
splitting them would spend the budget twice.

**Does addressing a renamed repository by its canonical name remove the toll?**
For each renamed root: resolve the catalogue address once, verifying the numeric
repository id, then issue the same three traversal shapes against the canonical
address. If the resolution is sound, those three cost one charge each instead of
two, and the repository measured is provably the same one -- the id was checked
before the name was adopted.

**Does the sum of per-response charges equal the provider's own counter?**
`/rate_limit` is read before and after the whole probe. It is not charged, so it
witnesses without disturbing. Any difference between that delta and the sum of
per-response deltas is recorded as `UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA` and
is **not** classified: a secondary limit, an invisible provider-side charge and a
second process on the same credential all look identical from here.

SFIR7's roots are spent development material. Nothing here is a capacity claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_roots as roots  # noqa: E402
import sfir8_provider_accounting as accounting  # noqa: E402
import sfir8_transport as transport  # noqa: E402

SCHEMA = "tavonel.sfir8.canonical_and_accounting.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"

MIN_INTERVAL_SECONDS = 0.5
_LAST = [0.0]


def _pace() -> None:
    wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _LAST[0])
    if wait > 0:
        time.sleep(wait)
    _LAST[0] = time.monotonic()


def traverse_shapes(
    client: transport.ManualRedirectTransport, address: str
) -> list[dict[str, Any]]:
    """The three shapes a traversal issues, against whatever address is given."""
    rows: list[dict[str, Any]] = []

    def record(url: str, label: str):
        _pace()
        result = client.get(url)
        rows.append(
            {
                "address_used": address,
                "endpoint": label,
                "status": result.status,
                "network_hops": result.network_hops,
                "provider_charged": result.provider_charged,
                "redirected": result.redirected,
            }
        )
        return result

    meta = record(f"https://api.github.com/repos/{address}", "repository_metadata")
    branch = (meta.body or {}).get("default_branch")
    if meta.status != 200 or not isinstance(branch, str):
        return rows
    head = record(f"https://api.github.com/repos/{address}/commits/{branch}", "immutable_head")
    tree_sha = (((head.body or {}).get("commit") or {}).get("tree") or {}).get("sha")
    if head.status != 200 or not isinstance(tree_sha, str):
        return rows
    record(f"https://api.github.com/repos/{address}/git/trees/{tree_sha}", "tree_object")
    return rows


def run(*, renamed_limit: int, unrenamed_limit: int) -> dict[str, Any]:
    census = json.loads(
        (NS / "receipts/sfir7-capacity-metadata-census.json").read_text(encoding="utf-8")
    )
    known_renames = set(census["identity_attestation"]["renames_observed"])
    renamed = sorted(known_renames)[:renamed_limit]
    # Every known rename is excluded from the baseline, not merely the sampled
    # ones. The first run of this probe excluded only the five it sampled, so
    # `facebook/react` sat in the control group and redirected on every request
    # -- the whole of the 1.2-vs-1.0 difference was that one contaminant.
    unrenamed = [
        name for name in roots.declared_roots() if name not in known_renames
    ][:unrenamed_limit]

    client = transport.ManualRedirectTransport()
    before = accounting.read_global()
    # The counter needs a baseline before the first hop, or that hop's charge is
    # unknowable and the run's charge sum is short by exactly one.
    client.seed_remaining(before.remaining)

    resolutions: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for address in renamed:
        _pace()
        resolution = client.resolve_canonical_address(address, roots.expected_uuid(address))
        resolutions.append(resolution)
        for row in traverse_shapes(client, client.address_for(address)):
            rows.append({**row, "group": "renamed_canonical", "catalogue_address": address})

    for address in unrenamed:
        for row in traverse_shapes(client, address):
            rows.append({**row, "group": "unrenamed", "catalogue_address": address})

    after = accounting.read_global()
    totals = client.totals()
    reconciliation = accounting.reconcile(
        before=before,
        after=after,
        logical_request_count=totals["logical_requests"],
        network_hop_count=totals["network_hops"],
        per_request_charge_sum=totals["provider_charged"],
        credential_exclusivity_established=False,
    )
    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "study_kind": "DEVELOPMENT_INSTRUMENT_CALIBRATION",
        "produces_capacity_claim": False,
        "sfir7_roots_are_spent_development_material": True,
        "automatic_redirect_following": False,
        "canonical_resolutions": resolutions,
        "traversal_rows": rows,
        "per_group": _per_group(rows),
        "totals": totals,
        "provider_accounting": reconciliation,
        "hop_atoms": client.atoms(),
        "canonical_addressing_removed_the_toll": _toll_verdict(rows),
        "baseline_group_is_uncontaminated": all(
            not row["redirected"] for row in rows if row["group"] == "unrenamed"
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def _per_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for group in sorted({row["group"] for row in rows}):
        selected = [r for r in rows if r["group"] == group and r["provider_charged"] is not None]
        charged = [r["provider_charged"] for r in selected]
        groups[group] = {
            "logical_requests": len(selected),
            "network_hops": sum(r["network_hops"] for r in selected),
            "provider_charged": sum(charged),
            "charged_per_logical_request": (
                round(sum(charged) / len(charged), 4) if charged else None
            ),
            "requests_that_redirected": sum(1 for r in selected if r["redirected"]),
        }
    return groups


def _toll_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Did traversing by canonical address cost the same as never having moved?"""
    groups = _per_group(rows)
    canonical = groups.get("renamed_canonical", {}).get("charged_per_logical_request")
    baseline = groups.get("unrenamed", {}).get("charged_per_logical_request")
    if canonical is None or baseline is None:
        return {"verdict": "NOT_MEASURED", "means": "one of the groups produced no rows"}
    if canonical == baseline:
        return {
            "verdict": "TOLL_REMOVED",
            "means": (
                "traversing a renamed repository by its canonical address costs the "
                "same per request as one that never moved. The redirect is paid once, "
                "during identity resolution, instead of on every request."
            ),
        }
    return {
        "verdict": "TOLL_REMAINS",
        "means": (
            f"canonical addressing cost {canonical} per request against {baseline} for "
            "repositories that never moved, so something other than the rename is "
            "charging. Not attributed here."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--renamed", type=int, default=5)
    parser.add_argument("--unrenamed", type=int, default=5)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()

    body = run(renamed_limit=args.renamed, unrenamed_limit=args.unrenamed)
    body["generated_at"] = args.generated_at
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    args.receipt.write_text(
        json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "toll": body["canonical_addressing_removed_the_toll"]["verdict"],
                "per_group": body["per_group"],
                "counts": body["provider_accounting"]["counts"],
                "UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA": body["provider_accounting"][
                    "UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA"
                ],
                "renames_resolved": len(body["canonical_resolutions"]),
                "receipt": args.receipt.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
