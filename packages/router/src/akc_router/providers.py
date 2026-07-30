"""Provider protocols and capability-aware registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, runtime_checkable

from akc_cir import ContractModel, StableId
from pydantic import Field, field_validator

from .models import Route


class ParserCapabilities(ContractModel):
    routes: frozenset[Route]
    languages: frozenset[str] = frozenset()
    supports_tables: bool = False
    supports_formulas: bool = False
    supports_charts: bool = False
    supports_bounding_boxes: bool = False
    max_pages_per_request: Annotated[int, Field(ge=1)] = 1


class ParseRequest(ContractModel):
    request_id: StableId
    tenant_id: StableId
    document_id: StableId
    document_version_id: StableId
    object_key: str
    page_indexes0: tuple[int, ...]
    route: Route
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("page_indexes0")
    @classmethod
    def validate_page_indexes(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value or any(index < 0 for index in value):
            raise ValueError("pageIndexes0 must contain non-negative page indexes")
        if len(value) != len(set(value)):
            raise ValueError("pageIndexes0 must be unique")
        return value


class ParseResult(ContractModel):
    request_id: StableId
    provider_id: str
    model_run_id: StableId
    raw_output_object_key: str
    page_indexes0: tuple[int, ...]
    usage_gpu_seconds: float = 0.0
    provider_request_id: str | None = None


class KnowledgeRequest(ContractModel):
    request_id: StableId
    tenant_id: StableId
    document_id: StableId
    input_object_key: str
    schema_name: str
    route_profile: str
    options: dict[str, Any] = Field(default_factory=dict)


class KnowledgeResult(ContractModel):
    request_id: StableId
    provider_id: str
    model_run_id: StableId
    output_object_key: str
    usage_gpu_seconds: float = 0.0


@runtime_checkable
class ParserProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> ParserCapabilities: ...

    async def parse(self, request: ParseRequest) -> ParseResult: ...


@runtime_checkable
class KnowledgeProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def compile(self, request: KnowledgeRequest) -> KnowledgeResult: ...


@dataclass
class _ProviderState:
    provider: ParserProvider | KnowledgeProvider
    enabled: bool
    ready: bool


class ProviderUnavailableError(LookupError):
    """Execution must route to manual review when this error is raised."""

    manual_review_required = True


class ProviderRegistry:
    """Reject duplicate and incapable providers instead of silently degrading."""

    def __init__(self) -> None:
        self._parsers: dict[str, _ProviderState] = {}
        self._knowledge: dict[str, _ProviderState] = {}

    @property
    def parsers(self) -> Mapping[str, ParserProvider]:
        return {
            provider_id: state.provider
            for provider_id, state in self._parsers.items()
            if isinstance(state.provider, ParserProvider)
        }

    def register_parser(
        self,
        provider: ParserProvider,
        *,
        enabled: bool = True,
        ready: bool = False,
    ) -> None:
        if provider.provider_id in self._parsers:
            raise ValueError(f"duplicate parser provider: {provider.provider_id}")
        self._parsers[provider.provider_id] = _ProviderState(
            provider=provider,
            enabled=enabled,
            ready=ready,
        )

    def register_knowledge(
        self,
        provider: KnowledgeProvider,
        *,
        enabled: bool = True,
        ready: bool = False,
    ) -> None:
        if provider.provider_id in self._knowledge:
            raise ValueError(f"duplicate knowledge provider: {provider.provider_id}")
        self._knowledge[provider.provider_id] = _ProviderState(
            provider=provider,
            enabled=enabled,
            ready=ready,
        )

    def set_parser_state(
        self,
        provider_id: str,
        *,
        enabled: bool | None = None,
        ready: bool | None = None,
    ) -> None:
        try:
            state = self._parsers[provider_id]
        except KeyError as exc:
            raise LookupError(f"unknown parser provider: {provider_id}") from exc
        if enabled is not None:
            state.enabled = enabled
        if ready is not None:
            state.ready = ready

    def set_knowledge_state(
        self,
        provider_id: str,
        *,
        enabled: bool | None = None,
        ready: bool | None = None,
    ) -> None:
        try:
            state = self._knowledge[provider_id]
        except KeyError as exc:
            raise LookupError(f"unknown knowledge provider: {provider_id}") from exc
        if enabled is not None:
            state.enabled = enabled
        if ready is not None:
            state.ready = ready

    def parser_for(self, provider_id: str, route: Route) -> ParserProvider:
        try:
            state = self._parsers[provider_id]
        except KeyError as exc:
            raise LookupError(f"unknown parser provider: {provider_id}") from exc
        if not state.enabled:
            raise ProviderUnavailableError(f"parser provider disabled: {provider_id}")
        if not state.ready:
            raise ProviderUnavailableError(f"parser provider not ready: {provider_id}")
        provider = state.provider
        if not isinstance(provider, ParserProvider):
            raise ProviderUnavailableError(f"invalid parser provider: {provider_id}")
        if route not in provider.capabilities.routes:
            raise LookupError(f"provider {provider_id} does not support route {route.value}")
        return provider

    def knowledge_for(self, provider_id: str) -> KnowledgeProvider:
        try:
            state = self._knowledge[provider_id]
        except KeyError as exc:
            raise LookupError(f"unknown knowledge provider: {provider_id}") from exc
        if not state.enabled:
            raise ProviderUnavailableError(f"knowledge provider disabled: {provider_id}")
        if not state.ready:
            raise ProviderUnavailableError(f"knowledge provider not ready: {provider_id}")
        provider = state.provider
        if not isinstance(provider, KnowledgeProvider):
            raise ProviderUnavailableError(f"invalid knowledge provider: {provider_id}")
        return provider
