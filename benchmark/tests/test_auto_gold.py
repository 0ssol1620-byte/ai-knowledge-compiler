from __future__ import annotations

import pytest

from benchmark.auto_gold import (
    AuthorityFact,
    AuthoritySource,
    AutoGoldError,
    MetamorphicKind,
    MutationKind,
    RoundTripProfile,
    apply_mutation,
    authority_snapshot,
    execute_metamorphic_case,
    execute_mutation_case,
    freeze_auto_gold_suite,
    generate_exact_html_fixture,
    generate_metamorphic_suite,
    generate_mutation_suite,
    materialize_metamorphic_artifact,
    verify_metamorphic_result,
    verify_round_trip,
)


def _authority():
    return authority_snapshot(
        case_id="dart-001",
        source=AuthoritySource.OPEN_DART,
        source_revision="receipt-20260731-001",
        source_bytes=b"<result><revenue unit='KRW'>1234</revenue></result>",
        facts=(
            AuthorityFact(
                fact_id="revenue-current",
                concept="Revenue",
                value="1234",
                unit="KRW",
                period="2026-Q2",
                source_ref="receipt-20260731-001#Revenue",
            ),
        ),
    )


def test_authority_truth_requires_immutable_exact_context() -> None:
    gold = _authority()
    assert gold.generated_by_model is False
    assert gold.source_sha256.startswith("sha256:")
    with pytest.raises(AutoGoldError, match="exact context"):
        authority_snapshot(
            case_id="broken",
            source=AuthoritySource.SEC_XBRL,
            source_revision="filing-sha",
            source_bytes=b"xbrl",
            facts=(AuthorityFact("f", "Revenue", "1", "", "2026", "ref"),),
        )


def test_synthetic_fixture_has_exact_table_formula_layout_and_two_pages() -> None:
    fixture = generate_exact_html_fixture()
    blocks = fixture.exact_ground_truth["pages"][0]["blocks"]
    assert {block["type"] for block in blocks} == {"heading", "table", "formula"}
    assert len(fixture.exact_ground_truth["pages"]) == 2
    assert fixture.claim_class == "contract_test"


def test_all_required_mutations_are_generated_with_terminal_oracles() -> None:
    fixture = generate_exact_html_fixture()
    cases = generate_mutation_suite(fixture)
    assert {case.kind for case in cases} == set(MutationKind)
    assert all(case.expected_terminal_state in {"unresolved", "quarantined"} for case in cases)
    injection = next(case for case in cases if case.kind is MutationKind.PROMPT_INJECTION)
    assert injection.expected_terminal_state == "quarantined"
    receipts = [execute_mutation_case(fixture, case) for case in cases]
    assert all(receipt.gate_passed for receipt in receipts)
    assert all(apply_mutation(fixture, case) != fixture.exact_ground_truth for case in cases)


def test_all_required_metamorphic_cases_share_a_zero_loss_oracle() -> None:
    fixture = generate_exact_html_fixture()
    cases = generate_metamorphic_suite(fixture)
    assert {case.kind for case in cases} == set(MetamorphicKind)
    assert {case.invariant_sha256 for case in cases} == {cases[0].invariant_sha256}
    verify_metamorphic_result(cases[0], fixture.exact_ground_truth)
    receipts = [execute_metamorphic_case(fixture, case) for case in cases]
    artifacts = [materialize_metamorphic_artifact(fixture, case) for case in cases]
    assert all(receipt.gate_passed for receipt in receipts)
    assert all("production_ocr_not_exercised" in receipt.limitations for receipt in receipts)
    assert len({artifact.sha256 for artifact in artifacts}) == len(MetamorphicKind)
    assert next(
        artifact for artifact in artifacts if artifact.kind is MetamorphicKind.COMPRESSION
    ).media_type.startswith("application/gzip")
    rerender = next(case for case in cases if case.kind is MetamorphicKind.RERENDER)
    assert rerender.transform == {
        "engine": "deterministic_dom_reserialize",
        "visual_renderer_exercised": False,
    }
    with pytest.raises(AutoGoldError, match="invariant"):
        verify_metamorphic_result(cases[0], {"pages": []})


def test_round_trip_requires_every_profile_and_zero_critical_loss() -> None:
    canonical = {"facts": [{"id": "f1", "value": "-1234.50", "unit": "USD"}]}
    profiles = {profile: canonical for profile in RoundTripProfile}
    assert set(verify_round_trip(canonical, profiles)) == {item.value for item in RoundTripProfile}
    del profiles[RoundTripProfile.RDF]
    with pytest.raises(AutoGoldError, match="profiles missing"):
        verify_round_trip(canonical, profiles)


def test_frozen_suite_is_deterministic_and_never_public_evidence() -> None:
    first = freeze_auto_gold_suite(suite_id="auto-gold-v1", authority=(_authority(),))
    second = freeze_auto_gold_suite(suite_id="auto-gold-v1", authority=(_authority(),))
    assert first.suite_sha256 == second.suite_sha256
    assert len(first.mutations) == 10
    assert len(first.metamorphic) == 6
    assert first.public_quality_claim_allowed is False
