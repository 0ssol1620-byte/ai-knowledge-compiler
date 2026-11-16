"""Drop-in horizontal blueprints (creative works, team workspace), composed beside the built-ins."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

import yaml

from .blueprints import (
    BlueprintModule,
    BlueprintRegistry,
    discover_blueprint_modules,
    registry_from_modules,
)


@lru_cache(maxsize=1)
def horizontal_blueprint_modules() -> tuple[BlueprintModule, ...]:
    try:
        return discover_blueprint_modules(files("akc_domain_packs").joinpath("horizontal_modules"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise RuntimeError("invalid horizontal blueprint module") from exc


@lru_cache(maxsize=1)
def horizontal_blueprints() -> BlueprintRegistry:
    return registry_from_modules(horizontal_blueprint_modules())


__all__ = ["horizontal_blueprint_modules", "horizontal_blueprints"]
