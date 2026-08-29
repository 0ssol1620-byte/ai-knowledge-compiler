#!/usr/bin/env python3
"""Open the cohort. Once, under both authorities, and sealed before anything reads it.

This is the irreversible step. Everything before it can be rerun; a roster
cannot, because the value of a held-out cohort is that nobody saw it while the
rule was still changeable. So the refusals here are the point and the happy path
is almost incidental.

**Both authorities, and both re-derived rather than read.** The instrument
freeze fixes the selection rule; the cohort-input binding fixes the catalogue,
the four readers and the inherited eligibility predicates. Each has a receipt on
disk saying it was satisfied when someone ran it, and neither receipt is
trusted: the freeze's digest is recomputed from its own body, and the binding is
rebuilt from scratch -- which means the ten-gigabyte member is re-hashed here,
now, against these bytes. A generator that trusted a stored digest would be
selecting from a file it never looked at.

**Nothing here decides anything.** The predicates come from SFIR7's sealed
receipt, evaluated by SFIR7's own `_evaluate`; the projection from raw record to
selectable record is SFIR7's; the partition, the ordering and N are the frozen
selection module's. This file contains no threshold, no field list and no
number. It streams rows and hands them over. If that seems like a thin module,
that is the intended shape: every quantity it could have held is one that
someone could later have chosen to suit the answer.

**The stream holds one row at a time.** The catalogue is ten gigabytes and
thirty million rows. `select()` accumulates only what survives the predicates
and lands in the partition, so the whole table never exists in memory at once.

**Three layers of accounting, not one number.** What the parser could not read,
what the predicates rejected and why, and what the selection excluded as spent
are different facts with different meanings. A single "rows dropped" total would
hide a header change behind a licence filter.

**It refuses to run twice.** A roster generated, inspected, and regenerated with
a different salt is not a held-out cohort, whatever the second one contains.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir9-cohort-roster.json"
SCHEMA = "tavonel.sfir9.cohort_roster_generation.v1"

FREEZE_RECEIPT = "receipts/sfir9-instrument-freeze.json"
BINDING_RECEIPT = "receipts/sfir9-cohort-input-binding.json"

ALREADY_OPENED = "REFUSED_COHORT_ALREADY_OPENED"
NO_FREEZE = "REFUSED_NO_INSTRUMENT_FREEZE"
FREEZE_INVALID = "REFUSED_INSTRUMENT_FREEZE_DOES_NOT_VERIFY"
NO_BINDING = "REFUSED_NO_COHORT_INPUT_BINDING"
BINDING_DRIFTED = "REFUSED_COHORT_INPUT_BINDING_DOES_NOT_REDERIVE"


class GenerationRefused(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _read(namespace: Path, relative: str, code: str) -> dict[str, Any]:
    path = namespace / relative
    if not path.is_file():
        raise GenerationRefused(code, f"{relative} is absent")
    return json.loads(path.read_text(encoding="utf-8"))


def require_authorities(namespace: Path, repository_root: Path) -> dict[str, Any]:
    """Both authorities, re-derived. The receipts are compared against, not believed."""
    sys.path.insert(0, str(namespace / "tools"))
    import sfir9_cohort_input as cohort_input
    import sfir9_freeze as freeze_module

    freeze = _read(namespace, FREEZE_RECEIPT, NO_FREEZE)
    verdict = freeze_module.verify(freeze)
    if not verdict["verified"]:
        raise GenerationRefused(FREEZE_INVALID, str(verdict["problems"]))

    recorded = _read(namespace, BINDING_RECEIPT, NO_BINDING)
    # Rebuilt, not read. This re-hashes the ten-gigabyte member against the
    # bytes on disk now, which is the only way the binding says anything about
    # the file this run is about to stream.
    rederived = cohort_input.binding(namespace=namespace, repository_root=repository_root)
    if rederived["binding_digest"] != recorded["binding_digest"]:
        raise GenerationRefused(
            BINDING_DRIFTED,
            f"the cohort input re-derives to {rederived['binding_digest']}, not the "
            f"recorded {recorded['binding_digest']}. Something in the catalogue, the "
            "readers or the inherited frame is not what was bound.",
        )
    return {"freeze": freeze, "binding": rederived}


def eligible_rows(
    binding: dict[str, Any], tally: Counter[str], parser_tally: Counter[str]
) -> Iterator[dict[str, Any]]:
    """Stream the catalogue, yielding the rows SFIR7's predicates admit.

    The predicates are the ones the binding read from SFIR7's sealed receipt,
    and they are evaluated by SFIR7's own `_evaluate` against SFIR7's own
    projection. Reimplementing either would be writing a new eligibility rule
    while claiming to inherit one.
    """
    import sfir7_catalog_parser as parser
    import sfir7_frame as frame
    import sfir7_projection as projection

    predicates = tuple(
        frame.EligibilityPredicate(
            field=declared["field"],
            op=declared["op"],
            value=declared["value"],
            why="inherited from SFIR7's sealed frame",
        )
        for declared in binding["inherited_frame"]["predicates"]
    )

    member = Path(binding["member_verification"]["path"])
    yielded = [0]
    for record, reason in parser.stream_records(member, yielded):
        if record is None:
            parser_tally[reason] += 1
            continue
        projected, sidecar = projection.project(record)
        verdict = "ELIGIBLE"
        for predicate in predicates:
            if not frame._evaluate(predicate, projected):
                verdict = f"REJECTED_{predicate.field}_{predicate.op}"
                break
        tally[verdict] += 1
        if verdict != "ELIGIBLE":
            continue
        if not sidecar.host_uuid:
            # The partition is keyed on the host's numeric id, and a row without
            # one cannot be assigned to a partition at all. Counted, not guessed.
            tally["ELIGIBLE_BUT_NO_HOST_UUID"] += 1
            continue
        yield {
            "host_uuid": sidecar.host_uuid,
            "record_id": projected.record_id,
            "name_with_owner": sidecar.name_with_owner,
            "source_rank": projected.catalog_rank_value,
        }
    tally["ROWS_READ"] = yielded[0]


def frozen_envelope(protocol_module: Any, selection_module: Any) -> Any:
    """The envelope, read from the frozen protocol rather than restated.

    Every term is `EXTERNAL`. N is derived from these three numbers and nothing
    else, and `require_no_observation_participates` refuses the selection if a
    term is ever sourced from something this study measured -- which is why the
    source is carried beside the value instead of being implied by the name.
    """

    def term(name: str, value: int, rationale: str) -> Any:
        return selection_module.EnvelopeTerm(
            name=name,
            value=value,
            source=selection_module.EXTERNAL,
            rationale=rationale,
        )

    return selection_module.ExecutionEnvelope(
        permitted_rate_windows=term(
            "permitted_rate_windows",
            protocol_module.PERMITTED_RATE_WINDOWS,
            "declared in the frozen protocol before any repository was chosen",
        ),
        usable_charge_per_window=term(
            "usable_charge_per_window",
            protocol_module.USABLE_CHARGE_PER_WINDOW,
            "the provider's published per-window allowance, less the headroom the "
            "protocol reserves for retries",
        ),
        per_root_charge_allowance=term(
            "per_root_charge_allowance",
            protocol_module.PER_ROOT_CHARGE_ALLOWANCE,
            "inherited from SFIR7's per-root bound, in provider-charged requests",
        ),
    )


def generate(
    *,
    namespace: Path = NS,
    repository_root: Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    repository_root = repository_root or namespace.resolve().parents[1]
    target = output or OUTPUT
    if target.is_file():
        raise GenerationRefused(
            ALREADY_OPENED,
            f"{target.name} already exists. A roster generated, inspected and "
            "regenerated is not a held-out cohort, whatever the second one holds.",
        )

    authorities = require_authorities(namespace, repository_root)

    import sfir7_roots
    import sfir9_cohort_roster as roster_module
    import sfir9_protocol as protocol_module
    import sfir9_selection as selection_module

    protocol = protocol_module.Protocol().freeze()
    spent = frozenset(str(entry["host_uuid"]) for entry in sfir7_roots.frozen_roster())
    rule = selection_module.FrozenSelection(
        salt=protocol_module.SELECTION_SALT,
        partition_count=protocol_module.PARTITION_COUNT,
        partition_index=protocol_module.PARTITION_INDEX,
        envelope=frozen_envelope(protocol_module, selection_module),
        spent_host_uuids=spent,
    )

    tally: Counter[str] = Counter()
    parser_tally: Counter[str] = Counter()
    selection = selection_module.select(
        eligible_rows(authorities["binding"], tally, parser_tally), rule
    )

    roster = roster_module.CohortRoster(
        protocol=protocol,
        selection=selection,
        exclusion_proof=selection["exclusions"],
    )
    # No check here that the seal took. `seal()` sets the flag on the line
    # above and raises otherwise, so the check could only ever pass -- the same
    # shape as the fields removed from the binding. What the roster records as
    # `sealed` is proved by the roster module's own controls, and `verify()`
    # below refuses a receipt whose seal is missing.
    seal = roster.seal()

    rows_read = tally.pop("ROWS_READ", 0)
    body = {
        "schema": SCHEMA,
        "study_id": protocol_module.PROTOCOL_ID,
        "instrument_freeze": authorities["freeze"]["freeze_digest"],
        "instrument_commit": authorities["freeze"]["instrument_commit"],
        "cohort_input_binding": authorities["binding"]["binding_digest"],
        "catalogue_accounting": {
            "rows_read": rows_read,
            "unreadable_rows": dict(sorted(parser_tally.items())),
            "unreadable_total": sum(parser_tally.values()),
            "eligibility_dispositions": dict(sorted(tally.items())),
            "eligible": tally.get("ELIGIBLE", 0),
            "why_three_layers": (
                "what the parser could not read, what the predicates rejected and "
                "why, and what the selection excluded as spent are different facts. "
                "One 'rows dropped' total would hide a header change behind a "
                "licence filter."
            ),
        },
        "selection": selection,
        "roster": roster.receipt(),
        "roster_seal": seal,
        "roster_fingerprint": selection_module.roster_fingerprint(selection),
        "spent_identities_excluded": len(spent),
        "what_this_is": (
            "the cohort. It was chosen by the frozen selection rule from the bound "
            "catalogue under SFIR7's inherited predicates, and sealed before any "
            "census ran against it."
        ),
        "what_this_does_not_establish": (
            "anything about capacity. No repository here has been contacted. "
            "C and Q do not exist yet, and the criterion has not been applied."
        ),
    }
    report = {**body, "generation_digest": _digest(body)}
    target.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def verify(report: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in report.items() if key != "generation_digest"}
    problems = []
    if _digest(body) != report.get("generation_digest"):
        problems.append("generation_digest does not recompute; the receipt was edited")
    if not report.get("roster_seal"):
        problems.append("the roster is not sealed")
    entries = report.get("roster", {}).get("entries", [])
    ordinals = [entry.get("selection_ordinal") for entry in entries]
    if ordinals != list(range(1, len(entries) + 1)):
        problems.append("the selection ordinals are not contiguous from one")
    return {
        "schema": SCHEMA + ".verification",
        "verified": not problems,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="open the SFIR9 cohort, once")
    parser.add_argument("--namespace", type=Path, default=NS)
    args = parser.parse_args(argv)
    try:
        report = generate(namespace=args.namespace)
    except GenerationRefused as error:
        print(f"REFUSED  {error}")
        return 1
    accounting = report["catalogue_accounting"]
    print(f"study            {report['study_id']}")
    print(f"freeze           {report['instrument_freeze']}")
    print(f"binding          {report['cohort_input_binding']}")
    print(f"rows read        {accounting['rows_read']:,}")
    print(f"unreadable       {accounting['unreadable_total']:,}")
    print(f"eligible         {accounting['eligible']:,}")
    print(f"in partition     {report['selection']['eligible_in_partition']:,}")
    print(f"spent excluded   {report['selection']['exclusions']['count']}")
    print(f"roster           {len(report['roster']['entries'])} roots")
    print(f"short            {report['selection']['roster_is_short']}")
    print(f"seal             {report['roster_seal']}")
    print(f"fingerprint      {report['roster_fingerprint']}")
    print(f"verify           {verify(report)}")
    print(f"written to       {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
