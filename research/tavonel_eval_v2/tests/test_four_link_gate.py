"""Tests for `tools/four_link_gate.py` — INC-V2-034's executable four-link gate.

No network, no GPU, no real acquisition artifact required: every fixture is a
small inline `SourceFact`-shaped dict, built from the shapes already declared
in `source_fact_ir/ir.py.SourceFact.as_dict` and
`source_fact_ir/fingerprint.py`. Mirrors `tests/test_successor_inputs.py`'s
own fixture style for the same reason that file gives: the real SFI2
acquisition artifact is not something a unit test should depend on being
present.

What this file guards, matching the task's definition of done:

1. a single boolean `eligible=true` never appears — every candidate lands in
   exactly one of the six named states
2. a candidate with all four links resolvable is classified `ELIGIBLE`, and
   every evidence digest it carries is independently recomputable
3. a fact whose `source_fact_ir` state is not `REPRESENTED_IN_COMPILED_STATE`
   is `UNRESOLVED_CHAIN`, not silently treated as ineligible-and-forgotten
4. a witness with no excerpt (nothing a reader could check the claim against)
   is `MISSING_SOURCE_WITNESS`
5. a `REPRESENTED` fact whose representation is null is
   `MISSING_CANONICAL_REPRESENTATION`
6. an unanchored fact (no `witness.unit_path`) is `MISSING_DEPENDENCY_PATH`,
   because link 4 cannot be resolved without link 1's anchor
7. a malformed candidate (unknown kind) is `UNRESOLVED_CHAIN`, not silently
   dropped or crashed on
8. the cohort-level gate STOPs below the floor and reports counts by state and
   by kind, never a bare pass/fail
9. the gate reaches READY at/above the floor
10. the CLI's `--no-receipt` path reports `STOP` honestly when no manifest
    exists, rather than estimating a count
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "source_fact_ir", "endpoint"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import four_link_gate as flg  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402


@pytest.fixture
def under_ns() -> Path:
    """A scratch directory under this namespace, not under pytest's `tmp_path`.

    `common.rel()` computes a path relative to the repo root and raises across
    a drive boundary; on this Windows environment `tmp_path` lives on `C:`
    while the repo lives on `D:`. `four_link_gate._safe_rel` already falls
    back safely for a genuinely out-of-repo path (mirroring
    `gpu_successor_preflight._safe_rel`, an existing pattern), so that fallback
    is not removed here. But the CLI test that writes a real immutable receipt
    should still exercise the real repo-relative addressing every actual run
    uses, end to end, rather than only the fallback — hence a scratch
    directory under `NS` instead of the cross-drive default.
    """
    root = NS / "artifacts" / "development" / "_scratch_four_link_gate"
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(dir=root))
    yield scratch
    shutil.rmtree(scratch, ignore_errors=True)
import ir  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


_DEFAULT_UNIT_PATH = ["git:fixture/repo:doc.md", "Section"]
_UNSET = object()


def _witness(
    *,
    construct: str = "md-inline-link",
    byte_start: int = 100,
    byte_end: int = 140,
    excerpt: str = "[load rule](../operations/rule-configuration.md#load-rules)",
    unit_path: Any = _UNSET,
) -> dict[str, Any]:
    return {
        "construct": construct,
        "byte_start": byte_start,
        "byte_end": byte_end,
        "excerpt": excerpt,
        "unit_path": _DEFAULT_UNIT_PATH if unit_path is _UNSET else unit_path,
    }


def _candidate(
    *,
    fact_id: str = "fact-1",
    kind: str = ir.REFERENCE_TARGET,
    state: str = ir.REPRESENTED,
    witness: dict[str, Any] | None = None,
    representation: Any = "not-none-by-default",
    policy_ref: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if representation == "not-none-by-default":
        representation = {"normalized": "../operations/rule-configuration.md#load-rules"}
    return {
        "fact_id": fact_id,
        "kind": kind,
        "state": state,
        "witness": _witness() if witness is None else witness,
        "representation": representation,
        "policy_ref": policy_ref,
        "reason": reason,
        "extra": {},
    }


# ---------------------------------------------------------------------------
# 1 & 2 — the eligible path, and its evidence is real
# ---------------------------------------------------------------------------


def test_eligible_candidate_carries_recomputable_evidence() -> None:
    record = flg.classify_candidate(_candidate())
    assert record["eligibility_state"] == flg.STATE_ELIGIBLE
    assert record["reason"] is None

    evidence = record["evidence"]
    for key in (
        "witness_digest",
        "representation_digest",
        "fingerprint",
        "dependency_digest",
        "chain_digest",
    ):
        assert evidence[key].startswith("sha256:"), key
    assert evidence["dependency_keys"], "an eligible candidate must name real artifact keys"

    # the chain digest is not an opaque token — a reader can recompute it from
    # the four link digests beneath it, without re-running this tool.
    recomputed = ir.digest(
        {
            "witness_digest": evidence["witness_digest"],
            "representation_digest": evidence["representation_digest"],
            "fingerprint": evidence["fingerprint"],
            "dependency_digest": evidence["dependency_digest"],
        }
    )
    assert recomputed == evidence["chain_digest"]


def test_no_state_in_this_repository_ever_reports_a_bare_boolean() -> None:
    # the shape contract: every classification is one of the six named
    # strings, and the field name is `eligibility_state`, never `eligible`.
    record = flg.classify_candidate(_candidate())
    assert "eligible" not in record
    assert record["eligibility_state"] in flg.ELIGIBILITY_STATES
    assert set(flg.ELIGIBILITY_STATES) == {
        "ELIGIBLE",
        "MISSING_SOURCE_WITNESS",
        "MISSING_CANONICAL_REPRESENTATION",
        "MISSING_FINGERPRINT",
        "MISSING_DEPENDENCY_PATH",
        "UNRESOLVED_CHAIN",
    }


# ---------------------------------------------------------------------------
# 3 — a fact that never claimed the chain
# ---------------------------------------------------------------------------


def test_non_represented_state_is_unresolved_chain_not_silently_dropped() -> None:
    candidate = _candidate(
        state=ir.UNRESOLVED,
        representation=None,
        reason="fragment target is not declared by any id in the source",
    )
    record = flg.classify_candidate(candidate)
    assert record["eligibility_state"] == flg.STATE_UNRESOLVED_CHAIN
    assert "REPRESENTED_IN_COMPILED_STATE" in record["reason"]


# ---------------------------------------------------------------------------
# 4 — witness with nothing a reader could check it against
# ---------------------------------------------------------------------------


def test_witness_with_no_excerpt_is_missing_source_witness() -> None:
    candidate = _candidate(witness=_witness(excerpt=""))
    record = flg.classify_candidate(candidate)
    assert record["eligibility_state"] == flg.STATE_MISSING_SOURCE_WITNESS
    assert record["evidence"] == {}


def test_witness_with_inverted_span_is_missing_source_witness() -> None:
    candidate = _candidate(witness=_witness(byte_start=50, byte_end=10))
    record = flg.classify_candidate(candidate)
    assert record["eligibility_state"] == flg.STATE_MISSING_SOURCE_WITNESS


# ---------------------------------------------------------------------------
# 5 — represented fact, null representation
# ---------------------------------------------------------------------------


def test_represented_state_with_null_representation_is_missing_representation() -> None:
    candidate = _candidate(representation=None)
    record = flg.classify_candidate(candidate)
    assert record["eligibility_state"] == flg.STATE_MISSING_CANONICAL_REPRESENTATION
    # link 1 was checked and passed before link 2 failed — evidence for it exists
    assert "witness_digest" in record["evidence"]
    assert "representation_digest" not in record["evidence"]


# ---------------------------------------------------------------------------
# 6 — unanchored fact, no witness.unit_path
# ---------------------------------------------------------------------------


def test_unanchored_fact_is_missing_dependency_path() -> None:
    candidate = _candidate(witness=_witness(unit_path=None))
    record = flg.classify_candidate(candidate)
    assert record["eligibility_state"] == flg.STATE_MISSING_DEPENDENCY_PATH
    # links 1-3 resolved before link 4 failed
    assert "fingerprint" in record["evidence"]
    assert "dependency_digest" not in record["evidence"]


# ---------------------------------------------------------------------------
# 7 — malformed candidate
# ---------------------------------------------------------------------------


def test_unknown_kind_is_unresolved_chain() -> None:
    candidate = _candidate(kind="NOT_A_REAL_KIND")
    record = flg.classify_candidate(candidate)
    assert record["eligibility_state"] == flg.STATE_UNRESOLVED_CHAIN
    assert "could not be reconstructed" in record["reason"]


# ---------------------------------------------------------------------------
# 8 & 9 — cohort-level gate
# ---------------------------------------------------------------------------


def test_cohort_below_floor_stops_and_reports_counts_never_a_bare_fail() -> None:
    candidates = [_candidate(fact_id=f"fact-{i}") for i in range(5)]
    candidates.append(
        _candidate(fact_id="fact-broken", witness=_witness(excerpt=""))
    )
    result = flg.gate(candidates, floor=10)
    assert result["verdict"] == "STOP"
    assert result["feasible"] is False
    assert result["eligible_count"] == 5
    assert result["by_state"]["ELIGIBLE"] == 5
    assert result["by_state"]["MISSING_SOURCE_WITNESS"] == 1
    assert result["candidates_considered"] == 6
    assert len(result["records"]) == 6


def test_cohort_at_floor_reaches_ready() -> None:
    candidates = [_candidate(fact_id=f"fact-{i}") for i in range(3)]
    result = flg.gate(candidates, floor=3)
    assert result["verdict"] == "READY"
    assert result["feasible"] is True
    assert result["eligible_count"] == 3


def test_gate_floor_defaults_to_the_preflight_floor() -> None:
    # the gate must not invent its own floor separate from
    # `gpu_successor_preflight.COHORT_FLOOR` — the founder's ruling is one
    # gate, not a second copy of the number.
    import inspect

    assert inspect.signature(flg.gate).parameters["floor"].default == gsp.COHORT_FLOOR


def test_by_kind_breakdown_never_summarised_away() -> None:
    candidates = [
        _candidate(fact_id="a", kind=ir.REFERENCE_TARGET),
        _candidate(fact_id="b", kind=ir.LANGUAGE, representation="en"),
        _candidate(fact_id="c", kind=ir.LANGUAGE, witness=_witness(excerpt="")),
    ]
    result = flg.gate(candidates, floor=1)
    assert result["by_kind"][ir.REFERENCE_TARGET]["ELIGIBLE"] == 1
    assert result["by_kind"][ir.LANGUAGE]["ELIGIBLE"] == 1
    assert result["by_kind"][ir.LANGUAGE]["MISSING_SOURCE_WITNESS"] == 1


# ---------------------------------------------------------------------------
# 10 — CLI honesty when no manifest exists
# ---------------------------------------------------------------------------


def test_cli_reports_stop_honestly_when_manifest_absent(
    under_ns: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = under_ns / "does_not_exist.json"
    exit_code = flg.main(["--manifest", str(missing), "--no-receipt"])
    assert exit_code == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "STOP"
    assert printed["manifest_present"] is False
    assert printed["eligible_count"] == 0


def test_cli_no_receipt_path_end_to_end(
    under_ns: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = under_ns / "typed_fact_cohort.json"
    manifest.write_text(
        json.dumps({"facts": [_candidate(fact_id=f"fact-{i}") for i in range(3)]}),
        encoding="utf-8",
    )
    exit_code = flg.main(["--manifest", str(manifest), "--floor", "3", "--no-receipt"])
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "READY"
    assert printed["eligible_count"] == 3
    assert printed["manifest_sha256"].startswith("sha256:")
    # a manifest under NS resolves to a clean repo-relative path, exercising
    # `common.rel` directly rather than only `_safe_rel`'s fallback.
    assert not printed["manifest"].startswith(str(under_ns.anchor))
    assert "records" not in printed  # summary print omits the full record list


def test_cli_writes_immutable_receipt(under_ns: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = under_ns / "typed_fact_cohort.json"
    manifest.write_text(
        json.dumps({"facts": [_candidate(fact_id=f"fact-{i}") for i in range(3)]}),
        encoding="utf-8",
    )
    exit_code = flg.main(["--manifest", str(manifest), "--floor", "3"])
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    # `write_immutable` returns a path relative to the repo root (two levels
    # above this namespace), not relative to `NS` itself.
    receipt_path = NS.parents[1] / printed["receipt"]
    try:
        assert receipt_path.exists()
        body = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert body["schema"] == flg.SCHEMA
        assert body["provenance"]["immutable"] is True
        assert len(body["records"]) == 3
    finally:
        if receipt_path.exists():
            receipt_path.unlink()
        # `write_immutable` also updates `receipts/latest/four-link-gate.json`,
        # a convenience pointer this test does not otherwise own. Removed only
        # when it still names the exact receipt this test just deleted, so a
        # concurrent real run's pointer is never touched.
        pointer = NS / "receipts" / "latest" / "four-link-gate.json"
        if pointer.exists():
            try:
                pointed_body = json.loads(pointer.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pointed_body = {}
            if pointed_body.get("points_to", "").endswith(printed["receipt"].split("/")[-1]):
                pointer.unlink()


# ---------------------------------------------------------------------------
# `_safe_rel`'s own fallback — deliberately exercised on a path outside the
# repo (pytest's own `tmp_path`, not `under_ns`), since that is exactly the
# case the fallback exists for.
# ---------------------------------------------------------------------------


def test_safe_rel_falls_back_for_a_path_outside_the_repo(tmp_path: Path) -> None:
    outside = tmp_path / "somewhere.json"
    # never raises, unlike bare `common.rel`
    assert flg._safe_rel(outside) == str(outside)


def test_safe_rel_returns_repo_relative_path_inside_the_repo() -> None:
    inside = NS / "tools" / "four_link_gate.py"
    assert flg._safe_rel(inside) == "research/tavonel_eval_v2/tools/four_link_gate.py"


# ---------------------------------------------------------------------------
# fixture sanity — the fixture itself must be a valid SourceFact
# ---------------------------------------------------------------------------


def test_fixture_reconstructs_as_a_real_source_fact() -> None:
    candidate = copy.deepcopy(_candidate())
    fact = flg._fact_from_dict(candidate)
    assert isinstance(fact, ir.SourceFact)
    assert fact.state == ir.REPRESENTED
