"""Reader provider contract and capability-resolving registry.

Blueprint §9, §22, §44. The registry resolves on **capability and failure
class**, never on a provider or model name — there is deliberately no public
method that takes a provider id. `akc_router.providers.ProviderUnavailableError`
is reused so an unavailable reader carries the same isolation semantics the
router already gives an unavailable parser.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import jsonschema
from akc_native_parsers.models import StructuredParseError
from akc_router.providers import ProviderUnavailableError

from .enums import (
    EVIDENCE_LOCATOR_SCHEMA_JSON,
    FEATURE_TO_FAILURE_CLASS,
    PARSE_ERROR_TO_CLASS,
    VERIFIED_STATUSES,
    CapabilityStatus,
    FailureClass,
    LocatorKind,
    ReaderFeature,
    ReaderRegistryStatus,
    SourceFamily,
    frozen_contract,
)
from .inspector import inspect_source
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
    digest_units,
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

#: Only an **operational** fault charges a provider's circuit breaker. A source
#: that is empty, corrupt, encrypted or hostile is the *source's* failure, and
#: taking a healthy reader offline for it would break the constitution's
#: "separate operational failure from semantic failure" invariant — three blank
#: customer files must never make a working reader PROVIDER_UNAVAILABLE.
OPERATIONAL_FAILURE_CLASSES: frozenset[FailureClass] = frozenset(
    {
        FailureClass.PARSER_TIMEOUT,
        FailureClass.PARSER_OOM,
        FailureClass.PROVIDER_UNAVAILABLE,
    }
)

#: A **semantic** fault: the reader ran and returned something that does not
#: belong to the source it was given. It never charges the circuit breaker
#: (§8.1); it charges `ReaderHealth.semantic_strikes`, which nothing acts on
#: automatically — de-registration is manual in P0.
SEMANTIC_FAILURE_CLASSES: frozenset[FailureClass] = frozenset(
    {FailureClass.RECEIPT_MISMATCH, FailureClass.EVIDENCE_BROKEN}
)

#: Which frozen `LocatorKind` can honestly address an inspected source. A MIME
#: absent from this table admits **no** locator (fail closed) — plain text is
#: absent because enums v1 has no `text` kind, which is why `plain_text_v1`
#: emits none rather than inventing an anchor.
_ADMISSIBLE_LOCATOR_KINDS: dict[str, frozenset[LocatorKind]] = {
    "application/pdf": frozenset({LocatorKind.PDF}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset(
        {LocatorKind.DOCX}
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset(
        {LocatorKind.XLSX}
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset(
        {LocatorKind.PPTX}
    ),
    "application/json": frozenset({LocatorKind.JSON}),
    "application/xml": frozenset({LocatorKind.XML}),
    "image/png": frozenset({LocatorKind.IMAGE}),
    "image/jpeg": frozenset({LocatorKind.IMAGE}),
    "image/gif": frozenset({LocatorKind.IMAGE}),
    "image/tiff": frozenset({LocatorKind.IMAGE}),
    "image/bmp": frozenset({LocatorKind.IMAGE}),
}


#: A capability names **concrete** lowercase `type/subtype` MIME values only
#: (contract §8.2). A glob is self-witnessing: `*` matches whatever probe sample
#: the provider happens to ship, so one `.txt` used to qualify a reader for every
#: MIME in existence. The pattern below admits no `*`, `?` or `[`, which is why
#: matching is plain equality everywhere below and `fnmatch` is gone.
_CONCRETE_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


class ReaderRegistrationError(ValueError):
    """A provider declared something the registry could not witness."""


@runtime_checkable
class ReaderProvider(Protocol):
    """Blueprint §9. `probe_samples` is what makes a declaration checkable."""

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

    def probe_samples(self) -> tuple[ReaderInput, ...]:
        """One sample per capability, at least. A capability no sample
        exercises cannot be witnessed, so registration refuses it."""
        ...


class VisualReaderProvider(ReaderProvider, Protocol):
    """The optional half of §9. No P0 provider implements it."""

    def render(self, source: ReaderInput) -> NativeExtraction: ...

    def extract_visual(self, rendered: NativeExtraction) -> NativeExtraction: ...


@cache
def _locator_validator() -> jsonschema.protocols.Validator:
    schema = frozen_contract(EVIDENCE_LOCATOR_SCHEMA_JSON)
    return jsonschema.validators.validator_for(schema)(schema)


def validate_evidence_locator(locator: dict[str, Any]) -> None:
    """Validate one locator against the frozen EvidenceLocator v2 schema."""
    _locator_validator().validate(locator)


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
    semantic_strikes: int = 0


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
        for capability in capabilities:
            for pattern in capability.mime_patterns:
                if _CONCRETE_MIME.fullmatch(pattern) is None:
                    raise ReaderRegistrationError(
                        f"{provider.provider_id} declares a non-concrete MIME pattern "
                        f"{pattern!r}; a capability names concrete lowercase MIME types only"
                    )
        declared = {feature for capability in capabilities for feature in capability.features}
        unprobeable = declared - PROBEABLE_FEATURES
        if unprobeable:
            raise ReaderRegistrationError(
                f"{provider.provider_id} declares features the registry cannot witness: "
                + ", ".join(sorted(unprobeable))
            )

        samples = tuple(provider.probe_samples())
        if not samples:
            raise ReaderRegistrationError(
                f"{provider.provider_id} supplies no probe sample; nothing can be witnessed"
            )
        for capability in capabilities:
            if capability.qualification_status in VERIFIED_STATUSES:
                _verify_qualification_receipt(provider.provider_id, capability)

        probes: list[tuple[SourceInspection, NativeExtraction]] = []
        for sample in samples:
            # The **registry's** inspector classifies the probe (contract §8.2):
            # witnessing measured by the same component that classifies a real
            # source. `provider.inspect()` is consulted only to check agreement —
            # before this, a provider could hand back "text/plain" for a PDF
            # sample and witness a `text/plain` pattern with bytes that are not.
            inspection = inspect_source(sample)
            if provider.inspect(sample) != inspection:
                raise ReaderRegistrationError(
                    f"{provider.provider_id} inspects its own probe sample "
                    f"{sample.filename} differently from the registry"
                )
            if not provider.can_read(sample, inspection):
                raise ReaderRegistrationError(
                    f"{provider.provider_id} cannot read its own probe sample {sample.filename}"
                )
            try:
                output = provider.extract_native(sample)
            except Exception as error:
                raise ReaderRegistrationError(
                    f"{provider.provider_id} probe extraction failed: {type(error).__name__}"
                ) from error
            for locator in provider.emit_evidence_locators(output):
                try:
                    validate_evidence_locator(locator)
                except jsonschema.ValidationError as error:
                    raise ReaderRegistrationError(
                        f"{provider.provider_id} emitted an invalid evidence locator: "
                        f"{error.message}"
                    ) from error
                binding = _verify_locator_binding(locator, sample, inspection)
                if binding is not None:
                    raise ReaderRegistrationError(
                        f"{provider.provider_id} emitted a probe locator that does not address "
                        f"the probe sample: {binding[1]}"
                    )
            probes.append((inspection, output))

        # Per **mime pattern and per source family**, not per capability and not
        # across their union (contract §8.1): a `.txt` probe witnesses the
        # `text/plain` pattern of the capability that declares it and nothing
        # else — not a second pattern folded into the same capability, not a
        # second family, and not the same feature on another capability.
        for capability in capabilities:
            observed: set[ReaderFeature] = set()
            patterns: set[str] = set()
            families: set[SourceFamily] = set()
            for inspection, output in probes:
                if inspection.source_family not in capability.source_families:
                    continue
                if inspection.detected_mime not in capability.mime_patterns:
                    continue
                patterns.add(inspection.detected_mime)
                families.add(inspection.source_family)
                observed |= output.observed_features()
            unwitnessed = [item for item in capability.mime_patterns if item not in patterns]
            if unwitnessed:
                raise ReaderRegistrationError(
                    f"{provider.provider_id} declares a capability no probe sample exercises: "
                    + ", ".join(unwitnessed)
                )
            unwitnessed_families = [
                item for item in capability.source_families if item not in families
            ]
            if unwitnessed_families:
                raise ReaderRegistrationError(
                    f"{provider.provider_id} declares a source family no probe sample "
                    "exercises: " + ", ".join(unwitnessed_families)
                )
            missing = set(capability.features) - observed
            if missing:
                raise ReaderRegistrationError(
                    f"{provider.provider_id} declares features its probe did not produce: "
                    + ", ".join(sorted(missing))
                )

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
                update={
                    "circuit_open": entry.breaker.is_open(now, self._cooldown_seconds),
                    "semantic_strikes": entry.semantic_strikes,
                }
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
                failure_class=_corruption_class(inspection.review_reasons),
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
        inspection: SourceInspection | None = None,
        required_features: Iterable[ReaderFeature] = (),
        queue_wait_ms: int = 0,
    ) -> tuple[NativeExtraction | None, ReaderRun]:
        """Run the resolved reader under a timeout and a circuit breaker.

        The inspection is **re-derived from the bytes** here; a caller-supplied
        one is a cross-check, never the decision (contract §8.1). A stale or
        forged inspection used to make the registry accept a source the
        inspector refuses, and turn a security refusal into ordinary corruption.

        Always returns a §44 receipt, including for every refusal.
        """
        started_at = self._clock()
        required = frozenset(required_features)
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

        derived = inspect_source(source)
        if inspection is not None and inspection != derived:
            return None, receipt(
                provider_id="registry",
                revision="uskc-p0",
                runtime_digest=_REGISTRY_RUNTIME_DIGEST,
                accepted=False,
                failure_class=FailureClass.RECEIPT_MISMATCH,
                escalation_reason="the caller's inspection disagrees with the source bytes",
            )
        inspection = derived

        resolution = self.resolve(inspection, required)
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
        if not provider.can_read(source, inspection):
            # Capability resolution says the *declaration* fits; `can_read` is
            # the provider's own look at these bytes. Both must agree.
            return None, receipt(
                provider_id=provider.provider_id,
                revision=provider.revision,
                runtime_digest=provider.runtime_digest,
                accepted=False,
                failure_class=FailureClass.UNSUPPORTED_FORMAT,
                escalation_reason="the resolved provider declined the source at can_read()",
            )
        failure: FailureClass | None = None
        escalation: str | None = None
        output: NativeExtraction | None = None
        cpu_seconds: float | None = None

        try:
            output, cpu_seconds = self._call_with_timeout(provider, source)
            verdict = _verify_output(output, source, provider, required, inspection)
            if verdict is not None:
                failure, escalation = verdict
                output = None
        except FutureTimeoutError:
            failure, escalation = FailureClass.PARSER_TIMEOUT, "extract_native exceeded the timeout"
        except MemoryError:
            failure, escalation = FailureClass.PARSER_OOM, "extract_native exhausted memory"
        except StructuredParseError as error:
            failure = PARSE_ERROR_TO_CLASS.get(error.code, FailureClass.CORRUPT_SOURCE)
            escalation = error.code
        except UnicodeDecodeError as error:
            # The source's own bytes are not what they were detected to be. That
            # is a source failure, not a fault of the reader that reported it.
            failure, escalation = FailureClass.CORRUPT_SOURCE, f"UnicodeDecodeError: {error.reason}"
        except ProviderUnavailableError as error:
            failure, escalation = FailureClass.PROVIDER_UNAVAILABLE, str(error)
        except Exception as error:
            # An exception no branch above classifies is a **defect in the
            # reader on this input**, never evidence that the provider is down.
            # Calling it PROVIDER_UNAVAILABLE published a fault that did not
            # happen and charged the *operational* breaker with it: three such
            # calls from one caller — a malformed `tenant_id` reaching a
            # provider's pydantic context was enough — opened the shared breaker
            # and refused every later caller, any tenant, for the cooldown.
            # PRESERVATION_FAILED is this module's declared "no specific class"
            # fallback and is in neither frozenset above, so the run fails
            # closed without taking a healthy reader offline, and the escalation
            # reason says the class was not diagnosed.
            failure = FailureClass.PRESERVATION_FAILED
            escalation = f"UNCLASSIFIED_READER_ERROR: {type(error).__name__}"

        if failure is None and output is not None and not output.units:
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

        if failure in OPERATIONAL_FAILURE_CLASSES:
            entry.breaker.failures += 1
            if entry.breaker.failures >= self._failure_threshold:
                entry.breaker.opened_at = self._clock()
        elif failure in SEMANTIC_FAILURE_CLASSES:
            # A separate counter, on purpose: a reader that binds evidence to the
            # wrong source is wrong, not unavailable, and taking it offline would
            # hide the defect behind PROVIDER_UNAVAILABLE. De-registration on
            # strikes is a manual act in P0 (contract §8.1).
            entry.semantic_strikes += 1
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


def _capability_matches(
    capability: ReaderCapability,
    inspection: SourceInspection,
    required: frozenset[ReaderFeature],
) -> bool:
    return (
        inspection.source_family in capability.source_families
        and inspection.detected_mime in capability.mime_patterns
        and required.issubset(capability.features)
    )


def _best_capability(
    capabilities: Iterable[ReaderCapability],
    inspection: SourceInspection,
    required: frozenset[ReaderFeature],
) -> ReaderCapability | None:
    best: ReaderCapability | None = None
    for capability in capabilities:
        if capability.qualification_status not in _STATUS_RANK:
            continue
        if not _capability_matches(capability, inspection, required):
            continue
        if best is None or _STATUS_RANK[capability.qualification_status] < _STATUS_RANK[
            best.qualification_status
        ]:
            best = capability
    return best


def _corruption_class(reasons: Iterable[str]) -> FailureClass:
    """A security refusal is never published as ordinary corruption.

    `validate_source()` reports active content, unsafe XML and archive-bomb
    limits through the same `corrupted` fact as a truncated file; the frozen
    class must still say which one it was (lane F reads these strings).
    """
    malware = FailureClass.MALWARE_QUARANTINED
    if any(PARSE_ERROR_TO_CLASS.get(reason) is malware for reason in reasons):
        return malware
    return FailureClass.CORRUPT_SOURCE


def _verify_qualification_receipt(provider_id: str, capability: ReaderCapability) -> None:
    """A VERIFIED tier names a receipt that exists in **this** repository.

    Contract §8.1: "a `VERIFIED_*` capability requires a receipt that exists on
    disk under the repo (path + sha256 + date) — a sha-shaped string alone is
    refused." §8.2 closes the rest of it: the file must be **git-tracked**.
    Present on disk is not committed — a file the provider wrote itself at
    registration time is on disk, and it qualified the tier. Nothing else stands
    between a self-declared `VERIFIED_NATIVE` and the top of `_STATUS_RANK`.
    """
    declared = capability.qualification_receipt_path or ""
    path = (_REPO_ROOT / declared).resolve()
    if not path.is_relative_to(_REPO_ROOT) or not path.is_file():
        raise ReaderRegistrationError(
            f"{provider_id} claims {capability.qualification_status} but no qualification "
            f"receipt is committed at {declared!r}"
        )
    if not _is_git_tracked(declared):
        raise ReaderRegistrationError(
            f"{provider_id} qualification receipt {declared!r} is not tracked by git; "
            "an untracked file is not a committed receipt"
        )
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != capability.qualification_receipt:
        raise ReaderRegistrationError(
            f"{provider_id} qualification receipt {declared!r} digests {digest}, not the "
            f"declared {capability.qualification_receipt}"
        )


def _is_git_tracked(repo_relative_path: str) -> bool:
    """`git ls-files --error-unmatch` on this checkout. No git, no tier."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv; the path is `--`-separated
            ["git", "ls-files", "--error-unmatch", "--", repo_relative_path],  # noqa: S607
            cwd=_REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _verify_locator_binding(
    locator: dict[str, Any],
    source: ReaderInput,
    inspection: SourceInspection,
) -> tuple[FailureClass, str] | None:
    """Bind one locator to the source actually read (contract §8.1).

    The frozen schema only says a locator is *well formed*. It cannot say that
    the ids are this source's, that the kind addresses this MIME, or that the
    page exists — so a schema-valid locator naming another tenant's source
    version, or page 999,999 of a file with no pages, used to ride out on an
    accepted run.
    """
    if (
        locator.get("sourceVersionId") != source.source_version_id
        or locator.get("representationId") != source.representation_id
    ):
        return (
            FailureClass.RECEIPT_MISMATCH,
            "evidence locator names a different source version or representation",
        )
    kind = locator.get("locatorKind")
    admissible = _ADMISSIBLE_LOCATOR_KINDS.get(inspection.detected_mime, frozenset())
    if kind not in admissible:
        return (
            FailureClass.EVIDENCE_BROKEN,
            f"locator kind {kind!r} cannot address a {inspection.detected_mime} source",
        )
    page = locator.get("page")
    pages = inspection.page_like_units
    if page is not None and (pages is None or not 1 <= page <= pages):
        return (
            FailureClass.EVIDENCE_BROKEN,
            f"locator page {page} is outside the source's {pages} page-like units",
        )
    return None


def _verify_output(
    output: NativeExtraction,
    source: ReaderInput,
    provider: ReaderProvider,
    required: frozenset[ReaderFeature],
    inspection: SourceInspection,
) -> tuple[FailureClass, str] | None:
    """Check the extraction against the source that was asked for.

    Registration is a probe, not a declaration — and so is a run: the ids, the
    output digest, the required features and every locator (shape, ids, kind and
    page) are verified here rather than trusted from the provider's assertion.
    """
    if (
        output.source_version_id != source.source_version_id
        or output.representation_id != source.representation_id
        or output.provider_id != provider.provider_id
    ):
        return (
            FailureClass.RECEIPT_MISMATCH,
            "extraction is bound to a different source version, representation or provider",
        )
    if output.output_digest != digest_units(output.units):
        return FailureClass.RECEIPT_MISMATCH, "outputDigest does not digest the units returned"
    missing = required - output.observed_features()
    if missing:
        first = sorted(missing)[0]
        return (
            FEATURE_TO_FAILURE_CLASS.get(
                ReaderFeature(first), FailureClass.PRESERVATION_FAILED
            ),
            "required feature absent from the output: " + ", ".join(sorted(missing)),
        )
    seen: set[int] = set()
    carried = (
        *provider.emit_evidence_locators(output),
        *(unit.locator for unit in output.units if unit.locator is not None),
    )
    for locator in carried:
        if id(locator) in seen:
            continue
        seen.add(id(locator))
        try:
            validate_evidence_locator(locator)
        except jsonschema.ValidationError as error:
            return FailureClass.EVIDENCE_BROKEN, f"invalid evidence locator: {error.message}"
        binding = _verify_locator_binding(locator, source, inspection)
        if binding is not None:
            return binding
    return None


_REGISTRY_RUNTIME_DIGEST = "sha256:" + hashlib.sha256(b"akc_readers.registry/uskc-p0").hexdigest()

#: This checkout's root: ``<repo>/packages/readers/src/akc_readers/registry.py``.
#: A qualification receipt is only a receipt if it is committed *here*.
_REPO_ROOT = Path(__file__).resolve().parents[4]


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_TIMEOUT_SECONDS",
    "OPERATIONAL_FAILURE_CLASSES",
    "SEMANTIC_FAILURE_CLASSES",
    "ReaderProvider",
    "ReaderRegistrationError",
    "ReaderRegistry",
    "VisualReaderProvider",
    "validate_evidence_locator",
]
