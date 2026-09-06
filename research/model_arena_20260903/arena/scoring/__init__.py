"""Lane E2 - QA gate, official evaluator adapters and score provenance.

Three rules shape every module here.

*The gate comes first.* ``qa.py`` implements masterplan section 44. No
evaluator input is prepared and no evaluator is launched for an output set
whose QA report is missing or red. A score computed over an output set that
was never counted, hashed and de-duplicated is not evidence.

*An evaluator that did not run produces no number.* A crash, a timeout or a
missing result file becomes ``status: "EVALUATOR_BLOCKED"`` carrying the tail
of stderr. It never becomes ``0.0``. ARENA_CONTRACT section 3.11.

*Official metric names survive.* ``parsers.py`` copies the evaluator's own
metric names into ``summary.json`` unchanged and records a metric the
evaluator does not publish as ``null`` with a reason, never as a value this
lane derived.
"""

from __future__ import annotations

__all__ = ["SCORING_LANE_VERSION"]

#: Bumped whenever the evaluator-input layouts or parsers change shape. It is
#: recorded in every summary so a score can be tied to the adapter that made
#: its input (masterplan section 45).
SCORING_LANE_VERSION = "arena-scoring-v1"
