"""Fail-closed validation for model releases and route recipes."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
HEX_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
FLOATING = {"", "main", "master", "latest", "head"}
LICENSE_FIELDS = {
    "weight_license",
    "code_license",
    "dataset_license",
    "runtime_license",
    "license_snapshot_sha256",
}
PRODUCTION_VALIDATION_STATUSES = {"champion", "canary", "fallback", "shadow"}


def release_is_attested(release: dict[str, Any]) -> bool:
    revision = release.get("upstream_revision")
    licenses = release.get("licenses") or {}
    runtime = release.get("runtime") or {}
    status = (release.get("internal_validation") or {}).get("status")
    return bool(
        isinstance(revision, str)
        and HEX_REVISION.fullmatch(revision)
        and isinstance(licenses.get("license_snapshot_sha256"), str)
        and SHA256_DIGEST.fullmatch(licenses["license_snapshot_sha256"])
        and isinstance(runtime.get("version"), str)
        and runtime["version"]
        and isinstance(runtime.get("image_digest"), str)
        and SHA256_DIGEST.fullmatch(runtime["image_digest"])
        and status in PRODUCTION_VALIDATION_STATUSES
    )


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
        requires_pin = (
            strict
            or traffic > 0
            or status
            in {
                "champion",
                "canary",
                "fallback",
                "shadow",
            }
        )
        if isinstance(revision, str) and revision.lower() in FLOATING:
            errors.append(f"{prefix}: floating revision is forbidden")
        if requires_pin and not (isinstance(revision, str) and HEX_REVISION.fullmatch(revision)):
            errors.append(f"{prefix}: exact 40-64 hex revision required")
        licenses = release.get("licenses") or {}
        missing = LICENSE_FIELDS.difference(licenses)
        if missing:
            errors.append(f"{prefix}: missing license fields {sorted(missing)}")
        license_snapshot = licenses.get("license_snapshot_sha256")
        if license_snapshot is not None and not (
            isinstance(license_snapshot, str) and SHA256_DIGEST.fullmatch(license_snapshot)
        ):
            errors.append(f"{prefix}: license snapshot must be a sha256 digest or null")
        if traffic < 0 or traffic > 100:
            errors.append(f"{prefix}: rollout traffic must be 0..100")
        if traffic > 0 and not release_is_attested(release):
            errors.append(f"{prefix}: traffic requires full license/runtime/internal attestation")

        if key == "gemma4_12b_challenger":
            discovery = release.get("public_discovery") or {}
            if release.get("upstream_id") != "google/gemma-4-12B":
                errors.append(f"{prefix}: exact public Gemma repository is required")
            if release.get("upstream_revision") != "023679ed352de9bb66cc873c9009ce3482585c08":
                errors.append(f"{prefix}: reviewed public Gemma revision changed")
            if licenses.get("weight_license") != "Apache-2.0":
                errors.append(f"{prefix}: reviewed public Gemma license metadata changed")
            if discovery.get("checkpoint_downloaded") is not False:
                errors.append(f"{prefix}: unverified checkpoint must remain undownloaded")
            if discovery.get("license_snapshot_captured") is not False:
                errors.append(f"{prefix}: uncaptured license snapshot must remain explicit")
            if traffic != 0:
                errors.append(f"{prefix}: unverified Gemma challenger traffic must stay zero")

    recipes = recipe_data.get("recipes") or {}
    if "parse_fast_v1" not in recipes:
        errors.append("recipes: parse_fast_v1 is required")
    gemma_recipe = recipes.get("knowledge_gemma_challenger_v1") or {}
    if gemma_recipe.get("model") != "gemma4_12b_challenger":
        errors.append("recipes.knowledge_gemma_challenger_v1: exact model binding required")
    if gemma_recipe.get("enabled") is not False:
        errors.append("recipes.knowledge_gemma_challenger_v1: must remain disabled")
    if gemma_recipe.get("fallback") != "unresolved":
        errors.append("recipes.knowledge_gemma_challenger_v1: fallback must fail closed")
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
                errors.append(f"recipes.{name}: unknown {provider_field} provider {provider}")
            if (
                recipe.get("enabled") is True
                and provider not in {None, "native"}
                and provider in by_key
                and not release_is_attested(by_key[provider])
            ):
                errors.append(f"recipes.{name}: enabled {provider_field} lacks attestation")
        fallback = recipe.get("fallback")
        if fallback not in {None, "unresolved"} and fallback not in recipes:
            errors.append(f"recipes.{name}: unknown fallback {fallback}")

    for start in recipes:
        seen: set[str] = set()
        current: str | None = start
        while current is not None and current in recipes:
            if current in seen:
                errors.append(f"recipes.{start}: fallback cycle through {current}")
                break
            seen.add(current)
            fallback = recipes[current].get("fallback")
            current = fallback if isinstance(fallback, str) and fallback != "unresolved" else None
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
