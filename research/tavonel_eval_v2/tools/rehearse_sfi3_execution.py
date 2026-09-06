#!/usr/bin/env python3
"""Prove the SFI3 execution path works, on development fixtures, before the freeze.

INC-V2-043: the freeze gate reported `may_freeze: True` with every one of the
nineteen scientific conditions green, while `tools/sfi3_worker.py` did not exist
and `summarise` emitted no E8 or E9 block. The declared order is

    freeze -> fresh acquisition -> reduce -> score exactly once

so that would have surfaced at the scorer, *after* acquisition — the step that
spends the corpus. The founder's response was explicit: **a freeze gate must not
pass merely because files exist.** This tool is what "exists" was replaced with.

It exercises the real chain end to end

    development fixture -> judge_pair -> deterministic reduction
                        -> summarise -> score_sfi3 contract consumption

and then tries to break it, because a rehearsal that can only succeed proves
nothing about a path's failure behaviour. Every negative control below removes
or corrupts one thing the scorer depends on and requires the scorer to REFUSE.
`score_sfi3` raises `ContractBroken` rather than recording SKIPPED for a missing
block, and that is the behaviour under test: SFI2's false SKIPPED (INC-V2-035)
came from a consumer that defaulted instead of refusing.

**No SFI3 payload is opened here.** The fixtures are synthetic documents built
from `compiler/channel_cases.py`'s own helpers — the same machinery the executor's
adversarial suite uses. The 14 SFI2 forensic cases are deliberately NOT used:
they are development regression fixtures for the identity/change repair and may
not certify anything about SFI3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "compiler", "acquisition", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import compiler.channel_cases as cc  # noqa: E402
import compiler.rebuild_equivalence as reb  # noqa: E402
import score_sfi3  # noqa: E402
import sfi3_worker  # noqa: E402
from common import now  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "sfi3-execution-rehearsal"

#: The four endpoints the executor summary must be able to answer. Taken from
#: the scorer rather than restated: a list maintained alongside it would drift,
#: and drift between producer and consumer is INC-V2-035 exactly.
REQUIRED_BLOCKS: tuple[str, ...] = tuple(block for _e, block, _c, _n in score_sfi3.EXECUTOR_BLOCKS)

#: Derived from the scorer's own contract, never re-spelled. A rehearsal that
#: named these keys itself would keep reporting a clean run after the scorer
#: renamed one -- which inverts the only thing a rehearsal is for.
_BY_ENDPOINT = {endpoint: block for endpoint, block, _c, _n in score_sfi3.EXECUTOR_BLOCKS}
E8_ENDPOINT = score_sfi3.SAFETY_VETO_ENDPOINT
E8_BLOCK = _BY_ENDPOINT[E8_ENDPOINT]
E9_ENDPOINT = next(endpoint for endpoint in _BY_ENDPOINT if endpoint.startswith("E9_"))
E9_BLOCK = _BY_ENDPOINT[E9_ENDPOINT]

#: The keys this rehearsal's readiness block publishes. `freeze_sfi3_protocol`
#: gates the freeze on E9_GATE_POWER_KEY; it imports the name from here rather
#: than spelling it, so a rename cannot leave the freezer reading a key that no
#: longer exists and treating the absence as "no power".
E8_GATE_POWER_KEY = "E8_gate_power"
E9_GATE_POWER_KEY = "E9_gate_power"


class RehearsalFailed(RuntimeError):
    """The execution path does not work, or does not fail when it should."""


# ---------------------------------------------------------------------------
# fixtures


def _fixture_pairs() -> list[tuple[str, bytes, bytes]]:
    """Development pairs that between them put E5, E6 and E9 at risk.

    Each is `(label, before_raw, after_raw)`; the canonical documents are built
    by `channel_cases.document`, so these are real canonical documents through
    the real canonicaliser, not stand-ins for one.
    """
    beta = cc.BODY_BETA
    return [
        (
            "semantic_edit",
            cc.markdown(cc.BODY_ALPHA, beta),
            cc.markdown(cc.BODY_ALPHA, beta + " An added sentence that changes this unit."),
        ),
        (
            "case_only_edit",
            cc.markdown(cc.BODY_ALPHA, beta),
            #: Lower, not upper: BODY_BETA already begins with a capital, so
            #: `beta[0].upper()` produced a byte-identical revision and this
            #: fixture was a second "unchanged" wearing the name of the edit
            #: INC-V2-037 is about. `_fixture_pairs` is asserted non-degenerate
            #: in tests/test_sfi3_execution_path.py so it cannot silently
            #: become one again.
            cc.markdown(cc.BODY_ALPHA, beta[0].lower() + beta[1:]),
        ),
        (
            "reorder_only",
            cc.markdown(cc.BODY_ALPHA, beta),
            cc.markdown(beta, cc.BODY_ALPHA),
        ),
        (
            "unchanged",
            cc.markdown(cc.BODY_ALPHA, beta),
            cc.markdown(cc.BODY_ALPHA, beta),
        ),
    ]


class _Judge:
    """The shape `sfi3_worker.build_summary` consumes, filled by real judging.

    Deliberately not `sfi2_worker.RebuildJudge`: that class exists to buffer a
    pair as the acquisition extractor walks it, and there is no acquisition
    here. What matters is that `build_summary` — the function the real run uses —
    is the one under test, so it is called rather than reimplemented.
    """

    def __init__(self) -> None:
        self.verdicts: list[Any] = []
        self.errors: list[dict[str, Any]] = []


def judge_fixtures() -> tuple[_Judge, dict[str, Any]]:
    judge = _Judge()
    for label, before_raw, after_raw in _fixture_pairs():
        before = cc.document(before_raw, "v1", source_id=f"rehearsal:{label}")
        after = cc.document(after_raw, "v2", source_id=f"rehearsal:{label}")
        verdict = reb.judge_pair(
            before_document=before,
            after_document=after,
            before_raw=before_raw,
            after_raw=after_raw,
            before_facts=[],
            after_facts=[],
        )
        judge.verdicts.append(verdict)

    #: The deterministic reduction's shape, with every fixture admitted. The
    #: real run gets this from `sfi1_worker.reduce_results`; here the cohort is
    #: the fixture list, and `build_summary`'s admitted-cohort filter is still
    #: the code path exercised.
    reduced = {
        "admitted": [{"lineage_id": row.lineage_id} for row in judge.verdicts],
    }
    return judge, reduced


# ---------------------------------------------------------------------------
# the positive path


def positive_path() -> dict[str, Any]:
    """A known development cohort, consumable end to end."""
    judge, reduced = judge_fixtures()
    summary = sfi3_worker.build_summary(judge, reduced)

    missing = [block for block in REQUIRED_BLOCKS if block not in summary]
    if missing:
        raise RehearsalFailed(f"summarise emitted no block for: {', '.join(missing)}")

    verdicts = score_sfi3.score_executor(summary)
    unreadable = [endpoint for endpoint, row in verdicts.items() if row.get("verdict") is None]
    if unreadable:
        raise RehearsalFailed(f"the scorer could not read: {', '.join(unreadable)}")

    e8 = summary[E8_BLOCK]
    stages_missing = [
        stage for stage in score_sfi3.STAGES_REQUIRED if stage not in e8["stages_checked"]
    ]
    if stages_missing:
        raise RehearsalFailed(
            "E8 was not observed at every declared stage: "
            + ", ".join(stages_missing)
            + ". An unwatched stage is a failure of the instrument"
        )

    e9 = summary[E9_BLOCK]
    #: Power, not just absence of violations. A rehearsal whose fixtures put E9
    #: at no risk would report it readable and prove nothing about whether a
    #: silent disappearance would be caught on a real cohort.
    if not e9["gate_power"]:
        raise RehearsalFailed(
            "no fixture put E9 at risk: every pair resolved to NO_DEPENDENT or "
            "UNRESOLVED, so a silent disappearance was unreachable and this "
            "rehearsal would not have noticed one"
        )

    return {
        "pairs_judged": len(judge.verdicts),
        "endpoints_readable": sorted(verdicts),
        "verdicts": {endpoint: row["verdict"] for endpoint, row in verdicts.items()},
        "E8_stages_checked": list(e8["stages_checked"]),
        E8_GATE_POWER_KEY: e8["gate_power"],
        "E8_reading": (
            "gate_power False is expected and is not a defect: the classification "
            "loop makes required-to-rebuild and carried-forward disjoint by "
            "construction, so this cohort could not have exhibited the failure. "
            "E8 vetoes a PASS if violated and credits nothing when clean"
        ),
        E9_GATE_POWER_KEY: e9["gate_power"],
        "E9_pairs_that_could_have_exhibited": e9["pairs_that_could_have_exhibited"],
    }


# ---------------------------------------------------------------------------
# the negative controls


def _base_summary() -> dict[str, Any]:
    judge, reduced = judge_fixtures()
    return sfi3_worker.build_summary(judge, reduced)


def _expect_contract_broken(label: str, mutate) -> dict[str, Any]:
    """Corrupt the summary one way and require the scorer to REFUSE.

    Refuse means raise, not degrade. A consumer that turned a contract failure
    into SKIPPED would report an unmeasured endpoint as unexercised, which is
    the false SKIPPED that made SFI2's E5 unreadable.
    """
    summary = _base_summary()
    mutate(summary)
    try:
        score_sfi3.score_executor(summary)
    except score_sfi3.ContractBroken as error:
        return {"control": label, "refused": True, "raised": str(error)[:160]}
    raise RehearsalFailed(
        f"negative control {label!r} did not make the scorer refuse. A defect the "
        "scorer accepts is a defect that reaches the verdict"
    )


def _expect_failed_verdict(label: str, endpoint: str, mutate) -> dict[str, Any]:
    """Inject a real violation and require that endpoint to come back FAILED."""
    summary = _base_summary()
    mutate(summary)
    verdicts = score_sfi3.score_executor(summary)
    got = verdicts[endpoint]["verdict"]
    if got != score_sfi3.FAILED:
        raise RehearsalFailed(
            f"negative control {label!r}: {endpoint} read {got!r}, not FAILED. An "
            "endpoint that cannot come back red has not been measured"
        )
    return {"control": label, "endpoint": endpoint, "verdict": got}


def negative_controls() -> list[dict[str, Any]]:
    e8_block = E8_BLOCK
    e9_block = E9_BLOCK
    e8_endpoint = E8_ENDPOINT
    e9_endpoint = E9_ENDPOINT

    def drop_block(name: str):
        def mutate(summary: dict[str, Any]) -> None:
            summary.pop(name)

        return mutate

    def drop_key(block: str, key: str):
        def mutate(summary: dict[str, Any]) -> None:
            summary[block].pop(key)

        return mutate

    def inject_e8_violation(summary: dict[str, Any]) -> None:
        summary[e8_block]["pairs_with_unexecuted_carry"] = 1
        summary[e8_block]["carried"] = [
            {"lineage_id": "rehearsal:injected", "artifacts": ["section:u:injected"]}
        ]

    def inject_e9_silence(summary: dict[str, Any]) -> None:
        summary[e9_block]["pairs_with_silent_disappearance"] = 1
        summary[e9_block]["silent"] = [
            {"lineage_id": "rehearsal:injected", "artifacts": ["section:u:injected"]}
        ]

    def drop_a_stage(summary: dict[str, Any]) -> None:
        summary[e8_block]["stages_checked"] = [score_sfi3.STAGES_REQUIRED[0]]

    return [
        _expect_contract_broken("E8 block absent", drop_block(e8_block)),
        _expect_contract_broken("E9 block absent", drop_block(e9_block)),
        _expect_contract_broken(
            "E8 block missing its violation count",
            drop_key(e8_block, "pairs_with_unexecuted_carry"),
        ),
        _expect_contract_broken(
            "E9 block missing its power denominator",
            drop_key(e9_block, "pairs_that_could_have_exhibited"),
        ),
        _expect_contract_broken("E9 block missing gate_power", drop_key(e9_block, "gate_power")),
        _expect_failed_verdict("an E8 violation is injected", e8_endpoint, inject_e8_violation),
        _expect_failed_verdict(
            "an E9 silent disappearance is injected", e9_endpoint, inject_e9_silence
        ),
        _expect_failed_verdict("E8 is observed at only one stage", e8_endpoint, drop_a_stage),
    ]


# ---------------------------------------------------------------------------


def rehearse() -> dict[str, Any]:
    positive = positive_path()
    controls = negative_controls()
    return {
        "schema": "tavonel.v2.sfi3_execution_rehearsal.v1",
        "study": "SOURCE_FACT_IR_HELDOUT_V3",
        "generated_at": now(),
        "opened_fresh_payload": False,
        "fixture_source": (
            "compiler/channel_cases.py helpers -- synthetic development documents. "
            "The 14 SFI2 forensic cases are NOT used: they are development "
            "regression fixtures for the identity/change repair and may not "
            "certify SFI3"
        ),
        "positive_path": positive,
        "negative_controls": controls,
        "negative_controls_passed": len(controls),
        "verdict": "PASS",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-receipt", action="store_true")
    arguments = parser.parse_args(argv)

    try:
        body = rehearse()
    except RehearsalFailed as error:
        print(json.dumps({"verdict": "FAIL", "why": str(error)}, indent=2), file=sys.stderr)
        return 4

    if arguments.write_receipt:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))

    print(json.dumps(body, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
