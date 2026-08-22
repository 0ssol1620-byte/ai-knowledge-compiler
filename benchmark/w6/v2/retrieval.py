"""Deterministic offline lexical retrieval used by the RAG arm and world retrieval.

Hashed bag-of-words vectors (dim 4096, L2-normalised) with cosine similarity —
no network, no model dependency, byte-stable across runs so the pilot stays
reproducible.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

DIMENSION = 4096

_WORD_PATTERN = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the
    this to was were what which who will with""".split()
)


def content_tokens(text: str) -> list[str]:
    tokens = _WORD_PATTERN.findall(text.casefold())
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 1]


def _slot(token: str) -> int:
    digest = hashlib.sha1(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % DIMENSION


def hashed_vector(text: str) -> list[float]:
    vector = [0.0] * DIMENSION
    counts = Counter(content_tokens(text))
    for token, count in counts.items():
        vector[_slot(token)] += float(count)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def chunk_text(text: str, *, chunk_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_chars, length)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = end - overlap_chars if end - overlap_chars > start else end
    return chunks


def snippet_around(text: str, needle: str, *, radius: int = 400) -> str:
    """Return a window of the document around the first occurrence of needle."""
    if not text:
        return ""
    probe = needle.strip()[:60]
    position = text.casefold().find(probe.casefold())
    if position < 0:
        words = content_tokens(needle)
        for token in words[:4]:
            position = text.casefold().find(token)
            if position >= 0:
                break
    if position < 0:
        return text[: radius * 2].replace("\n", " ")
    start = max(0, position - radius)
    end = min(len(text), position + len(probe) + radius)
    window = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{window}{suffix}"


class LexicalRetriever:
    """In-memory index of (id, text) items scored by hashed-vector cosine."""

    def __init__(self, items: list[tuple[str, str]]) -> None:
        self._ids = [item_id for item_id, _ in items]
        self._vectors = [hashed_vector(text) for _, text in items]

    def search(self, query: str, *, top_k: int = 5) -> list[tuple[str, float]]:
        if not self._ids:
            return []
        query_vector = hashed_vector(query)
        scores = [cosine(query_vector, vector) for vector in self._vectors]
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [(self._ids[i], scores[i]) for i in order]


class RagIndex:
    """Chunk-level index over all usable documents."""

    def __init__(
        self,
        documents: dict[str, dict],
        *,
        chunk_chars: int = 900,
        overlap_chars: int = 120,
    ) -> None:
        items: list[tuple[str, str]] = []
        self.chunk_sources: dict[str, tuple[str, int]] = {}
        for source_id in sorted(documents):
            text = documents[source_id]["text"]
            for position, chunk in enumerate(chunk_text(text, chunk_chars=chunk_chars, overlap_chars=overlap_chars)):
                chunk_id = f"{source_id}#c{position:03d}"
                items.append((chunk_id, chunk))
                self.chunk_sources[chunk_id] = (source_id, position)
        self._retriever = LexicalRetriever(items)
        self.chunk_count = len(items)

    def context_for(self, documents: dict[str, dict], question: str, *, top_k: int = 5) -> tuple[str, list[str]]:
        hits = self._retriever.search(question, top_k=top_k)
        lines: list[str] = []
        source_ids: list[str] = []
        for chunk_id, _score in hits:
            source_id, _position = self.chunk_sources.get(chunk_id, ("", 0))
            source_ids.append(source_id)
            text = documents.get(source_id, {}).get("text", "")
            position = int(chunk_id.rsplit("c", 1)[-1])
            window_start = max(0, position * (900 - 120))  # informational only
            chunk = text[window_start : window_start + 900] or "(chunk unavailable)"
            lines.append(f"[{source_id} chunk {position}] {chunk}")
        header = (
            "RETRIEVED CHUNKS:\n" if lines else "RETRIEVED CHUNKS: none matched this question.\n"
        )
        return header + "\n\n".join(lines), source_ids
