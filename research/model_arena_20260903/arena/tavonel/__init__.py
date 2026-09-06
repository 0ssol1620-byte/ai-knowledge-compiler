"""TAVONEL replay lane (E1) — signals, route freeze, replay, recovery plan, cost.

Masterplan sections 23-27 and ARENA_CONTRACT section 8. This package turns the
frozen per-model outputs into TAVONEL system variants without running a single
extra inference, and it freezes every route decision before anything in the
campaign is allowed to read an answer key.

What the package is careful about, in one place:

* **Order.** ``freeze.py`` refuses to seal a deployable variant once the
  primary model has scoring output on disk (masterplan section 2.2).
* **Boundary.** ``guards.py`` blocks reads under the answer-key and evaluator
  roots at runtime; a source scan keeps that vocabulary out of every module
  except ``oracle.py``.
* **Calibration.** Every threshold is a named parameter carrying
  ``calibrated: false``. Nothing here has been measured against a corpus.
* **Absence.** A number that cannot be computed is ``null`` with a reason.
  Zero means measured-and-zero.
"""

from __future__ import annotations

from arena.tavonel.features import FEATURE_SET_VERSION
from arena.tavonel.paths import ArenaPaths
from arena.tavonel.variants import ORACLE_LABEL, VARIANT_IDS

__all__ = ["FEATURE_SET_VERSION", "ORACLE_LABEL", "VARIANT_IDS", "ArenaPaths"]
