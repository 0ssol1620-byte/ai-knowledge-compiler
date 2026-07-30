from __future__ import annotations

import pytest

from tests.chaos.compose_drill import CONFIRMATION, compose_command, validate_guardrails


def test_guard_accepts_only_explicit_local_development() -> None:
    validate_guardrails(
        target="api",
        base_url="http://127.0.0.1:8000",
        environment="development",
        confirmation=CONFIRMATION,
        outage=5,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target", "minio"),
        ("base_url", "https://staging.example.com"),
        ("environment", "production"),
        ("confirmation", "yes"),
        ("outage", 31),
    ],
)
def test_guard_rejects_unsafe_scope(field: str, value: str | int) -> None:
    values: dict[str, str | int] = {
        "target": "postgres",
        "base_url": "http://localhost:8000",
        "environment": "test",
        "confirmation": CONFIRMATION,
        "outage": 1,
    }
    values[field] = value
    with pytest.raises(ValueError):
        validate_guardrails(
            target=str(values["target"]),
            base_url=str(values["base_url"]),
            environment=str(values["environment"]),
            confirmation=str(values["confirmation"]),
            outage=int(values["outage"]),
        )


def test_compose_command_has_fixed_project_and_file() -> None:
    command = compose_command("C:/safe/docker.exe", "pause", "api")
    assert command[:4] == [  # nosec B101
        "C:/safe/docker.exe",
        "compose",
        "--project-name",
        "akc-dev",
    ]
    assert command[-2:] == ["pause", "api"]  # nosec B101
