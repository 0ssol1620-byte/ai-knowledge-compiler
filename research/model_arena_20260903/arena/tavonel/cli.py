"""``python -m arena.tavonel <command>`` — the TAVONEL replay lane's entry point.

Nothing in this lane spends money or touches a provider: it reads frozen
outputs and writes records under ``tavonel/``. The ``--execute`` gate the
contract puts on the paid lanes therefore has no counterpart here; what this
lane guards instead is the *order* of operations, and ``freeze-routes`` refuses
to run once the primary model has been scored.

Commands:

``signals``        per (model, page) GT-free features
``freeze-routes``  seal one variant's route decisions before scoring
``replay``         materialise the composite output tree for a frozen variant
``plan-recovery``  contract 3.6 rows for pages needing new inference
``disagreement``   the pairwise matrix, and ``--correlate`` after scoring
``cost``           counterfactual cost of one variant
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Sequence
from pathlib import Path

from arena.tavonel import (
    correlate,
    cost,
    disagreement,
    freeze,
    recovery_plan,
    replay,
    signals,
    variants,
)
from arena.tavonel.errors import TavonelError
from arena.tavonel.paths import ArenaPaths
from arena.tavonel.policies import ModelSlots, PolicyParams


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="campaign output root (defaults to the arena namespace root)",
    )


def _add_variant(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--variant",
        required=True,
        help=f"one of {', '.join(variants.VARIANT_IDS)} (or a/b/c/d/e)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m arena.tavonel", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    signals_parser = subparsers.add_parser("signals", help="compute per-page GT-free signals")
    _add_root(signals_parser)
    signals_parser.add_argument("--model", action="append", dest="models", default=None)

    freeze_parser = subparsers.add_parser("freeze-routes", help="seal one variant's routes")
    _add_root(freeze_parser)
    _add_variant(freeze_parser)
    freeze_parser.add_argument("--primary", default=None, help="override the primary model key")
    freeze_parser.add_argument(
        "--set-threshold",
        action="append",
        dest="thresholds",
        default=None,
        metavar="NAME=VALUE",
        help="override one named policy threshold (it stays calibrated: false)",
    )

    replay_parser = subparsers.add_parser("replay", help="build the composite output tree")
    _add_root(replay_parser)
    _add_variant(replay_parser)

    recovery_parser = subparsers.add_parser("plan-recovery", help="plan new-inference recovery")
    _add_root(recovery_parser)
    _add_variant(recovery_parser)
    recovery_parser.add_argument("--round", dest="round_number", type=int, default=1)

    disagreement_parser = subparsers.add_parser("disagreement", help="pairwise matrix")
    _add_root(disagreement_parser)
    disagreement_parser.add_argument("--model", action="append", dest="models", default=None)
    disagreement_parser.add_argument(
        "--correlate",
        action="store_true",
        help="join the matrix with official scores (only valid after scoring)",
    )
    disagreement_parser.add_argument(
        "--target-model",
        default=ModelSlots().primary,
        help="model whose evaluator failures the correlation is measured against",
    )

    cost_parser = subparsers.add_parser("cost", help="counterfactual cost of one variant")
    _add_root(cost_parser)
    _add_variant(cost_parser)

    return parser


def _params(args: argparse.Namespace) -> PolicyParams:
    params = PolicyParams()
    primary = getattr(args, "primary", None)
    if primary:
        params = dataclasses.replace(
            params, models=dataclasses.replace(params.models, primary=str(primary))
        )
    for override in getattr(args, "thresholds", None) or []:
        name, separator, raw = str(override).partition("=")
        if not separator:
            raise TavonelError(f"--set-threshold needs NAME=VALUE, got {override!r}")
        try:
            value = float(raw)
        except ValueError as exc:
            raise TavonelError(f"threshold {name} needs a number, got {raw!r}") from exc
        params = params.with_threshold(name.strip(), value)
    return params


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ArenaPaths(root=args.root) if args.root else ArenaPaths.default()

    try:
        if args.command == "signals":
            report = signals.build_signals(paths, args.models)
            print(
                f"signals: {report.case_count} page(s) across {len(report.models)} model(s) "
                f"-> {paths.tavonel / 'signals'}"
            )
            for mismatch in report.hash_mismatches:
                print(f"  hash mismatch against the receipt: {mismatch}", file=sys.stderr)
            for missing in report.missing_outputs:
                print(f"  no output text on disk: {missing}", file=sys.stderr)
            return 0 if report.ok else 1

        if args.command == "freeze-routes":
            frozen = freeze.freeze_routes(paths, variant=args.variant, params=_params(args))
            print(
                f"frozen {frozen.decision_count} route decision(s) for {frozen.variant}\n"
                f"  policy      {frozen.policy_id} {frozen.policy_sha256}\n"
                f"  manifest    {frozen.decision_manifest_sha256}\n"
                f"  written to  {frozen.decisions_dir}"
            )
            if not frozen.disagreement_available:
                print(
                    "  note: no disagreement matrix was available, so the peer-disagreement "
                    "trigger did not fire for any page",
                    file=sys.stderr,
                )
            return 0

        if args.command == "replay":
            result = replay.replay_variant(paths, variant=args.variant)
            print(
                f"replay {result.variant}: {result.resolved} resolved, "
                f"{result.unresolved} unresolved of {result.total}\n"
                f"  manifest {result.manifest_path} ({result.manifest_sha256})\n"
                f"  pages per model: {result.model_page_counts}"
            )
            return 0

        if args.command == "plan-recovery":
            plan = recovery_plan.plan_recovery(
                paths, variant=args.variant, round_number=args.round_number
            )
            print(
                f"planned {plan.row_count} recovery job(s) for {plan.variant}: {plan.type_counts}\n"
                f"  variant plan {plan.variant_plan_path}\n"
                f"  merged plan  {plan.merged_plan_path} ({plan.merged_row_count} row(s))"
            )
            return 0

        if args.command == "disagreement":
            if args.correlate:
                joined = correlate.correlate(paths, model_key=args.target_model)
                print(
                    f"correlation for {joined.model_key}: {joined.finding} over "
                    f"{joined.cases_used} scored page(s); best metric {joined.best_metric} "
                    f"(spearman {joined.best_spearman}) -> {joined.path}"
                )
                return 0
            matrix = disagreement.build_disagreement(paths, args.models)
            print(
                f"disagreement: {matrix.row_count} pair row(s) over {matrix.case_count} page(s) "
                f"and {len(matrix.models)} model(s) -> {matrix.pairs_path}"
            )
            return 0

        if args.command == "cost":
            priced = cost.variant_cost(paths, variant=args.variant)
            print(
                f"cost {priced.variant}: total {priced.total_usd} USD over "
                f"{priced.priced_pages} priced page(s), {priced.unpriced_pages} unpriced; "
                f"all-models contrast {priced.all_models_contrast_usd} USD -> {priced.path}"
            )
            return 0
    except TavonelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"error: unknown command {args.command!r}", file=sys.stderr)
    return 2


__all__ = ["build_parser", "main"]
