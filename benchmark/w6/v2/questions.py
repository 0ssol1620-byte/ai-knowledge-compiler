"""Question generation (phase 2) — frozen before any arm runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .llm import OpenRouterClient

QUESTION_PROMPT = """You are writing ONE benchmark question from a source document.

Requirements:
- answerable from THIS document alone, and not from general knowledge without it
- targets one specific verifiable fact: an exact number, date, measurement, or proper name
- "gold_value_exact" is the minimal exact string (number/date/name) that proves the answer
- "key_facts" lists 1-3 facts a correct answer must state; keep them short and checkable

Return ONLY JSON:
{{"question": "...", "gold_answer": "...", "gold_value_exact": "...", "key_facts": ["...", ...]}}

DOCUMENT TITLE: {title} (source id {source_id})
DOCUMENT TEXT (may be truncated):
{body}
"""


def generate_question(
    client: OpenRouterClient,
    *,
    source_id: str,
    title: str,
    text: str,
    body_budget_chars: int = 6000,
) -> dict[str, Any]:
    prompt = QUESTION_PROMPT.format(source_id=source_id, title=title, body=text[:body_budget_chars])
    parsed = client.complete_json(
        [{"role": "user", "content": prompt}],
        max_tokens=350,
        phase="question_generation",
    )
    question = str(parsed.get("question", "")).strip()
    gold_value = str(parsed.get("gold_value_exact", "")).strip()
    if not question or not gold_value:
        raise ValueError("question generation returned incomplete schema")
    return {
        "question_id": f"q-{source_id}",
        "source_id": source_id,
        "title": title,
        "question": question,
        "gold_answer": str(parsed.get("gold_answer", "")).strip(),
        "gold_value_exact": gold_value,
        "key_facts": [
            str(fact).strip() for fact in parsed.get("key_facts", []) if str(fact).strip()
        ],
    }


def freeze_questions(questions: list[dict[str, Any]], path) -> str:
    """Write the frozen question set and return its sha256."""
    payload = {"question_count": len(questions), "questions": questions}
    blob = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(blob, encoding="utf-8")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
