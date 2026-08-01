"""Generate deterministic TypeScript wire types from canonical Pydantic schemas."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from akc_cir.collection_events import (
    COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS,
    COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS,
    COLLECTION_EVENT_TYPES,
    PayloadFieldType,
)
from akc_cir.schema import all_json_schemas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packages" / "contracts" / "src" / "generated-contracts.ts"
COLLECTION_EVENT_SCHEMA_OUTPUT = (
    ROOT / "packages" / "contracts" / "schemas" / "collection-event.schema.json"
)
_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_$]", "_", value)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _pascal(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(part[:1].upper() + part[1:] for part in parts if part) or "Contract"


def _property_name(value: str) -> str:
    return value if _IDENTIFIER.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def _literal(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _payload_field_descriptor(expected: PayloadFieldType) -> str:
    expected_types = expected if isinstance(expected, tuple) else (expected,)
    labels = [
        "string"
        if item is str
        else "integer"
        if item is int
        else "boolean"
        if item is bool
        else "object"
        if item is dict
        else "array"
        if item is list
        else "null"
        for item in expected_types
    ]
    return "|".join(labels)


def _union(values: list[str]) -> str:
    unique = list(dict.fromkeys(values))
    if not unique:
        return "never"
    if len(unique) == 1:
        return unique[0]
    return " | ".join(f"({value})" if " & " in value else value for value in unique)


def _render_schema(schema: Any) -> str:
    if not isinstance(schema, Mapping):
        return "GeneratedJsonValue"
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return _identifier(reference.rsplit("/", 1)[-1])
    if "const" in schema:
        return _literal(schema["const"])
    enum = schema.get("enum")
    if isinstance(enum, list):
        return _union([_literal(item) for item in enum])
    for keyword, operator in (("anyOf", " | "), ("oneOf", " | "), ("allOf", " & ")):
        variants = schema.get(keyword)
        if isinstance(variants, list):
            typed_variants = [
                item for item in variants if not (isinstance(item, Mapping) and "if" in item)
            ]
            if not typed_variants or (
                keyword == "allOf"
                and ("type" in schema or isinstance(schema.get("properties"), Mapping))
            ):
                continue
            rendered = list(dict.fromkeys(_render_schema(item) for item in typed_variants))
            return operator.join(
                f"({item})" if operator == " & " and " | " in item else item for item in rendered
            )

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return _union([_render_schema({**schema, "type": item}) for item in schema_type])
    if schema_type == "null":
        return "null"
    if schema_type == "boolean":
        return "boolean"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "string":
        return "string"
    if schema_type == "array":
        prefix_items = schema.get("prefixItems")
        if isinstance(prefix_items, list):
            return "readonly [" + ", ".join(_render_schema(item) for item in prefix_items) + "]"
        return f"ReadonlyArray<{_render_schema(schema.get('items', {}))}>"

    properties = schema.get("properties")
    additional = schema.get("additionalProperties")
    if schema_type == "object" or isinstance(properties, Mapping) or additional is not None:
        required = {str(item) for item in schema.get("required", []) if isinstance(item, str)}
        fields: list[str] = []
        if isinstance(properties, Mapping):
            for name, child in properties.items():
                optional = "" if name in required else "?"
                fields.append(
                    f"readonly {_property_name(str(name))}{optional}: {_render_schema(child)};"
                )
        declared = "{ " + " ".join(fields) + " }"
        if isinstance(additional, Mapping):
            return declared + " & Readonly<Record<string, " + _render_schema(additional) + ">>"
        if additional is True:
            return declared + " & Readonly<Record<string, GeneratedJsonValue>>"
        return declared
    return "GeneratedJsonValue"


def generate_types() -> str:
    schemas = all_json_schemas()
    lines = [
        "/* AUTO-GENERATED by scripts/generate_contract_types.py. DO NOT EDIT. */",
        "",
        "export type GeneratedJsonPrimitive = string | number | boolean | null;",
        "export type GeneratedJsonValue =",
        "  | GeneratedJsonPrimitive",
        "  | ReadonlyArray<GeneratedJsonValue>",
        "  | Readonly<{ [key: string]: GeneratedJsonValue }>;",
        "",
        "export const COLLECTION_EVENT_TYPES = [",
        *[f"  {_literal(event_type)}," for event_type in COLLECTION_EVENT_TYPES],
        "] as const;",
        "export type CollectionEventType = (typeof COLLECTION_EVENT_TYPES)[number];",
        "",
        "export const COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS = {",
        *[
            "  "
            + _literal(event_type)
            + ": { "
            + ", ".join(
                f"{_property_name(key)}: {_literal(_payload_field_descriptor(expected))}"
                for key, expected in required.items()
            )
            + " },"
            for event_type, required in COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS.items()
        ],
        "} as const;",
        "",
        "export const COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS = {",
        *[
            "  "
            + _literal(event_type)
            + ": { "
            + ", ".join(
                f"{_property_name(key)}: {_literal(_payload_field_descriptor(expected))}"
                for key, expected in optional.items()
            )
            + " },"
            for event_type, optional in COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS.items()
        ],
        "} as const;",
        "",
    ]
    for schema_name, schema in schemas.items():
        namespace = _pascal(schema_name) + "Contract"
        lines.append(f"export namespace {namespace} {{")
        definitions = schema.get("$defs")
        if isinstance(definitions, Mapping):
            for definition_name, definition in sorted(definitions.items()):
                lines.append(
                    f"  export type {_identifier(str(definition_name))} = "
                    f"{_render_schema(definition)};"
                )
        root_without_defs = {key: value for key, value in schema.items() if key != "$defs"}
        lines.append(f"  export type Root = {_render_schema(root_without_defs)};")
        lines.append("}")
        lines.append(f"export type {_pascal(schema_name)}Generated = {namespace}.Root;")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the checked-in generated file is stale.",
    )
    args = parser.parse_args()
    generated = generate_types()
    collection_event_schema = (
        json.dumps(
            all_json_schemas()["collection-event"],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if args.check:
        stale_types = not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != generated
        stale_collection_event_schema = (
            not COLLECTION_EVENT_SCHEMA_OUTPUT.is_file()
            or COLLECTION_EVENT_SCHEMA_OUTPUT.read_text(encoding="utf-8") != collection_event_schema
        )
        if stale_types or stale_collection_event_schema:
            raise SystemExit(
                "generated contracts are stale; run python scripts/generate_contract_types.py"
            )
        print(
            "generated contracts are current: "
            f"{OUTPUT.relative_to(ROOT)}, "
            f"{COLLECTION_EVENT_SCHEMA_OUTPUT.relative_to(ROOT)}"
        )
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated, encoding="utf-8", newline="\n")
    COLLECTION_EVENT_SCHEMA_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    COLLECTION_EVENT_SCHEMA_OUTPUT.write_text(
        collection_event_schema,
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)}, {COLLECTION_EVENT_SCHEMA_OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
