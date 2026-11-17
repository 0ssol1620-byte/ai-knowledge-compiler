"""Every ``runtime.serving`` block in the model registry names what the runner attests.

A recipe (a block without ``verdict``) launches ``image`` by digest under the served name
``<upstream_id>@<upstream_revision>``, which the chat runners require the server to echo.
A verdict block records why there is no recipe; any image it names is still a digest.
Every row with a serving block carries zero traffic.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

_REGISTRY = Path(__file__).resolve().parents[2] / "infra/model-registry/models.yaml"
_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")


def _rows() -> list[dict[str, Any]]:
    releases = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))["releases"]
    return [r for r in releases if isinstance((r.get("runtime") or {}).get("serving"), dict)]


def _problems(row: dict[str, Any]) -> list[str]:
    serving = row["runtime"]["serving"]
    out = []
    if (row.get("rollout") or {}).get("traffic_percent") != 0:
        out.append("traffic_percent is not 0")
    if "verdict" not in serving:
        for field in ("image", "served_model_name"):
            if not serving.get(field):
                out.append(f"recipe without {field}")
    expected = f"{row.get('upstream_id')}@{row.get('upstream_revision')}"
    if "served_model_name" in serving and serving["served_model_name"] != expected:
        out.append(f"served_model_name is not {expected}")
    for field in ("image", "candidate_image"):
        if field in serving and not _DIGEST.search(str(serving[field])):
            out.append(f"{field} carries no @sha256 digest")
    return out


def test_every_serving_block_matches_its_row() -> None:
    rows = _rows()
    assert any("verdict" not in r["runtime"]["serving"] for r in rows), "no recipe to check"
    assert {r["provider_key"]: _problems(r) for r in rows if _problems(r)} == {}


def test_a_drifted_serving_block_is_caught() -> None:
    recipe = next(r for r in _rows() if "verdict" not in r["runtime"]["serving"])
    cases = {
        "served_model_name": ("served_model_name", recipe["upstream_id"]),
        "@sha256 digest": ("image", "vllm/vllm-openai:v0.33.0"),
        "recipe without image": ("image", None),
    }
    for message, (field, value) in cases.items():
        bad = copy.deepcopy(recipe)
        if value is None:
            del bad["runtime"]["serving"][field]
        else:
            bad["runtime"]["serving"][field] = value
        assert any(message in p for p in _problems(bad)), message
    bad = copy.deepcopy(recipe)
    bad["rollout"]["traffic_percent"] = 5
    assert _problems(bad) == ["traffic_percent is not 0"]
