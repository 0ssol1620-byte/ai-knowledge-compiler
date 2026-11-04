"""The four task adapters: case -> chat messages, raw output -> normalised, cases -> scores.

Normalisation is limited to what masterplan v5 section 9.5 allows: envelope
removal (the chat-completion wrapper), Unicode/line-ending normalisation and
JSON parsing. Nothing here repairs, completes or re-asks. An output that does
not parse or does not satisfy the frozen schema is ``INVALID_OUTPUT``.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from string import Template
from typing import Any, Final

from jsonschema import Draft202012Validator

from karena import NAMESPACE_ROOT
from karena import evaluators as ev
from karena.corpus import Case

__all__ = ["TASKS", "Normalised", "TaskAdapter", "load_task"]

TASKS: Final = ("doc_type", "schema_induction", "typed_extraction", "grounded_answer")
PROMPT_VERSION: Final = "v1"


@dataclass(frozen=True, slots=True)
class Normalised:
    status: str  # SUCCESS | INVALID_OUTPUT | TRUNCATED
    value: dict[str, Any] | None
    problem: str | None = None

    def canonical(self) -> str:
        return json.dumps(
            self.value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        )


@dataclass(frozen=True)
class TaskAdapter:
    name: str
    system_prompt: str
    user_template: Template
    output_schema: Mapping[str, Any]
    params: Mapping[str, Any]
    variables: Callable[[Case], dict[str, str]]
    score: Callable[[Sequence[tuple[Case, Normalised]]], dict[str, Any]]

    @property
    def prompt_paths(self) -> tuple[Path, Path]:
        return prompt_paths(self.name)

    def messages(self, case: Case) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_template.substitute(self.variables(case))},
        ]

    def normalise(self, content: str | None, finish_reason: str | None) -> Normalised:
        if finish_reason == "length":
            return Normalised("TRUNCATED", None, "finish_reason=length")
        if content is None:
            return Normalised("INVALID_OUTPUT", None, "empty message content")
        text = unicodedata.normalize("NFC", content.replace("\r\n", "\n")).strip()
        try:
            value = json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            return Normalised("INVALID_OUTPUT", None, f"not JSON: {exc.msg}")
        errors = sorted(
            Draft202012Validator(self.output_schema).iter_errors(json.loads(text)), key=str
        )
        if errors:
            return Normalised("INVALID_OUTPUT", None, f"schema: {errors[0].message[:200]}")
        if not isinstance(value, dict):
            return Normalised("INVALID_OUTPUT", None, "not a JSON object")
        return Normalised("SUCCESS", value)


def prompt_paths(task: str) -> tuple[Path, Path]:
    base = NAMESPACE_ROOT / "prompt_registry"
    return (
        base / f"{task}_{PROMPT_VERSION}.system.txt",
        base / f"{task}_{PROMPT_VERSION}.user.txt",
    )


def schema_path(task: str) -> Path:
    return NAMESPACE_ROOT / "schemas" / f"{task}.output.schema.json"


def task_config() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (NAMESPACE_ROOT / "config" / "tasks.json").read_text(encoding="utf-8")
    )
    return loaded


def _excerpts_block(excerpts: Sequence[Mapping[str, Any]]) -> str:
    return "\n\n".join(f'<excerpt id="{e["id"]}">\n{e["text"]}\n</excerpt>' for e in excerpts)


def _vars_doc_type(case: Case) -> dict[str, str]:
    return {"document": str(case.input["text"])}


def _vars_typed(case: Case) -> dict[str, str]:
    field = case.input["field"]
    return {
        "excerpt": str(case.input["excerpt"]),
        "field_name": str(field["name"]),
        "field_description": str(field["description"]),
        "entity": str(field["entity"]),
        "period": str(field["period"]),
        "unit": str(field["unit"]),
    }


def _vars_grounded(case: Case) -> dict[str, str]:
    return {
        "question": str(case.input["question"]),
        "excerpts": _excerpts_block(case.input["excerpts"]),
    }


def _vars_schema(case: Case) -> dict[str, str]:
    return {"excerpts": _excerpts_block(case.input["excerpts"])}


def _score_doc_type(rows: Sequence[tuple[Case, Normalised]]) -> dict[str, Any]:
    return ev.doc_type_scores(
        [
            (str(case.truth["label"]), None if out.value is None else str(out.value["label"]))
            for case, out in rows
        ]
    )


def _score_typed(rows: Sequence[tuple[Case, Normalised]]) -> dict[str, Any]:
    return ev.typed_extraction_scores(
        [
            {
                "gold_value": case.truth["value"],
                "displayed": case.truth["displayed"],
                "excerpt": case.input["excerpt"],
                "output": out.value,
            }
            for case, out in rows
        ]
    )


def _score_grounded(rows: Sequence[tuple[Case, Normalised]]) -> dict[str, Any]:
    return ev.grounded_answer_scores(
        [
            {
                "truth": case.truth,
                "excerpts": {e["id"]: e["text"] for e in case.input["excerpts"]},
                "output": out.value,
            }
            for case, out in rows
        ]
    )


def _score_schema(rows: Sequence[tuple[Case, Normalised]]) -> dict[str, Any]:
    return ev.schema_induction_scores(
        [
            {
                "excerpts": {e["id"]: e["text"] for e in case.input["excerpts"]},
                "output": out.value,
                "reference": case.truth.get("reference_schema"),
            }
            for case, out in rows
        ]
    )


_BINDINGS: Final = {
    "doc_type": (_vars_doc_type, _score_doc_type),
    "typed_extraction": (_vars_typed, _score_typed),
    "grounded_answer": (_vars_grounded, _score_grounded),
    "schema_induction": (_vars_schema, _score_schema),
}


def load_task(name: str) -> TaskAdapter:
    if name not in _BINDINGS:
        raise KeyError(f"unknown task {name!r}; tasks are {TASKS}")
    system_path, user_path = prompt_paths(name)
    variables, score = _BINDINGS[name]
    return TaskAdapter(
        name=name,
        system_prompt=system_path.read_text(encoding="utf-8"),
        user_template=Template(user_path.read_text(encoding="utf-8")),
        output_schema=json.loads(schema_path(name).read_text(encoding="utf-8")),
        params=task_config()["tasks"][name],
        variables=variables,
        score=score,
    )
