from __future__ import annotations

import pytest
from akc_cir import all_json_schemas, json_schema
from akc_telemetry import TelemetryPolicy, contains_obvious_secret, redact_telemetry


def test_runtime_schema_registry_is_versioned_and_complete() -> None:
    schemas = all_json_schemas()
    assert {"canonical-document", "processing-event", "knowledge-bundle"} <= set(schemas)
    assert schemas["canonical-document"]["$schema"].endswith("2020-12/schema")
    with pytest.raises(KeyError, match="unknown schema"):
        json_schema("missing")


def test_redaction_handles_nested_sequences_urls_bytes_and_unknown_values() -> None:
    class Value:
        pass

    result = redact_telemetry(
        {
            "items": [
                "https://example.com/path?token=secret",
                b"document bytes",
                Value(),
            ],
            "email": "Contact person@example.com now",
            "long": "x" * 500,
            "nullable": None,
        },
        policy=TelemetryPolicy(max_string_length=20),
    )
    assert "?" not in result["items"][0]
    assert result["items"][0].endswith("…[TRUNCATED]")
    assert result["items"][1] == "[BYTES]"
    assert result["items"][2] == "[VALUE]"
    assert "[EMAIL]" in result["email"]
    assert result["long"].endswith("…[TRUNCATED]")
    assert not contains_obvious_secret(result)


def test_secret_detector_flags_unredacted_nested_value() -> None:
    assert contains_obvious_secret({"nested": [{"authorization": "secret"}]})
