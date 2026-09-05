"""Resolve a model's prompt hash from ``prompt_registry/`` (D15, D17, D34).

The chain has exactly one direction and no shortcuts:

    runtimes/<model_key>/runtime.json  ->  prompt_id
    prompt_registry/sha256.json        ->  prompt_id -> sha256
    prompt_registry/<prompt_id>.txt    ->  the bytes the adapter sends

The registry (``model_registry.json``) is a derived copy and is never the
source of a prompt hash for a canary: D16 makes ``runtime.json`` the owner of
``prompt_id``, and D17 keys ``sha256.json`` by that id. A prompt id with no
entry, a ``null`` entry, or an entry whose text file is absent is a refusal
naming the id -- a pod started against an unknown prompt would produce output
attributed to a prompt nobody can reproduce.

``prompt_kind: "none"`` (D34) is not an exception to any of that. A pipeline
with no prompt still has a registry entry: an empty file whose sha256 is the
hash of the empty string. Lane R writes it; this module only checks that it is
there, because a missing entry and a deliberately empty one look identical from
here and only one of them is a decision anybody made.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from arena.provider.safety import read_json, sha256_bytes

__all__ = [
    "EMPTY_PROMPT_SHA256",
    "PROMPT_KINDS",
    "PromptError",
    "PromptRef",
    "prompt_registry_dir",
    "resolve_prompt",
]

PROMPT_KINDS: Final = ("text", "toolkit", "none")
EMPTY_PROMPT_SHA256: Final = "sha256:" + hashlib.sha256(b"").hexdigest()

# ARENA_CONTRACT 11.3(2)/D17: the bundle carries prompt_registry/ and every
# baked image copies it here, so the worker resolves the same file the
# controller hashed.
POD_PROMPT_DIR: Final = "/opt/arena/prompt_registry"


class PromptError(RuntimeError):
    """The prompt for this model cannot be resolved from the registry."""


@dataclass(frozen=True, slots=True)
class PromptRef:
    prompt_id: str
    prompt_sha256: str
    prompt_kind: str
    text_path: Path | None
    pod_prompt_file: str

    def to_dict(self) -> dict[str, object]:
        return {
            "prompt_id": self.prompt_id,
            "prompt_sha256": self.prompt_sha256,
            "prompt_kind": self.prompt_kind,
            "prompt_text_file": None if self.text_path is None else self.text_path.name,
            "pod_prompt_file": self.pod_prompt_file,
        }


def prompt_registry_dir(root: Path) -> Path:
    return root / "prompt_registry"


def resolve_prompt(
    root: Path,
    *,
    prompt_id: str,
    prompt_kind: str | None = None,
    verify_text: bool = True,
) -> PromptRef:
    """Look ``prompt_id`` up in ``prompt_registry/sha256.json`` (D17).

    ``verify_text`` re-hashes ``prompt_registry/<prompt_id>.txt`` and refuses a
    mismatch. It is on by default because the two halves of the registry can
    drift, and a pod sent a ``prompt_sha256`` the file no longer produces
    fails on the pod after the GPU has already been paid for.
    """

    if not prompt_id:
        raise PromptError("runtime.json carries no prompt_id; D16 makes it the owner of one")
    if prompt_kind is not None and prompt_kind not in PROMPT_KINDS:
        raise PromptError(
            f"prompt_kind {prompt_kind!r} is not one of {list(PROMPT_KINDS)} (D34)"
        )
    directory = prompt_registry_dir(root)
    index_path = directory / "sha256.json"
    if not index_path.is_file():
        raise PromptError(
            f"{index_path} is absent; lane R owns prompt_registry/sha256.json (D17)"
        )
    document = read_json(index_path)
    if not isinstance(document, Mapping):
        raise PromptError("prompt_registry/sha256.json is not a JSON object")
    if prompt_id not in document:
        known = ", ".join(sorted(str(key) for key in document)[:8])
        raise PromptError(
            f"prompt_registry/sha256.json has no entry for prompt_id {prompt_id!r}. "
            f"D17 keys this file by the runtime.json prompt_id; present keys include: {known}"
        )
    recorded = document[prompt_id]
    if recorded is None:
        raise PromptError(
            f"prompt_registry/sha256.json maps {prompt_id!r} to null. A null hash is a gap, "
            "not a prompt; lane R fills it (an empty prompt is the hash of the empty string, "
            f"{EMPTY_PROMPT_SHA256})"
        )
    if not isinstance(recorded, str) or not _is_sha256_ref(recorded):
        raise PromptError(
            f"prompt_registry/sha256.json maps {prompt_id!r} to {recorded!r}, which is not "
            "'sha256:<64 lowercase hex>'"
        )

    text_path = directory / f"{prompt_id}.txt"
    if verify_text:
        if not text_path.is_file():
            raise PromptError(
                f"prompt_registry/{prompt_id}.txt is absent; the worker resolves "
                f"{POD_PROMPT_DIR}/{prompt_id}.txt and would fail closed on the pod (D17)"
            )
        actual = sha256_bytes(text_path.read_bytes())
        if actual != recorded:
            raise PromptError(
                f"prompt_registry/{prompt_id}.txt hashes to {actual}, but sha256.json records "
                f"{recorded}; the two halves of the prompt registry disagree"
            )
    return PromptRef(
        prompt_id=prompt_id,
        prompt_sha256=recorded,
        prompt_kind=prompt_kind or "unknown",
        text_path=text_path if text_path.is_file() else None,
        pod_prompt_file=f"{POD_PROMPT_DIR}/{prompt_id}.txt",
    )


def _is_sha256_ref(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    hexpart = value[len("sha256:") :]
    return len(hexpart) == 64 and all(character in "0123456789abcdef" for character in hexpart)
