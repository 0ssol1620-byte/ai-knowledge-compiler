from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RENDERER = Path(__file__).with_name("render_folynta_portable_report.mjs")
FINALIZER = Path(__file__).with_name("finalize_folynta_public_benchmark_campaign_v2.ps1")
PACKAGER = (
    Path(__file__).parents[2]
    / "benchmark/runpod_eval/package_public_benchmark_review.py"
)

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _artifact() -> dict:
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "FOLYNTA Public Benchmark Recovery Technical Report",
            "description": "Evidence-bound technical report.",
            "generatedAt": "2026-08-07T10:00:00+00:00",
            "cards": [
                {
                    "id": "corpus_card",
                    "description": "Full frozen public benchmark corpus.",
                    "dataset": "headline_metrics",
                    "metrics": [
                        {"label": "Public cases", "field": "full_corpus", "format": "number"},
                        {"label": "RunPod cost", "field": "cost_usd", "format": "currency"},
                    ],
                }
            ],
            "charts": [
                {
                    "id": "accuracy_gain_chart",
                    "title": "Absolute official-pass-rate gain",
                    "type": "bar",
                    "dataset": "accuracy",
                    "valueFormat": "percent",
                    "encodings": {
                        "x": {"field": "suite", "type": "nominal"},
                        "y": {"field": "absolute_rate_gain", "type": "quantitative"},
                    },
                }
            ],
            "tables": [
                {
                    "id": "accuracy_table",
                    "title": "Benchmark-level recovery effects",
                    "dataset": "accuracy",
                    "columns": [
                        {"field": "suite", "label": "Benchmark", "type": "text"},
                        {"field": "input_count", "label": "Input", "format": "number"},
                    ],
                }
            ],
            "sources": [{"id": "final_report", "label": "Final report", "path": "final.json"}],
            "blocks": [
                {
                    "id": "technical_summary",
                    "type": "markdown",
                    "body": "## Technical summary\n\nProcessed with **MinerU 3.4.4**.",
                },
                {"id": "headline_metrics", "type": "metric-strip", "cardIds": ["corpus_card"]},
                {"id": "accuracy_gain", "type": "chart", "chartId": "accuracy_gain_chart"},
                {"id": "accuracy_detail", "type": "table", "tableId": "accuracy_table"},
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": "2026-08-07T10:00:00+00:00",
            "status": "ready",
            "datasets": {
                "headline_metrics": [{"full_corpus": 5132, "cost_usd": 112.5}],
                "accuracy": [
                    {"suite": "omnidocbench", "absolute_rate_gain": 0.0123, "input_count": 1651},
                    {"suite": "parsebench", "absolute_rate_gain": 0.0087, "input_count": 2078},
                ],
            },
            "accessIssues": [],
        },
        "sources": [],
    }


def _render(tmp_path: Path, artifact: dict) -> tuple[subprocess.CompletedProcess, Path, Path]:
    source = tmp_path / "report.artifact.json"
    source.write_text(json.dumps(artifact), encoding="utf-8")
    html = tmp_path / "report.html"
    receipt = tmp_path / "report.delivery-receipt.json"
    process = subprocess.run(
        [
            NODE,
            str(RENDERER),
            "--input",
            str(source),
            "--output",
            str(html),
            "--receipt",
            str(receipt),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return process, html, receipt


@requires_node
def test_renderer_emits_self_contained_document_and_delivery_receipt(tmp_path: Path) -> None:
    process, html_path, receipt_path = _render(tmp_path, _artifact())
    assert process.returncode == 0, process.stderr

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["ok"] is True
    assert receipt["stages"] == {
        "validation": "passed",
        "package": "passed",
        "verification": "structural_only",
    }
    # A structural check must never be reported as a rendered-browser check.
    assert receipt["browser_render_verified"] is False

    html = html_path.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert 'id="chart-accuracy_gain_chart"' in html
    assert 'id="table-accuracy_table"' in html
    assert 'id="block-technical_summary"' in html
    # Values come from the snapshot verbatim and are formatted, not recomputed.
    assert "1.23%" in html and "0.87%" in html
    assert "5,132" in html and "USD 112.50" in html
    # Self-contained: a reviewer offline must see the same document.
    assert "https://" not in html and "http://" not in html
    assert "<script" not in html


@requires_node
def test_renderer_refuses_an_artifact_whose_block_has_no_chart(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["manifest"]["charts"] = []
    process, html_path, receipt_path = _render(tmp_path, artifact)

    assert process.returncode != 0
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["ok"] is False
    assert receipt["stages"]["validation"] == "failed"
    assert not html_path.exists()


@requires_node
def test_renderer_refuses_an_empty_dataset(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["snapshot"]["datasets"]["accuracy"] = []
    process, _html_path, receipt_path = _render(tmp_path, artifact)

    assert process.returncode != 0
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["stages"]["validation"] == "failed"
    assert "empty" in receipt["error"]


def test_finalizer_falls_back_to_the_repository_renderer() -> None:
    finalizer = FINALIZER.read_text(encoding="utf-8")
    # The external plugin cache is optional; a missing cache must not be fatal.
    assert "-ErrorAction Stop" not in finalizer.split("dataAnalyticsCache")[1].split("if (")[0]
    assert "render_folynta_portable_report.mjs" in finalizer
    assert "portable-report-plugin-unavailable" in finalizer
    render_position = finalizer.index("render_folynta_portable_report.mjs")
    gate_position = finalizer.index("Patent and paper HTML report verification gate failed")
    assert render_position < gate_position


def test_review_package_ships_the_renderer_that_produced_the_report() -> None:
    packager = PACKAGER.read_text(encoding="utf-8")
    assert '"tools/release/render_folynta_portable_report.mjs"' in packager
