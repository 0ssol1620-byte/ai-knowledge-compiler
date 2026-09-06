"""The seventeen red controls for SOURCE_FACT_IR_HELDOUT_ACCEPTANCE_V1.

The GPU authorization path used to require a PASS from `sfi2-native-provenance`.
SFI2 is frozen, FAIL, spent and permanently non-rescorable, so that requirement
was structurally impossible -- a stale implementation binding, not a live gate.

Replacing it needs more than a new stem. SFI2's acceptance semantics were "seven
endpoints, every one MET"; SFI3 declares nine, of which E1-E7 and E9 are the
PASS-contributing primaries and E8 is a mandatory safety veto whose clean state
is `VETO_CLEAR_NO_POSITIVE_CREDIT` and never `MET`. Requiring `MET` of E8 would
fail every honest SFI3 run. Crediting its clean zero would manufacture positive
evidence from an instrument whose seam is structurally closed and which could not
have fired.

Control 11 is the one that would be easiest to get backwards, so it is stated
positively: a clean veto is ACCEPTED without being MET.

Every control below runs before SFI3 fresh acquisition, on fixtures. No held-out
SFI3 material is read anywhere in this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import score_sfi3  # noqa: E402
import sfi3_acceptance as acc  # noqa: E402

PRIMARIES = acc.PRIMARY_ENDPOINTS
VETO = acc.VETO_ENDPOINT


def _endpoint(stem: str) -> str:
    """The scorer's own spelling of an endpoint id, looked up rather than copied.

    A control that re-spells an endpoint id agrees with a copy of the contract
    instead of the contract itself: rename the id in the scorer and the copy
    still reads, still passes, and now guards an endpoint that no longer exists.
    Looking it up by stem follows a rename and raises on a removal.
    """
    found = [name for name in score_sfi3.ENDPOINTS if name.split("_", 1)[0] == stem]
    if len(found) != 1:
        raise AssertionError(
            f"{stem} names {found} in score_sfi3.ENDPOINTS, not exactly one endpoint"
        )
    return found[0]


def _endpoints(**overrides: Any) -> dict[str, Any]:
    """A clean SFI3 endpoint block: eight primaries MET and exercised, E8 clear."""
    block: dict[str, Any] = {
        name: {"verdict": acc.MET, "violations": 0, "pairs_exercising": 12, "why": None}
        for name in PRIMARIES
    }
    block[VETO] = {
        "verdict": acc.VETO_CLEAR,
        "violations": 0,
        "pairs_exercising": 0,
        "natural_gate_power": False,
        "stages_checked": list(acc.STAGES_REQUIRED),
        "stages_missing": [],
        "cases": [],
    }
    block.update(overrides)
    return block


def _measurement(
    *,
    endpoints: dict[str, Any] | None = None,
    verdict: str = "PASS",
    split: str = "held_out",
    pairs: int = 240,
    families: tuple[str, ...] = ("git_docs", "regulation_ecfr", "sec_edgar"),
    schema: str = acc.MEASUREMENT_SCHEMA,
) -> dict[str, Any]:
    return {
        "schema": schema,
        "protocol": "research/tavonel_eval_v2/protocols/SOURCE_FACT_IR_HELDOUT_V3.yaml",
        "protocol_sha256": "sha256:" + "a" * 64,
        "protocol_freeze_receipt": "receipts/freeze.json",
        "split": split,
        "acquisition": "artifacts/acq.json",
        "acquisition_sha256": "sha256:" + "c" * 64,
        "provenance": {"run_id": "20260910T000000Z-sfi3measure0"},
        "cohort_gates": {
            "pairs_scored": pairs,
            "pairs_required": acc.COHORT_FLOOR_PAIRS,
            "pairs_met": pairs >= acc.COHORT_FLOOR_PAIRS,
            "families": list(families),
            "families_required": acc.FAMILIES_REQUIRED,
            "families_met": len(families) >= acc.FAMILIES_REQUIRED,
        },
        "endpoints": endpoints if endpoints is not None else _endpoints(),
        "verdict": verdict,
    }


@pytest.fixture
def landed(tmp_path, monkeypatch):
    """Write a measurement plus its chain under a fake ROOT; return an acceptance."""
    monkeypatch.setattr(acc, "ROOT", tmp_path)
    (tmp_path / "receipts").mkdir()
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "research/tavonel_eval_v2/protocols").mkdir(parents=True)

    def land(body: dict[str, Any]) -> dict[str, Any]:
        protocol = tmp_path / body["protocol"]
        protocol.write_text("# fixture protocol\n", encoding="utf-8")
        freeze = tmp_path / body["protocol_freeze_receipt"]
        freeze.write_text(
            json.dumps({"provenance": {"run_id": "20260909T000000Z-sfi3freeze0"}}),
            encoding="utf-8",
        )
        acquisition = tmp_path / body["acquisition"]
        acquisition.write_text(json.dumps({"admitted": []}), encoding="utf-8")
        body = {
            **body,
            "protocol_sha256": acc._sha_file(protocol),
            "acquisition_sha256": acc._sha_file(acquisition),
        }
        measurement = tmp_path / "receipts" / "sfi3-score.json"
        measurement.write_text(json.dumps(body), encoding="utf-8")
        return {
            "schema": acc.SCHEMA,
            "protocol_id": acc.ACCEPTED_PROTOCOL_ID,
            "protocol": body["protocol"],
            "protocol_sha256": body["protocol_sha256"],
            "protocol_freeze_receipt": body["protocol_freeze_receipt"],
            "protocol_freeze_run_id": "20260909T000000Z-sfi3freeze0",
            "protocol_freeze_sha256": acc._sha_file(freeze),
            "measurement_receipt": "receipts/sfi3-score.json",
            "measurement_run_id": body["provenance"]["run_id"],
            "measurement_sha256": acc._sha_file(measurement),
            "acquisition": body["acquisition"],
            "acquisition_sha256": body["acquisition_sha256"],
        }

    return land


# ---------------------------------------------------------------------------
# control 17 -- the green direction, first, so the rest are not vacuous


def test_control_17_an_exact_valid_sfi3_pass_is_accepted(landed):
    held = acc.verify(landed(_measurement()))
    assert held["held"] is True
    assert held["verdict"] == "PASS"
    assert held["endpoint_domain"]["equal"] is True
    assert held["primaries"]["all_met_and_exercised"] is True
    assert held["cohort"]["pairs_scored"] == 240


def test_control_11_a_clean_veto_is_accepted_without_being_met(landed):
    """The control easiest to get backwards, stated positively.

    E8 reads VETO_CLEAR_NO_POSITIVE_CREDIT and zero natural gate power, and the
    study is accepted anyway. Requiring MET of the veto would fail every honest
    SFI3 run; crediting its clean zero would manufacture evidence from an
    instrument that could not have fired.
    """
    held = acc.verify(landed(_measurement()))
    assert held["safety_veto"]["verdict"] == acc.VETO_CLEAR
    assert held["safety_veto"]["verdict"] != acc.MET
    assert held["safety_veto"]["natural_gate_power"] is False
    assert held["safety_veto"]["contributes_positive_evidence"] is False


# ---------------------------------------------------------------------------
# control 1 -- SFI2 cannot authorize


def test_control_1_an_sfi2_pass_shaped_fixture_does_not_authorize_gpu(landed):
    """Seven endpoints, every one MET, verdict PASS -- SFI2's exact shape.

    Under the old launcher semantics this is precisely what authorized a GPU
    run. It must not now, and it fails on the endpoint domain: SFI3 declares
    nine and this reports seven, so `E8` and `E9` are simply absent.
    """
    seven = {
        name: {"verdict": acc.MET, "violations": 0, "pairs_exercising": 12}
        for name in PRIMARIES[:7]
    }
    acceptance = landed(_measurement(endpoints=seven))
    with pytest.raises(acc.AcceptanceRefused, match="not the same set"):
        acc.verify(acceptance)


def test_an_sfi2_shaped_measurement_schema_is_refused(landed):
    """A receipt that is not an SFI3 score does not become one by being named."""
    acceptance = landed(_measurement(schema="tavonel.v2.sfi2_score.v1"))
    with pytest.raises(acc.AcceptanceRefused, match="not an SFI3 score"):
        acc.verify(acceptance)


def test_an_acceptance_for_the_wrong_protocol_id_is_refused(landed):
    acceptance = landed(_measurement())
    acceptance["protocol_id"] = "SOURCE_FACT_IR_HELDOUT_V2"
    with pytest.raises(acc.AcceptanceRefused, match="permanently non-rescorable"):
        acc.verify(acceptance)


# ---------------------------------------------------------------------------
# controls 2 to 8 -- the primaries


def test_control_2_an_overall_fail_refuses(landed):
    with pytest.raises(acc.AcceptanceRefused, match="own verdict is 'FAIL'"):
        acc.verify(landed(_measurement(verdict="FAIL")))


def test_control_3_a_missing_primary_endpoint_refuses(landed):
    endpoints = _endpoints()
    endpoints.pop(PRIMARIES[2])
    with pytest.raises(acc.AcceptanceRefused, match="the measurement omits"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_control_4_an_extra_graded_endpoint_refuses(landed):
    endpoints = _endpoints()
    endpoints["E10_invented_after_the_freeze"] = {"verdict": acc.MET, "pairs_exercising": 3}
    with pytest.raises(acc.AcceptanceRefused, match="that nothing declares"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_a_renamed_primary_refuses(landed):
    """A rename is both an omission and an addition; either alone would refuse."""
    endpoints = _endpoints()
    renamed = _endpoint("E7")
    endpoints[renamed + "_but_renamed"] = endpoints.pop(renamed)
    with pytest.raises(acc.AcceptanceRefused, match="not the same set"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_control_5_a_primary_reported_skipped_refuses(landed):
    endpoints = _endpoints()
    endpoints[PRIMARIES[0]] = {
        "verdict": acc.SKIPPED,
        "violations": 0,
        "pairs_exercising": 0,
    }
    with pytest.raises(acc.AcceptanceRefused, match="nothing in the cohort could have"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_a_failed_primary_refuses(landed):
    endpoints = _endpoints()
    endpoints[PRIMARIES[1]] = {
        "verdict": acc.FAILED,
        "violations": 4,
        "pairs_exercising": 12,
    }
    with pytest.raises(acc.AcceptanceRefused, match="is FAILED with 4 violation"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


@pytest.mark.parametrize(
    "endpoint",
    #: The set comes from the scorer, so an endpoint added to or removed from
    #: the must-run policy changes what these controls actually cover.
    [
        pytest.param(endpoint, id=f"control {6 + offset} -- {endpoint.split('_', 1)[0]}")
        for offset, endpoint in enumerate(acc.MUST_BE_EXERCISED)
    ],
)
def test_controls_6_7_8_an_unexercised_must_run_endpoint_refuses(landed, endpoint):
    """MET over zero exercising pairs is a verdict about a question never posed.

    E5 and E6 are the two SFI2 failed outright; E9 is the one no predecessor
    study asked at all. None of the three may reach a PASS unexercised.
    """
    endpoints = _endpoints()
    endpoints[endpoint] = {"verdict": acc.MET, "violations": 0, "pairs_exercising": 0}
    with pytest.raises(acc.AcceptanceRefused, match="zero exercising pairs"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_any_primary_met_over_zero_pairs_refuses(landed):
    """Not only the three named: an unexercised primary is unexercised."""
    endpoints = _endpoints()
    endpoints[PRIMARIES[3]] = {"verdict": acc.MET, "violations": 0, "pairs_exercising": 0}
    with pytest.raises(acc.AcceptanceRefused, match="zero exercising pairs"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


# ---------------------------------------------------------------------------
# controls 9, 10 and 12 -- the veto


def test_control_9_an_e8_violation_refuses(landed):
    endpoints = _endpoints()
    endpoints[VETO] = {**endpoints[VETO], "verdict": acc.FAILED, "violations": 2}
    with pytest.raises(acc.AcceptanceRefused, match="not tradeable against"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_control_10_an_e8_reported_failed_refuses(landed):
    """FAILED with zero violations: the staged-coverage failure mode."""
    endpoints = _endpoints()
    endpoints[VETO] = {**endpoints[VETO], "verdict": acc.FAILED, "violations": 0}
    with pytest.raises(acc.AcceptanceRefused, match="not 'VETO_CLEAR_NO_POSITIVE_CREDIT'"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_an_e8_reported_met_refuses(landed):
    """The veto never earns MET, and a receipt claiming it has drifted."""
    endpoints = _endpoints()
    endpoints[VETO] = {**endpoints[VETO], "verdict": acc.MET}
    with pytest.raises(acc.AcceptanceRefused, match="never MET and never credits"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_control_12_a_missing_required_e8_stage_refuses(landed):
    """An endpoint watched after execution but not at activation.

    It reports a clean number while leaving the path it exists to guard
    unobserved -- INC-V2-036, in the one endpoint that can veto the study.
    """
    endpoints = _endpoints()
    endpoints[VETO] = {
        **endpoints[VETO],
        "stages_checked": [acc.STAGES_REQUIRED[0]],
        "stages_missing": [acc.STAGES_REQUIRED[1]],
    }
    with pytest.raises(acc.AcceptanceRefused, match="not observed at every required stage"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


def test_an_absent_veto_refuses(landed):
    endpoints = _endpoints()
    endpoints.pop(VETO)
    with pytest.raises(acc.AcceptanceRefused, match="not the same set"):
        acc.verify(landed(_measurement(endpoints=endpoints)))


# ---------------------------------------------------------------------------
# controls 13 and 14 -- the cohort


def test_control_13_one_pair_below_the_floor_refuses(landed):
    acceptance = landed(_measurement(pairs=acc.COHORT_FLOOR_PAIRS - 1))
    with pytest.raises(acc.AcceptanceRefused, match="never lowered to reach feasibility"):
        acc.verify(acceptance)


def test_the_floor_exactly_is_accepted(landed):
    """The permissive boundary, so the floor is not off by one."""
    held = acc.verify(landed(_measurement(pairs=acc.COHORT_FLOOR_PAIRS)))
    assert held["cohort"]["pairs_scored"] == acc.COHORT_FLOOR_PAIRS


def test_control_14_only_two_families_refuses(landed):
    acceptance = landed(_measurement(families=("git_docs", "regulation_ecfr")))
    with pytest.raises(acc.AcceptanceRefused, match="families against a required"):
        acc.verify(acceptance)


# ---------------------------------------------------------------------------
# controls 15 and 16 -- the digests


def test_control_15_a_protocol_digest_mismatch_refuses(landed, tmp_path):
    acceptance = landed(_measurement())
    (tmp_path / acceptance["protocol"]).write_text("# edited\n", encoding="utf-8")
    with pytest.raises(acc.AcceptanceRefused, match="has changed since it was accepted"):
        acc.verify(acceptance)


def test_control_16_a_measurement_digest_mismatch_refuses(landed, tmp_path):
    acceptance = landed(_measurement())
    path = tmp_path / acceptance["measurement_receipt"]
    body = json.loads(path.read_text(encoding="utf-8"))
    body["cohort_gates"]["pairs_scored"] = 9999
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(acc.AcceptanceRefused, match="has changed since it was accepted"):
        acc.verify(acceptance)


@pytest.mark.parametrize("field", ["protocol_freeze_receipt", "acquisition"])
def test_a_chain_member_digest_mismatch_refuses(landed, tmp_path, field):
    acceptance = landed(_measurement())
    (tmp_path / acceptance[field]).write_text('{"edited": true}', encoding="utf-8")
    with pytest.raises(acc.AcceptanceRefused, match="has changed since it was accepted"):
        acc.verify(acceptance)


@pytest.mark.parametrize("field", acc.REQUIRED_BINDINGS)
def test_an_acceptance_missing_any_binding_refuses(landed, field):
    acceptance = landed(_measurement())
    acceptance.pop(field)
    with pytest.raises(acc.AcceptanceRefused, match="carries no"):
        acc.verify(acceptance)


def test_a_development_split_cannot_authorize(landed):
    acceptance = landed(_measurement(split="development"))
    with pytest.raises(acc.AcceptanceRefused, match="cannot authorize GPU spend"):
        acc.verify(acceptance)


def test_an_absent_measurement_refuses(landed):
    acceptance = landed(_measurement())
    acceptance["measurement_receipt"] = "receipts/never-written.json"
    with pytest.raises(acc.AcceptanceRefused, match="not on disk"):
        acc.verify(acceptance)


def test_a_foreign_schema_refuses():
    with pytest.raises(acc.AcceptanceRefused, match="not an SFI3 acceptance"):
        acc.verify({"schema": "something.else.v1"})


# ---------------------------------------------------------------------------
# there is one implementation, and it is the scorer's


def test_the_acceptance_rule_is_imported_not_restated():
    """A copy of the endpoint sets here would be a second acceptance rule."""
    assert acc.PRIMARY_ENDPOINTS is score_sfi3.PRIMARY_ENDPOINTS
    assert acc.VETO_ENDPOINT is score_sfi3.SAFETY_VETO_ENDPOINT
    assert acc.VETO_CLEAR is score_sfi3.VETO_CLEAR
    assert acc.MUST_BE_EXERCISED is score_sfi3.MAY_NOT_BE_SKIPPED
    assert acc.COHORT_FLOOR_PAIRS is score_sfi3.COHORT_FLOOR_PAIRS


def test_the_primary_set_is_exactly_e1_to_e7_plus_e9():
    ordinals = sorted(int(name.split("_")[0][1:]) for name in acc.PRIMARY_ENDPOINTS)
    assert ordinals == [1, 2, 3, 4, 5, 6, 7, 9]
    assert acc.VETO_ENDPOINT not in acc.PRIMARY_ENDPOINTS


def test_build_drafts_and_verifies_in_one_step(landed, tmp_path):
    acceptance = landed(_measurement())
    draft = acc.build(tmp_path / acceptance["measurement_receipt"])
    assert draft["protocol_id"] == acc.ACCEPTED_PROTOCOL_ID
    assert acc.verify(draft)["held"] is True


def test_the_module_offers_no_search(landed):
    """No stem glob, no `latest`, no newest-wins. One path, one digest."""
    assert not hasattr(acc, "latest_acceptance")
    held = acc.verify(landed(_measurement()))
    assert "no newest-wins" in held["no_glob"]


def test_seal_writes_one_fixed_immutable_acceptance_authority(landed, tmp_path):
    acceptance = landed(_measurement())
    target = tmp_path / "receipts" / acc.AUTHORITY_NAME
    sealed = acc.seal(
        tmp_path / acceptance["measurement_receipt"],
        authority_path=target,
    )
    assert sealed["held"] is True
    assert target.is_file()
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body["authority"]["single_immutable_authority"] is True
    assert body["provenance"]["immutable"] is True
    assert body["receipt_sha256"]
    with pytest.raises(acc.AcceptanceRefused, match="already exists"):
        acc.seal(
            tmp_path / acceptance["measurement_receipt"],
            authority_path=target,
        )


def test_verify_authority_refuses_an_alternate_exact_path(landed, tmp_path):
    acceptance = landed(_measurement())
    authority = tmp_path / "receipts" / acc.AUTHORITY_NAME
    acc.seal(tmp_path / acceptance["measurement_receipt"], authority_path=authority)
    alternate = tmp_path / "receipts" / "alternate-acceptance.json"
    alternate.write_bytes(authority.read_bytes())
    with pytest.raises(acc.AcceptanceRefused, match="not the single SFI3 acceptance authority"):
        acc.verify_authority(alternate, authority_path=authority)


def test_sealed_acceptance_self_digest_is_enforced(landed, tmp_path):
    acceptance = landed(_measurement())
    authority = tmp_path / "receipts" / acc.AUTHORITY_NAME
    acc.seal(tmp_path / acceptance["measurement_receipt"], authority_path=authority)
    body = json.loads(authority.read_text(encoding="utf-8"))
    body["authority"]["newest_wins"] = True
    authority.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(acc.AcceptanceRefused, match="envelope digest"):
        acc.verify_authority(authority, authority_path=authority)


def test_seal_refuses_preexisting_alternate_acceptance_authority(landed, tmp_path):
    acceptance = landed(_measurement())
    alternate = tmp_path / "receipts" / "sfi3-acceptance--other.json"
    alternate.write_text("{}", encoding="utf-8")
    with pytest.raises(acc.AcceptanceRefused, match="refusing to choose one"):
        acc.seal(
            tmp_path / acceptance["measurement_receipt"],
            authority_path=tmp_path / "receipts" / acc.AUTHORITY_NAME,
        )
