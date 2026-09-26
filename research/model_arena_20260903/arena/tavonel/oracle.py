"""Variant E — the post-hoc best-of-models ceiling. ORACLE_POST_HOC_NOT_DEPLOYABLE.

This is the only module in ``arena.tavonel`` allowed to consume official
per-case scores, and it is deliberately quarantined here so the source scan in
``tests/tavonel/test_gt_blindness.py`` can prove the rest of the lane never
touches them.

Three properties keep it from being mistaken for a product path:

* it cannot run before scoring, because its input is the scoring output;
* every record it writes carries ``deployability`` =
  ``ORACLE_POST_HOC_NOT_DEPLOYABLE`` and the label is in its directory name;
* it is reported beside the deployable variants as a ceiling, never as a
  system anyone could ship (masterplan section 3.2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from arena.tavonel import guards, variants
from arena.tavonel.errors import MissingInputError
from arena.tavonel.paths import ArenaPaths
from arena.tavonel.policies import (
    DECISION_ACCEPT,
    DECISION_ORACLE_SELECT,
    CaseContext,
    RouteDecision,
    RoutePolicy,
    evaluate_triggers,
)

ORACLE_LABEL = variants.ORACLE_LABEL

_CASE_BLOCK_KEYS = ("cases", "per_case", "case_scores")
_SCORE_KEYS = ("official_score", "score", "overall")
_BLOCKED_STATUS = "EVALUATOR_BLOCKED"


def _score_from(entry: Any) -> float | None:
    """A per-case score, or ``None`` — a blocked evaluator is never a zero."""
    if isinstance(entry, bool):
        return None
    if isinstance(entry, int | float):
        return float(entry)
    if not isinstance(entry, dict):
        return None
    if entry.get("evaluator_status") == _BLOCKED_STATUS or entry.get("status") == _BLOCKED_STATUS:
        return None
    for key in _SCORE_KEYS:
        value = entry.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
    return None


def _case_block(payload: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    for key in _CASE_BLOCK_KEYS:
        block = payload.get(key)
        if isinstance(block, dict):
            return block
        if isinstance(block, list):
            rows: dict[str, Any] = {}
            for row in block:
                if isinstance(row, dict) and isinstance(row.get("case_key"), str):
                    rows[row["case_key"]] = row
            return rows
    raise MissingInputError(
        f"{path}: no per-case block. The oracle variant needs one of "
        f"{', '.join(_CASE_BLOCK_KEYS)} mapping case_key to a score or to an object "
        "carrying official_score/evaluator_status."
    )


def load_official_scores(
    paths: ArenaPaths, model_keys: Sequence[str]
) -> dict[str, dict[str, float]]:
    """``case_key -> {model_key: score}`` from ``scores/<model_key>/scores.json``.

    Only models with a scores file contribute. A case a model has no score for
    simply does not appear for that model; it is never scored as zero.
    """
    by_case: dict[str, dict[str, float]] = {}
    found = False
    for model_key in model_keys:
        path = paths.model_scores(model_key)
        if not path.is_file():
            continue
        found = True
        payload = guards.read_json_guarded(path, what=f"scores for {model_key}")
        for case_key, entry in _case_block(payload, str(path)).items():
            score = _score_from(entry)
            if score is None or not isinstance(case_key, str):
                continue
            by_case.setdefault(case_key, {})[model_key] = score
    if not found:
        raise MissingInputError(
            "the oracle variant needs at least one scores/<model_key>/scores.json; "
            "it can only run after official scoring (masterplan section 2.2)"
        )
    return by_case


class OraclePolicy(RoutePolicy):
    """Variant E — pick the highest officially scored output per page.

    Not deployable, by construction: the input is the answer the system is
    supposed to be judged against.
    """

    variant = variants.VARIANT_E
    policy_id = "tavonel.variant-e.oracle-post-hoc.v1"

    def decide(self, ctx: CaseContext) -> RouteDecision:
        triggers = evaluate_triggers(ctx, self.params)
        decision = replace(
            self._base(ctx, triggers), deployability=ORACLE_LABEL, decision=DECISION_ACCEPT
        )
        scores = ctx.official_scores
        if not scores:
            return replace(
                decision,
                notes=(
                    "no official score for any candidate on this page; the oracle made no "
                    "selection and the primary output stands",
                ),
            )
        candidates = {
            model_key: score
            for model_key, score in scores.items()
            if not ctx.available_models or model_key in ctx.available_models
        }
        if not candidates:
            return replace(
                decision,
                notes=("every scored candidate lacks a frozen output for this page",),
            )
        best = min(candidates.items(), key=lambda item: (-item[1], item[0]))
        target = best[0]
        return replace(
            decision,
            decision=DECISION_ORACLE_SELECT,
            target=target,
            final_model=target,
            candidate_models=tuple(sorted(candidates)),
            route_stages=(
                self._primary_stage(),
                {
                    "stage": 1,
                    "model_key": target,
                    "reason": "highest official per-case score (post hoc)",
                },
            ),
            escalation_stage=1,
            escalation_reasons=(ORACLE_LABEL,),
            number_of_model_calls=len(candidates),
            notes=(
                f"{ORACLE_LABEL}: selected after scoring; this is a ceiling, not a system",
            ),
        )


__all__ = ["ORACLE_LABEL", "OraclePolicy", "load_official_scores"]
