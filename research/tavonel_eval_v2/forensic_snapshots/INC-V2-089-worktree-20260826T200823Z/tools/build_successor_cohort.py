#!/usr/bin/env python3
"""Freeze the one GPU-successor candidate universe authorised by SFI3.

The scientific route accepts only an immutable ``sfi3-acceptance`` receipt for
``SOURCE_FACT_IR_HELDOUT_V3`` and the exact acquisition artifact that receipt
binds.  The resulting manifest is itself an immutable receipt at one fixed
authority path.  There is no mutable ``typed_fact_cohort.json`` authority, no
``latest`` lookup, and no second freeze.

Eligibility here is `GPU_SUCCESSOR_STUDY_V1.yaml` section 4, applied to one
typed fact on its CURRENT revision alone:

* kind is one of `gpu_successor_preflight.ELIGIBLE_KINDS`
* state is `REPRESENTED_IN_COMPILED_STATE` on the current (`after`) revision
* the representation is not a substring of the witness's own excerpt — the
  same `_invisible_in_unit_text` predicate the preflight already applies, not
  a second copy of it
* an immediately-preceding revision of the same lineage exists in the corpus
  (structural, from the acquisition artifact's own admission rule: every
  admitted lineage carries an `after`/`before` pair by construction)

Nothing here compares the `before` and `after` value of a fact — that would be
`REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS`, which this design does not use
and which `gpu_successor_preflight.py` declares `False`. A fact excluded by
any of the rules above is counted, by reason, never silently dropped, and if
the eligible count sits below the floor this tool reports that plainly rather
than padding, sampling with replacement, or relaxing a kind to reach it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_TOOLS = Path(__file__).resolve().parent
_NS = _TOOLS.parent
for _path in (_TOOLS, _NS / "source_fact_ir", _NS / "endpoint"):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)

import gpu_successor_preflight as gsp  # noqa: E402
import ir  # noqa: E402
import sfi3_acceptance  # noqa: E402
import successor_prompt_schema as sps  # noqa: E402
from common import canonical_json, sha_bytes, sha_file  # noqa: E402
from evidence import ReceiptExists, write_immutable  # noqa: E402

MANIFEST_SCHEMA = "tavonel.v2.successor_cohort_manifest.v1"
SFI3_ACQUISITION_SCHEMA = "tavonel.v2.source_fact_ir_heldout.acquisition.v3"
RECEIPT_STEM = "successor-candidate-universe"
AUTHORITY_RUN_ID = "SFI3_SUCCESSOR_UNIVERSE_V1"


class SuccessorFreezeRefused(RuntimeError):
    """The requested input is not the one SFI3 authorised, or is already frozen."""


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(relative: str) -> Path:
    candidate = _NS.parents[1] / relative
    if candidate.is_file():
        return candidate.resolve()
    plain = Path(relative)
    if plain.is_file():
        return plain.resolve()
    raise SuccessorFreezeRefused(f"the SFI3 acceptance names absent file {relative!r}")


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_NS.parents[1])).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def require_sfi3_authority(acquisition_path: Path, acceptance_path: Path) -> dict[str, Any]:
    """Verify the sealed SFI3 PASS and its exact acquisition binding."""
    raw = json.loads(acceptance_path.read_text(encoding="utf-8"))
    provenance = raw.get("provenance") or {}
    if provenance.get("receipt_stem") != sfi3_acceptance.STEM or not provenance.get("immutable"):
        raise SuccessorFreezeRefused(
            "the named SFI3 acceptance is not an immutable sfi3-acceptance receipt"
        )
    try:
        held = sfi3_acceptance.verify_authority(acceptance_path)
    except sfi3_acceptance.AcceptanceRefused as error:
        raise SuccessorFreezeRefused(f"SFI3 acceptance refused: {error}") from error
    accepted_acquisition = _resolve(str(held["acquisition"]))
    requested = acquisition_path.resolve()
    if requested != accepted_acquisition:
        raise SuccessorFreezeRefused(
            "the requested acquisition is not the acquisition SFI3 accepted"
        )
    digest = _sha_file(requested)
    if digest != held["acquisition_sha256"]:
        raise SuccessorFreezeRefused("the SFI3 acquisition bytes moved after acceptance")
    return held


# ---------------------------------------------------------------------------
# exclusion reasons — every fact that is not eligible is counted under one
# of these, never dropped without a reason
# ---------------------------------------------------------------------------

REASON_INELIGIBLE_KIND = "INELIGIBLE_KIND"
REASON_FAIL_CLOSED_STATE = "FAIL_CLOSED_STATE"
REASON_IGNORED_BY_POLICY = "IGNORED_BY_POLICY"
REASON_VISIBLE_IN_UNIT_TEXT = "VISIBLE_IN_UNIT_TEXT"
REASON_NO_PRECEDING_REVISION = "NO_PRECEDING_REVISION"

EXCLUSION_REASONS: tuple[str, ...] = (
    REASON_INELIGIBLE_KIND,
    REASON_FAIL_CLOSED_STATE,
    REASON_IGNORED_BY_POLICY,
    REASON_VISIBLE_IN_UNIT_TEXT,
    REASON_NO_PRECEDING_REVISION,
)


def eligibility_reason(fact: dict[str, Any], *, has_preceding_revision: bool) -> str | None:
    """`None` if `fact` is eligible; otherwise the one reason it is excluded.

    Checked in the order section 4 states its `all_required` list, so the
    first rule a fact fails is the reason recorded — a fact can fail more than
    one, but only one is ever needed to exclude it and reporting the first is
    honest about that.
    """
    if not has_preceding_revision:
        return REASON_NO_PRECEDING_REVISION
    if fact.get("kind") not in gsp.ELIGIBLE_KINDS:
        return REASON_INELIGIBLE_KIND
    state = fact.get("state")
    if state in ir.FAIL_CLOSED:
        return REASON_FAIL_CLOSED_STATE
    if state == ir.IGNORED:
        return REASON_IGNORED_BY_POLICY
    if state != ir.REPRESENTED:
        # any state not already named above and not REPRESENTED — defensive,
        # not expected to be reachable given `ir.STATES`, but a fact in an
        # unrecognised state is excluded and counted, never assumed eligible.
        return REASON_FAIL_CLOSED_STATE
    # `gsp._invisible_in_unit_text` is reused, not reimplemented: it is the
    # exact predicate `cohort_feasibility` applies when it re-checks this
    # manifest, and a second copy here could silently drift from it.
    if not gsp._invisible_in_unit_text(fact):
        return REASON_VISIBLE_IN_UNIT_TEXT
    return None


def eligible_facts_for_row(row: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One admitted acquisition row's eligible current-revision facts.

    `row["facts"]["after"]` is the current revision's fact set (SFI2's
    `_extract_pair` names the newer of the two revisions `after`); `before`
    is read only to confirm a preceding revision exists in the corpus, never
    compared value-for-value against `after`.
    """
    has_preceding = bool(row.get("before_version")) and "before" in row.get("facts", {})
    after_facts = row.get("facts", {}).get("after", [])
    eligible: list[dict[str, Any]] = []
    excluded: dict[str, int] = {reason: 0 for reason in EXCLUSION_REASONS}
    for fact in after_facts:
        reason = eligibility_reason(fact, has_preceding_revision=has_preceding)
        if reason is None:
            eligible.append(
                {
                    **fact,
                    "lineage_id": row.get("lineage_id"),
                    "family": row.get("family"),
                    "current_revision": row.get("after_version"),
                    "preceding_revision": row.get("before_version"),
                }
            )
        else:
            excluded[reason] += 1
    return eligible, excluded


def build_manifest(acquisition: dict[str, Any]) -> dict[str, Any]:
    """The full manifest body, from an SFI2 acquisition artifact's parsed JSON.

    Deterministic: facts are sorted by `(kind, fact_id)` regardless of the
    order lineages were admitted in, so two builds from the same acquisition
    artifact produce a byte-identical `facts` list and the same digest.
    """
    admitted = acquisition.get("admitted", [])
    eligible_facts: list[dict[str, Any]] = []
    excluded_totals: dict[str, int] = {reason: 0 for reason in EXCLUSION_REASONS}
    for row in admitted:
        row_eligible, row_excluded = eligible_facts_for_row(row)
        eligible_facts.extend(row_eligible)
        for reason, count in row_excluded.items():
            excluded_totals[reason] += count

    eligible_facts.sort(
        key=lambda fact: (
            fact["kind"],
            fact["fact_id"],
            str(fact.get("lineage_id")),
            str(fact.get("current_revision")),
        )
    )

    by_kind: dict[str, int] = {kind: 0 for kind in gsp.ELIGIBLE_KINDS}
    for fact in eligible_facts:
        by_kind[fact["kind"]] += 1

    eligible_count = len(eligible_facts)
    floor = gsp.COHORT_FLOOR
    facts_digest = sha_bytes(canonical_json(eligible_facts).encode("utf-8"))

    return {
        "schema": MANIFEST_SCHEMA,
        "study_id": gsp.STUDY_ID,
        "source_acquisition_schema": acquisition.get("schema"),
        "lineages_considered": len(admitted),
        "eligible_count": eligible_count,
        "by_kind": by_kind,
        "floor": floor,
        "feasible": eligible_count >= floor,
        "feasibility_rule": (
            "below the floor this manifest refuses to claim feasibility; the "
            "floor is never lowered and the cohort is never padded, "
            "sample-with-replacement, or widened by relaxing a kind to reach it"
        ),
        "requires_value_transition_between_revisions": (
            gsp.REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS
        ),
        "excluded": excluded_totals,
        "excluded_total": sum(excluded_totals.values()),
        "facts": eligible_facts,
        "facts_digest": facts_digest,
        #: The prompt schema this cohort was built against, pinned at build time.
        #: `materialize_successor_inputs` refuses a manifest whose recorded digest
        #: is absent or does not match the schema module it imports, so a prompt
        #: edited between cohort construction and materialization cannot reach a
        #: billed run silently. Recording it here is what makes that refusal
        #: reachable — the materializer was fail-closed against a field nothing
        #: wrote, which meant no real manifest could ever pass it.
        "prompt_schema_digest": sps.schema_digest(),
    }


def build_manifest_from_path(acquisition_path: Path) -> dict[str, Any]:
    body = json.loads(acquisition_path.read_text(encoding="utf-8"))
    manifest = build_manifest(body)
    manifest["source_acquisition_artifact"] = {
        "path": _relative(acquisition_path),
        "sha256": sha_file(acquisition_path),
    }
    return manifest


def write_manifest(manifest: dict[str, Any], out_path: Path) -> Path:
    """Fixture/export helper: exclusive-create only, never an authority."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return out_path


def build_authorised_manifest(acquisition_path: Path, acceptance_path: Path) -> dict[str, Any]:
    held = require_sfi3_authority(acquisition_path, acceptance_path)
    manifest = build_manifest_from_path(acquisition_path)
    if manifest["source_acquisition_schema"] != SFI3_ACQUISITION_SCHEMA:
        raise SuccessorFreezeRefused(
            f"the acquisition schema is {manifest['source_acquisition_schema']!r}, "
            f"not {SFI3_ACQUISITION_SCHEMA!r}"
        )
    manifest["source_sfi3_acceptance"] = {
        "path": _relative(acceptance_path),
        "sha256": _sha_file(acceptance_path),
        "protocol_id": held["protocol_id"],
        "measurement_receipt": held["measurement_receipt"],
        "measurement_sha256": held["measurement_sha256"],
        "verdict": held["verdict"],
    }
    manifest["authority"] = (
        "the exact immutable SFI3 PASS acceptance and the acquisition it binds; "
        "no pre-SFI3 manifest or four-link receipt is eligible"
    )
    return manifest


def seal(acquisition_path: Path, acceptance_path: Path) -> dict[str, str]:
    """Write the sole immutable successor universe, or refuse forever after."""
    manifest = build_authorised_manifest(acquisition_path, acceptance_path)
    try:
        return write_immutable(
            RECEIPT_STEM,
            manifest,
            tool=Path(__file__).resolve(),
            protocol=None,
            run_id=AUTHORITY_RUN_ID,
            pointer=False,
        )
    except ReceiptExists as error:
        raise SuccessorFreezeRefused(
            "the SFI3 successor universe is already frozen; a second authority is forbidden"
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "acquisition_artifact",
        type=Path,
        help="the exact SFI3 acquisition artifact named by --sfi3-acceptance",
    )
    parser.add_argument("--sfi3-acceptance", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        written = seal(args.acquisition_artifact, args.sfi3_acceptance)
    except SuccessorFreezeRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2))
        return 4
    print(json.dumps({"state": "FROZEN", **written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
