"""Provider boundary regressions. Synthetic tests, not model-quality evidence."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from akc_router.evidence_execution import (
    EvidenceDisposition,
    IndependentTextWitness,
    RegionAttempt,
    RegionBinding,
    TextObservation,
    execute_text_region,
    text_digest,
)
from akc_router.models import Route

BINDING = RegionBinding(
    "sha256:" + "a" * 64, "sha256:" + "b" * 64, 0, "region:boundary", (0, 0, 1000, 1000)
)
TEXT = "Revenue was -12.5 million USD."


def observation(producer: str = "visual.primary") -> TextObservation:
    return TextObservation(BINDING, producer, TEXT, text_digest(TEXT))


def run_provider(provider: Any, timeout: float = 0.01):
    return asyncio.run(
        execute_text_region(
            binding=BINDING,
            witness=IndependentTextWitness(observation("native.source"), "source:1", True),
            attempts=(RegionAttempt(Route.PADDLE_FAST, "visual.primary", 1.0, timeout),),
            providers={Route.PADDLE_FAST: provider},
            permitted_routes=frozenset({Route.PADDLE_FAST}),
            cost_budget=1.0,
            deadline_seconds=1.0,
        )
    )


def test_provider_cannot_accept_a_result_after_suppressing_timeout() -> None:
    async def suppress_cancel(_: RegionBinding) -> TextObservation:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return observation()
        raise AssertionError("timeout was not delivered")

    result = run_provider(suppress_cancel)
    assert result.disposition is EvidenceDisposition.UNRESOLVED
    assert result.accepted is None
    assert result.receipts[0].reasons == ("PROVIDER_TIMEOUT",)
    assert result.reserved_cost == 1.0


def test_blocking_provider_cannot_accept_after_expired_wall_deadline() -> None:
    async def blocking(_: RegionBinding) -> TextObservation:
        time.sleep(0.03)  # noqa: ASYNC251 -- deliberately emulate a blocking adapter
        return observation()

    result = run_provider(blocking, timeout=0.001)
    assert result.disposition is EvidenceDisposition.UNRESOLVED
    assert result.accepted is None
    assert result.receipts[0].reasons == ("PROVIDER_TIMEOUT",)


@pytest.mark.parametrize("invalid", [None, {}, {"text": TEXT}, "not-an-observation", 42])
def test_malformed_provider_result_is_recorded_without_an_uncaught_exception(invalid: Any) -> None:
    async def malformed(_: RegionBinding) -> Any:
        return invalid

    result = run_provider(malformed)
    assert result.disposition is EvidenceDisposition.UNRESOLVED
    assert result.accepted is None
    assert len(result.receipts) == 1
    assert result.receipts[0].reasons == ("PROVIDER_RESULT_INVALID",)
    assert result.receipts[0].output_sha256 is None
    assert result.reserved_cost == 1.0


def test_caller_cancellation_is_not_swallowed_by_a_provider() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()

        async def suppress_cancel(_: RegionBinding) -> TextObservation:
            entered.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                return observation()
            raise AssertionError("cancellation was not delivered")

        task = asyncio.create_task(
            execute_text_region(
                binding=BINDING,
                witness=IndependentTextWitness(observation("native.source"), "source:1", True),
                attempts=(RegionAttempt(Route.PADDLE_FAST, "visual.primary", 1.0, 1.0),),
                providers={Route.PADDLE_FAST: suppress_cancel},
                permitted_routes=frozenset({Route.PADDLE_FAST}),
                cost_budget=1.0,
                deadline_seconds=2.0,
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_attempt_mutation_cannot_add_an_unpermitted_route_after_validation() -> None:
    attempts = [RegionAttempt(Route.PADDLE_FAST, "visual.primary", 1.0, 1.0)]
    calls: list[str] = []

    async def primary(_: RegionBinding) -> TextObservation:
        attempts.append(RegionAttempt(Route.PADDLE_VL, "visual.recovery", 1.0, 1.0))
        return TextObservation(BINDING, "visual.primary", "wrong", text_digest("wrong"))

    async def recovery(_: RegionBinding) -> TextObservation:
        calls.append("unpermitted")
        return observation("visual.recovery")

    result = asyncio.run(
        execute_text_region(
            binding=BINDING,
            witness=IndependentTextWitness(observation("native.source"), "source:1", True),
            attempts=attempts,
            providers={Route.PADDLE_FAST: primary, Route.PADDLE_VL: recovery},
            permitted_routes=frozenset({Route.PADDLE_FAST}),
            cost_budget=3.0,
            deadline_seconds=2.0,
        )
    )
    assert calls == []
    assert result.disposition is EvidenceDisposition.UNRESOLVED
    assert len(result.receipts) == 1


def test_provider_map_is_bound_before_first_await() -> None:
    calls: list[str] = []
    providers: dict[Route, Any] = {}

    async def trusted(_: RegionBinding) -> TextObservation:
        calls.append("trusted")
        return observation("visual.recovery")

    async def replacement(_: RegionBinding) -> TextObservation:
        calls.append("replacement")
        return observation("visual.recovery")

    async def primary(_: RegionBinding) -> TextObservation:
        providers[Route.PADDLE_VL] = replacement
        return TextObservation(BINDING, "visual.primary", "wrong", text_digest("wrong"))

    providers.update({Route.PADDLE_FAST: primary, Route.PADDLE_VL: trusted})
    result = asyncio.run(
        execute_text_region(
            binding=BINDING,
            witness=IndependentTextWitness(observation("native.source"), "source:1", True),
            attempts=(
                RegionAttempt(Route.PADDLE_FAST, "visual.primary", 1.0, 1.0),
                RegionAttempt(Route.PADDLE_VL, "visual.recovery", 1.0, 1.0),
            ),
            providers=providers,
            permitted_routes=frozenset(providers),
            cost_budget=3.0,
            deadline_seconds=2.0,
        )
    )
    assert calls == ["trusted"]
    assert result.disposition is EvidenceDisposition.VERIFIED_TEXT_REGION
