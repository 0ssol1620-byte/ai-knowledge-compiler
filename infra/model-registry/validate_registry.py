"""Fail-closed validation for model releases and route recipes."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
HEX_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
FLOATING = {"", "main", "master", "latest", "head"}
LICENSE_FIELDS = {
    "weight_license",
    "code_license",
    "dataset_license",
    "runtime_license",
    "license_snapshot_sha256",
}


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def validate(strict: bool = False) -> list[str]:
    models = load_yaml(ROOT / "models.yaml")
    recipe_data = load_yaml(ROOT / "recipes.yaml")
    errors: list[str] = []
    releases = models.get("releases") or []
    by_key: dict[str, dict[str, Any]] = {}

    for index, release in enumerate(releases):
        key = str(release.get("provider_key") or "")
        prefix = f"releases[{index}]({key or 'missing'})"
        if not key or key in by_key:
            errors.append(f"{prefix}: provider_key missing or duplicate")
            continue
        by_key[key] = release
        revision = release.get("upstream_revision")
        status = (release.get("internal_validation") or {}).get("status")
        traffic = (release.get("rollout") or {}).get("traffic_percent", 0)
        requires_pin = strict or traffic > 0 or status in {
            "champion",
            "canary",
            "fallback",
            "shadow",
        }
        if isinstance(revision, str) and revision.lower() in FLOATING:
            errors.append(f"{prefix}: floating revision is forbidden")
        if requires_pin and not (isinstance(revision, str) and HEX_REVISION.fullmatch(revision)):
            errors.append(f"{prefix}: exact 40-64 hex revision required")
        licenses = release.get("licenses") or {}
        missing = LICENSE_FIELDS.difference(licenses)
        if missing:
            errors.append(f"{prefix}: missing license fields {sorted(missing)}")
        if traffic < 0 or traffic > 100:
            errors.append(f"{prefix}: rollout traffic must be 0..100")

    recipes = recipe_data.get("recipes") or {}
    if "parse_fast_v1" not in recipes:
        errors.append("recipes: parse_fast_v1 is required")
    if (recipe_data.get("defaults") or {}).get("allow_external") is not False:
        errors.append("defaults.allow_external must be false")
    for name, recipe in recipes.items():
        if recipe.get("allow_external") is not False:
            errors.append(f"recipes.{name}: allow_external must be explicitly false")
        for provider_field in (
            "parser",
            "model",
            "embedding",
            "reranker",
            "challenger",
            "long_context_shadow",
            "optional_external_fallback",
        ):
            provider = recipe.get(provider_field)
            if provider not in {None, "native"} and provider not in by_key:
                errors.append(
                    f"recipes.{name}: unknown {provider_field} provider {provider}"
                )
        fallback = recipe.get("fallback")
        if fallback not in {None, "review"} and fallback not in recipes:
            errors.append(f"recipes.{name}: unknown fallback {fallback}")

    for start in recipes:
        seen: set[str] = set()
        current: str | None = start
        while current in recipes:
            if current in seen:
                errors.append(f"recipes.{start}: fallback cycle through {current}")
                break
            seen.add(current)
            fallback = recipes[current].get("fallback")
            current = fallback if isinstance(fallback, str) else None
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="require every real model to be pinned",
    )
    args = parser.parse_args()
    errors = validate(strict=args.strict)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("model registry validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
