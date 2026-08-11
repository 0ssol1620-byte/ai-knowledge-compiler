"""Absorption challengers for `docs/research/ABSORPTION_EXPERIMENT_CONTRACTS_BATCH1.md`.

Shadow only. Not in the wheel, gated by `ABSORB_*` flags that default false, and
never a substitute for a Protected Core module. See `README.md` in the package
root for why both halves of that are needed.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Tracks the experiment batch, not the repository version.
__version__ = "0.1.0-exp0101"
