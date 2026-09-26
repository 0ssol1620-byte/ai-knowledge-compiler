"""TAVONEL-arm world compilation (pilot-grade stand-in — see DEVIATION-02).

Each usable document is compiled once into typed elements with provenance ids:

    {element_id, source_id, type: definition|entity|metric|date_event|relation,
     subject, text, value?}

At answer time the question is scored against compiled elements lexically; the
top elements plus their source snippets form the answering context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .llm import OpenRouterClient
from .retrieval import LexicalRetriever, snippet_around

VALID_TYPES = {"definition", "entity", "metric", "date_event", "relation"}

COMPILE_PROMPT = """You are compiling one source document into a structured knowledge world.
Extract 6 to 12 of the most load-bearing facts as typed JSON elements.

Rules:
- type is exactly one of: definition, entity, metric, date_event, relation
- "subject" names what the element is about
- "text" states the fact precisely, self-contained, with numbers/dates kept verbatim
- include "value" only when the fact hinges on one exact number/date/name
- provenance stays implicit: every element belongs to this single document

Return ONLY a JSON array. Element schema:
{{"type": "...", "subject": "...", "text": "...", "value": "..." }}

DOCUMENT TITLE: {title}
DOCUMENT TEXT (may be truncated):
{body}
"""


@dataclass
class WorldElement:
    element_id: str
    source_id: str
    type: str
    subject: str
    text: str
    value: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "element_id": self.element_id,
            "source_id": self.source_id,
            "type": self.type,
            "subject": self.subject,
            "text": self.text,
        }
        if self.value:
            payload["value"] = self.value
        return payload


@dataclass
class CompiledWorld:
    elements: list[WorldElement] = field(default_factory=list)
    compile_failures: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_count": len(self.elements),
            "compile_failures": self.compile_failures,
            "elements": [element.to_dict() for element in self.elements],
        }


def compile_document(
    client: OpenRouterClient,
    *,
    source_id: str,
    title: str,
    text: str,
    body_budget_chars: int = 6000,
) -> list[WorldElement]:
    body = text[:body_budget_chars]
    prompt = COMPILE_PROMPT.format(title=title, body=body)
    parsed = client.complete_json(
        [{"role": "user", "content": prompt}],
        max_tokens=900,
        phase="compilation",
    )
    raw_elements = parsed if isinstance(parsed, list) else parsed.get("elements", [])
    elements: list[WorldElement] = []
    for position, item in enumerate(raw_elements):
        if not isinstance(item, dict):
            continue
        element_type = str(item.get("type", "")).strip()
        element_text = str(item.get("text", "")).strip()
        if element_type not in VALID_TYPES or not element_text:
            continue
        elements.append(
            WorldElement(
                element_id=f"{source_id}#e{position:02d}",
                source_id=source_id,
                type=element_type,
                subject=str(item.get("subject", "")).strip()[:160],
                text=element_text[:500],
                value=str(item.get("value", "")).strip(),
            )
        )
    return elements


def compile_world(
    client: OpenRouterClient, documents: dict[str, dict], *, body_budget_chars: int = 6000
) -> CompiledWorld:
    """Compile every document; per-document failures are ledgered, never silent."""
    world = CompiledWorld()
    for source_id in sorted(documents):
        document = documents[source_id]
        try:
            world.elements.extend(
                compile_document(
                    client,
                    source_id=source_id,
                    title=document.get("title", ""),
                    text=document["text"],
                    body_budget_chars=body_budget_chars,
                )
            )
        except Exception as exc:
            world.compile_failures.append(
                {"source_id": source_id, "error_class": type(exc).__name__}
            )
    return world


class WorldRetriever:
    """Score compiled elements against a question; return elements plus snippets."""

    def __init__(self, world: CompiledWorld, documents: dict[str, dict]) -> None:
        self.world = world
        self.documents = documents
        self._retriever = LexicalRetriever(
            [
                (element.element_id, f"{element.subject} {element.text}")
                for element in world.elements
            ]
        )

    def context_for(self, question: str, *, top_k: int = 8, radius: int = 400) -> str:
        hits = self._retriever.search(question, top_k=top_k)
        lines: list[str] = []
        seen_snippets: set[str] = set()
        for element_id, _score in hits:
            element = next(e for e in self.world.elements if e.element_id == element_id)
            document = self.documents.get(element.source_id, {})
            snippet = snippet_around(document.get("text", ""), element.text[:80], radius=radius)
            dedupe_key = (element.source_id, snippet[:60])
            if dedupe_key in seen_snippets:
                continue
            seen_snippets.add(dedupe_key)
            value_note = f" [value: {element.value}]" if element.value else ""
            lines.append(
                f"[{element.source_id} | {element.type}] "
                f"{element.subject}: {element.text}{value_note}\n"
                f"    excerpt: {snippet}"
            )
        header = (
            "COMPILED WORLD ELEMENTS (each line carries its source id):\n"
            if lines
            else "COMPILED WORLD ELEMENTS: none matched this question.\n"
        )
        return header + "\n".join(lines)


def save_world(world: CompiledWorld, path) -> None:
    path.write_text(json.dumps(world.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
