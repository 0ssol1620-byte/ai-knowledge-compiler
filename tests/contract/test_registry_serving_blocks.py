"""Every ``runtime.serving`` block in the model registry names what the runner attests.

A recipe (a block without ``verdict``) launches ``image`` by digest under the served name
``<upstream_id>@<upstream_revision>``, which the chat runners require the server to echo.
A recipe on the AKC external protocol attests ``upstream_revision`` instead
(``attested_revision``). An image built from a Dockerfile in this repository has no digest
until it is built: such a block says ``built: false``, ``image: null`` and ``image_build``
(the Dockerfile), and needs the digest as soon as ``built`` is true. A verdict block records
why there is no recipe; any image it names is still a digest. ``serving_variants`` (labelled
alternatives to the row's primary block) follow the same rules. Every row with a serving
block carries zero traffic.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _ROOT / "infra/model-registry/models.yaml"
_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")


def _rows() -> list[dict[str, Any]]:
    releases = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))["releases"]
    return [r for r in releases if isinstance((r.get("runtime") or {}).get("serving"), dict)]


def _blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    runtime = row["runtime"]
    return [runtime["serving"], *(runtime.get("serving_variants") or [])]


def _block_problems(row: dict[str, Any], serving: dict[str, Any]) -> list[str]:
    out = []
    unbuilt = serving.get("built") is False
    if "verdict" not in serving:
        if unbuilt:
            if serving.get("image") is not None:
                out.append("image named while built is false")
            build = serving.get("image_build")
            if not isinstance(build, str) or not (_ROOT / build).is_file():
                out.append("image_build is not a Dockerfile in this repository")
        elif not serving.get("image"):
            out.append("recipe without image")
        if serving.get("protocol") == "akc-external-runner":
            if serving.get("attested_revision") != row.get("upstream_revision"):
                out.append("attested_revision is not the upstream revision")
        elif not serving.get("served_model_name"):
            out.append("recipe without served_model_name")
    expected = f"{row.get('upstream_id')}@{row.get('upstream_revision')}"
    if "served_model_name" in serving and serving["served_model_name"] != expected:
        out.append(f"served_model_name is not {expected}")
    for field in ("image", "candidate_image"):
        if field not in serving or (field == "image" and unbuilt and serving[field] is None):
            continue
        if not _DIGEST.search(str(serving[field])):
            out.append(f"{field} carries no @sha256 digest")
    return out


def _problems(row: dict[str, Any]) -> list[str]:
    out = []
    if (row.get("rollout") or {}).get("traffic_percent") != 0:
        out.append("traffic_percent is not 0")
    for serving in _blocks(row):
        out += _block_problems(row, serving)
    return out


def test_every_serving_block_matches_its_row() -> None:
    rows = _rows()
    assert any("verdict" not in r["runtime"]["serving"] for r in rows), "no recipe to check"
    assert any(r["runtime"]["serving"].get("built") is False for r in rows), "no unbuilt image"
    assert any(r["runtime"].get("serving_variants") for r in rows), "no variant to check"
    assert {r["provider_key"]: _problems(r) for r in rows if _problems(r)} == {}


def test_a_drifted_serving_block_is_caught() -> None:
    recipe = next(r for r in _rows() if "served_model_name" in r["runtime"]["serving"])
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


def test_an_image_built_here_needs_its_digest_once_built() -> None:
    """An unbuilt block is allowed exactly as ``image: null`` + ``image_build`` + ``built:
    false``; the public-image rule is unchanged for every other block."""
    row = next(r for r in _rows() if r["runtime"]["serving"].get("built") is False)
    assert _problems(row) == []
    cases: dict[str, tuple[str, Any]] = {
        "recipe without image": ("built", True),
        "image named while built is false": ("image", "registry.example/akc@sha256:" + "0" * 64),
        "image_build is not a Dockerfile": ("image_build", "infra/no/such/Dockerfile"),
        "attested_revision is not the upstream revision": ("attested_revision", "1" * 40),
    }
    for message, (field, value) in cases.items():
        bad = copy.deepcopy(row)
        bad["runtime"]["serving"][field] = value
        assert any(message in p for p in _problems(bad)), message
    built = copy.deepcopy(row)
    built["runtime"]["serving"].update(built=True, image="registry.example/akc:latest")
    assert "image carries no @sha256 digest" in _problems(built)
    built["runtime"]["serving"]["image"] = "registry.example/akc@sha256:" + "0" * 64
    assert _problems(built) == []


def test_a_drifted_variant_is_caught() -> None:
    row = next(r for r in _rows() if r["runtime"].get("serving_variants"))
    bad = copy.deepcopy(row)
    bad["runtime"]["serving_variants"][0]["image"] = "vllm/vllm-openai:latest"
    assert "image carries no @sha256 digest" in _problems(bad)
