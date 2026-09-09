"""Source-bound region execution tests; synthetic fixtures, no OCR quality claim."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from akc_router.evidence_execution import (
    EvidenceDisposition as D,
)
from akc_router.evidence_execution import (
    IndependentTextWitness,
    RegionAttempt,
    RegionBinding,
    TextObservation,
    execute_text_region,
    text_digest,
    verify_text_region,
)
from akc_router.models import Route

TEXT = "Revenue was \u221212.5 million USD in 2025. 서울 매출 12억 원."
BINDING = RegionBinding(
    "sha256:" + "a" * 64, "sha256:" + "b" * 64, 2, "region:financial:3", (100, 100, 800, 400)
)


def observation(
    text: str = TEXT, producer: str = "visual.primary", binding: RegionBinding = BINDING
) -> TextObservation:
    return TextObservation(binding, producer, text, text_digest(text))


def witness(text: str = TEXT, producer: str = "native.source") -> IndependentTextWitness:
    return IndependentTextWitness(observation(text, producer), "source-witness:region:3", True)


def test_exact_independent_region_passes_only_its_declared_scope() -> None:
    check = verify_text_region(BINDING, observation(), witness())
    assert check.disposition is D.VERIFIED_TEXT_REGION
    assert check.reasons == ()


@pytest.mark.parametrize(
    "text",
    [
        TEXT.replace("\u2212", ""),
        TEXT.replace("12.5", "125"),
        TEXT.replace("USD", "EUR"),
        TEXT.replace("2025", "2026"),
        TEXT.replace("million", "billion"),
        TEXT.replace("12억", "12만"),
        TEXT + " Revenue is guaranteed.",
        "",
        "Revenue was Revenue was",
    ],
)
def test_critical_changes_or_missing_text_do_not_pass(text: str) -> None:
    result = verify_text_region(BINDING, observation(text), witness())
    assert result.disposition is D.UNRESOLVED
    assert "TEXT_WITNESS_MISMATCH" in result.reasons


def test_only_whitespace_and_nfc_normalization_are_permitted() -> None:
    assert (
        verify_text_region(BINDING, observation(TEXT.replace(" ", "\n  ")), witness()).disposition
        is D.VERIFIED_TEXT_REGION
    )
    assert (
        verify_text_region(BINDING, observation(TEXT.lower()), witness()).disposition
        is D.UNRESOLVED
    )


@pytest.mark.parametrize(
    "change",
    [
        {"source_version": "sha256:" + "c" * 64},
        {"representation_sha256": "sha256:" + "d" * 64},
        {"page_index0": 3},
        {"region_id": "different-region"},
        {"bbox1000": (100, 101, 800, 400)},
    ],
)
def test_wrong_source_or_locator_is_quarantined(change: dict[str, object]) -> None:
    other = replace(BINDING, **change)
    assert (
        verify_text_region(BINDING, observation(binding=other), witness()).disposition
        is D.QUARANTINED
    )
    wrong_witness = IndependentTextWitness(
        observation(producer="native.source", binding=other), "witness:1", True
    )
    assert verify_text_region(BINDING, observation(), wrong_witness).disposition is D.QUARANTINED


def test_two_identical_outputs_from_same_producer_are_not_independent() -> None:
    result = verify_text_region(BINDING, observation(), witness(producer="visual.primary"))
    assert result.disposition is D.UNRESOLVED
    assert "INDEPENDENT_EVIDENCE_REQUIRED" in result.reasons


def test_missing_and_partial_witnesses_are_not_complete() -> None:
    assert verify_text_region(BINDING, observation(), None).disposition is D.UNRESOLVED
    result = verify_text_region(
        BINDING, observation(), replace(witness(), covers_declared_text_region=False)
    )
    assert "WITNESS_COVERAGE_UNMEASURED" in result.reasons


def test_equal_empty_strings_do_not_prove_a_blank_page() -> None:
    result = verify_text_region(BINDING, observation(""), witness(""))
    assert result.disposition is D.UNRESOLVED
    assert "EMPTY_WITNESS_NOT_BLANK_PAGE_PROOF" in result.reasons


def test_observation_digest_and_region_geometry_fail_early() -> None:
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        replace(observation(), output_sha256="sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="GEOMETRY"):
        replace(BINDING, bbox1000=(1, 2, 1, 3))
    with pytest.raises(ValueError, match="SOURCE_DIGEST"):
        replace(BINDING, source_version="latest")
    with pytest.raises(ValueError, match="GEOMETRY"):
        replace(BINDING, bbox1000=(100.5, 100, 800, 400))
    with pytest.raises(ValueError, match="LOCATION"):
        replace(BINDING, page_index0=True)
    with pytest.raises(ValueError, match="BOOLEAN"):
        replace(witness(), covers_declared_text_region="false")


PRIMARY = RegionAttempt(Route.PADDLE_FAST, "visual.primary", 1, 1)
RECOVERY = RegionAttempt(Route.PADDLE_VL, "visual.recovery", 3, 1)


def execute(providers, *, attempts=(PRIMARY, RECOVERY), budget=4, evidence=None, permitted=None):
    return asyncio.run(
        execute_text_region(
            binding=BINDING,
            witness=evidence if evidence is not None else witness(),
            attempts=attempts,
            providers=providers,
            permitted_routes=permitted if permitted is not None else frozenset(providers),
            cost_budget=budget,
            deadline_seconds=3,
        )
    )


def provider(text: str = TEXT, name: str = "visual.primary", calls=None):
    async def run(binding):
        assert binding == BINDING
        if calls is not None:
            calls.append(name)
        return observation(text, name)

    return run


def test_verified_primary_skips_more_expensive_recovery() -> None:
    calls = []
    result = execute(
        {
            Route.PADDLE_FAST: provider(calls=calls),
            Route.PADDLE_VL: provider(name="visual.recovery", calls=calls),
        }
    )
    assert calls == ["visual.primary"]
    assert result.reserved_cost == 1
    assert result.verification_scope == "declared_text_region_only"
    assert result.disposition is D.VERIFIED_TEXT_REGION


def test_missing_sign_triggers_alternate_and_every_replacement_is_verified() -> None:
    result = execute(
        {
            Route.PADDLE_FAST: provider(TEXT.replace("\u2212", "")),
            Route.PADDLE_VL: provider(name="visual.recovery"),
        }
    )
    assert len(result.receipts) == 2
    assert result.accepted.text == TEXT
    assert result.accepted.producer_id == "visual.recovery"
    assert result.reserved_cost == 4
    assert "TEXT_WITNESS_MISMATCH" in result.receipts[0].reasons


def test_two_agreeing_wrong_models_do_not_pass() -> None:
    bad = TEXT.replace("USD", "EUR")
    result = execute(
        {Route.PADDLE_FAST: provider(bad), Route.PADDLE_VL: provider(bad, "visual.recovery")}
    )
    assert result.disposition is D.UNRESOLVED
    assert result.accepted is None


def test_budget_never_launches_an_unfunded_attempt() -> None:
    calls = []
    result = execute(
        {
            Route.PADDLE_FAST: provider("wrong", calls=calls),
            Route.PADDLE_VL: provider(name="visual.recovery", calls=calls),
        },
        budget=3,
    )
    assert calls == ["visual.primary"]
    assert result.reasons == ("EXECUTION_BUDGET_REACHED",)
    assert result.reserved_cost == 1


def test_provider_identity_mismatch_stops_without_recovery() -> None:
    calls = []
    result = execute(
        {
            Route.PADDLE_FAST: provider(name="undeclared.model"),
            Route.PADDLE_VL: provider(name="visual.recovery", calls=calls),
        }
    )
    assert result.disposition is D.QUARANTINED
    assert calls == []


def test_transport_failure_is_not_quality_failure_and_is_accounted() -> None:
    async def fail(_):
        raise RuntimeError("private document content must never appear in receipt")

    result = execute({Route.PADDLE_FAST: fail, Route.PADDLE_VL: provider(name="visual.recovery")})
    assert result.receipts[0].reasons == ("PROVIDER_FAILURE",)
    assert "private document" not in repr(result.receipts)
    assert result.reserved_cost == 4
    assert result.disposition is D.VERIFIED_TEXT_REGION


def test_timeout_cancels_cooperative_worker_before_recovery() -> None:
    stopped = []

    async def slow(_):
        try:
            await asyncio.sleep(60)
        finally:
            stopped.append(True)

    result = execute(
        {Route.PADDLE_FAST: slow, Route.PADDLE_VL: provider(name="visual.recovery")},
        attempts=(replace(PRIMARY, timeout_seconds=0.01), RECOVERY),
    )
    assert stopped == [True]
    assert result.receipts[0].reasons == ("PROVIDER_TIMEOUT",)
    assert result.disposition is D.VERIFIED_TEXT_REGION


def test_explicit_cancellation_never_becomes_a_recovery_attempt() -> None:
    calls = []

    async def cancel(_):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        execute(
            {
                Route.PADDLE_FAST: cancel,
                Route.PADDLE_VL: provider(name="visual.recovery", calls=calls),
            }
        )
    assert calls == []


def test_unpermitted_route_refused_before_any_provider_call() -> None:
    calls = []
    with pytest.raises(ValueError, match="UNPERMITTED"):
        execute(
            {
                Route.PADDLE_FAST: provider(calls=calls),
                Route.PADDLE_VL: provider(name="visual.recovery", calls=calls),
            },
            permitted=frozenset({Route.PADDLE_FAST}),
        )
    assert calls == []


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), -1])
def test_nonfinite_or_negative_budget_is_invalid(budget: float) -> None:
    with pytest.raises(ValueError, match="BUDGET"):
        execute({Route.PADDLE_FAST: provider()}, attempts=(PRIMARY,), budget=budget)
