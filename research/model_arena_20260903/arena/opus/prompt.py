"""Prompt resolution for the Opus lane (masterplan section 21.5).

Lane A4 owns ``prompt_registry/opus5_transcription_v1.txt``. Until it exists this
lane uses a private copy transcribed verbatim from the masterplan code fence and
says so in every receipt. When the registry copy appears it wins unconditionally,
and a difference between the two is reported rather than silently accepted --
the prompt sha256 is part of ``inference_job_id``, so two different texts are two
different experiments.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arena.opus.paths import FALLBACK_PROMPT_PATH, REGISTRY_PROMPT_PATH, sha256_tagged

PROMPT_ID = "opus5_transcription_v1"


class PromptError(RuntimeError):
    """Raised when no usable prompt text can be resolved."""


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    prompt_id: str
    text: str
    sha256: str
    path: Path
    source: str
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "prompt_id": self.prompt_id,
            "prompt_sha256": self.sha256,
            "prompt_path": str(self.path),
            "prompt_source": self.source,
            "prompt_notes": list(self.notes),
        }


def resolve_prompt(
    *, registry_path: Path | None = None, fallback_path: Path | None = None
) -> ResolvedPrompt:
    registry = registry_path or REGISTRY_PROMPT_PATH
    fallback = fallback_path or FALLBACK_PROMPT_PATH

    if registry.is_file():
        data = registry.read_bytes()
        notes = ["Prompt read from the lane A4 registry copy."]
        if fallback.is_file():
            fallback_sha = sha256_tagged(fallback.read_bytes())
            registry_sha = sha256_tagged(data)
            if fallback_sha != registry_sha:
                notes.append(
                    "Lane D's private copy of the masterplan section 21.5 text hashes to "
                    f"{fallback_sha}, the registry copy to {registry_sha}. The registry copy "
                    "is authoritative; the difference is reported, not reconciled here."
                )
        return ResolvedPrompt(
            prompt_id=PROMPT_ID,
            text=data.decode("utf-8"),
            sha256=sha256_tagged(data),
            path=registry,
            source="prompt_registry",
            notes=tuple(notes),
        )

    if not fallback.is_file():
        raise PromptError(
            f"no prompt available: neither {registry} (lane A4) nor {fallback} exists"
        )
    data = fallback.read_bytes()
    return ResolvedPrompt(
        prompt_id=PROMPT_ID,
        text=data.decode("utf-8"),
        sha256=sha256_tagged(data),
        path=fallback,
        source="lane_d_fallback",
        notes=(
            "prompt_registry/opus5_transcription_v1.txt does not exist yet; used lane D's "
            "private copy transcribed verbatim from masterplan section 21.5 (LF newlines, "
            "one trailing newline).",
            "The registry copy MUST hash to this value or the receipts describe a different "
            "prompt than the campaign registry claims.",
        ),
    )


__all__ = ["PROMPT_ID", "PromptError", "ResolvedPrompt", "resolve_prompt"]
