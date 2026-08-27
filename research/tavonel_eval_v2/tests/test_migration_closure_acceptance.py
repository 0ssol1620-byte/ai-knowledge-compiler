"""The explicit closure acceptance, and every substitution it must refuse.

The SFI3 gate used to resolve its migration closure by globbing
`identity-change-migration-closure--*.json` and taking the newest. That stem
matches only V1's closure; V2R1, V2R2, V2R3 and V2R3R1 all write different stems,
so four successors in a row were invisible to the gate and nothing in it could
say so. INC-V2-069.

The founder's ruling names eight red controls for the replacement, and each is
below:

    V1 receipt substituted        wrong protocol id
    V2R3R1 receipt substituted    wrong protocol id AND seven invariants absent
    wrong protocol id             refused
    missing overall               refused
    overall FAIL                  refused
    one invariant omitted         refused as a domain break
    one invariant UNPROVEN        refused
    digest mismatch               refused

`test_the_real_v2r3r1_receipt_is_refused` uses the artefact on disk rather than a
reconstruction of it, because that is the receipt this gate would actually have
been handed if the glob had merely been repointed at the newest closure stem.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import invariant_domain as dom  # noqa: E402
import migration_closure_acceptance as mca  # noqa: E402

CANON = dom.CANONICAL_INVARIANTS


def _measurement(
    *,
    protocol_id: str = mca.ACCEPTED_PROTOCOL_ID,
    verdicts: dict[str, str] | None = None,
    invariants: tuple[str, ...] = CANON,
    overall: str | None = dom.PASS,
    pairs: int = 240,
    families: tuple[str, ...] = ("git_docs", "regulation_ecfr", "sec_edgar"),
) -> dict[str, Any]:
    block = {
        name: {"verdict": (verdicts or {}).get(name, dom.MET), "exercising_observations": 9}
        for name in invariants
    }
    body: dict[str, Any] = {
        "schema": "tavonel.v2.identity_change_migration_closure.v2r4_result.v1",
        "protocol_id": protocol_id,
        "protocol_sha256": "sha256:" + "a" * 64,
        "universe_sha256": "sha256:" + "b" * 64,
        "provenance": {"run_id": "20260901T000000Z-abcdef123456"},
        "pairs_resolved": pairs,
        "by_family": dict.fromkeys(families, pairs // max(len(families), 1)),
        "invariants": block,
    }
    if overall is not None:
        body["overall"] = overall
    return body


@pytest.fixture
def landed(tmp_path, monkeypatch):
    """Write a measurement under a fake ROOT and return (path, acceptance)."""
    monkeypatch.setattr(mca, "ROOT", tmp_path)
    receipts = tmp_path / "receipts"
    receipts.mkdir()

    def land(body: dict[str, Any], name: str = "closure.json") -> tuple[Path, dict[str, Any]]:
        path = receipts / name
        path.write_text(json.dumps(body), encoding="utf-8")
        acceptance = {
            "schema": mca.SCHEMA,
            "protocol_id": body.get("protocol_id"),
            "measurement_receipt": f"receipts/{name}",
            "measurement_run_id": (body.get("provenance") or {}).get("run_id"),
            "measurement_sha256": mca._sha_file(path),
            "protocol_sha256": body.get("protocol_sha256"),
            "universe_sha256": body.get("universe_sha256"),
        }
        return path, acceptance

    return land


# ---------------------------------------------------------------------------
# the green direction


def test_a_complete_v2r4_pass_is_accepted(landed):
    _path, acceptance = landed(_measurement())
    held = mca.verify(acceptance)
    assert held["held"] is True
    assert held["overall"] == dom.PASS
    assert held["pairs_resolved"] == 240
    assert len(held["families"]) == 3
    assert set(held["invariants"]) == set(CANON)


def test_build_drafts_and_verifies_in_one_step(landed):
    """A draft is never returned unverified; a claim is what this replaces."""
    path, _acceptance = landed(_measurement())
    draft = mca.build(path)
    assert draft["protocol_id"] == mca.ACCEPTED_PROTOCOL_ID
    assert mca.verify(draft)["held"] is True


def test_the_acceptance_names_no_glob_anywhere(landed):
    _path, acceptance = landed(_measurement())
    held = mca.verify(acceptance)
    assert "no implicit predecessor selection" in held["no_glob"]
    assert held["measurement_run_id"] == "20260901T000000Z-abcdef123456"


# ---------------------------------------------------------------------------
# the eight red controls


def test_control_a_v1_receipt_substituted_is_refused(landed):
    """V1's closure is a different scientific object, whatever its verdict."""
    _path, acceptance = landed(
        _measurement(protocol_id="IDENTITY_CHANGE_MIGRATION_CLOSURE_V1")
    )
    with pytest.raises(mca.AcceptanceRefused, match="superseded chain"):
        mca.verify(acceptance)


def test_control_a_v2r3r1_receipt_substituted_is_refused(landed):
    _path, acceptance = landed(
        _measurement(protocol_id="IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1")
    )
    with pytest.raises(mca.AcceptanceRefused, match="superseded chain"):
        mca.verify(acceptance)


def test_control_a_wrong_protocol_id_inside_the_measurement_is_refused(landed):
    """The acceptance says V2R4 and the receipt it names says something else."""
    body = _measurement(protocol_id="IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R5")
    _path, acceptance = landed(body)
    acceptance["protocol_id"] = mca.ACCEPTED_PROTOCOL_ID
    with pytest.raises(mca.AcceptanceRefused, match="disagree about which study"):
        mca.verify(acceptance)


def test_control_a_missing_overall_is_refused(landed):
    _path, acceptance = landed(_measurement(overall=None))
    with pytest.raises(mca.AcceptanceRefused, match="declared invariant set"):
        mca.verify(acceptance)


def test_control_an_overall_fail_is_refused(landed):
    _path, acceptance = landed(
        _measurement(overall=dom.FAIL, verdicts={CANON[3]: dom.VIOLATED})
    )
    with pytest.raises(mca.AcceptanceRefused, match="not PASS"):
        mca.verify(acceptance)


def test_control_one_invariant_omitted_is_refused(landed):
    _path, acceptance = landed(_measurement(invariants=CANON[:7]))
    with pytest.raises(mca.AcceptanceRefused, match="declared invariant set"):
        mca.verify(acceptance)


def test_control_one_invariant_unproven_is_refused(landed):
    """A PASS whose own blocks contradict it.

    The receipt is built claiming `overall: PASS` while one invariant reads
    UNPROVEN -- a state the V2R4 scorer cannot produce, and exactly the state a
    hand-written or drifted receipt could.
    """
    _path, acceptance = landed(_measurement(verdicts={CANON[2]: dom.UNPROVEN}))
    with pytest.raises(mca.AcceptanceRefused, match="own blocks contradict"):
        mca.verify(acceptance)


def test_control_a_digest_mismatch_is_refused(landed):
    path, acceptance = landed(_measurement())
    body = json.loads(path.read_text(encoding="utf-8"))
    body["pairs_resolved"] = 999
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(mca.AcceptanceRefused, match="has changed since it was accepted"):
        mca.verify(acceptance)


# ---------------------------------------------------------------------------
# the remaining clauses


def test_a_run_id_mismatch_is_refused(landed):
    _path, acceptance = landed(_measurement())
    acceptance["measurement_run_id"] = "20260101T000000Z-000000000000"
    with pytest.raises(mca.AcceptanceRefused, match="names run"):
        mca.verify(acceptance)


@pytest.mark.parametrize("field", ["protocol_sha256", "universe_sha256"])
def test_a_chain_digest_mismatch_is_refused(landed, field):
    _path, acceptance = landed(_measurement())
    acceptance[field] = "sha256:" + "f" * 64
    with pytest.raises(mca.AcceptanceRefused, match=f"{field} disagrees"):
        mca.verify(acceptance)


@pytest.mark.parametrize("field", mca.REQUIRED_DIGESTS)
def test_an_acceptance_missing_a_digest_is_refused(landed, field):
    _path, acceptance = landed(_measurement())
    acceptance.pop(field)
    with pytest.raises(mca.AcceptanceRefused, match=f"records no {field}"):
        mca.verify(acceptance)


def test_a_cohort_below_the_floor_is_refused(landed):
    _path, acceptance = landed(_measurement(pairs=mca.COHORT_FLOOR - 1))
    with pytest.raises(mca.AcceptanceRefused, match="never lowered to reach feasibility"):
        mca.verify(acceptance)


def test_a_cohort_at_the_floor_exactly_is_accepted(landed):
    """The boundary in the permissive direction, so the floor is not off by one."""
    _path, acceptance = landed(_measurement(pairs=mca.COHORT_FLOOR))
    assert mca.verify(acceptance)["pairs_resolved"] == mca.COHORT_FLOOR


def test_too_few_families_is_refused(landed):
    _path, acceptance = landed(_measurement(families=("git_docs", "regulation_ecfr")))
    with pytest.raises(mca.AcceptanceRefused, match="families against a required"):
        mca.verify(acceptance)


def test_an_absent_measurement_is_refused(landed):
    _path, acceptance = landed(_measurement())
    acceptance["measurement_receipt"] = "receipts/never-written.json"
    with pytest.raises(mca.AcceptanceRefused, match="not on disk"):
        mca.verify(acceptance)


def test_a_foreign_schema_is_refused():
    with pytest.raises(mca.AcceptanceRefused, match="not a migration closure acceptance"):
        mca.verify({"schema": "something.else.v1"})


# ---------------------------------------------------------------------------
# the real artefacts


def test_the_real_v2r3r1_receipt_is_refused():
    """The receipt the gate would have been handed by a merely-repointed glob.

    It carries `INVARIANT_6_…` at the top level, no `invariants` block and no
    `overall`. Refused on the protocol id first, and it would be refused on the
    domain even if the id matched.
    """
    found = sorted(
        glob.glob(str(NS / "receipts" / "identity-change-migration-closure-v2r3r1--*.json"))
    )
    assert found, "no V2R3R1 measurement receipt on disk"
    body = json.loads(Path(found[-1]).read_text(encoding="utf-8"))
    acceptance = {
        "schema": mca.SCHEMA,
        "protocol_id": body.get("protocol_id"),
        "measurement_receipt": str(Path(found[-1]).relative_to(ROOT)).replace("\\", "/"),
        "measurement_sha256": mca._sha_file(Path(found[-1])),
        "protocol_sha256": body.get("protocol_sha256"),
        "universe_sha256": body.get("universe_sha256"),
    }
    with pytest.raises(mca.AcceptanceRefused):
        mca.verify(acceptance)


def test_the_sfi3_gate_consumes_the_exact_accepted_v2r4_closure():
    """The live chain now has the explicit V2R4 acceptance this gate requires."""
    import freeze_sfi3_protocol as freezer

    result = freezer._identity_change_separation_complete()
    assert result["verdict"] == freezer.CONDITION_MET
    assert result["closure_acceptance"]["protocol_id"] == mca.ACCEPTED_PROTOCOL_ID
    assert result["closure_acceptance"]["overall"] == "PASS"
    assert result["closure_acceptance_receipt"].endswith(
        "migration-closure-acceptance--20260826T065127Z-0d8f9b2c3e28.json"
    )
    assert "never a stem glob" in result["closure_bound_by"]
