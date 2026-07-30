"""Migration evidence for GPU invocation transition grants."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

MIGRATION = importlib.import_module("migrations.versions.0020_gpu_invocation_transitions")


class _PostgresRecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: str) -> None:
        self.statements.append(str(statement))


def test_gpu_worker_grants_are_individual_prepared_statements(
    monkeypatch: Any,
) -> None:
    recorder = _PostgresRecordingOp()
    monkeypatch.setattr(MIGRATION, "op", recorder)

    MIGRATION._grant_gpu_worker_transition_access()

    assert recorder.statements == [
        "GRANT SELECT ON TABLE model_registry TO akc_gpu_worker",
        ("GRANT INSERT ON TABLE audit_events, job_events TO akc_gpu_worker"),
        ("GRANT UPDATE (progress, event_sequence) ON TABLE processing_jobs TO akc_gpu_worker"),
    ]
    assert all(";" not in statement for statement in recorder.statements)
