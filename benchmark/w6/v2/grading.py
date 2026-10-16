"""Grading (phase 4): deterministic critical match plus one judge call per question.

The judge scores all three arm answers in a single call so every arm is graded
under identical conditions.
"""

from __future__ import annotations

import re
from typing import Any

from .llm import OpenRouterClient

JUDGE_PROMPT = """You are a strict grader for a retrieval benchmark. Grade each arm's \
answer INDEPENDENTLY.

Gold answer: {gold_answer}
Key facts that a correct answer must state: {key_facts}

Scoring per arm:
- 1 iff the answer states the key fact(s) correctly and contradicts none of them
- 0 otherwise (missing fact, wrong value, hedging without the fact, or refusal)

Return ONLY JSON:
{{"raw": {{"score": 0, "reason": "..."}}, "rag": {{"score": 0, "reason": "..."}}, \
"tavonel": {{"score": 0, "reason": "..."}}}}

QUESTION: {question}
RAW ANSWER: {raw}
RAG ANSWER: {rag}
TAVONEL ANSWER: {tavonel}
"""

_ARMS = ("raw", "rag", "tavonel")


def normalise(text: str) -> str:
    lowered = text.casefold()
    lowered = re.sub(r"(?<=\d),(?=\d)", "", lowered)  # thousand separators inside numbers
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    lowered = re.sub(r"\b(a|an|the)\b", " ", lowered)
    return " ".join(lowered.split())


def critical_match(answer: str, gold_value_exact: str) -> bool:
    if not gold_value_exact:
        return False
    return normalise(gold_value_exact) in normalise(answer)


def judge_all_arms(
    client: OpenRouterClient,
    *,
    question: str,
    gold_answer: str,
    key_facts: list[str],
    answers: dict[str, str],
) -> dict[str, Any]:
    prompt = JUDGE_PROMPT.format(
        question=question,
        gold_answer=gold_answer,
        key_facts="; ".join(key_facts) or "(gold answer above)",
        raw=answers.get("raw", "") or "(execution failure)",
        rag=answers.get("rag", "") or "(execution failure)",
        tavonel=answers.get("tavonel", "") or "(execution failure)",
    )
    parsed = client.complete_json(
        [{"role": "user", "content": prompt}], max_tokens=320, phase="judging"
    )
    verdicts: dict[str, Any] = {}
    for arm in _ARMS:
        entry = parsed.get(arm, {}) if isinstance(parsed, dict) else {}
        try:
            score = int(entry.get("score", 0))
        except (TypeError, ValueError):
            score = 0
        verdicts[arm] = {
            "score": 1 if score == 1 else 0,
            "reason": str(entry.get("reason", ""))[:300],
        }
    return verdicts


def provenance_hit(answer: str, true_source_id: str) -> bool | None:
    """Informational: did the answer cite the true source id? None when no Sources line."""
    matches = re.findall(r"Sources:\s*(.+)", answer, flags=re.IGNORECASE)
    if not matches:
        return None
    cited = {token.strip().casefold() for token in matches[-1].split(",")}
    return true_source_id.casefold() in cited


def grade_run(
    client: OpenRouterClient,
    *,
    question_items: list[dict[str, Any]],
    runs: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (per-question grade rows, aggregate metrics)."""
    by_question: dict[str, dict[str, dict[str, Any]]] = {}
    for arm, rows in runs.items():
        for row in rows:
            by_question.setdefault(row["question_id"], {})[arm] = row

    grades: list[dict[str, Any]] = []
    aggregates: dict[str, dict[str, float]] = {
        arm: {
            "correct": 0.0,
            "critical": 0.0,
            "judged": 0.0,
            "provenance_hits": 0.0,
            "provenance_seen": 0.0,
            "failures": 0.0,
            "latency_sum": 0.0,
            "n_executed": 0.0,
        }
        for arm in _ARMS
    }

    for item in question_items:
        qid = item["question_id"]
        arm_rows = by_question.get(qid, {})
        answers = {arm: (arm_rows.get(arm, {}).get("answer") or "") for arm in _ARMS}
        verdicts = judge_all_arms(
            client,
            question=item["question"],
            gold_answer=item["gold_answer"],
            key_facts=item.get("key_facts", []),
            answers=answers,
        )
        row: dict[str, Any] = {"question_id": qid, "source_id": item["source_id"], "arms": {}}
        for arm in _ARMS:
            arm_row = arm_rows.get(arm, {})
            failed = bool(arm_row.get("api_failure")) or not answers[arm]
            crit = critical_match(answers[arm], item["gold_value_exact"])
            judge_score = verdicts[arm]["score"]
            correct = (crit or judge_score == 1) and not failed
            prov = provenance_hit(answers[arm], item["source_id"])
            bucket = aggregates[arm]
            bucket["failures"] += 1.0 if failed else 0.0
            if not failed:
                bucket["n_executed"] += 1.0
                bucket["correct"] += 1.0 if correct else 0.0
                bucket["critical"] += 1.0 if crit else 0.0
                bucket["judged"] += float(judge_score)
                bucket["latency_sum"] += float(arm_row.get("latency_seconds", 0.0))
                if prov is not None:
                    bucket["provenance_seen"] += 1.0
                    bucket["provenance_hits"] += 1.0 if prov else 0.0
            row["arms"][arm] = {
                "answer": answers[arm][:600],
                "api_failure": failed,
                "error_class": arm_row.get("error_class", ""),
                "critical_match": crit,
                "judge_score": judge_score,
                "judge_reason": verdicts[arm]["reason"],
                "correct": correct,
                "provenance_hit": prov,
                "latency_seconds": arm_row.get("latency_seconds", 0.0),
            }
        grades.append(row)

    metrics: dict[str, Any] = {}
    total = max(1, len(question_items))
    for arm, bucket in aggregates.items():
        executed = bucket["n_executed"]
        metrics[arm] = {
            "accuracy": round(bucket["correct"] / total, 4),
            "accuracy_over_executed": round(bucket["correct"] / executed, 4) if executed else None,
            "critical_only_rate": round(bucket["critical"] / total, 4),
            "judge_only_rate": round(bucket["judged"] / total, 4),
            "provenance_hit_rate": (
                round(bucket["provenance_hits"] / bucket["provenance_seen"], 4)
                if bucket["provenance_seen"]
                else None
            ),
            "api_failure_rate": round(bucket["failures"] / total, 4),
            "mean_latency_seconds": round(bucket["latency_sum"] / executed, 2)
            if executed
            else None,
            "executed": int(executed),
            "wilson_ci_accuracy": wilson_interval(bucket["correct"], total),
        }
    return grades, metrics


def wilson_interval(successes: float, total: int, z: float = 1.96) -> list[float]:
    if total == 0:
        return [0.0, 1.0]
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denominator
    return [round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4)]
