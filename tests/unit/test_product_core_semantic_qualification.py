"""The committed mixed-corpus qualification remains reproducible."""

from benchmark.product_core_semantic_qualification import run_qualification


def test_product_core_semantic_qualification_passes_without_external_claims() -> None:
    report = run_qualification()

    assert report["externalGeneralizationClaim"] is False
    assert report["baseline"]["precisionAt1"] == 0.4
    assert report["candidate"]["precisionAt1"] == 1.0
    assert report["candidate"]["absoluteDelta"] == 0.6
    assert report["qualification"]["status"] == "passed"
    assert all(case["adaptiveCorrect"] for case in report["cases"])
    entity_case = next(case for case in report["cases"] if case["query"] == "TAVONEL")
    assert entity_case["adaptiveScore"]["graphScore"] > 0
    temporal_case = next(case for case in report["cases"] if case["query"].startswith("2025"))
    assert temporal_case["adaptiveScore"]["temporalScore"] == 1.0
    authority_case = next(case for case in report["cases"] if case["query"] == "security policy")
    assert authority_case["baselineTop1"] == "b-informal"
    assert authority_case["adaptiveTop1"] == "x-security"
