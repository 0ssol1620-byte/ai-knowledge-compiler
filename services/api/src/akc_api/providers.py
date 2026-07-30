"""Provider contracts with deterministic local and fail-closed external adapters."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal, Protocol


class ProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledNote:
    stable_key: str
    title: str
    markdown: str
    evidence_block_ids: tuple[str, ...]
    content_origin: str = "ai_summarized"


class KnowledgeProvider(Protocol):
    async def compile(
        self,
        *,
        title: str,
        blocks: list[tuple[str, str]],
    ) -> list[CompiledNote]: ...


class KnowledgeProviderSettings(Protocol):
    env: Literal["development", "test", "production"]
    knowledge_provider: Literal["deterministic", "qwen_durable"]
    private_mode: bool
    external_ocr_enabled: bool
    qwen_endpoint_id: str
    qwen_provider_key: str
    qwen_model_revision: str
    qwen_runtime_image_digest: str
    qwen_adapter_version: str
    qwen_prompt_revision: str
    qwen_knowledge_schema_sha256: str
    qwen_max_attempts: int


class DeterministicKnowledgeProvider:
    revision = "deterministic-local-1"

    async def compile(self, *, title: str, blocks: list[tuple[str, str]]) -> list[CompiledNote]:
        evidence = tuple(block_id for block_id, text in blocks if text.strip())
        body = "\n\n".join(text.strip() for _, text in blocks if text.strip())
        digest = hashlib.sha256((title + body).encode()).hexdigest()[:16]
        safe_key = re.sub(r"[^a-z0-9._-]", "-", title.lower()).strip("-")[:80]
        stable_key = f"{safe_key or 'document'}.{digest}"
        return [
            CompiledNote(
                stable_key=stable_key,
                title=title,
                markdown=f"# {title}\n\n{body}".rstrip() + "\n",
                evidence_block_ids=evidence,
            )
        ]


@dataclass(frozen=True, slots=True)
class DurableQwenKnowledgeProvider:
    endpoint_id: str
    provider_key: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    prompt_revision: str
    knowledge_schema_sha256: str
    max_attempts: int


class FailClosedExternalProvider:
    def __init__(self, settings: KnowledgeProviderSettings) -> None:
        self.settings = settings

    async def compile(
        self,
        *,
        title: str,
        blocks: list[tuple[str, str]],
    ) -> list[CompiledNote]:
        del title, blocks
        if self.settings.private_mode:
            raise ProviderUnavailable("PRIVATE_MODE_EXTERNAL_TRANSFER_DENIED")
        if not self.settings.external_ocr_enabled:
            raise ProviderUnavailable("EXTERNAL_PROVIDER_DISABLED")
        raise ProviderUnavailable("EXTERNAL_PROVIDER_NOT_CONFIGURED")


def knowledge_provider(
    settings: KnowledgeProviderSettings,
    external_requested: bool,
) -> DeterministicKnowledgeProvider | DurableQwenKnowledgeProvider | FailClosedExternalProvider:
    if external_requested:
        return FailClosedExternalProvider(settings)
    if settings.knowledge_provider == "deterministic":
        if settings.env == "production":
            raise ProviderUnavailable("DETERMINISTIC_PROVIDER_FORBIDDEN_IN_PRODUCTION")
        return DeterministicKnowledgeProvider()
    if settings.knowledge_provider == "qwen_durable":
        return DurableQwenKnowledgeProvider(
            endpoint_id=settings.qwen_endpoint_id,
            provider_key=settings.qwen_provider_key,
            model_revision=settings.qwen_model_revision,
            runtime_image_digest=settings.qwen_runtime_image_digest,
            adapter_version=settings.qwen_adapter_version,
            prompt_revision=settings.qwen_prompt_revision,
            knowledge_schema_sha256=settings.qwen_knowledge_schema_sha256,
            max_attempts=settings.qwen_max_attempts,
        )
    raise ProviderUnavailable("KNOWLEDGE_PROVIDER_NOT_CONFIGURED")


__all__ = [
    "CompiledNote",
    "DeterministicKnowledgeProvider",
    "DurableQwenKnowledgeProvider",
    "FailClosedExternalProvider",
    "KnowledgeProvider",
    "KnowledgeProviderSettings",
    "ProviderUnavailable",
    "knowledge_provider",
]
