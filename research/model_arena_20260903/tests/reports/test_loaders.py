"""``arena.reports.loaders``: missing input never crashes; presence is read correctly."""

from __future__ import annotations

from pathlib import Path

from arena.reports.loaders import load_campaign_sources
from arena.reports.paths import SourcePaths
from arena.reports.variant_ids import VARIANT_IDS, variant_dir_name

MODELS = ("model_a",)
BENCHMARKS = ("parsebench",)
VARIANT_DIRS = {v: variant_dir_name(v) for v in VARIANT_IDS}


def test_load_campaign_sources_on_empty_root_never_raises(tmp_path: Path) -> None:
    sources = load_campaign_sources(
        SourcePaths(root=tmp_path),
        models=MODELS,
        benchmarks=BENCHMARKS,
        variant_dir_names=VARIANT_DIRS,
    )
    assert sources.pod_ledger == []
    assert sources.pod_ledger_reason is not None
    assert sources.model_registry is None
    assert sources.scores[("model_a", "parsebench")].summary is None
    for variant in VARIANT_IDS:
        assert sources.variants[variant].route_decisions == []


def test_load_campaign_sources_reads_present_files(tmp_path: Path) -> None:
    (tmp_path / "runs" / "model_a" / "receipts").mkdir(parents=True)
    (tmp_path / "runs" / "model_a" / "receipts" / "case-0.json").write_text(
        '{"status": "SUCCESS", "case_key": "case-0"}', encoding="utf-8"
    )
    (tmp_path / "scores" / "model_a" / "parsebench").mkdir(parents=True)
    (tmp_path / "scores" / "model_a" / "parsebench" / "summary.json").write_text(
        '{"overall": 0.5}', encoding="utf-8"
    )
    (tmp_path / "cost").mkdir()
    (tmp_path / "cost" / "pod_ledger.jsonl").write_text(
        '{"model_key": "model_a", "billed_seconds": 10}\n', encoding="utf-8"
    )

    sources = load_campaign_sources(
        SourcePaths(root=tmp_path),
        models=MODELS,
        benchmarks=BENCHMARKS,
        variant_dir_names=VARIANT_DIRS,
    )
    assert sources.runs["model_a"].receipts == [{"status": "SUCCESS", "case_key": "case-0"}]
    assert sources.scores[("model_a", "parsebench")].summary == {"overall": 0.5}
    assert sources.pod_ledger == [{"model_key": "model_a", "billed_seconds": 10}]


def test_load_campaign_sources_malformed_receipt_becomes_load_error_not_crash(
    tmp_path: Path,
) -> None:
    receipts_dir = tmp_path / "runs" / "model_a" / "receipts"
    receipts_dir.mkdir(parents=True)
    (receipts_dir / "bad.json").write_text("[1, 2]", encoding="utf-8")

    sources = load_campaign_sources(
        SourcePaths(root=tmp_path),
        models=MODELS,
        benchmarks=BENCHMARKS,
        variant_dir_names=VARIANT_DIRS,
    )
    assert "_load_error" in sources.runs["model_a"].receipts[0]
