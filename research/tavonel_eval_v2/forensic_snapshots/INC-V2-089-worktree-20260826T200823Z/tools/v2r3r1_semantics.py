"""Prove V2R3R1 asks exactly the scientific question V2R3 asked.

WHY THIS HAS TO BE MECHANICAL. V2R3R1 exists because a runtime crash made V2R3's
frozen chain non-executable. The founder ruling permits the successor to reuse
V2R3's unscored 300-pair cohort ONLY because the successor is the same
experiment. The moment a threshold, an obligation, a population rule or a pass
rule moves, the material stops being a prospective denominator for the question
being asked and a fresh cohort is required. Saying "we did not change the
science" in prose is worth nothing; this file computes it.

THE PROJECTION IS THE WHOLE ARGUMENT, so it is declared rather than inferred.
Two protocols will always differ -- id, stems, file paths, run ids, the
provenance of the repair. A projection that quietly dropped whatever happened to
differ would pass by construction. So the SPLIT is declared here, both halves of
it, and a block that appears in neither list is a failure rather than a default:
a new top-level block added to one protocol and not the other has to be
classified by a person, not absorbed silently.

WHAT IS DELIBERATELY NOT IN THE PROJECTION, and why each is administrative:

    protocol_id, schema        the successor's identity. Changing it is the point.
    status, split              draft/frozen bookkeeping.
    authorised_by              the successor is authorised by a later ruling.
    parent_protocol            lineage metadata; it exists only in the successor.
    carry_forward              how the cohort arrived, proven separately and far
                               more strongly by exact-set equality over the rows.
    freeze                     stems and rung wiring. Its ONE binding sentence --
                               `no_post_freeze_change.rule` -- is checked
                               separately and by exact text, because that is the
                               rule this whole episode turned on.
    companion_attestations     instrument provenance.
    scorer_acceptance          the module list. This is precisely what the repair
                               changed, and pretending otherwise would make the
                               equivalence proof a lie.
    cohort.<acquisition path>  frame file, fetcher, enumerator, path_taken. The
                               POPULATION is unchanged and proven row by row;
                               the route it took to disk is not science.
    execution.<sequencing>     rung order and preconditions. `no_preview`,
                               `on_fail`, `on_pass`, `on_contract_broken`,
                               `what_counts_as_a_score`, `scored_once`,
                               `network`, `gpu_seconds` and `cost_usd` all stay
                               IN the projection -- they are the execution
                               contract, not its plumbing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from evidence import canonical_sha  # noqa: E402

PARENT = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.yaml"
SUCCESSOR = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml"

#: Blocks carried forward whole and compared whole.
SCIENTIFIC_BLOCKS: tuple[str, ...] = (
    "supersedes_nothing",
    "predecessor",
    "cohort_sufficiency",
    "background",
    "v1_standing",
    "retrospective_evidence",
    "legacy_is_not_ground_truth",
    "anti_fitting",
    "protocol_delta",
    "exclusion_policy",
    "expectation_oracle",
    "facet_channels",
    "unresolved_fail_closed",
    "quarantine_channel",
    "diff_level",
    "why_L4",
    "predeclared_ignored_facets",
    "effective_identity_disposition",
    "contract_consistency_gate",
    "root_normalisation",
    "invariants",
    "vacuity_rule",
    "pass_rule",
    "fixture_battery",
    "release",
    "declared_blind_spots",
)

#: Blocks excluded from the projection, each with the reason it is administrative.
#: A block in neither table raises.
ADMINISTRATIVE_BLOCKS: dict[str, str] = {
    "schema": "the successor's schema id",
    "protocol_id": "the successor's identity",
    "status": "draft/frozen bookkeeping",
    "split": "development/production bookkeeping",
    "authorised_by": "the successor is authorised by a later founder ruling",
    "parent_protocol": "lineage metadata; exists only in the successor",
    "carry_forward": "how the cohort arrived; proven row by row instead",
    "freeze": "stems and rung wiring; its one binding rule is checked by text",
    "companion_attestations": "instrument provenance",
    "scorer_acceptance": "the module list, which is exactly what the repair changed",
}

#: Sub-keys of `cohort` describing the ROUTE the material took, not the material.
COHORT_ADMINISTRATIVE: tuple[str, ...] = (
    "path_taken",
    "frame",
    "frame_is_freeze_rung_0",
    "acquired_by",
    "enumerated_by",
)

#: Sub-keys of `manifest_contract` naming WHERE the manifest is, not what its
#: rows must contain. The field contract -- `rows_key`, `required_row_fields`,
#: the digest key names, the alias lists -- stays in the projection, because that
#: is the part a changed instrument could quietly relax.
MANIFEST_ADMINISTRATIVE: tuple[str, ...] = (
    "path",
    "owner_tool",
    "acquisition_manifest",
    "acquisition_manifest_is_inherited",
    "enumeration_schema",
)

#: Sub-keys of `execution` describing rung sequencing, not the execution contract.
EXECUTION_ADMINISTRATIVE: tuple[str, ...] = (
    "order",
    "runs_after",
    "preconditions_that_must_all_be_PROVEN_before_the_single_run",
    #: HOW the single run is invoked, not what it grades. The successor adds an
    #: authorisation boundary so that an accidental `run()` from a test refuses
    #: before reading a pair -- which is the defect that ended the parent chain.
    #: It changes no population rule, no obligation, no threshold and no verdict
    #: rule, and the parent's own `no_preview` and `scored_once` clauses stay in
    #: the projection unchanged, where a weakening of them would be caught.
    "one_shot_authorisation",
)

#: Blocks projected in PART: their scientific half is compared and their plumbing
#: half is dropped by the tables above. Named here so `_classify` counts them as
#: classified -- an omission would report them as unknown blocks and refuse.
PARTIALLY_PROJECTED: tuple[str, ...] = ("cohort", "execution", "manifest_contract")

#: The sentence the whole episode turned on. Compared by exact text rather than
#: folded into the projection, because `freeze` as a whole must differ.
NO_POST_FREEZE_CHANGE = ("freeze", "no_post_freeze_change", "rule")


class SemanticsDiffer(RuntimeError):
    """The successor is not asking the parent's question. Carry-forward is refused."""


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _classify(protocol: dict[str, Any], where: str) -> None:
    known = set(SCIENTIFIC_BLOCKS) | set(ADMINISTRATIVE_BLOCKS) | set(PARTIALLY_PROJECTED)
    unclassified = sorted(set(protocol) - known)
    if unclassified:
        raise SemanticsDiffer(
            f"{where} declares top-level blocks this projection has never classified: "
            f"{unclassified}. A block absorbed silently is a block that could carry a "
            "changed scientific rule past the equivalence proof. Classify it as "
            "scientific or administrative deliberately."
        )
    missing = sorted(
        block for block in SCIENTIFIC_BLOCKS + PARTIALLY_PROJECTED if block not in protocol
    )
    if missing:
        raise SemanticsDiffer(
            f"{where} is missing scientific blocks {missing}. A projection over an "
            "absent block compares nothing."
        )


def project(protocol: dict[str, Any], where: str) -> dict[str, Any]:
    """The normalised scientific/acceptance subtree."""
    _classify(protocol, where)
    projected: dict[str, Any] = {block: protocol[block] for block in SCIENTIFIC_BLOCKS}

    cohort = dict(protocol["cohort"])
    dropped_cohort = [key for key in COHORT_ADMINISTRATIVE if key in cohort]
    for key in dropped_cohort:
        cohort.pop(key)
    projected["cohort"] = cohort

    execution = dict(protocol["execution"])
    dropped_execution = [key for key in EXECUTION_ADMINISTRATIVE if key in execution]
    for key in dropped_execution:
        execution.pop(key)
    projected["execution"] = execution

    manifest = dict(protocol["manifest_contract"])
    dropped_manifest = [key for key in MANIFEST_ADMINISTRATIVE if key in manifest]
    for key in dropped_manifest:
        manifest.pop(key)
    projected["manifest_contract"] = manifest

    #: A projection that dropped nothing from one of the three partially
    #: projected blocks is looking at a protocol whose shape has moved, and would
    #: then be comparing two things neither of which is what this file describes
    #: (INC-V2-044: a check that can only return one answer is not a
    #: measurement).
    empty = [
        name
        for name, dropped in (
            ("cohort", dropped_cohort),
            ("execution", dropped_execution),
            ("manifest_contract", dropped_manifest),
        )
        if not dropped
    ]
    if empty:
        raise SemanticsDiffer(
            f"{where}: the projection removed nothing from {empty}. Every partially "
            "projected block is supposed to lose at least one key; the protocol's "
            "shape has changed under this projection."
        )
    return projected


def _first_difference(left: Any, right: Any, path: str = "") -> str | None:
    if type(left) is not type(right):
        return f"{path or '<root>'}: {type(left).__name__} vs {type(right).__name__}"
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                return f"{path}/{key}: absent in parent"
            if key not in right:
                return f"{path}/{key}: absent in successor"
            found = _first_difference(left[key], right[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: {len(left)} entries vs {len(right)}"
        for index, (one, other) in enumerate(zip(left, right, strict=True)):
            found = _first_difference(one, other, f"{path}[{index}]")
            if found:
                return found
        return None
    if left != right:
        one = json.dumps(left, default=str)[:160]
        other = json.dumps(right, default=str)[:160]
        return f"{path}: {one} vs {other}"
    return None


def _dig(protocol: dict[str, Any], keys: tuple[str, ...]) -> Any:
    node: Any = protocol
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def prove_semantic_equivalence(
    parent_path: Path | None = None, successor_path: Path | None = None
) -> dict[str, Any]:
    """Exact equality of the normalised scientific projection. Raises otherwise."""
    parent_path = parent_path or PARENT
    successor_path = successor_path or SUCCESSOR
    for path in (parent_path, successor_path):
        if not path.is_file():
            raise SemanticsDiffer(f"{path} is not on disk")

    parent = load(parent_path)
    successor = load(successor_path)
    parent_projection = project(parent, "the parent protocol")
    successor_projection = project(successor, "the successor protocol")

    difference = _first_difference(parent_projection, successor_projection)
    if difference is not None:
        raise SemanticsDiffer(
            "the successor's scientific semantics differ from the parent's at "
            f"{difference}. Exact carry-forward of the parent's unscored cohort is "
            "NOT permitted: a changed scientific question requires fresh material."
        )

    parent_rule = _dig(parent, NO_POST_FREEZE_CHANGE)
    successor_rule = _dig(successor, NO_POST_FREEZE_CHANGE)
    if not parent_rule or parent_rule != successor_rule:
        raise SemanticsDiffer(
            "freeze.no_post_freeze_change.rule is absent or has changed. That is the "
            "rule the parent chain died on, and the successor may not soften it while "
            "inheriting the cohort it protected."
        )

    digest = canonical_sha(parent_projection)
    return {
        "held": True,
        "parent": str(parent_path.relative_to(NS)),
        "successor": str(successor_path.relative_to(NS)),
        "scientific_projection_sha256": digest,
        "scientific_blocks": list(SCIENTIFIC_BLOCKS),
        "partially_projected_blocks": list(PARTIALLY_PROJECTED),
        "manifest_keys_excluded": list(MANIFEST_ADMINISTRATIVE),
        "administrative_blocks": dict(sorted(ADMINISTRATIVE_BLOCKS.items())),
        "cohort_keys_excluded": list(COHORT_ADMINISTRATIVE),
        "execution_keys_excluded": list(EXECUTION_ADMINISTRATIVE),
        "no_post_freeze_change_rule_identical": True,
        "how": (
            "both files were parsed from disk, projected onto the declared "
            "scientific subtree, and compared node by node. The first difference "
            "raises with its path. Every top-level block is classified as scientific "
            "or administrative explicitly; an unclassified block refuses."
        ),
        "what_a_failure_means": (
            "not that the successor is wrong, but that it is a different experiment "
            "and may not reuse the parent's unscored material."
        ),
    }


def main() -> int:
    try:
        body = prove_semantic_equivalence()
    except SemanticsDiffer as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4
    print(json.dumps(body, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
