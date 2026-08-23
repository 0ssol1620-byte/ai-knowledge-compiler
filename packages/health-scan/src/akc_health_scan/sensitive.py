"""§5.2 (7) sensitive exposure — filename/pattern presence heuristics.

Policy: matched VALUES are never captured anywhere in the report; findings
record the path, line number and rule id only.
"""

from __future__ import annotations

import re
from typing import Any

from . import inventory
from .config import HealthScanConfig
from .inventory import FileRecord
from .models import HEURISTIC_LABEL

FILENAME_RULES = (
    ("dotenv-filename", re.compile(r"(?:^|/)\.env(?:\.[^/]+)?$")),
    (
        "private-key-file",
        re.compile(r"(?:id_(?:rsa|dsa|ecdsa|ed25519)|\.(?:pem|ppk|pfx|p12|kdbx))$", re.IGNORECASE),
    ),
    (
        "secret-named-file",
        re.compile(
            r"(?:passw(or)?d|passwd|secret|credential|api[_-]?key|apikey"
            r"|access[_-]?token|private[_-]?key)",
            re.IGNORECASE,
        ),
    ),
)

CONTENT_RULES = (
    (
        "credential-assignment-pattern",
        re.compile(
            r"\b(?:api[_-]?key|apikey|client[_-]?secret|secret|passw(or)?d|passwd"
            r"|access[_-]?token)\b\s*[:=]",
            re.IGNORECASE,
        ),
    ),
    ("aws-access-key-id-pattern", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key-block-pattern", re.compile(r"^-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer-token-pattern", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}")),
)

POLICY = (
    "filename/pattern presence only; matched values are never captured "
    "in this report"
)


def analyze(records: list[FileRecord], config: HealthScanConfig) -> dict[str, Any]:
    findings: list[dict[str, object]] = []
    for record in records:
        for rule_id, pattern in FILENAME_RULES:
            if pattern.search(record.rel_path):
                findings.append({"path": record.rel_path, "line": None, "rule_id": rule_id})
        text = inventory.read_text(record, config)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rule_id, pattern in CONTENT_RULES:
                if pattern.search(line):
                    findings.append(
                        {"path": record.rel_path, "line": lineno, "rule_id": rule_id}
                    )
    return {"label": HEURISTIC_LABEL, "policy": POLICY, "findings": findings}
