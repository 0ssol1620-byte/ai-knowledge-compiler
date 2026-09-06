"""Freeze route decisions before any evaluator runs (MP 2.2, 23.2; contract 3.5).

The masterplan's order is SOURCE → INFERENCE → FREEZE OUTPUT → **FREEZE ROUTE
DECISION** → ground truth → scoring. If a route decision were made after the
scores existed, the adaptive result would be a post-hoc selection and the whole
comparison would be void. So this module enforces the order mechanically:

* it refuses to write decisions for a deployable variant when the primary
  model already has scoring output on disk;
* it refuses to overwrite an existing ``FROZEN.json``;
* every decision it writes carries ``decided_before_gt: true`` and a
  ``decision_sha256`` over its own body, and the freeze file carries a
  manifest hash over all of them.

Variant E is the single exception, and it is the exception in the other
direction: it *requires* scores and is labelled not deployable everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arena.constants import CAMPAIGN_ID
from arena.tavonel import guards, jsonio, outputs, signals, variants
from arena.tavonel.errors import FreezeOrderError, MissingInputError
from arena.tavonel.paths import ArenaPaths
from arena.tavonel.policies import CaseContext, PolicyParams, RoutePolicy, build_policy

FROZEN_SCHEMA = "tavonel.arena.route-freeze.v1"


@dataclass(frozen=True, slots=True)
class FreezeReport:
    variant: str
    policy_id: str
    policy_sha256: str
    decision_count: int
    frozen_path: Path
    decisions_dir: Path
    decision_manifest_sha256: str
    disagreement_available: bool


def _scores_present(paths: ArenaPaths, model_key: str) -> list[str]:
    """Any scoring artefact already on disk for ``model_key``."""
    directory = paths.scores / model_key
    guards.assert_readable(directory)
    if not directory.is_dir():
        return []
    return sorted(
        path.relative_to(paths.root).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    )


def assert_gt_order(paths: ArenaPaths, *, variant: str, primary_model_key: str) -> dict[str, Any]:
    """Refuse to freeze a deployable route after its primary model was scored."""
    present = _scores_present(paths, primary_model_key)
    checked = f"scores/{primary_model_key}"
    if variants.is_oracle(variant):
        if not present:
            raise MissingInputError(
                f"variant {variant} is the post-hoc oracle and needs scoring output; "
                f"nothing found under {checked}"
            )
        return {"checked": checked, "result": "present", "artefacts": len(present)}
    if present:
        raise FreezeOrderError(
            f"{checked} already holds {len(present)} scoring artefact(s) "
            f"(for example {present[0]}). Masterplan section 2.2 requires route decisions to "
            f"be frozen before ground truth is read; only --variant "
            f"{variants.VARIANT_E} may run after scoring."
        )
    return {"checked": checked, "result": "absent", "artefacts": 0}


def load_peer_similarity(paths: ArenaPaths, primary_model_key: str) -> dict[str, dict[str, float]]:
    """``case_key -> {other_model: normalized text similarity}`` from the pairs file."""
    path = paths.disagreement_pairs
    if not path.is_file():
        return {}
    similarity: dict[str, dict[str, float]] = {}
    for row in guards.iter_jsonl_guarded(path, what="disagreement pairs"):
        case_key = row.get("case_key")
        model_a = row.get("model_a")
        model_b = row.get("model_b")
        metrics = row.get("metrics")
        if not isinstance(case_key, str) or not isinstance(metrics, dict):
            continue
        value = metrics.get("text_similarity")
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        if model_a == primary_model_key and isinstance(model_b, str):
            similarity.setdefault(case_key, {})[model_b] = float(value)
        elif model_b == primary_model_key and isinstance(model_a, str):
            similarity.setdefault(case_key, {})[model_a] = float(value)
    return similarity


def build_contexts(
    paths: ArenaPaths,
    *,
    primary_model_key: str,
    official_scores: Mapping[str, Mapping[str, float]] | None = None,
) -> list[CaseContext]:
    """One context per page that has a signals record for the primary model."""
    primary_signals = signals.load_all_signals(paths, primary_model_key)
    if not primary_signals:
        raise MissingInputError(
            f"no signals records for the primary model {primary_model_key}; "
            "run `python -m arena.tavonel signals` first"
        )
    availability = outputs.availability_index(outputs.load_outputs(paths))
    similarity = load_peer_similarity(paths, primary_model_key)
    contexts: list[CaseContext] = []
    for case_key in sorted(primary_signals):
        record = primary_signals[case_key]
        peers = similarity.get(case_key, {})
        contexts.append(
            CaseContext(
                case_key=case_key,
                sample_id=record.get("sample_id"),
                benchmark=record.get("benchmark"),
                primary_signals=record,
                available_models=availability.get(case_key, ()),
                peer_similarity=peers,
                peer_similarity_available=bool(peers),
                official_scores=(
                    None if official_scores is None else official_scores.get(case_key, {})
                ),
            )
        )
    return contexts


def freeze_routes(
    paths: ArenaPaths,
    *,
    variant: str,
    params: PolicyParams | None = None,
) -> FreezeReport:
    """Compute, write and seal the route decisions for one variant."""
    canonical_variant = variants.normalize_variant(variant)
    policy: RoutePolicy = build_policy(canonical_variant, params)
    primary_model_key = policy.params.models.primary

    guard = assert_gt_order(
        paths, variant=canonical_variant, primary_model_key=primary_model_key
    )

    frozen_path = paths.route_frozen_path(canonical_variant)
    if frozen_path.exists():
        raise FreezeOrderError(
            f"{frozen_path} already exists; a frozen route set is immutable. Remove the "
            "variant directory deliberately if the freeze has to be redone."
        )

    official: Mapping[str, Mapping[str, float]] | None = None
    if variants.is_oracle(canonical_variant):
        from arena.tavonel.oracle import load_official_scores

        official = load_official_scores(paths, outputs.discover_output_models(paths))

    contexts = build_contexts(
        paths, primary_model_key=primary_model_key, official_scores=official
    )
    decisions = policy.decide_all(contexts)

    manifest_rows: list[dict[str, str]] = []
    for decision in decisions:
        record = decision.as_record(
            campaign_id=CAMPAIGN_ID, variant=canonical_variant, policy=policy
        )
        jsonio.write_json_atomic(
            paths.route_decision_path(canonical_variant, decision.case_key), record
        )
        manifest_rows.append(
            {"case_key": decision.case_key, "decision_sha256": record["decision_sha256"]}
        )

    manifest_sha = jsonio.prefixed(
        jsonio.json_sha256_hex(sorted(manifest_rows, key=lambda row: row["case_key"]))
    )
    frozen: dict[str, Any] = {
        "schema": FROZEN_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "variant": canonical_variant,
        "variant_directory": variants.variant_dir_name(canonical_variant),
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "decision_manifest_sha256": manifest_sha,
        "count": len(manifest_rows),
        "policy_id": policy.policy_id,
        "policy_sha256": policy.policy_sha256,
        "policy": policy.describe(),
        "primary_model_key": primary_model_key,
        "decided_before_gt": True,
        "gt_order_guard": guard,
        "disagreement_trigger_available": any(ctx.peer_similarity_available for ctx in contexts),
    }
    if variants.is_oracle(canonical_variant):
        frozen["deployability"] = variants.ORACLE_LABEL
        frozen["decided_before_gt"] = False
    jsonio.write_json_atomic(frozen_path, frozen)

    return FreezeReport(
        variant=canonical_variant,
        policy_id=policy.policy_id,
        policy_sha256=policy.policy_sha256,
        decision_count=len(manifest_rows),
        frozen_path=frozen_path,
        decisions_dir=paths.route_decisions_dir(canonical_variant),
        decision_manifest_sha256=manifest_sha,
        disagreement_available=bool(frozen["disagreement_trigger_available"]),
    )


def load_route_decisions(paths: ArenaPaths, variant: str) -> list[dict[str, Any]]:
    """Read a frozen decision set back, refusing an unsealed directory."""
    canonical_variant = variants.normalize_variant(variant)
    frozen_path = paths.route_frozen_path(canonical_variant)
    if not frozen_path.is_file():
        raise MissingInputError(
            f"{frozen_path} is absent; freeze the routes for {canonical_variant} first"
        )
    directory = paths.route_decisions_dir(canonical_variant)
    records = [
        guards.read_json_guarded(path, what="route decision")
        for path in sorted(directory.glob("*.json"))
        if path.name != "FROZEN.json"
    ]
    frozen = guards.read_json_guarded(frozen_path, what="route freeze")
    recomputed = jsonio.prefixed(
        jsonio.json_sha256_hex(
            sorted(
                (
                    {
                        "case_key": record["case_key"],
                        "decision_sha256": record["decision_sha256"],
                    }
                    for record in records
                ),
                key=lambda row: str(row["case_key"]),
            )
        )
    )
    if recomputed != frozen.get("decision_manifest_sha256"):
        raise FreezeOrderError(
            f"{directory}: the decisions on disk do not match the sealed manifest hash in "
            f"{frozen_path.name}"
        )
    return records


def route_decisions_by_case(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {str(record["case_key"]): record for record in records}


__all__ = [
    "FROZEN_SCHEMA",
    "FreezeReport",
    "assert_gt_order",
    "build_contexts",
    "freeze_routes",
    "load_peer_similarity",
    "load_route_decisions",
    "route_decisions_by_case",
]
