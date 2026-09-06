"""The independent four-link validator, and the negative control the gate lacked.

TWO GAPS ARE CLOSED HERE.

FIRST, `MISSING_FINGERPRINT` had no red direction. Five of the six eligibility
states were driven red by `test_four_link_gate.py`; link 3 was the one nobody had
made fail. A state that has never been observed is a state nobody has shown is
reachable, and a classifier branch that has never fired is indistinguishable from
one that cannot (INC-V2-036).

SECOND, the gate wrote its own evidence. `classify_candidate` decides the state
AND records the digests, so a receipt it produced agrees with it by construction.
`four_link_validator` re-derives the whole classification from the manifest the
receipt binds, and every way of breaking that binding is driven red below.

NOTHING HERE READS AN OUTCOME. A four-link classification is a statement about
followable provenance, not about any closure result.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "source_fact_ir"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import four_link_gate as flg  # noqa: E402
import four_link_validator as flv  # noqa: E402
import ir  # noqa: E402

ValidationRefused = flv.ValidationRefused


def _witness(**overrides: Any) -> dict[str, Any]:
    witness = {
        "construct": "md-inline-link",
        "byte_start": 100,
        "byte_end": 140,
        "excerpt": "[load rule](../operations/rule-configuration.md#load-rules)",
        "unit_path": ["git:fixture/repo:doc.md", "Section"],
    }
    witness.update(overrides)
    return witness


def _candidate(**overrides: Any) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "fact_id": "fact-1",
        "kind": ir.REFERENCE_TARGET,
        "state": ir.REPRESENTED,
        "witness": _witness(),
        "representation": {"normalized": "../operations/rule-configuration.md#load-rules"},
        "policy_ref": None,
        "reason": None,
        "extra": {},
    }
    candidate.update(overrides)
    return candidate


# ---------------------------------------------------------------------------
# the negative control link 3 never had


def test_a_fingerprint_that_raises_is_missing_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Link 3's failure branch, observed rather than assumed reachable.

    Driven by making `fingerprint` raise, because the real function does not
    fail on any candidate this fixture can build -- which is exactly why the
    branch had never been exercised. The point is not that fingerprinting is
    fragile; it is that the classifier reports the RIGHT state when link 3 is
    the one that cannot be followed.
    """

    def explode(fact: Any) -> str:
        raise RuntimeError("fingerprint backend unavailable")

    monkeypatch.setattr(flg.fp, "fingerprint", explode)
    record = flg.classify_candidate(_candidate())
    assert record["eligibility_state"] == flg.STATE_MISSING_FINGERPRINT
    assert "RuntimeError" in record["reason"]
    #: The evidence carries links 1 and 2 -- which WERE computed -- and no
    #: fingerprint. A record must never carry a digest for a link that failed.
    assert set(record["evidence"]) == {"witness_digest", "representation_digest"}


def test_an_empty_fingerprint_is_missing_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other branch: it returned, but returned nothing.

    A separate test because a returned-empty and a raised are different
    failures, and a single test covering "link 3 broke somehow" would leave one
    of the two branches unexercised.
    """
    monkeypatch.setattr(flg.fp, "fingerprint", lambda fact: "")
    record = flg.classify_candidate(_candidate())
    assert record["eligibility_state"] == flg.STATE_MISSING_FINGERPRINT
    assert "empty" in record["reason"]
    assert "fingerprint" not in record["evidence"]


def test_every_eligibility_state_now_has_a_red_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    """All six states are reachable, and each is produced here.

    A closed set whose members cannot all be produced is a list, not a
    classification.
    """
    observed = {flg.classify_candidate(_candidate())["eligibility_state"]}
    observed.add(
        flg.classify_candidate(_candidate(state=ir.UNRESOLVED))["eligibility_state"]
    )
    observed.add(
        flg.classify_candidate(_candidate(witness=_witness(excerpt="  ")))["eligibility_state"]
    )
    observed.add(
        flg.classify_candidate(_candidate(representation=None))["eligibility_state"]
    )
    monkeypatch.setattr(flg.fp, "fingerprint", lambda fact: "")
    observed.add(flg.classify_candidate(_candidate())["eligibility_state"])
    monkeypatch.undo()
    monkeypatch.setattr(flg.fp, "dependency_keys", lambda fact: [])
    observed.add(flg.classify_candidate(_candidate())["eligibility_state"])
    assert observed == set(flg.ELIGIBILITY_STATES), sorted(set(flg.ELIGIBILITY_STATES) - observed)


# ---------------------------------------------------------------------------
# the validator, green


@pytest.fixture
def bound(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """A manifest and the gate receipt that binds it."""
    candidates = [
        _candidate(fact_id=f"fact-{index}") for index in range(3)
    ] + [_candidate(fact_id="fact-bad", state=ir.UNRESOLVED)]
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps({"facts": candidates}), encoding="utf-8")
    receipt = flg.gate(candidates, floor=1)
    receipt["manifest"] = str(manifest)
    receipt["manifest_sha256"] = flv._sha_file(manifest)
    return manifest, receipt


def test_an_intact_receipt_validates(bound: tuple[Path, dict[str, Any]]) -> None:
    _manifest, receipt = bound
    body = flv.validate(receipt)
    assert body["held"] is True
    assert body["eligible_count"] == 3
    assert body["eligible_records_evidence_rederived"] == 3
    assert body["by_state"][flg.STATE_UNRESOLVED_CHAIN] == 1


def test_the_validator_reads_no_outcome(bound: tuple[Path, dict[str, Any]]) -> None:
    """It is safe to run before the cohort is measured."""
    _manifest, receipt = bound
    body = flv.validate(receipt)
    for forbidden in ("verdict_about_migration", "violations", "INVARIANT_6", "score"):
        assert forbidden not in body


# ---------------------------------------------------------------------------
# the validator, red


def test_a_changed_manifest_refuses(bound: tuple[Path, dict[str, Any]]) -> None:
    manifest, receipt = bound
    body = json.loads(manifest.read_text(encoding="utf-8"))
    body["facts"].append(_candidate(fact_id="smuggled"))
    manifest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValidationRefused, match="has changed since the gate ran"):
        flv.validate(receipt)


def test_a_receipt_with_no_manifest_binding_refuses(
    bound: tuple[Path, dict[str, Any]],
) -> None:
    _manifest, receipt = bound
    receipt.pop("manifest_sha256")
    with pytest.raises(ValidationRefused, match="no manifest or no manifest digest"):
        flv.validate(receipt)


def test_a_record_count_mismatch_refuses(bound: tuple[Path, dict[str, Any]]) -> None:
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    receipt["records"] = receipt["records"][:-1]
    with pytest.raises(ValidationRefused, match="silently widened or shrunk"):
        flv.validate(receipt)


def test_a_flipped_state_refuses(bound: tuple[Path, dict[str, Any]]) -> None:
    """The receipt claiming ELIGIBLE for a candidate that is not."""
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    for record in receipt["records"]:
        if record["eligibility_state"] == flg.STATE_UNRESOLVED_CHAIN:
            record["eligibility_state"] = flg.STATE_ELIGIBLE
            break
    with pytest.raises(ValidationRefused, match="does not reproduce the receipt"):
        flv.validate(receipt)


def test_reordered_records_refuse(bound: tuple[Path, dict[str, Any]]) -> None:
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    receipt["records"] = [receipt["records"][1], receipt["records"][0], *receipt["records"][2:]]
    with pytest.raises(ValidationRefused, match="not in the manifest's order"):
        flv.validate(receipt)


def test_an_eligible_record_missing_a_link_digest_refuses(
    bound: tuple[Path, dict[str, Any]],
) -> None:
    """The defect the gate could not catch: a state with no evidence behind it."""
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    for record in receipt["records"]:
        if record["eligibility_state"] == flg.STATE_ELIGIBLE:
            record["evidence"].pop("fingerprint")
            break
    with pytest.raises(ValidationRefused, match=r"ELIGIBLE but lacks"):
        flv.validate(receipt)


def test_a_chain_digest_that_is_not_the_composition_refuses(
    bound: tuple[Path, dict[str, Any]],
) -> None:
    """Four plausible digests and a fifth from somewhere else."""
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    for record in receipt["records"]:
        if record["eligibility_state"] == flg.STATE_ELIGIBLE:
            record["evidence"]["chain_digest"] = ir.digest({"invented": True})
            break
    with pytest.raises(ValidationRefused, match="not the composition of its four links"):
        flv.validate(receipt)


def test_a_dependency_digest_that_does_not_rederive_refuses(
    bound: tuple[Path, dict[str, Any]],
) -> None:
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    for record in receipt["records"]:
        if record["eligibility_state"] == flg.STATE_ELIGIBLE:
            record["evidence"]["dependency_keys"] = ["not-the-real-keys"]
            break
    with pytest.raises(ValidationRefused, match="does not re-derive"):
        flv.validate(receipt)


def test_a_drifted_summary_refuses(bound: tuple[Path, dict[str, Any]]) -> None:
    """Per-record states agree, but the summary they roll up to does not."""
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    receipt["by_state"][flg.STATE_ELIGIBLE] += 5
    with pytest.raises(ValidationRefused, match="drifted from the records"):
        flv.validate(receipt)


def test_ready_below_the_floor_refuses(bound: tuple[Path, dict[str, Any]]) -> None:
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    receipt["floor"] = 999
    receipt["verdict"] = "READY"
    with pytest.raises(ValidationRefused, match="never relaxed to reach feasibility"):
        flv.validate(receipt)


def test_stop_above_the_floor_also_refuses(bound: tuple[Path, dict[str, Any]]) -> None:
    """A gate that stops when it should not is as broken as one that passes."""
    _manifest, receipt = bound
    receipt = copy.deepcopy(receipt)
    receipt["verdict"] = "STOP"
    with pytest.raises(ValidationRefused, match="as broken as one that passes"):
        flv.validate(receipt)


def test_an_empty_manifest_refuses(tmp_path: Path) -> None:
    """A classification over zero candidates agrees with anything."""
    manifest = tmp_path / "empty.json"
    manifest.write_text(json.dumps({"facts": []}), encoding="utf-8")
    receipt = {
        "schema": flg.SCHEMA,
        "manifest": str(manifest),
        "manifest_sha256": flv._sha_file(manifest),
        "records": [],
        "floor": 1,
        "verdict": "STOP",
    }
    with pytest.raises(ValidationRefused, match="agrees with anything"):
        flv.validate(receipt)


def test_a_foreign_schema_refuses() -> None:
    with pytest.raises(ValidationRefused, match="not a four-link gate receipt"):
        flv.validate({"schema": "something.else.v1"})


def test_an_absent_manifest_refuses(tmp_path: Path) -> None:
    with pytest.raises(ValidationRefused, match="not on disk"):
        flv.validate(
            {
                "schema": flg.SCHEMA,
                "manifest": str(tmp_path / "gone.json"),
                "manifest_sha256": "sha256:" + "0" * 64,
            }
        )


# ---------------------------------------------------------------------------
# the actual-universe binding interface


def test_a_universe_shaped_manifest_binds_through_the_facts_key(tmp_path: Path) -> None:
    """The interface a frozen successor universe will be bound through.

    The gate takes `--manifest` plus `--facts-key`, so a universe receipt whose
    candidates live under some other key binds without the gate learning
    anything about universes. Proven here on a synthetic body, so that after
    SFI3 the real one is a parameter change rather than a code change.
    """
    candidates = [_candidate(fact_id=f"fact-{index}") for index in range(2)]
    manifest = tmp_path / "successor_universe.json"
    manifest.write_text(
        json.dumps({"schema": "some.universe.v1", "typed_facts": candidates}),
        encoding="utf-8",
    )
    loaded = flg._load_candidates(manifest, "typed_facts")
    assert len(loaded) == 2
    receipt = flg.gate(loaded, floor=2)
    receipt["manifest"] = str(manifest)
    receipt["manifest_sha256"] = flv._sha_file(manifest)
    assert receipt["verdict"] == "READY"
    assert flv.validate(receipt, facts_key="typed_facts")["eligible_count"] == 2


def test_a_wrong_facts_key_reports_rather_than_guessing(tmp_path: Path) -> None:
    """It does not go hunting for a list that looks about right."""
    manifest = tmp_path / "universe.json"
    manifest.write_text(json.dumps({"typed_facts": [_candidate()]}), encoding="utf-8")
    assert flg._load_candidates(manifest, "facts") == []
