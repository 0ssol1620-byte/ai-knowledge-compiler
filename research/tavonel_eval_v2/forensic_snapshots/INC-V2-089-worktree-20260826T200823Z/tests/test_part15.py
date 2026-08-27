"""Route A closure and the Paper Closure Program: A, B and C.

These tests are about the properties that are easy to lose quietly:

* a stopping record that says what was stopped and what was not refitted;
* a diagnostic that stays a diagnostic;
* an instrument whose failure state is reachable, so its gate is not vacuous;
* an oracle that cannot reach the implementation it audits, checked from the
  syntax tree rather than from a guard someone could delete;
* a claim matrix that refuses a claim rather than decorating one.

Nothing here runs a network fetch, a model, or a GPU.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

for _sub in ("tools", "acquisition", "canonicalization", "endpoint", "compiler"):
    sys.path.insert(0, str(NS / _sub))

LEDGER = NS / "incident_ledger.md"
RECEIPTS = NS / "receipts"
PROTOCOLS = NS / "protocols"
PAPER = NS / "paper"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _newest(stem: str) -> dict[str, Any]:
    paths = sorted(RECEIPTS.glob(stem + "--*.json"))
    assert paths, "no receipt for " + stem
    return json.loads(_text(paths[-1]))


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


# --- Route A closure ------------------------------------------------------------


def test_the_stopping_record_carries_the_label_the_founder_named() -> None:
    ledger = _text(LEDGER)
    assert (
        "EXACT_VALUE_MODEL_ENDPOINT_NOT_FEASIBLE_UNDER_DECLARED_PUBLIC_SOURCE_FRAME"
        in ledger
    )
    receipt = _newest("route-a-closure")
    assert receipt["label"] == (
        "EXACT_VALUE_MODEL_ENDPOINT_NOT_FEASIBLE_UNDER_DECLARED_PUBLIC_SOURCE_FRAME"
    )
    assert receipt["founder_label"] == "STOP-V2-004"


def test_the_identifier_collision_is_explained_rather_than_resolved_by_overwriting() -> None:
    """STOP-V2-004 was taken. An append-only ledger cannot reuse it."""
    ledger = _text(LEDGER)
    assert "STOP-V2-004 — P4d-Core-Semantic FAIL" in ledger
    assert "STOP-V2-005 — EXACT_VALUE_MODEL_ENDPOINT" in ledger
    receipt = _newest("route-a-closure")
    assert "append-only" in receipt["identifier_note"]


def test_the_model_experiment_is_not_run_and_not_failed() -> None:
    receipt = _newest("route-a-closure")
    assert receipt["model_experiment_status"].startswith("NOT_RUN")
    assert "PREDEFINED CPU PREFLIGHT INFEASIBLE" in receipt["model_experiment_status"]
    assert "NOT_RUN — PREDEFINED CPU PREFLIGHT INFEASIBLE" in _text(LEDGER)


def test_the_gpu_authorisation_is_terminated_and_does_not_carry_forward() -> None:
    authorisation = _newest("route-a-closure")["gpu_authorisation"]
    assert authorisation["state"] == "TERMINATED_FOR_THIS_RESEARCH_CYCLE"
    assert authorisation["seconds_used"] == 0
    assert authorisation["spend_usd"] == 0.0
    assert "separate founder approval" in authorisation["reinstatement"]


def test_the_frozen_vbc2_contract_is_pinned_by_digest_so_a_later_edit_is_visible() -> None:
    """The ruling forbids refitting these to the result. Pinning makes an edit visible."""
    unchanged = _newest("route-a-closure")["unchanged_frozen_contract"]
    for name in (
        "twelve_revision_bound",
        "history_horizon_1460_days",
        "source_families_and_weighting",
        "value_scorer",
        "value_fact_taxonomy_and_extractor",
        "cohort_floor_190",
    ):
        entry = unchanged[name]
        assert _sha(ROOT / entry["path"]) == entry["sha256"], name


def test_no_successor_cohort_was_created_to_chase_the_floor() -> None:
    assert not list(PROTOCOLS.glob("VALUE_BEARING_COHORT_V3*"))
    assert "No successor cohort is created to chase 190" in _text(LEDGER)


def test_inc_v2_023_is_a_post_acquisition_diagnostic_not_a_confirmatory_result() -> None:
    disposition = _newest("route-a-closure")["inc_v2_023_disposition"]
    assert disposition["class"] == "POST_ACQUISITION_DIAGNOSTIC"
    assert disposition["is_confirmatory_result"] is False
    assert disposition["repair_is_valid_forward"] is True
    assert disposition["effect_on_primary_stop_verdict"] == "none"
    assert "3 < 190" in disposition["why_none"]

    ledger = _text(LEDGER)
    assert "INC-V2-024" in ledger
    assert "must\nnot be called a confirmatory result" in ledger or (
        "must" in ledger and "not be called a confirmatory result" in ledger
    )


def test_the_three_failures_are_recorded_as_narrowing_not_repeating() -> None:
    failures = _newest("route-a-closure")["three_failures"]
    assert [row["protocol"] for row in failures] == [
        "MODEL_ENDPOINT_V1",
        "VALUE_BEARING_COHORT_V1",
        "VALUE_BEARING_COHORT_V2",
    ]
    assert [row["survivors"] for row in failures] == [10, 0, 3]
    assert len({row["finding"] for row in failures}) == 3


# --- Workstream A: source front-end faithfulness ---------------------------------

SFH1 = PROTOCOLS / "SOURCE_FAITHFULNESS_HELDOUT_V1.yaml"


@pytest.fixture(scope="module")
def sfh1() -> Any:
    import yaml  # noqa: PLC0415

    return yaml.safe_load(_text(SFH1))


def test_the_faithfulness_protocol_is_held_out_and_frozen_before_its_data(sfh1: Any) -> None:
    assert sfh1["split"] == "held_out"
    assert "Frozen before any held-out pair" in _text(SFH1)
    assert sfh1["boundaries"]["gpu"]["approved"] is False
    assert sfh1["boundaries"]["model_calls"]["approved"] is False


def test_exactly_three_states_and_nothing_falls_through(sfh1: Any) -> None:
    states = sfh1["classification"]["states"]
    assert set(states) == {
        "MODELED",
        "IGNORED_BY_PREDECLARED_POLICY",
        "UNRESOLVED_SOURCE_FACT",
    }
    assert "hard failure" in sfh1["classification"]["exactly_one"]


def test_the_four_to_three_collapse_is_toward_fail_closed_and_never_toward_ignored(
    sfh1: Any,
) -> None:
    from changed_regions import IGNORED, POLICY_TO_STATE, UNRESOLVED  # noqa: PLC0415
    from markup_policy import UNMODELED  # noqa: PLC0415

    assert POLICY_TO_STATE[UNMODELED] == UNRESOLVED
    assert IGNORED not in {POLICY_TO_STATE[UNMODELED]}
    assert "forbidden" in sfh1["classification"]["four_to_three"]


def test_the_unsupported_grammar_is_declared_in_advance(sfh1: Any) -> None:
    unsupported = " ".join(sfh1["grammar"]["not_supported"]["constructs"]).casefold()
    for construct in ("javascript", "css", "pdf", "binary"):
        assert construct in unsupported
    assert "NOT removed" in sfh1["grammar"]["not_supported"]["note"]


def test_an_unsupported_construct_is_not_removed_from_the_cohort_after_the_fact(
    sfh1: Any,
) -> None:
    rules = " ".join(sfh1["anti_fitting"]).casefold()
    assert "is not removed from the cohort" in rules
    assert "not extended after seeing a result" in rules
    assert "a fail is reported as a fail" in rules


def test_the_compiled_state_is_what_the_compiler_stores_not_what_the_analysis_extracts(
    sfh1: Any,
) -> None:
    """Counting the analysis layer as part of the model would credit storage that does not exist."""
    definition = sfh1["silent_drop"]["compiled_state"]
    assert "selective_build.py" in definition["is"]
    assert "NOT in the compiled state" in definition["is_not"]

    from changed_regions import FACET_IN_COMPILED_STATE  # noqa: PLC0415
    from markup_policy import (  # noqa: PLC0415
        CONTENT_LEXICAL,
        METADATA,
        REFERENCE_LOCATOR,
    )

    assert FACET_IN_COMPILED_STATE[CONTENT_LEXICAL] is True
    assert FACET_IN_COMPILED_STATE[REFERENCE_LOCATOR] is False
    assert FACET_IN_COMPILED_STATE[METADATA] is False


def test_a_silent_drop_requires_a_scope_the_run_called_complete(sfh1: Any) -> None:
    definition = sfh1["silent_drop"]["definition"]
    assert "locally complete" in definition
    reasons = " ".join(sfh1["silent_drop"]["not_a_silent_drop"]).casefold()
    assert "the loss is declared" in reasons


def test_every_frozen_control_passes_including_both_burned_ones() -> None:
    from changed_region_controls import run_controls  # noqa: PLC0415

    result = run_controls()
    assert result["all_passed"], result["failed"]
    kinds = {row["name"]: row["kind"] for row in result["controls"]}
    assert kinds["burned_reference_target_only"] == "burned_positive"
    assert kinds["burned_short_block_dropped"] == "burned_positive"
    assert kinds["unclassified_is_reachable"] == "reachability"


def test_the_hard_failure_state_is_reachable_so_its_gate_is_not_vacuous() -> None:
    from changed_region_controls import _parse_failure_regions  # noqa: PLC0415
    from changed_regions import UNCLASSIFIED  # noqa: PLC0415

    assert _parse_failure_regions()["by_state"].get(UNCLASSIFIED, 0) >= 1


def test_the_instrument_catches_a_reference_target_that_the_compiled_state_cannot_carry() -> None:
    """INC-V2-006 on a fixture. This is the one failure that must never read clean."""
    from changed_region_controls import _MD_LINK_AFTER, _MD_LINK_BEFORE, _pair  # noqa: PLC0415

    result = _pair(_MD_LINK_BEFORE, _MD_LINK_AFTER, ".md")
    assert result["modeled_claims_unverified"] >= 1
    assert result["compiled_state_changed"] is False
    assert result["unclassified"] == 0


def test_punctuation_only_edits_are_not_reported_as_lost_facts() -> None:
    """An instrument that flags emphasis markers produces a large meaningless number."""
    from changed_region_controls import _MD_EMPH_AFTER, _MD_EMPH_BEFORE, _pair  # noqa: PLC0415

    result = _pair(_MD_EMPH_BEFORE, _MD_EMPH_AFTER, ".md")
    assert result["modeled_claims_unverified"] == 0


def test_a_deletion_is_scored_on_the_revision_it_was_deleted_from() -> None:
    from changed_region_controls import (  # noqa: PLC0415
        _MD_DELETE_AFTER,
        _MD_DELETE_BEFORE,
        _pair,
    )

    result = _pair(_MD_DELETE_BEFORE, _MD_DELETE_AFTER, ".md")
    assert any(row["side"] == "before" for row in result["rows"])


def test_the_sealed_instrument_was_not_edited_to_build_the_new_one() -> None:
    """A new question gets a new module. Editing a sealed one moves an older result."""
    identity = _newest("source-map-contract")["instrument_identity"]
    for name, path in identity["part_files"].items():
        assert _sha(ROOT / path) == identity["parts"][name], name
    for path, digest in identity["superseded_parts_left_untouched"].items():
        assert _sha(ROOT / path) == digest, path


# --- Workstream B: independent oracle --------------------------------------------

OI2 = PROTOCOLS / "ORACLE_INDEPENDENCE_V2.yaml"
ORACLE = NS / "oracle" / "source_derived_expected.py"
COMPARATOR = NS / "comparator" / "compare_recompilation.py"


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(_text(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _load_isolated(path: Path, name: str) -> Any:
    """Load a guarded module without letting its guard escape into this process.

    Both the oracle and the comparator install a meta-path finder at import time.
    That is the guard doing exactly its job; it also means importing either one
    here would refuse every later `common` import in the whole test session. The
    guard is snapshotted out again, so it protects its own module and nothing
    else.
    """
    import importlib.util  # noqa: PLC0415

    before = list(sys.meta_path)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.meta_path[:] = before


ENGINE_MODULES = {
    "akc_cir",
    "selective_build",
    "canonical_document",
    "changed_regions",
    "source_map",
    "source_map_v2",
    "markup_policy",
    "markup_semantics",
    "common",
    "evidence",
    "coverage_witness",
    "coverage_witness_v2",
}


def test_the_oracle_cannot_reach_the_engine_from_its_syntax_tree() -> None:
    """A runtime guard proves one run. The import graph proves what the file can ever do."""
    assert not (_imported_roots(ORACLE) & ENGINE_MODULES)


def test_the_comparator_cannot_reach_either_side_from_its_syntax_tree() -> None:
    reachable = _imported_roots(COMPARATOR)
    assert not (reachable & ENGINE_MODULES)
    assert "source_derived_expected" not in reachable


def test_the_oracle_starts_at_raw_bytes_and_never_at_a_canonical_document() -> None:
    """The v1 oracle consumed engine output; that is the whole defect being fixed."""
    source = _text(ORACLE)
    assert "after_payload_b64" in source
    assert "canonical_document" not in _imported_roots(ORACLE)


def test_neither_side_hashes_the_comparison() -> None:
    """Whichever side hashes becomes the standard, and the point is that neither is."""
    module = _load_isolated(COMPARATOR, "compare_recompilation_test")

    engine = {
        "portable_state": {"section:a": {"path": "a", "text": "one"}},
        "portable_carried_forward": ["section:a"],
        "structural_change_present": False,
        "detected_change_kinds": [],
    }
    oracle = {
        "judgeable": True,
        "expected_state": {"section:a": {"path": "a", "text": "two"}},
        "must_change": ["section:a"],
        "change_type": {"label": "lexical_only"},
    }
    result = module.compare(engine, oracle)
    assert result["verdict"] == "DIVERGENT"
    assert result["stale_escape_count"] == 1
    assert result["comparator_state_digest"]["engine"].startswith("sha256:")


def test_an_unjudgeable_pair_is_never_counted_as_a_pass() -> None:
    module = _load_isolated(COMPARATOR, "compare_recompilation_pass")

    result = module.compare({}, {"judgeable": False, "unresolved": ["READER_FAILED"]})
    assert result["verdict"] == "UNJUDGED"
    assert result["equivalent"] is None


def test_the_protocol_states_what_independence_it_does_not_achieve() -> None:
    import yaml  # noqa: PLC0415

    body = yaml.safe_load(_text(OI2))
    missing = body["independence"]["not_achieved"]
    assert "independent IMPLEMENTATION" in missing["specification_is_shared"]
    assert "common-mode" in missing["specification_is_shared"]


def test_the_28_pair_result_is_not_restated_as_an_independent_oracle() -> None:
    text = _text(OI2)
    assert "is NOT an independent-oracle result" in text
    assert "same-implementation full recomputation equivalence" in text
    body = __import__("yaml").safe_load(text)
    assert "independent oracle" in " ".join(body["anti_fitting"])


def test_the_oracle_cohort_is_a_declared_slice_and_not_a_chosen_one() -> None:
    import yaml  # noqa: PLC0415

    body = yaml.safe_load(_text(OI2))
    assert body["cohort"]["salt"] == ":oracle-v2"
    assert "fixed before any payload is read" in body["cohort"]["order"]
    assert "not chosen after seeing" in body["cohort"]["salt_why"]


def test_the_oracle_derives_units_from_bytes_with_its_own_reader() -> None:
    """A smoke test of the oracle in isolation, without the driver."""
    module = _load_isolated(ORACLE, "source_derived_test")

    filler = "word " * 60
    units = module.units_from_blocks(
        module.blocks_from_markdown("# Title\n\n" + filler + "\n")
    )
    assert len(units) == 1
    assert units[0]["explicit_path"] == ["Title"]
    state = module.portable_state("doc", units)
    assert "structure-map" in state and "document-index" in state


# --- Workstream C: claim matrix ---------------------------------------------------

MATRIX = PAPER / "CLAIM_MATRIX.yaml"
DRAFT = PAPER / "TAVONEL_PAPER_DRAFT_INTERNAL.md"


@pytest.fixture(scope="module")
def matrix() -> Any:
    import yaml  # noqa: PLC0415

    return yaml.safe_load(_text(MATRIX))


def test_every_claim_carries_wording_evidence_split_and_both_wording_lists(
    matrix: Any,
) -> None:
    for claim in matrix["claims"]:
        for field in (
            "wording",
            "protocol",
            "receipt",
            "split",
            "status",
            "allowed",
            "forbidden",
            "limitations",
        ):
            assert field in claim, (claim.get("id"), field)
        assert claim["split"] in ("development", "development_diagnostic", "held_out")


def test_every_non_pending_claim_binds_to_a_receipt_whose_bytes_still_match(
    matrix: Any,
) -> None:
    pins = json.loads(_text(PAPER / "claim_receipt_pins.json"))
    for claim in matrix["claims"]:
        if claim["receipt"] == "PENDING":
            continue
        path = NS / claim["receipt"]
        assert path.exists(), claim["id"]
        assert pins[claim["id"]] == _sha(path), claim["id"]


def test_the_validator_refuses_a_claim_that_cites_a_receipt_that_moved(matrix: Any) -> None:
    """The pin is only worth having if a mismatch fails."""
    from build_claim_matrix import check_claims  # noqa: PLC0415

    pins = json.loads(_text(PAPER / "claim_receipt_pins.json"))
    tampered = dict(pins)
    tampered["C-01"] = "sha256:" + "0" * 64
    failures = check_claims(matrix, tampered)["failures"]
    assert any(row["claim"] == "C-01" and "moved" in row["why"] for row in failures)


def test_the_validator_refuses_forbidden_wording_inside_a_claim(matrix: Any) -> None:
    from build_claim_matrix import check_claims  # noqa: PLC0415

    import copy  # noqa: PLC0415

    poisoned = copy.deepcopy(matrix)
    poisoned["claims"][0]["wording"] = "The system improves question answering everywhere."
    failures = check_claims(poisoned, {})["failures"]
    assert any("forbidden phrase" in row["why"] for row in failures)


def test_a_pending_row_may_not_carry_an_established_status_or_permitted_wording(
    matrix: Any,
) -> None:
    """The rule, not a fixed list: rows fill in as workstreams land."""
    rows = {claim["id"]: claim for claim in matrix["claims"]}
    assert {"C-16", "C-17"} <= set(rows), "the workstream rows must exist either way"
    for claim in rows.values():
        if claim["receipt"] != "PENDING":
            continue
        assert claim["status"] == "NOT_YET_ESTABLISHED", claim["id"]
        assert claim["allowed"] == [], claim["id"]


def test_a_filled_workstream_row_carries_its_verdict_and_its_caveats(matrix: Any) -> None:
    rows = {claim["id"]: claim for claim in matrix["claims"]}
    for identifier in ("C-16", "C-17"):
        claim = rows[identifier]
        if claim["receipt"] == "PENDING":
            continue
        assert claim["status"] != "NOT_YET_ESTABLISHED"
        assert claim["allowed"], identifier
        assert claim["limitations"], identifier
        assert (NS / claim["receipt"]).exists(), identifier


def test_the_five_forbidden_claims_are_all_declared(matrix: Any) -> None:
    claims = {entry["claim"] for entry in matrix["forbidden_claims"]}
    assert any("source-faithful end-to-end" in claim for claim in claims)
    assert any("all semantic revisions" in claim for claim in claims)
    assert any("forced-continuation" in claim for claim in claims)
    assert any("P3b" in claim for claim in claims)
    assert any("independent oracle" in claim for claim in claims)


def test_the_negative_findings_are_present_and_each_binds_to_a_claim(matrix: Any) -> None:
    known = {claim["id"] for claim in matrix["claims"]}
    findings = {entry["finding"] for entry in matrix["negative_findings"]}
    for entry in matrix["negative_findings"]:
        assert entry["evidence"] in known
    for expected in (
        "full rebuild equivalence is not source faithfulness",
        "canonical atom granularity is not retrieval granularity",
        "surface lexical overlap is not information-provenance leakage",
        "value-bearing structure is not frequently observable value transition",
        "an outcome-independent preflight can correctly stop an expensive experiment",
    ):
        assert expected in findings


def test_the_draft_is_internal_only_and_carries_no_forbidden_phrase(matrix: Any) -> None:
    from build_claim_matrix import scan_draft  # noqa: PLC0415

    text = _text(DRAFT)
    assert "INTERNAL DRAFT — NOT FOR RELEASE" in text
    assert "IP gate CLOSED" in text
    assert scan_draft(matrix)["clean"]


def test_the_release_gate_is_closed_in_the_matrix_itself(matrix: Any) -> None:
    release = matrix["release"]
    assert release["ip_gate"] == "CLOSED"
    for channel in ("public_arxiv", "public_github", "dataset_release", "demo_release"):
        assert release[channel] == "FORBIDDEN"


def test_the_readiness_gaps_name_the_split_and_the_absent_model(matrix: Any) -> None:
    gaps = {entry["id"]: entry["gap"] for entry in matrix["paper_readiness_gaps"]}
    joined = " ".join(gaps.values()).casefold()
    assert "development split" in joined
    assert "no model was run" in joined
    assert "specification" in joined
    assert "calibration" in joined


def test_docs_ip_was_not_modified_by_any_of_this() -> None:
    import subprocess  # noqa: PLC0415

    out = subprocess.run(
        ["git", "status", "--porcelain", "docs/ip"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout.strip() == "", out.stdout


# --- the bisect index is a speed change, not a result change ---------------------


def test_the_span_index_returns_exactly_what_a_linear_scan_returns() -> None:
    """The overlap search was made logarithmic mid-build. That must change nothing.

    A quadratic overlap test stalled the first full run on large documents. The
    fix is a search change, and a search change that quietly drops a span would
    move every count this protocol reports. So the two searches are compared
    directly, over ranges chosen to hit the awkward cases: zero-width, exactly on
    a boundary, spanning many spans, and past the end of the document.
    """
    from changed_regions import _overlaps, index_spans, side_spans  # noqa: PLC0415
    from source_map import LOCATION_VERIFIED  # noqa: PLC0415

    raw = (
        "# Title\n\nSee [one](https://a/x) and [two](https://b/y). "
        + "filler words " * 40
        + "\n\n## Second\n\n"
        + "more filler here " * 40
        + "\n"
    )
    spans, _ = side_spans(raw, ".md", [raw])
    index = index_spans(spans)

    def linear(low: int, high: int) -> list[Any]:
        ceiling = max(high, low + 1)
        return [
            span
            for span in spans
            if span.location_state == LOCATION_VERIFIED
            and span.start is not None
            and span.end is not None
            and span.start < ceiling
            and span.end > low
        ]

    edges = sorted({0, len(raw), len(raw) + 5} | {
        edge
        for span in spans
        if span.start is not None
        for edge in (span.start, span.end)
    })
    probes = [(low, low) for low in edges]
    probes += [(low, low + 1) for low in edges]
    probes += [(edges[index_a], edges[index_b])
               for index_a in range(0, len(edges), 3)
               for index_b in range(index_a, len(edges), 5)]

    for low, high in probes:
        expected = sorted((s.start, s.end, s.kind) for s in linear(low, high))
        found = sorted((s.start, s.end, s.kind) for s in _overlaps(index, low, high))
        assert found == expected, (low, high)


def test_the_payload_bound_is_declared_with_its_basis_and_its_insensitivity() -> None:
    """A bound is only honest if it names what it was chosen on and what it was not."""
    import yaml  # noqa: PLC0415

    import sources_sfh1  # noqa: PLC0415

    body = yaml.safe_load(_text(SFH1))
    bound = body["sampling"]["payload_bound"]
    assert bound["max_payload_bytes"] == sources_sfh1.MAX_PAYLOAD_BYTES == 2_000_000
    assert bound["explicitly_not_basis"] == "observed classification outcome"
    assert "bimodal" in bound["insensitivity"]
    assert "never silently skipped" in bound["reporting"]
    assert "PAYLOAD_TOO_LARGE_TO_CLASSIFY" in sources_sfh1.FAILURE_CODES


def test_the_amended_freeze_names_what_it_amends() -> None:
    freeze = _newest("sfh1-protocol-freeze")
    assert freeze.get("amendment_of") or freeze.get("amend")
    assert freeze["protocol_sha256"] == _sha(SFH1)


# --- the two held-out verdicts, as executed --------------------------------------


def test_the_faithfulness_run_covered_every_changed_region_and_still_failed() -> None:
    """The half that passed is what makes the half that failed readable."""
    receipt = _newest("sfh1-source-faithfulness")
    summary = receipt["summary"]
    assert receipt["verdict"] == "FAIL"
    assert receipt["gates"]["G_SFH1_NO_UNCLASSIFIED"] is True
    assert summary["unclassified_changed_regions"] == 0
    assert summary["pairs_scored"] >= 200
    assert len(summary["families"]) == 4
    assert receipt["gpu_seconds"] == 0


def test_the_silent_drop_gate_had_power_when_it_failed() -> None:
    """A safety endpoint that was never exercised has not been met, only skipped."""
    receipt = _newest("sfh1-source-faithfulness")
    power = receipt["gate_power"]
    assert power["silent_drop_gate_exercised"] is True
    assert power["scopes_declared_complete"] > 0
    assert receipt["gates"]["G_SFH1_NO_SILENT_DROP"] is False


def test_the_payload_bound_exclusions_are_reported_not_dropped() -> None:
    receipt = _newest("sfh1-source-faithfulness")
    assert "PAYLOAD_TOO_LARGE_TO_CLASSIFY" in receipt["rejected_by_code"]
    bound = receipt["payload_bound"]
    assert bound["max_payload_bytes"] == 2_000_000
    assert bound["explicitly_not_basis"] == "observed classification outcome"


def test_the_oracle_ran_isolated_in_every_judged_pair() -> None:
    receipt = _newest("oracle-independence-v2")
    isolation = receipt["isolation"]
    assert isolation["oracle_graph"]["clean"] is True
    assert isolation["oracle_runtime_clean"] is True
    assert isolation["oracle_runs_isolated"] is True
    assert isolation["comparator_graph"]["clean"] is True
    assert isolation["comparator_runtime_clean"] is True
    assert receipt["gates"]["G_OI2_ORACLE_ISOLATED"] is True
    assert receipt["gates"]["G_OI2_COMPARATOR_ISOLATED"] is True


def test_a_raw_byte_oracle_found_escapes_the_canonical_document_oracle_could_not() -> None:
    """P0b's same-implementation oracle reported zero on 34 pairs. This is the difference."""
    receipt = _newest("oracle-independence-v2")
    summary = receipt["summary"]
    assert summary["stale_escapes"] > 0
    assert receipt["gates"]["G_OI2_NO_STALE_ESCAPE"] is False
    p0b = json.loads(_text(RECEIPTS / "p0b-mechanics.json"))
    assert p0b["gates"]["G_P0B_EQUIVALENCE"]["stale_left_behind_total"] == 0


def test_unjudgeable_pairs_were_reported_and_not_counted_as_passes() -> None:
    summary = _newest("oracle-independence-v2")["summary"]
    assert summary["pairs_judged"] + summary["pairs_unjudged"] == summary["pairs_attempted"]
    assert summary["exact_state_equivalent"] <= summary["pairs_judged"]
    assert summary["pairs_unjudged"] == 0 or summary["unjudged_reasons"]


def test_both_instruments_reproduced_the_same_reference_locator_finding() -> None:
    """Two protocols, disjoint cohorts, different questions, same answer."""
    oracle = _newest("oracle-independence-v2")["summary"]
    assert oracle["reference_locator_only_pairs"] > 0
    assert (
        oracle["reference_locator_only_reported_clean"]
        == oracle["reference_locator_only_pairs"]
    )
    faithfulness = _newest("sfh1-source-faithfulness")["summary"]
    assert (
        faithfulness["unverified_by_reason"]["FACET_NOT_REPRESENTABLE_IN_COMPILED_STATE"] > 0
    )


def test_the_two_cohorts_are_disjoint() -> None:
    sfh1 = json.loads(_text(NS / "artifacts" / "development" / "sfh1" / "sfh1_pairs.json"))
    oracle = json.loads(
        _text(NS / "artifacts" / "development" / "oracle_v2" / "oracle_v2_pairs.json")
    )
    left = {row["lineage_id"] for row in sfh1}
    right = {row["lineage_id"] for row in oracle}
    assert not (left & right)
