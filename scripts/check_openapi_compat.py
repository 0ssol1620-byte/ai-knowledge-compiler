"""Detect breaking changes against the frozen public OpenAPI v1 contract."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from akc_api.main import create_app
from akc_api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "packages" / "contracts" / "openapi" / "openapi-v1.json"
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "patch", "options", "head"})
Direction = Literal["request", "response"]


def current_openapi() -> dict[str, Any]:
    settings = Settings(
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        data_dir=Path(tempfile.gettempdir()) / "akc-openapi-contract",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        email_verification_provider="disabled",
        payment_provider="disabled",
        oidc_enabled=False,
        test_support_key=None,
    )
    return create_app(settings).openapi()


def _resolve(schema: Any, spec: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(schema, Mapping):
        return {}
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return schema
    value: Any = spec
    for component in reference[2:].split("/"):
        if not isinstance(value, Mapping) or component not in value:
            return schema
        value = value[component]
    return value if isinstance(value, Mapping) else schema


def _types(schema: Mapping[str, Any]) -> set[str]:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return {raw_type}
    if isinstance(raw_type, list):
        return {str(item) for item in raw_type}
    alternatives = schema.get("anyOf", schema.get("oneOf"))
    if isinstance(alternatives, list):
        result: set[str] = set()
        for alternative in alternatives:
            if isinstance(alternative, Mapping):
                result.update(_types(alternative))
        return result
    if "properties" in schema:
        return {"object"}
    return set()


def _number(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return float(value)
    return None


def _compare_schema(
    old_schema: Any,
    new_schema: Any,
    *,
    old_spec: Mapping[str, Any],
    new_spec: Mapping[str, Any],
    direction: Direction,
    location: str,
    changes: list[str],
    seen: set[tuple[int, int, Direction]],
) -> None:
    old = _resolve(old_schema, old_spec)
    new = _resolve(new_schema, new_spec)
    identity = (id(old), id(new), direction)
    if identity in seen:
        return
    seen.add(identity)

    old_types = _types(old)
    new_types = _types(new)
    if old_types and new_types:
        compatible = (
            old_types.issubset(new_types)
            if direction == "request"
            else new_types.issubset(old_types)
        )
        if not compatible:
            changes.append(
                f"{location}: {direction} types changed {sorted(old_types)} -> {sorted(new_types)}"
            )

    old_enum = old.get("enum")
    new_enum = new.get("enum")
    if isinstance(old_enum, list) and isinstance(new_enum, list):
        old_values = {json.dumps(value, sort_keys=True) for value in old_enum}
        new_values = {json.dumps(value, sort_keys=True) for value in new_enum}
        compatible = (
            old_values.issubset(new_values)
            if direction == "request"
            else new_values.issubset(old_values)
        )
        if not compatible:
            changes.append(f"{location}: {direction} enum compatibility narrowed")

    old_properties = old.get("properties")
    new_properties = new.get("properties")
    if isinstance(old_properties, Mapping):
        new_property_mapping = new_properties if isinstance(new_properties, Mapping) else {}
        old_required = {str(item) for item in old.get("required", []) if isinstance(item, str)}
        new_required = {str(item) for item in new.get("required", []) if isinstance(item, str)}
        if direction == "request":
            for name in sorted(new_required - old_required):
                changes.append(f"{location}.{name}: new required request field")
        else:
            for name in sorted(old_required - new_required):
                changes.append(f"{location}.{name}: required response field removed")
        for name, child in old_properties.items():
            if name not in new_property_mapping:
                changes.append(f"{location}.{name}: {direction} field removed")
                continue
            _compare_schema(
                child,
                new_property_mapping[name],
                old_spec=old_spec,
                new_spec=new_spec,
                direction=direction,
                location=f"{location}.{name}",
                changes=changes,
                seen=seen,
            )

    if "items" in old and "items" in new:
        _compare_schema(
            old["items"],
            new["items"],
            old_spec=old_spec,
            new_spec=new_spec,
            direction=direction,
            location=f"{location}[]",
            changes=changes,
            seen=seen,
        )

    for minimum_name in ("minimum", "minLength", "minItems"):
        old_value = _number(old.get(minimum_name))
        new_value = _number(new.get(minimum_name))
        if old_value is None or new_value is None:
            continue
        tightened = new_value > old_value if direction == "request" else new_value < old_value
        if tightened:
            changes.append(f"{location}: incompatible {minimum_name} change")
    for maximum_name in ("maximum", "maxLength", "maxItems"):
        old_value = _number(old.get(maximum_name))
        new_value = _number(new.get(maximum_name))
        if old_value is None or new_value is None:
            continue
        tightened = new_value < old_value if direction == "request" else new_value > old_value
        if tightened:
            changes.append(f"{location}: incompatible {maximum_name} change")
    if old.get("pattern") != new.get("pattern") and (
        old.get("pattern") is not None or new.get("pattern") is not None
    ):
        changes.append(f"{location}: pattern changed")


def _parameters(path_item: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
        if not isinstance(raw, Mapping):
            continue
        location = raw.get("in")
        name = raw.get("name")
        if isinstance(location, str) and isinstance(name, str):
            result[f"{location}:{name}"] = raw
    return result


def breaking_changes(
    old_spec: Mapping[str, Any],
    new_spec: Mapping[str, Any],
) -> list[str]:
    changes: list[str] = []
    old_paths = old_spec.get("paths")
    new_paths = new_spec.get("paths")
    if not isinstance(old_paths, Mapping) or not isinstance(new_paths, Mapping):
        return ["OpenAPI paths object is missing"]
    for path, old_path_value in sorted(old_paths.items()):
        if path not in new_paths:
            changes.append(f"{path}: path removed")
            continue
        old_path = old_path_value if isinstance(old_path_value, Mapping) else {}
        new_path_value = new_paths[path]
        new_path = new_path_value if isinstance(new_path_value, Mapping) else {}
        for method in sorted(HTTP_METHODS & set(old_path)):
            if method not in new_path:
                changes.append(f"{method.upper()} {path}: operation removed")
                continue
            old_operation = old_path[method]
            new_operation = new_path[method]
            if not isinstance(old_operation, Mapping) or not isinstance(new_operation, Mapping):
                changes.append(f"{method.upper()} {path}: invalid operation contract")
                continue
            location = f"{method.upper()} {path}"
            old_parameters = _parameters(old_path, old_operation)
            new_parameters = _parameters(new_path, new_operation)
            for key, old_parameter in old_parameters.items():
                if key not in new_parameters:
                    changes.append(f"{location} parameter {key}: removed")
                    continue
                new_parameter = new_parameters[key]
                _compare_schema(
                    old_parameter.get("schema", {}),
                    new_parameter.get("schema", {}),
                    old_spec=old_spec,
                    new_spec=new_spec,
                    direction="request",
                    location=f"{location} parameter {key}",
                    changes=changes,
                    seen=set(),
                )
            for key, new_parameter in new_parameters.items():
                if (
                    key not in old_parameters
                    and isinstance(new_parameter, Mapping)
                    and new_parameter.get("required") is True
                ):
                    changes.append(f"{location} parameter {key}: new required parameter")

            old_body = old_operation.get("requestBody")
            new_body = new_operation.get("requestBody")
            if isinstance(old_body, Mapping):
                if not isinstance(new_body, Mapping):
                    changes.append(f"{location}: request body removed")
                else:
                    old_content = old_body.get("content")
                    new_content = new_body.get("content")
                    old_content = old_content if isinstance(old_content, Mapping) else {}
                    new_content = new_content if isinstance(new_content, Mapping) else {}
                    for media_type, old_media in old_content.items():
                        if media_type not in new_content:
                            changes.append(f"{location}: request media type {media_type} removed")
                            continue
                        _compare_schema(
                            old_media.get("schema", {}) if isinstance(old_media, Mapping) else {},
                            new_content[media_type].get("schema", {})
                            if isinstance(new_content[media_type], Mapping)
                            else {},
                            old_spec=old_spec,
                            new_spec=new_spec,
                            direction="request",
                            location=f"{location} request {media_type}",
                            changes=changes,
                            seen=set(),
                        )
            elif isinstance(new_body, Mapping) and new_body.get("required") is True:
                changes.append(f"{location}: new required request body")

            old_responses = old_operation.get("responses")
            new_responses = new_operation.get("responses")
            old_responses = old_responses if isinstance(old_responses, Mapping) else {}
            new_responses = new_responses if isinstance(new_responses, Mapping) else {}
            for status, old_response in old_responses.items():
                if status not in new_responses:
                    changes.append(f"{location}: response {status} removed")
                    continue
                old_content = (
                    old_response.get("content", {}) if isinstance(old_response, Mapping) else {}
                )
                new_response = new_responses[status]
                new_content = (
                    new_response.get("content", {}) if isinstance(new_response, Mapping) else {}
                )
                if not isinstance(old_content, Mapping) or not isinstance(new_content, Mapping):
                    continue
                for media_type, old_media in old_content.items():
                    if media_type not in new_content:
                        changes.append(
                            f"{location}: response {status} media type {media_type} removed"
                        )
                        continue
                    _compare_schema(
                        old_media.get("schema", {}) if isinstance(old_media, Mapping) else {},
                        new_content[media_type].get("schema", {})
                        if isinstance(new_content[media_type], Mapping)
                        else {},
                        old_spec=old_spec,
                        new_spec=new_spec,
                        direction="response",
                        location=f"{location} response {status} {media_type}",
                        changes=changes,
                        seen=set(),
                    )
    return list(dict.fromkeys(changes))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Explicitly replace the frozen v1 baseline with the current contract.",
    )
    args = parser.parse_args()
    current = current_openapi()
    if args.update_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"updated {BASELINE.relative_to(ROOT)}")
        return 0
    if not BASELINE.is_file():
        raise SystemExit("OpenAPI baseline is missing; review and run --update-baseline")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changes = breaking_changes(baseline, current)
    if changes:
        print("breaking OpenAPI changes detected:")
        for change in changes:
            print(f"- {change}")
        return 1
    print("OpenAPI v1 compatibility gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
