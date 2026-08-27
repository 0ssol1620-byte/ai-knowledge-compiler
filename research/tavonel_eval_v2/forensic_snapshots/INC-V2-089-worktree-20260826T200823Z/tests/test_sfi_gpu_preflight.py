"""Tests for `tools/gpu_successor_preflight.py` and `paper/SOURCE_FACT_IR_PAPER_SECTION.md`.

No network, no GPU. The preflight is CPU-only by design and these tests hold
it to that: every check here either exercises pure functions with in-memory
fixtures or reads files already on disk.

Six things this file guards, matching the six requirements the tool was built
against:

1. the central gate refuses "ready" unless BOTH acceptance receipts are named
   explicitly and both verify -- the fresh held-out SFI3 study, and the
   four-link chain over the exact cohort about to run
2. the cost-cap arithmetic refuses an over-cap configuration
3. the closed exact-value VBC endpoint cannot be selected by this design
4. capability is never inferred from a bare model name
5. the claim rows proposed in the paper section parse as YAML and satisfy
   `build_claim_matrix.py`'s own required fields and declared splits
6. no sentence in the paper section asserts an unproven positive without a
   provisional marker
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS / "source_fact_ir"))

import gpu_authorization_fixtures as fixtures  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import ir  # noqa: E402
import sfi3_acceptance as acc  # noqa: E402

PAPER_SECTION = NS / "paper" / "SOURCE_FACT_IR_PAPER_SECTION.md"


# ---------------------------------------------------------------------------
# 1. the central gate - two explicit acceptances, no stem, no search
# ---------------------------------------------------------------------------
#
# The gate this replaces searched `sfi2-native-provenance--*.json` for a body
# declaring `split == "held_out"` and `verdict == "PASS"`. That search could
# never succeed: SFI2 is frozen, FAIL, spent and permanently non-rescorable. It
# was not replaced with a search under an SFI3 stem -- an authority that can be
# searched for is an authority that can be found by accident -- so every test
# below names the receipt it is gating on.


def test_the_retired_stem_lookup_is_gone_and_says_why():
    """The old entry point cannot be called back into existence by accident."""
    assert not hasattr(gsp, "held_out_pass_receipt")
    assert not hasattr(gsp, "HELD_OUT_STUDY_STEM")
    assert gsp.RETIRED_HELD_OUT_STUDY_STEM == ""
    assert "sfi2-native-provenance" in gsp.RETIRED_HELD_OUT_STUDY_REASON


def test_an_unnamed_sfi3_acceptance_is_a_hard_block():
    """Absence is a block, not a reason to go looking."""
    result = gsp.sfi3_acceptance_gate(None)
    assert result["passed"] is False
    assert result["receipt"] is None
    assert "one explicit immutable path" in result["why"]


def test_an_unnamed_four_link_acceptance_is_a_hard_block():
    result = gsp.four_link_acceptance_gate(None)
    assert result["passed"] is False
    assert result["receipt"] is None


def test_a_named_acceptance_that_is_not_on_disk_is_refused(tmp_path):
    result = gsp.sfi3_acceptance_gate(tmp_path / "never-written.json")
    assert result["passed"] is False
    assert "not on disk" in result["why"]


def test_an_unreadable_acceptance_is_refused_rather_than_crashing(tmp_path, monkeypatch):
    path = tmp_path / "acceptance.json"
    monkeypatch.setattr(acc, "AUTHORITY_PATH", path)
    path.write_text("{ not json", encoding="utf-8")
    result = gsp.sfi3_acceptance_gate(path)
    assert result["passed"] is False
    assert "could not be read" in result["why"]


def test_a_genuine_sfi3_acceptance_passes_the_gate(tmp_path, monkeypatch):
    path = fixtures.land_sfi3_acceptance(tmp_path, monkeypatch)
    result = gsp.sfi3_acceptance_gate(path)
    assert result["passed"] is True
    assert result["receipt_sha256"].startswith("sha256:")
    assert result["body"]["held"] is True


def test_an_sfi3_acceptance_over_a_failing_measurement_is_refused(tmp_path, monkeypatch):
    path = fixtures.land_sfi3_acceptance(tmp_path, monkeypatch, verdict="FAIL")
    result = gsp.sfi3_acceptance_gate(path)
    assert result["passed"] is False


def test_the_preflight_delegates_and_does_not_restate_sfi3_arithmetic():
    """One implementation of the acceptance rule, not two.

    A second copy here could pass while `sfi3_acceptance` refused, and the
    receipt would look identical either way.
    """
    source = (NS / "tools" / "gpu_successor_preflight.py").read_text(encoding="utf-8")
    for endpoint in ("E1_", "E7_", "E8_", "E9_"):
        assert endpoint not in source, f"{endpoint} arithmetic re-implemented in the preflight"
    assert "VETO_CLEAR_NO_POSITIVE_CREDIT" not in source


def test_a_four_link_acceptance_bound_to_another_manifest_is_refused(tmp_path, monkeypatch):
    """A green receipt over a different manifest authorizes nothing about this one."""
    _manifest, path = fixtures.land_four_link_acceptance(tmp_path, monkeypatch)
    assert gsp.four_link_acceptance_gate(path)["passed"] is True
    refused = gsp.four_link_acceptance_gate(
        path, launch_manifest_sha256="sha256:" + "0" * 64
    )
    assert refused["passed"] is False


def test_run_reports_blocked_when_neither_acceptance_is_named(tmp_path):
    """The end-to-end preflight, with no acceptance named anywhere."""
    body = gsp.run(
        manifest=tmp_path / "no-such-manifest.json",
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert body["verdict"] == "BLOCKED"
    for gate_name in ("G_GSP_SFI3_ACCEPTANCE_PASS", "G_GSP_FOUR_LINK_ACCEPTANCE_PASS"):
        assert gate_name in body["blocking_gates"]
        assert body["gates"][gate_name]["passed"] is False
        assert body["gates"][gate_name]["detail"]["receipt"] is None


def _wired_model_pin() -> dict[str, str]:
    return {
        "repository": "Qwen/Qwen3.6-27B",
        "revision": "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9",
        "tokenizer_file_sha256": "sha256:" + "a" * 64,
        "capability_evidence": "research/experiments/H1-W6.../receipts/v8-model-attestation.json",
    }


def _wired_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "cohort.json"
    facts = [
        {
            "fact_id": f"fact-{index}",
            "kind": gsp.ELIGIBLE_KINDS[index % len(gsp.ELIGIBLE_KINDS)],
            "state": ir.REPRESENTED,
            "representation": {"target": f"unit-{index}"},
            "witness": {"excerpt": "some prose that never names the target"},
        }
        for index in range(gsp.COHORT_FLOOR)
    ]
    manifest.write_text(json.dumps({"facts": facts}), encoding="utf-8")
    return manifest


def test_ready_verdict_requires_both_acceptances_even_when_all_else_is_wired(tmp_path):
    """Every other gate can pass and the verdict still refuses to say ready."""
    body = gsp.run(
        manifest=_wired_manifest(tmp_path),
        model_pin=_wired_model_pin(),
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert body["gates"]["G_GSP_MODEL_PINNED"]["passed"] is True
    assert body["gates"]["G_GSP_COHORT_FEASIBILITY"]["passed"] is True
    assert body["gates"]["G_GSP_SFI3_ACCEPTANCE_PASS"]["passed"] is False
    assert body["gates"]["G_GSP_FOUR_LINK_ACCEPTANCE_PASS"]["passed"] is False
    assert body["verdict"] == "BLOCKED"
    assert {
        "G_GSP_FOUR_LINK_ACCEPTANCE_PASS",
        "G_GSP_SFI3_ACCEPTANCE_PASS",
        "G_GSP_PROTOCOL_BUNDLE_FROZEN",
        "G_GSP_MODEL_PIN_SOURCE_SEALED",
    }.issubset(body["blocking_gates"])


def test_neither_acceptance_substitutes_for_the_other(tmp_path, monkeypatch):
    """An SFI3 PASS alone does not authorize, and a four-link PASS alone does not."""
    sfi3 = fixtures.land_sfi3_acceptance(tmp_path, monkeypatch)
    manifest, four_link = fixtures.land_four_link_acceptance(tmp_path, monkeypatch)

    only_sfi3 = gsp.run(
        manifest=_wired_manifest(tmp_path),
        model_pin=_wired_model_pin(),
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
        sfi3_acceptance_receipt=sfi3,
    )
    assert only_sfi3["gates"]["G_GSP_SFI3_ACCEPTANCE_PASS"]["passed"] is True
    assert "G_GSP_FOUR_LINK_ACCEPTANCE_PASS" in only_sfi3["blocking_gates"]
    assert "G_GSP_PROTOCOL_BUNDLE_FROZEN" in only_sfi3["blocking_gates"]
    assert "G_GSP_MODEL_PIN_SOURCE_SEALED" in only_sfi3["blocking_gates"]

    only_four_link = gsp.run(
        manifest=manifest,
        model_pin=_wired_model_pin(),
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
        four_link_acceptance_receipt=four_link,
    )
    assert only_four_link["gates"]["G_GSP_FOUR_LINK_ACCEPTANCE_PASS"]["passed"] is True
    assert "G_GSP_SFI3_ACCEPTANCE_PASS" in only_four_link["blocking_gates"]


# ---------------------------------------------------------------------------
# 1b. the six bound inputs the preflight records and the launcher re-reads


def test_the_declaration_domain_is_exactly_six_names_by_set_equality():
    digests = gsp.declaration_digests()
    assert set(digests) == set(gsp.DECLARATION_KEYS)
    assert len(gsp.DECLARATION_KEYS) == 6


def test_an_unnamed_bound_input_is_recorded_as_absent_not_skipped():
    """Absent and unread are different states; only one is a reason to stop."""
    digests = gsp.declaration_digests()
    assert digests["manifest"] == {"path": None, "sha256": gsp.ABSENT}
    assert digests["study"]["sha256"].startswith("sha256:")


def test_a_named_bound_input_is_recorded_by_digest(tmp_path, monkeypatch):
    sfi3 = fixtures.land_sfi3_acceptance(tmp_path, monkeypatch)
    digests = gsp.declaration_digests(sfi3_acceptance=sfi3)
    assert digests["sfi3_acceptance"]["sha256"] == gsp.sha_file(sfi3)


def test_the_run_body_records_every_bound_input_it_decided_against(tmp_path, monkeypatch):
    sfi3 = fixtures.land_sfi3_acceptance(tmp_path, monkeypatch)
    manifest, four_link = fixtures.land_four_link_acceptance(tmp_path, monkeypatch)
    body = gsp.run(
        manifest=manifest,
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
        sfi3_acceptance_receipt=sfi3,
        four_link_acceptance_receipt=four_link,
    )
    declarations = body["declarations"]
    assert set(declarations) == set(gsp.DECLARATION_KEYS)
    assert declarations["manifest"]["sha256"] == gsp.sha_file(manifest)
    assert declarations["sfi3_acceptance"]["sha256"] == gsp.sha_file(sfi3)
    assert declarations["four_link_acceptance"]["sha256"] == gsp.sha_file(four_link)


# ---------------------------------------------------------------------------
# 2. cost-cap arithmetic refuses an over-cap configuration
# ---------------------------------------------------------------------------


def test_cost_estimate_shows_its_arithmetic():
    estimate = gsp.estimate_cost(cohort_size=gsp.COHORT_FLOOR)
    assert estimate["within_cap"] is True
    assert "x" in estimate["arithmetic"]["total_calls"]
    assert str(gsp.COHORT_FLOOR) in estimate["arithmetic"]["total_calls"]


def test_cost_cap_refuses_a_configuration_that_exceeds_the_hour_cap():
    huge_cohort = 1_000_000
    estimate = gsp.estimate_cost(cohort_size=huge_cohort)
    assert estimate["estimated_gpu_hours"] > gsp.CAP_GPU_HOURS
    assert estimate["within_hours_cap"] is False
    assert estimate["within_cap"] is False


def test_cost_cap_refuses_a_configuration_that_exceeds_the_dollar_cap_alone():
    """A configuration can blow the dollar cap without blowing the hour cap."""
    estimate = gsp.estimate_cost(
        cohort_size=gsp.COHORT_FLOOR,
        gpu_hourly_rate_usd=10_000.0,
    )
    assert estimate["within_hours_cap"] is True
    assert estimate["within_usd_cap"] is False
    assert estimate["within_cap"] is False


def test_declared_design_parameters_fit_under_the_approved_cap():
    """The design this tool actually declares must not be self-refuting."""
    estimate = gsp.estimate_cost(cohort_size=gsp.COHORT_FLOOR)
    assert estimate["within_cap"] is True
    assert estimate["cap_gpu_hours"] == pytest.approx(6.0)
    assert estimate["cap_usd"] == pytest.approx(40.0)


def test_the_preflight_itself_declares_zero_gpu_cost():
    """The preflight is CPU-only; its own receipt must say so unconditionally."""
    body = gsp.run(
        manifest=NS / "definitely-does-not-exist" / "manifest.json",
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
    assert body["gates"]["G_GSP_NO_GPU_YET"]["passed"] is True


# ---------------------------------------------------------------------------
# 3. the closed exact-value VBC endpoint cannot be selected
# ---------------------------------------------------------------------------


def test_design_excludes_the_closed_endpoint_identifier():
    exclusion = gsp.design_excludes_closed_endpoint()
    assert exclusion["clean"] is True
    assert gsp.STUDY_ID != gsp.FORBIDDEN_ENDPOINT_ID
    assert exclusion["forbidden_endpoint_id"] == "MODEL_ENDPOINT_V1"
    assert exclusion["forbidden_stop_record"] == "STOP-V2-005"


def test_design_scorer_classes_do_not_reuse_the_closed_endpoints_scorer():
    """Import the real closed scorer's classes rather than trusting our copy."""
    sys.path.insert(0, str(NS / "endpoint"))
    import value_scorer

    assert set(gsp.FORBIDDEN_SCORER_CLASSES) == set(value_scorer.CLASSES)
    overlap = set(gsp.SCORER_CLASSES) & set(value_scorer.CLASSES)
    assert overlap == set()


def test_design_does_not_require_a_value_transition_between_revisions():
    """This is the structural property that made the closed cohort scarce."""
    assert gsp.REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS is False
    exclusion = gsp.design_excludes_closed_endpoint()
    assert exclusion["requires_value_transition_between_revisions"] is False


def test_eligible_kinds_are_drawn_from_the_ir_not_from_value_markers():
    """The successor's questions come from SOURCE_FACT_IR kinds, never from
    the closed endpoint's numeric/date/currency value-marker vocabulary."""
    assert set(gsp.ELIGIBLE_KINDS).issubset(set(ir.KINDS))
    for kind in gsp.ELIGIBLE_KINDS:
        assert kind in {ir.REFERENCE_TARGET, ir.LANGUAGE, ir.EFFECTIVE_TIME, ir.APPLICABILITY}


def test_a_design_that_reintroduces_the_forbidden_study_id_is_caught():
    """The exclusion check must actually be able to fail, not just always pass."""
    original = gsp.STUDY_ID
    try:
        gsp.STUDY_ID = gsp.FORBIDDEN_ENDPOINT_ID
        exclusion = gsp.design_excludes_closed_endpoint()
        assert exclusion["clean"] is False
        assert exclusion["is_forbidden_endpoint"] is True
    finally:
        gsp.STUDY_ID = original


# ---------------------------------------------------------------------------
# 4. capability is never inferred from a model name
# ---------------------------------------------------------------------------


def test_capability_not_claimed_from_a_bare_name():
    result = gsp.capability_from_registry({"repository": "SomeVendor/BigImpressiveModel-9000"})
    assert result["capability_claimed"] is False
    assert "not inferred" in result["reason"] or "no" in result["reason"]


def test_capability_not_claimed_when_evidence_equals_the_name_itself():
    """A caller cannot launder a name into 'evidence' by repeating it."""
    result = gsp.capability_from_registry(
        {"repository": "Vendor/Model", "capability_evidence": "Vendor/Model"}
    )
    assert result["capability_claimed"] is False


def test_capability_claimed_only_with_distinct_pinned_evidence():
    result = gsp.capability_from_registry(
        {
            "repository": "Qwen/Qwen3.6-27B",
            "capability_evidence": (
                "research/experiments/H1-W6-SAME-INTELLIGENCE-01/"
                "receipts/v8-model-attestation.json"
            ),
        }
    )
    assert result["capability_claimed"] is True
    assert result["inferred_from_name"] is False


def test_model_identity_pin_gate_fails_closed_with_no_pin_supplied():
    identity = gsp.model_identity_pin({})
    assert identity["pinned_by_exact_revision"] is False
    assert identity["capability"]["capability_claimed"] is False


def test_model_identity_pin_rejects_a_floating_latest_revision():
    identity = gsp.model_identity_pin(
        {
            "repository": "Qwen/Qwen3.6-27B",
            "revision": "latest",
            "tokenizer_file_sha256": "sha256:" + "a" * 64,
        }
    )
    assert identity["pinned_by_exact_revision"] is False
    assert identity["not_resolved_to_latest"] is False


# ---------------------------------------------------------------------------
# 5. proposed claim rows parse as YAML and satisfy build_claim_matrix.py
# ---------------------------------------------------------------------------


def _extract_proposed_rows() -> list[dict]:
    text = PAPER_SECTION.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)\n```", text, re.S)
    assert blocks, "no fenced yaml block found in the paper section"
    rows: list[dict] = []
    for block in blocks:
        parsed = yaml.safe_load(block)
        assert "claims" in parsed, "the fenced yaml block must be a claims mapping"
        rows.extend(parsed["claims"])
    return rows


def test_proposed_rows_parse_and_are_nonempty():
    rows = _extract_proposed_rows()
    assert len(rows) >= 1


def test_proposed_rows_carry_every_field_build_claim_matrix_requires():
    import build_claim_matrix as matrix

    rows = _extract_proposed_rows()
    for row in rows:
        missing = [field for field in matrix.REQUIRED if field not in row]
        assert not missing, f"{row.get('id')} missing {missing}"


def test_proposed_rows_declare_a_split_matrix_recognises():
    import build_claim_matrix as matrix

    rows = _extract_proposed_rows()
    for row in rows:
        assert row["split"] in matrix.SPLITS, f"{row['id']} has undeclared split {row['split']!r}"
        assert row["split"] == "held_out"


def test_proposed_rows_use_the_pending_receipt_established_status_pairing():
    """build_claim_matrix.py requires exactly this pairing for anything unproven."""
    import build_claim_matrix as matrix

    rows = _extract_proposed_rows()
    for row in rows:
        assert row["receipt"] == matrix.PENDING
        assert row["status"] == "NOT_YET_ESTABLISHED"


def test_proposed_rows_wording_contains_no_forbidden_phrase():
    matrix_body = yaml.safe_load((NS / "paper" / "CLAIM_MATRIX.yaml").read_text(encoding="utf-8"))
    forbidden = [
        (entry["id"], phrase)
        for entry in matrix_body["forbidden_claims"]
        for phrase in entry["phrases"]
    ]
    rows = _extract_proposed_rows()
    for row in rows:
        lowered = str(row["wording"]).casefold()
        hits = [(fid, phrase) for fid, phrase in forbidden if phrase.casefold() in lowered]
        assert not hits, f"{row['id']} wording contains forbidden phrase(s): {hits}"


def test_proposed_rows_ids_do_not_collide_with_existing_matrix_claims():
    matrix_body = yaml.safe_load((NS / "paper" / "CLAIM_MATRIX.yaml").read_text(encoding="utf-8"))
    existing_ids = {claim["id"] for claim in matrix_body["claims"]}
    rows = _extract_proposed_rows()
    for row in rows:
        #: A proposed row that now appears in the matrix has been ADOPTED, which
        #: is the outcome the proposal exists to reach. What must never happen is
        #: an id reused for a different claim, so the check is on what the id is
        #: bound to rather than on the id's absence.
        if row["id"] in existing_ids:
            adopted = next(c for c in matrix_body["claims"] if c["id"] == row["id"])
            assert adopted["protocol"] == row["protocol"], (
                f"{row['id']} exists in CLAIM_MATRIX.yaml bound to a different "
                f"protocol ({adopted['protocol']} vs {row['protocol']})"
            )


# ---------------------------------------------------------------------------
# 6. no unproven positive assertion without a provisional marker
# ---------------------------------------------------------------------------

#: Phrases that would assert SOURCE_FACT_IR's own held-out result — a thing
#: this section is explicit does not exist yet. Any prose sentence naming
#: SOURCE_FACT_IR alongside one of these, outside a fenced code block, must sit
#: in a paragraph that also carries a provisional marker.
_COMPLETION_TRIGGERS = (
    "the repair passed",
    "sfh1 passed",
    "sfh1 was repeated and passed",
    "is source-faithful",
    "resolves the failure",
    "confirms the repair",
    "proves the repair",
    "the repair works",
    "establishes source faithfulness",
    "source_fact_ir passed",
    "source_fact_ir is proven",
    "source_fact_ir holds",
)


def _prose_paragraphs(text: str) -> list[str]:
    """Paragraphs with fenced code blocks removed, since the proposed YAML
    rows are explicitly NOT_YET_ESTABLISHED / PENDING and are not prose
    assertions."""
    without_code = re.sub(r"```.*?```", "", text, flags=re.S)
    return [block for block in without_code.split("\n\n") if block.strip()]


def test_no_completion_trigger_phrase_appears_at_all():
    """The strongest form of the guard: these phrases should not appear in the
    prose in the first place, marker or not — the section is written to avoid
    the sentence shape entirely rather than to hedge it."""
    text = PAPER_SECTION.read_text(encoding="utf-8")
    for paragraph in _prose_paragraphs(text):
        lowered = paragraph.casefold()
        for trigger in _COMPLETION_TRIGGERS:
            assert trigger not in lowered, (
                f"unmarked completion claim {trigger!r} found in paragraph: {paragraph[:200]!r}"
            )


def test_checker_actually_catches_a_bad_sentence():
    """Prove the check above is not vacuous by running it against a fixture
    that should fail it."""
    bad_text = (
        "Some heading\n\n"
        "SOURCE_FACT_IR is source-faithful on the fresh corpus and the repair "
        "passed cleanly.\n\n"
        "A second, unrelated paragraph.\n"
    )
    paragraphs = _prose_paragraphs(bad_text)
    caught = any(
        trigger in paragraph.casefold()
        for paragraph in paragraphs
        for trigger in _COMPLETION_TRIGGERS
    )
    assert caught, "the checker failed to catch a deliberately bad sentence"


def test_provisional_marker_is_actually_present_and_precedes_forward_looking_claims():
    text = PAPER_SECTION.read_text(encoding="utf-8")
    assert text.count("PROVISIONAL") >= 2, (
        "the provisional marker should guard more than one place — the section "
        "opening and the forward-looking section about a fresh held-out run"
    )
    # the marker must appear before the section describing what a fresh run
    # would have to show, not after it
    forward_looking = text.index("What a fresh held-out run would have to show")
    nearest_marker_before = text.rfind("PROVISIONAL", 0, forward_looking + 400)
    assert nearest_marker_before != -1
    assert nearest_marker_before < forward_looking + 400


def test_paper_section_states_sfh1_and_oracle_v2_are_not_source_fact_irs_own_result():
    """The section must not let SFH1's or ORACLE_INDEPENDENCE_V2's status
    quietly stand in for a result about SOURCE_FACT_IR itself."""
    text = " ".join(PAPER_SECTION.read_text(encoding="utf-8").casefold().split())
    assert "may not reuse sfh1 to claim its repair passed" in text
    assert "there is no positive held-out result behind source_fact_ir today" in text


def test_paper_section_declares_ip_gate_closed_and_internal_only():
    text = PAPER_SECTION.read_text(encoding="utf-8")
    assert "INTERNAL DRAFT" in text
    assert "IP gate CLOSED" in text
    assert "No arXiv" in text
