"""Answering arms (phase 3): raw / rag / tavonel — identical frozen model."""

from __future__ import annotations

import time
from typing import Any

from .llm import OpenRouterClient
from .retrieval import RagIndex

ANSWER_PROMPT = """Answer the question using ONLY the context below.

Rules:
- at most 80 words
- state the exact fact asked for; do not hedge with unrelated material
- if the context does not contain the answer, reply exactly: NOT IN CONTEXT
- finish with a final line "Sources: <comma-separated source ids>"

CONTEXT:
{context}

QUESTION: {question}
"""


def answer_once(
    client: OpenRouterClient,
    *,
    question: str,
    context: str,
    phase: str,
) -> tuple[str, float, bool, str]:
    """Return (answer, latency_seconds, api_failure, error_class)."""
    started = time.monotonic()
    try:
        text = client.complete(
            [{"role": "user", "content": ANSWER_PROMPT.format(context=context, question=question)}],
            max_tokens=300,
            phase=phase,
        )
    except Exception as exc:
        return "", time.monotonic() - started, True, type(exc).__name__
    return text.strip(), time.monotonic() - started, False, ""


def run_raw_arm(
    client: OpenRouterClient,
    documents: dict[str, dict],
    questions: list[dict],
    *,
    budget_chars: int = 6000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in questions:
        document = documents.get(item["source_id"], {})
        context = (
            f"[{item['source_id']} | {document.get('title', item['title'])}]\n"
            f"{document.get('text', '')[:budget_chars]}"
        )
        answer, latency, failed, error_class = answer_once(
            client, question=item["question"], context=context, phase="answering_raw"
        )
        rows.append(
            {
                "question_id": item["question_id"],
                "source_id": item["source_id"],
                "answer": answer,
                "latency_seconds": round(latency, 2),
                "api_failure": failed,
                "error_class": error_class,
            }
        )
    return rows


def run_rag_arm(
    client: OpenRouterClient,
    index: RagIndex,
    documents: dict[str, dict],
    questions: list[dict],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in questions:
        context, _sources = index.context_for(documents, item["question"], top_k=top_k)
        answer, latency, failed, error_class = answer_once(
            client, question=item["question"], context=context, phase="answering_rag"
        )
        rows.append(
            {
                "question_id": item["question_id"],
                "source_id": item["source_id"],
                "answer": answer,
                "latency_seconds": round(latency, 2),
                "api_failure": failed,
                "error_class": error_class,
            }
        )
    return rows


def run_tavonel_arm(
    client: OpenRouterClient, world_retriever, questions: list[dict], *, top_k: int = 8
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in questions:
        context = world_retriever.context_for(item["question"], top_k=top_k)
        answer, latency, failed, error_class = answer_once(
            client, question=item["question"], context=context, phase="answering_tavonel"
        )
        rows.append(
            {
                "question_id": item["question_id"],
                "source_id": item["source_id"],
                "answer": answer,
                "latency_seconds": round(latency, 2),
                "api_failure": failed,
                "error_class": error_class,
            }
        )
    return rows
