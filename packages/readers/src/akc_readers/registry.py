"""Reader provider contract and capability-resolving registry.

Blueprint §9, §22, §44. The registry resolves on **capability and failure
class**, never on a provider or model name — there is deliberately no public
method that takes a provider id. `akc_router.providers.ProviderUnavailableError`
is reused so an unavailable reader carries the same isolation semantics the
router already gives an unavailable parser.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any, Protocol, runtime_checkable

import jsonschema
from akc_native_parsers.models import StructuredParseError
from akc_router.providers import ProviderUnavailableError

from .enums import (
    EVIDENCE_LOCATOR_SCHEMA_JSON,
    PARSE_ERROR_TO_CLASS,
    CapabilityStatus,
    FailureClass,
    ReaderFeature,
    ReaderRegistryStatus,
    frozen_contract,
)
from .models import (
    PROBEABLE_FEATURES,
    NativeExtraction,
    ReaderCapability,
    ReaderHealth,
    ReaderInput,
    ReaderRegistryEntry,
    ReaderResolution,
    ReaderRun,
    SourceInspection,
)

#: Preference order when several providers can read the same source. It is a
#: qualification-tier order; `provider_id` breaks a tie only so resolution is
#: deterministic, and it is never a preference for a name.
_STATUS_RANK: dict[CapabilityStatus, int] = {
    CapabilityStatus.VERIFIED_NATIVE: 0,
    CapabilityStatus.VERIFIED_HYBRID: 1,
    CapabilityStatus.BEST_EFFORT: 2,
    CapabilityStatus.METADATA_ONLY: 3,
}

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 30.0


class ReaderRegistrationError(ValueError):
    """A provider declared something the registry could not witness."""


@runtime_checkable
class ReaderProvider(Protocol):
    """Blueprint §9. `probe_sample` is what makes a declaration checkable."""

    @property
    def provider_id(self) -> str: ...

    @property
    def revision(self) -> str: ...

    @property
    def runtime_digest(self) -> str: ...

    def capabilities(self) -> tuple[ReaderCapability, ...]: ...

    def inspect(self, source: ReaderInput) -> SourceInspection: ...

    def can_read(self, source: ReaderInput, inspection: SourceInspection) -> bool: ...

    def extract_native(self, source: ReaderInput) -> NativeExtraction: ...

    def emit_evidence_locators(self, output: NativeExtraction) -> tuple[dict[str, Any], ...]: ...

    def health_check(self) -> ReaderHealth: ...

    def probe_sample(self) -> ReaderInput: ...


class VisualReaderProvider(ReaderProvider, Protocol):
    """The optional half of §9. No P0 provider implements it."""

    def render(self, source: ReaderInput) -> NativeExtraction: ...

    def extract_visual(self, rendered: NativeExtraction) -> NativeExtraction: ...


def validate_evidence_locator(locator: dict[str, Any]) -> None:
    """Validate one locator against the frozen EvidenceLocator v2 schema."""
    jsonschema.validate(locator, frozen_contract(EVIDENCE_LOCATOR_SCHEMA_JSON))


@dataclass
class _Breaker:
    failures: int = 0
    opened_at: datetime | None = None

    def is_open(self, now: datetime, cooldown_seconds: float) -> bool:
        if self.opened_at is None:
            return False
        if (now - self.opened_at).total_seconds() >= cooldown_seconds:
            self.opened_at = None
            self.failures = 0
            return False
        return True


@dataclass
class _Entry:
    provider: ReaderProvider
    capabilities: tuple[ReaderCapability, ...]
    breaker: _Breaker = field(default_factory=_Breaker)


class ReaderRegistry:
    """Registers probed readers and resolves one by capability."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._entries: dict[str, _Entry] = {}
        self._timeout_seconds = timeout_seconds
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- registration ---------------------------------------------------

    def register(self, provider: ReaderProvider) -> None:
        """Accept a provider only after witnessing every feature it declares."""
        if provider.provider_id in self._entries:
            raise ReaderRegistrationError(f"duplicate reader provider: {provider.provider_id}")
        capabilities = tuple(provider.capabilities())
        if not capabilities:
            raise ReaderRegistrationError(
                f"{provider.provider_id} declares no capability; nothing can be probed"
            )
        declared = {feature for capability in capabilities for feature in capability.features}
        unprobeable = declared - PROBEABLE_FEATURES
        if unprobeable:
            raise ReaderRegistrationError(
                f"{provider.provider_id} declares features the registry cannot witness: "
                + ", ".join(sorted(unprobeable))
            )

        sample = provider.probe_sample()
        inspection = provider.inspect(sample)
        if not provider.can_read(sample, inspection):
            raise ReaderRegistrationError(
                f"{provider.provider_id} cannot read its own probe sample"
            )
        try:
            output = provider.extract_native(sample)
        except Exception as error:
            raise ReaderRegistrationError(
                f"{provider.provider_id} probe extraction failed: {type(error).__name__}"
            ) from error
        observed = output.observed_features()
        missing = declared - observed
        if missing:
            raise ReaderRegistrationError(
                f"{provider.provider_id} declares features its probe did not produce: "
                + ", ".join(sorted(missing))
            )
        for locator in provider.emit_evidence_locators(output):
            try:
                validate_evidence_locator(locator)
            except jsonschema.ValidationError as error:
                raise ReaderRegistrationError(
                    f"{provider.provider_id} emitted an invalid evidence locator: {error.message}"
                ) from error

        health = provider.health_check()
        if not health.healthy:
            raise ReaderRegistrationError(
                f"{provider.provider_id} is unhealthy at registration: {health.detail}"
            )
        self._entries[provider.provider_id] = _Entry(provider=provider, capabilities=capabilities)

    # -- projections ----------------------------------------------------

    def entries(self) -> tuple[ReaderRegistryEntry, ...]:
        """Blueprint §22 rows. Every measured field is `None` until an
        evaluator receipt exists, so no entry is ever `qualified` here."""
        rows: list[ReaderRegistryEntry] = []
        for entry in sorted(self._entries.values(), key=lambda item: item.provider.provider_id):
            families = sorted(
                {
                    family
                    for capability in entry.capabilities
                    for family in capability.source_families
                }
            )
            rows.append(
                ReaderRegistryEntry(
                    reader_id=entry.provider.provider_id,
                    model_revision=entry.provider.revision,
                    runtime_digest=entry.provider.runtime_digest,
                    qualified_source_families=tuple(families),
                    status=ReaderRegistryStatus.CANDIDATE,
                )
            )
        return tuple(rows)

    def health(self) -> tuple[ReaderHealth, ...]:
        now = self._clock()
        return tuple(
            entry.provider.health_check().model_copy(
                update={"circuit_open": entry.breaker.is_open(now, self._cooldown_seconds)}
            )
            for entry in sorted(self._entries.values(), key=lambda item: item.provider.provider_id)
        )

    # -- resolution -----------------------------------------------------

    def resolve(
        self,
        inspection: SourceInspection,
        required_features: Iterable[ReaderFeature] = (),
    ) -> ReaderResolution:
        """Pick a reader by capability. Hostile input is described, not raised."""
        required = frozenset(required_features)
        if inspection.encrypted:
            return ReaderResolution(
                status=CapabilityStatus.REVIEW_REQUIRED,
                failure_class=FailureClass.ENCRYPTED_SOURCE,
                reasons=inspection.review_reasons,
            )
        if inspection.corrupted:
            return ReaderResolution(
                status=CapabilityStatus.REVIEW_REQUIRED,
                failure_class=FailureClass.CORRUPT_SOURCE,
                reasons=inspection.review_reasons,
            )

        now = self._clock()
        matches: list[tuple[int, str, ReaderCapability]] = []
        blocked = False
        for entry in self._entries.values():
            capability = _best_capability(entry.capabilities, inspection, required)
            if capability is None:
                continue
            if entry.breaker.is_open(now, self._cooldown_seconds):
                blocked = True
                continue
            rank = _STATUS_RANK[capability.qualification_status]
            matches.append((rank, entry.provider.provider_id, capability))

        if not matches:
            if blocked:
                return ReaderResolution(
                    status=CapabilityStatus.REVIEW_REQUIRED,
                    failure_class=FailureClass.PROVIDER_UNAVAILABLE,
                    reasons=("circuit_open",),
                )
            return ReaderResolution(
                status=CapabilityStatus.UNSUPPORTED,
                failure_class=FailureClass.UNSUPPORTED_FORMAT,
                reasons=(f"no reader declares {inspection.detected_mime}",),
            )

        _, provider_id, capability = min(matches, key=lambda item: (item[0], item[1]))
        return ReaderResolution(
            status=capability.qualification_status,
            provider_id=provider_id,
            reasons=inspection.review_reasons,
        )

    # -- execution ------------------------------------------------------

    def read(
        self,
        source: ReaderInput,
        *,
        inspection: SourceInspection,
        required_features: Iterable[ReaderFeature] = (),
        queue_wait_ms: int = 0,
    ) -> tuple[NativeExtraction | None, ReaderRun]:
        """Run the resolved reader under a timeout and a circuit breaker.

        Always returns a §44 receipt, including for every refusal.
        """
        started_at = self._clock()
        input_digest = "sha256:" + hashlib.sha256(source.data).hexdigest()

        def receipt(
            *,
            provider_id: str,
            revision: str,
            runtime_digest: str,
            accepted: bool,
            output_digest: str | None = None,
            failure_class: FailureClass | None = None,
            escalation_reason: str | None = None,
            cpu_seconds: float | None = None,
        ) -> ReaderRun:
            return ReaderRun(
                run_id=uuid.uuid4().hex,
                source_version_id=source.source_version_id,
                representation_id=source.representation_id,
                provider_id=provider_id,
                reader_revision=revision,
                runtime_digest=runtime_digest,
                input_digest=input_digest,
                output_digest=output_digest,
                started_at=started_at,
                ended_at=self._clock(),
                queue_wait_ms=queue_wait_ms,
                accepted=accepted,
                failure_class=failure_class,
                cpu_seconds=cpu_seconds,
                escalation_reason=escalation_reason,
            )

        if source.content_sha256 != input_digest:
            return None, receipt(
                provider_id="registry",
                revision="uskc-p0",
                runtime_digest=_REGISTRY_RUNTIME_DIGEST,
                accepted=False,
                failure_class=FailureClass.RECEIPT_MISMATCH,
                escalation_reason="sourceVersion contentSha256 does not digest the bytes supplied",
            )

        resolution = self.resolve(inspection, required_features)
        if resolution.provider_id is None:
            return None, receipt(
                provider_id="registry",
                revision="uskc-p0",
                runtime_digest=_REGISTRY_RUNTIME_DIGEST,
                accepted=False,
                failure_class=resolution.failure_class,
                escalation_reason=f"{resolution.status}: {'; '.join(resolution.reasons)}",
            )

        entry = self._entries[resolution.provider_id]
        provider = entry.provider
        failure: FailureClass | None = None
        escalation: str | None = None
        output: NativeExtraction | None = None
        cpu_seconds: float | None = None

        try:
            output, cpu_seconds = self._call_with_timeout(provider, source)
        except FutureTimeoutError:
            failure, escalation = FailureClass.PARSER_TIMEOUT, "extract_native exceeded the timeout"
        except MemoryError:
            failure, escalation = FailureClass.PARSER_OOM, "extract_native exhausted memory"
        except StructuredParseError as error:
            failure = PARSE_ERROR_TO_CLASS.get(error.code, FailureClass.CORRUPT_SOURCE)
            escalation = error.code
        except ProviderUnavailableError as error:
            failure, escalation = FailureClass.PROVIDER_UNAVAILABLE, str(error)
        except Exception as error:
            failure, escalation = FailureClass.PROVIDER_UNAVAILABLE, type(error).__name__

        if output is not None and not output.units:
            failure, escalation = FailureClass.EMPTY_OUTPUT, "reader produced no units"
            output = None

        if failure is None and output is not None:
            entry.breaker.failures = 0
            return output, receipt(
                provider_id=provider.provider_id,
                revision=provider.revision,
                runtime_digest=provider.runtime_digest,
                accepted=True,
                output_digest=output.output_digest,
                cpu_seconds=cpu_seconds,
            )

        entry.breaker.failures += 1
        if entry.breaker.failures >= self._failure_threshold:
            entry.breaker.opened_at = self._clock()
        return None, receipt(
            provider_id=provider.provider_id,
            revision=provider.revision,
            runtime_digest=provider.runtime_digest,
            accepted=False,
            failure_class=failure,
            escalation_reason=escalation,
            cpu_seconds=cpu_seconds,
        )

    def _call_with_timeout(
        self, provider: ReaderProvider, source: ReaderInput
    ) -> tuple[NativeExtraction, float]:
        # ponytail: a timed-out worker thread keeps running to completion —
        # Python cannot kill one. That is a leaked CPU second, not a leaked
        # result: the receipt is PARSER_TIMEOUT and the output is discarded. A
        # hard kill needs the repo's existing `-I` subprocess sandbox, which is
        # the upgrade path when a reader can actually hang unboundedly.
        def call() -> tuple[NativeExtraction, float]:
            started = time.thread_time()
            result = provider.extract_native(source)
            return result, round(time.thread_time() - started, 6)

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(call).result(timeout=self._timeout_seconds)


def _best_capability(
    capabilities: Iterable[ReaderCapability],
    inspection: SourceInspection,
    required: frozenset[ReaderFeature],
) -> ReaderCapability | None:
    best: ReaderCapability | None = None
    for capability in capabilities:
        if capability.qualification_status not in _STATUS_RANK:
            continue
        if inspection.source_family not in capability.source_families:
            continue
        if not any(
            fnmatchcase(inspection.detected_mime, pattern) for pattern in capability.mime_patterns
        ):
            continue
        if not required.issubset(capability.features):
            continue
        if best is None or _STATUS_RANK[capability.qualification_status] < _STATUS_RANK[
            best.qualification_status
        ]:
            best = capability
    return best


_REGISTRY_RUNTIME_DIGEST = "sha256:" + hashlib.sha256(b"akc_readers.registry/uskc-p0").hexdigest()


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_TIMEOUT_SECONDS",
    "ReaderProvider",
    "ReaderRegistrationError",
    "ReaderRegistry",
    "VisualReaderProvider",
    "validate_evidence_locator",
]
