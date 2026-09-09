"""Runtime-visible features and a learned decision representation, not a verifier.

No paths, benchmark metadata, labels, score files or alternate output are inputs.
The offline training/evaluation module supplies a frozen tree; production does not.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

FEATURE_NAMES = (
    "primary_present",
    "log_chars",
    "log_lines",
    "table_line_share",
    "formula_marker_share",
    "digit_share",
    "replacement_share",
    "duplicate_line_share",
    "aspect_ratio",
    "edge_density",
    "near_white_ratio",
    "render_entropy",
)


def visible_features(
    text: str | None,
    *,
    width: int,
    height: int,
    edge_density: float | None,
    near_white_ratio: float | None,
    render_entropy: float | None,
) -> tuple[float, ...]:
    content = text or ""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    count = max(1, len(content))
    values = (
        float(text is not None),
        math.log1p(len(content)),
        math.log1p(len(lines)),
        sum(line.startswith("|") or "<tr" in line.lower() for line in lines) / max(1, len(lines)),
        len(re.findall(r"\\(?:frac|sum|int|begin|sqrt)|\$", content)) / count,
        sum(c.isdigit() for c in content) / count,
        content.count("\ufffd") / count,
        (len(lines) - len(set(lines))) / max(1, len(lines)),
        width / max(height, 1),
        -1.0 if edge_density is None else edge_density,
        -1.0 if near_white_ratio is None else near_white_ratio,
        -1.0 if render_entropy is None else render_entropy,
    )
    if not all(math.isfinite(x) for x in values):
        raise ValueError("NONFINITE_VISIBLE_FEATURE")
    return values


@dataclass(frozen=True, slots=True)
class Decision:
    action: int
    feature: int | None = None
    threshold: float = 0.0
    left: Decision | None = None
    right: Decision | None = None

    def choose(self, features: tuple[float, ...]) -> int:
        if len(features) != len(FEATURE_NAMES):
            raise ValueError("FEATURE_VECTOR_MISMATCH")
        node = self
        for _ in range(3):
            if node.feature is None:
                return node.action
            child = node.left if features[node.feature] <= node.threshold else node.right
            if child is None:
                raise ValueError("INCOMPLETE_SELECTOR")
            node = child
        raise ValueError("SELECTOR_DEPTH_EXCEEDED")
