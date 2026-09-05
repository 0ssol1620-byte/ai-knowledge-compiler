"""TAVONEL variant identity, re-exported from lane E1 (masterplan section 25).

Variant ids, their directory names and the oracle label are frozen contract
vocabulary, not this lane's to redefine. Importing ``arena.tavonel.variants``
keeps this lane's tables in step with lane E1 automatically instead of
carrying a second, driftable copy of the same five strings.
"""

from __future__ import annotations

from arena.tavonel.variants import (
    ORACLE_LABEL,
    VARIANT_DESCRIPTIONS,
    VARIANT_IDS,
    is_oracle,
    variant_dir_name,
)

__all__ = [
    "ORACLE_LABEL",
    "VARIANT_DESCRIPTIONS",
    "VARIANT_IDS",
    "is_oracle",
    "variant_dir_name",
]
