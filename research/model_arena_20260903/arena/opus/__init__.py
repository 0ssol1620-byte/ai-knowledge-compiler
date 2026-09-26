"""Claude Opus 5 subscription-surface runner (masterplan section 21, lane D).

This lane is not a GPU runtime. It drives the locally installed Claude Code CLI
once per page with a fresh process, records the full ``--output-format json``
payload verbatim, and writes an arena page receipt with
``runtime_mode = "subscription"``.

Hard rules that are contract, not style (masterplan sections 21.3, 21.8, 43):

- ``--bare`` is forbidden: it never reads the OAuth credential and would move the
  run onto API-key billing, which is a different experiment.
- On a subscription/rate/capacity limit the pool stops, checkpoints and exits 75.
  There is no fallback, no model downgrade and no API auto-switch.
- If the payload does not name an Opus 5 model the page fails with
  ``UNKNOWN / "unexpected model"`` and the pool stops.
"""

from __future__ import annotations

OPUS_MODEL_KEY = "opus5_subscription"

__all__ = ["OPUS_MODEL_KEY"]
