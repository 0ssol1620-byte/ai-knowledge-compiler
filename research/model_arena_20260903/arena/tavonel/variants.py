"""Variant identifiers for the TAVONEL system configurations (masterplan section 25).

These are system configurations, not models. Variant E is the post-hoc oracle:
it is allowed to read official per-case scores, which is exactly why it can
never be a product. Its label travels in the directory name and in every record
it writes so that a file cannot be mistaken for a deployable result later.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from arena.tavonel.errors import PolicyError

ORACLE_LABEL: Final = "ORACLE_POST_HOC_NOT_DEPLOYABLE"

VARIANT_A: Final = "A_base"
VARIANT_B: Final = "B_recovery"
VARIANT_C: Final = "C_adaptive"
VARIANT_D: Final = "D_opus_escalation"
VARIANT_E: Final = "E_oracle"

VARIANT_IDS: Final = (VARIANT_A, VARIANT_B, VARIANT_C, VARIANT_D, VARIANT_E)

VARIANT_DESCRIPTIONS: Final = MappingProxyType(
    {
        VARIANT_A: "base primary only",
        VARIANT_B: "primary output plus a recovery plan for tripped pages",
        VARIANT_C: "adaptive specialist selection on non-GT signals",
        VARIANT_D: "adaptive plus capped Opus escalation for the riskiest pages",
        VARIANT_E: f"post-hoc best-of-models ceiling — {ORACLE_LABEL}",
    }
)

# Directory names. Variant E carries its label in the path (contract section 8).
_VARIANT_DIR_NAMES: Final = MappingProxyType(
    {
        VARIANT_A: VARIANT_A,
        VARIANT_B: VARIANT_B,
        VARIANT_C: VARIANT_C,
        VARIANT_D: VARIANT_D,
        VARIANT_E: f"E_{ORACLE_LABEL}",
    }
)

# Single letters and the bare masterplan names are accepted on the CLI.
_ALIASES: Final = MappingProxyType(
    {
        "a": VARIANT_A,
        "b": VARIANT_B,
        "c": VARIANT_C,
        "d": VARIANT_D,
        "e": VARIANT_E,
        "base": VARIANT_A,
        "recovery": VARIANT_B,
        "adaptive": VARIANT_C,
        "escalation": VARIANT_D,
        "oracle": VARIANT_E,
    }
)


def normalize_variant(raw: str) -> str:
    """Map a CLI spelling to a canonical variant id, or fail loudly."""
    candidate = raw.strip()
    if candidate in VARIANT_IDS:
        return candidate
    alias = _ALIASES.get(candidate.casefold())
    if alias is not None:
        return alias
    raise PolicyError(f"unknown variant {raw!r}; choose one of {', '.join(VARIANT_IDS)}")


def variant_dir_name(variant: str) -> str:
    """Directory segment for a variant. Variant E's carries the oracle label."""
    try:
        return _VARIANT_DIR_NAMES[variant]
    except KeyError as exc:
        raise PolicyError(f"unknown variant {variant!r}") from exc


def is_oracle(variant: str) -> bool:
    return variant == VARIANT_E


__all__ = [
    "ORACLE_LABEL",
    "VARIANT_A",
    "VARIANT_B",
    "VARIANT_C",
    "VARIANT_D",
    "VARIANT_DESCRIPTIONS",
    "VARIANT_E",
    "VARIANT_IDS",
    "is_oracle",
    "normalize_variant",
    "variant_dir_name",
]
