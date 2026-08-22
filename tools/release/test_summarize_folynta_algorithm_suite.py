from __future__ import annotations

from pathlib import Path

from tools.release.summarize_folynta_algorithm_suite import markdown, summarize


def test_summary_is_area_complete_and_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "suite.xml"
    source.write_text(
        """<?xml version="1.0"?>
<testsuites><testsuite tests="3">
  <testcase classname="tests.unit.test_router_preflight" name="test_route" time="0.1" />
  <testcase classname="packages.parallel-runtime.tests.test_scheduling_and_credits"
            name="test_credit" time="0.2" />
  <testcase classname="services.api.tests.test_collection_semantic_runtime"
            name="test_plan" time="0.3"><failure /></testcase>
</testsuite></testsuites>
""",
        encoding="utf-8",
    )

    result = summarize(source)

    assert result["totals"] == {
        "tests": 3,
        "passed": 2,
        "failed": 1,
        "errors": 0,
        "skipped": 0,
    }
    assert result["gates"]["deterministic_contract_suite"] == "FAIL"
    areas = {area["key"]: area for area in result["areas"]}
    assert areas["classification_routing"]["tests"] == 1
    assert areas["credit_cost_accounting"]["tests"] == 1
    assert areas["knowledge_architecture"]["gate"] == "FAIL"
    assert "현실 분포 전체 정확도" in markdown(result)


def test_summary_includes_fail_closed_full_regression_receipt(tmp_path: Path) -> None:
    algorithm = tmp_path / "algorithm.xml"
    algorithm.write_text(
        (
            '<testsuites><testsuite><testcase classname="router" name="route" />'
            "</testsuite></testsuites>"
        ),
        encoding="utf-8",
    )
    regression = tmp_path / "regression.xml"
    regression.write_text(
        """<testsuites><testsuite>
  <testcase classname="api" name="ok" time="0.4" />
  <testcase classname="billing" name="broken" time="0.6"><error /></testcase>
</testsuite></testsuites>""",
        encoding="utf-8",
    )

    result = summarize(algorithm, regression_path=regression)

    assert result["full_backend_regression"] == {
        "path": regression.as_posix(),
        "sha256": result["full_backend_regression"]["sha256"],
        "tests": 2,
        "passed": 1,
        "failed": 0,
        "errors": 1,
        "skipped": 0,
        "duration_seconds": 1.0,
        "gate": "FAIL",
    }
    assert "전체 백엔드 회귀" in markdown(result)
