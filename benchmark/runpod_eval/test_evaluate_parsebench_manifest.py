from __future__ import annotations

import json
import sys
import types
from pathlib import Path

evaluation_cli = types.ModuleType("parse_bench.evaluation.cli")
evaluation_cli.EvaluationCLI = object  # type: ignore[attr-defined]
loader = types.ModuleType("parse_bench.test_cases.loader")
loader.load_test_cases = lambda **_: []  # type: ignore[attr-defined]
# Stubs let the module under test import without the real evaluator installed,
# but leaving them in sys.modules would hand a later test in the same session a
# hollow parse_bench. Install, import, then take them back out.
_stubs = (
    ("parse_bench", types.ModuleType("parse_bench")),
    ("parse_bench.evaluation", types.ModuleType("parse_bench.evaluation")),
    ("parse_bench.evaluation.cli", evaluation_cli),
    ("parse_bench.test_cases", types.ModuleType("parse_bench.test_cases")),
    ("parse_bench.test_cases.loader", loader),
)
_stubbed = [name for name, stub in _stubs if sys.modules.setdefault(name, stub) is stub]

from evaluate_parsebench_official import (  # noqa: E402
    _manifest_case_lookup,
    _rule_failures,
)

for _name in _stubbed:
    del sys.modules[_name]


def test_parsebench_frozen_source_manifest_is_supported(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-source-manifest.v1",
                "source_count": 2,
                "sources": [
                    {
                        "case_id": "parsebench-chart",
                        "source_relative_path": "docs/chart/example.pdf",
                    },
                    {
                        "case_id": "parsebench-text",
                        "source_relative_path": "docs/text/example.pdf",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _manifest_case_lookup(manifest) == {
        "chart/example": "parsebench-chart",
        "text/example": "parsebench-text",
    }


def test_layout_rule_fallback_is_recorded_instead_of_aborting() -> None:
    failures = _rule_failures(
        report={
            "per_example_results": [
                {
                    "test_id": "layout/example",
                    "success": True,
                    "metrics": [
                        {
                            "metric_name": "rule_pass_rate",
                            "metadata": {
                                "rule_results": [
                                    {
                                        "type": "order",
                                        "id": "rule-1",
                                        "passed": False,
                                        "score": 0.0,
                                        "explanation": "No markdown content provided",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ]
        },
        group="layout",
        case_lookup={"layout/example": "parsebench-layout"},
    )

    assert len(failures) == 1
    assert failures[0]["case_id"] == "parsebench-layout"
    assert failures[0]["location_id"] == "rule-1"
