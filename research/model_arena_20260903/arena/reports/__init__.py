"""TAVONEL Model Arena report generation (lane E3, ARENA_CONTRACT section 8).

``python -m arena.reports build --out reports/ [--evidence]`` reads only
``scores/**``, ``runs/*/receipts/*.json``, ``runs/*/run-summary.json``,
``cost/pod_ledger.jsonl``, ``failures/errors.jsonl``, ``tavonel/**``,
``model_registry.json``, ``evaluator_registry.json``, ``campaign_manifest.json``
and ``receipts/{canary,opus}-*.json``, and writes every masterplan section 29
report and evidence file. A missing input is never a crash and never a made-up
number: the corresponding cell is ``n/a`` with a reason, per
:mod:`arena.reports.common`.
"""

from __future__ import annotations

from arena.reports.build import BuildResult, build_reports

__all__ = ["BuildResult", "build_reports"]
