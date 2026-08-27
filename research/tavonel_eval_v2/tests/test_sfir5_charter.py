"""SFIR5's pre-freeze gates, and what each one is for.

A successor protocol is the easiest place in a study to launder a result. The
temptation is not to change a threshold outright -- nobody would sign that --
but to restate the science in the new document "for readability", edit one
number in the restatement, and let the two copies disagree quietly. Or to
enlarge the budget the predecessor died on, and call the enlargement part of the
new design.

So most of these controls are about what SFIR5 must NOT be able to do. Each one
is paired: a refusal and the case that must still pass, because a gate that
refuses everything satisfies the refusal test and proves nothing.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir4_protocol as protocol  # noqa: E402
import sfir5_charter as charter  # noqa: E402
import sfir5_transport as t5  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402


@pytest.fixture
def document():
    return charter.load()


# --- the carry-forward, which is the whole design ---------------------------


def test_the_charter_as_written_passes_every_gate(document):
    """The paired positive for everything below. Without it, a set of gates that
    refused every possible document would look exactly like this file."""
    charter.require_carried_forward(document)
    charter.require_transport_matches_charter(document)
    charter.require_sfir4_bounds_untouched(document)
    charter.require_batching_unchanged(document)
    charter.require_census_identity(document)


@pytest.mark.parametrize("field", charter.SCIENTIFIC_FIELDS_OWNED_BY_SFIR4)
def test_restating_any_of_sfir4s_science_is_refused(document, field):
    """One case per field, not one case for the list. A loop over a list inside
    the check would pass a single-field test while skipping five fields."""
    mutant = copy.deepcopy(document)
    mutant[field] = {"anything": "at all"}
    with pytest.raises(charter.SFIR5Refused, match=field):
        charter.require_carried_forward(mutant)


def test_restating_the_capacity_rule_with_the_same_value_is_still_refused(document):
    """The case that shows this is not a value check. Copying `C_f >= 750`
    correctly today is refused, because the copy is free to diverge tomorrow and
    nothing would notice. The reference is the point, not the number."""
    mutant = copy.deepcopy(document)
    sfir4 = yaml.safe_load(charter.SFIR4_CHARTER_YAML.read_text(encoding="utf-8"))
    mutant["capacity_rule"] = sfir4["capacity_rule"]
    with pytest.raises(charter.SFIR5Refused, match="capacity_rule"):
        charter.require_carried_forward(mutant)


def test_pointing_at_a_different_charter_is_refused(document):
    mutant = copy.deepcopy(document)
    mutant["carried_forward_by_reference"]["charter"] = (
        "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V3_DESIGN_CHARTER.yaml"
    )
    with pytest.raises(charter.SFIR5Refused):
        charter.require_carried_forward(mutant)


def test_dropping_a_field_from_the_carried_list_is_refused(document):
    """Shortening the list is how a field stops being carried without anyone
    editing it: it simply falls out of scope and becomes SFIR5's to define."""
    mutant = copy.deepcopy(document)
    mutant["carried_forward_by_reference"]["fields_owned_by_that_document"] = list(
        charter.SCIENTIFIC_FIELDS_OWNED_BY_SFIR4[:-1]
    )
    with pytest.raises(charter.SFIR5Refused):
        charter.require_carried_forward(mutant)


def test_the_sealed_digest_is_of_sfir4s_charter_on_disk(document):
    carried = charter.require_carried_forward(document)
    assert carried["sha256"] == "sha256:" + protocol.sha_file(
        charter.SFIR4_CHARTER_YAML
    ).removeprefix("sha256:")


# --- the budget SFIR4 stopped on --------------------------------------------


def test_a_charter_claiming_a_larger_retry_budget_than_sfir4_has_is_refused(document):
    mutant = copy.deepcopy(document)
    mutant["transport_policy"]["sfir4_retry_bounds_unmodified"][
        "max_total_rate_limit_wait_seconds"
    ] = 3600
    with pytest.raises(charter.SFIR5Refused):
        charter.require_sfir4_bounds_untouched(mutant)


def test_the_gate_reads_the_live_module_not_a_constant_here(monkeypatch, document):
    """The direction that actually matters. If someone edits `sources_sfir4` to
    enlarge the budget, this must go red even though the charter is untouched --
    which it cannot do if the expected values live in this file or in the
    charter alone."""
    monkeypatch.setattr(sources, "MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS", 3600)
    with pytest.raises(charter.SFIR5Refused):
        charter.require_sfir4_bounds_untouched(document)


# --- the transport the receipt will describe --------------------------------


def test_a_charter_that_promises_pacing_the_module_does_not_do_is_refused(document):
    mutant = copy.deepcopy(document)
    mutant["transport_policy"]["host_min_interval_seconds"]["en.wikipedia.org"] = 0.1
    with pytest.raises(charter.SFIR5Refused):
        charter.require_transport_matches_charter(mutant)


def test_a_module_that_paces_differently_from_the_charter_is_refused(monkeypatch, document):
    """The other direction: the code moves, the document does not."""
    monkeypatch.setattr(t5, "MAX_TOTAL_REQUESTS", 999_999)
    with pytest.raises(charter.SFIR5Refused):
        charter.require_transport_matches_charter(document)


def test_an_unbounded_wall_clock_declaration_is_refused(document):
    mutant = copy.deepcopy(document)
    mutant["transport_policy"]["max_total_wall_clock_seconds"] = None
    with pytest.raises(charter.SFIR5Refused):
        charter.require_transport_matches_charter(mutant)


def test_the_charter_admits_pacing_is_not_charged_to_the_retry_budget(document):
    """Not a computation -- a disclosure. A paced census spends wall-clock the
    frozen fail-safe does not count, and that is the most attackable property of
    this design. It is stated in the charter rather than left to be found, and
    `max_total_wall_clock_seconds` is the finite bound that answers it."""
    policy = document["transport_policy"]
    assert policy["pacing_seconds_are_not_rate_limit_wait_seconds"] is True
    assert isinstance(policy["max_total_wall_clock_seconds"], int)
    assert 0 < policy["max_total_wall_clock_seconds"] < 24 * 60 * 60


def test_the_server_retry_after_outranks_local_pacing(document):
    assert document["transport_policy"]["server_retry_after_takes_priority_over_local_pacing"]
    assert document["transport_policy"]["retry_only_on"] == [429, 503]


# --- batching, semantic equivalence -----------------------------------------


def test_a_charter_declaring_new_batching_is_refused(document):
    """The founder's ruling permitted official batching only where it is
    semantically equivalent. It is not adopted, because it is not needed: the
    adapter already batches at frozen sizes. A charter that claimed otherwise
    would be claiming a change to the instrument."""
    mutant = copy.deepcopy(document)
    mutant["batching_policy"]["new_batching_introduced_by_sfir5"] = True
    with pytest.raises(charter.SFIR5Refused):
        charter.require_batching_unchanged(mutant)


def test_a_different_batch_size_is_refused_because_it_changes_what_a_response_covers(document):
    mutant = copy.deepcopy(document)
    mutant["batching_policy"]["category_page_size"] = 100
    with pytest.raises(charter.SFIR5Refused):
        charter.require_batching_unchanged(mutant)


def test_the_declared_batch_sizes_are_the_frozen_adapters_own(document):
    """The equivalence proof, and it is short because nothing changed: SFIR5
    issues the same requests, in the same order, covering the same pages, as
    SFIR4 would have. Equivalence between two batchings is hard; equivalence
    between a batching and itself is a digest comparison."""
    pool = sources.SOURCE_POOLS["encyclopedia_wikipedia"]
    declared = document["batching_policy"]
    assert declared["category_page_size"] == pool["category_page_size"]
    assert declared["revision_batch_size"] == pool["revision_batch_size"]


# --- whose result is this ---------------------------------------------------


def test_a_charter_that_hides_the_sfir4_protocol_id_is_refused(document):
    """The census input will literally say SFIR4, because it is SFIR4's probe.
    A charter that omitted this would leave a reader free to find the field
    later and conclude that SFIR4 produced a census. It did not."""
    mutant = copy.deepcopy(document)
    mutant["census_identity"]["census_input_carries_sfir4_protocol_id"] = False
    with pytest.raises(charter.SFIR5Refused):
        charter.require_census_identity(mutant)


def test_a_charter_claiming_to_execute_under_sfir4_is_refused(document):
    mutant = copy.deepcopy(document)
    mutant["census_identity"]["executed_under"] = protocol.PROTOCOL_ID
    with pytest.raises(charter.SFIR5Refused):
        charter.require_census_identity(mutant)


def test_the_header_must_name_the_predecessor_and_why_it_ended(document):
    assert document["succeeds"] == protocol.PROTOCOL_ID
    assert document["succeeds_because"] == "TERMINAL_OPERATIONAL_STOP"
    assert document["state"] == "PROSPECTIVE_PRE_CENSUS"
    assert document["result_blind_design"] is True


# --- a refused freeze seals nothing -----------------------------------------


def test_a_refused_gate_leaves_no_receipt_behind(tmp_path, monkeypatch):
    """Cancellation restores state. A half-written charter freeze is worse than
    none: it is an authority downstream tooling would bind to."""
    monkeypatch.setattr(sources, "MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS", 3600)
    destination = tmp_path / "sfir5-design-charter-freeze.json"
    with pytest.raises(charter.SFIR5Refused):
        charter.freeze(destination, "2026-08-27T00:00:00Z")
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_freeze_that_passes_writes_one_receipt_and_seals_its_own_digest(tmp_path):
    destination = tmp_path / "sfir5-design-charter-freeze.json"
    written = charter.freeze(destination, "2026-08-27T00:00:00Z")
    import json

    body = json.loads(written.read_text(encoding="utf-8"))
    assert body["state"] == "FROZEN_PRE_CENSUS"
    assert body["protocol_id"] == charter.PROTOCOL_ID
    assert body["carried_forward_by_reference"]["fields_redeclared"] == []
    assert body["toolchain"]["sfir5_transport"]["sha256"].startswith("sha256:")
    import hashlib

    core = {key: value for key, value in body.items() if key != "content_sha256"}
    assert (
        body["content_sha256"]
        == "sha256:"
        + hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_the_freeze_pins_the_transport_that_will_actually_run(tmp_path):
    """INC-V2-092's lesson: a pin over the wrong file is a pin over nothing.
    The sealed digest must be the module the census will import."""
    written = charter.freeze(tmp_path / "seal.json", "2026-08-27T00:00:00Z")
    import json

    body = json.loads(written.read_text(encoding="utf-8"))
    assert body["toolchain"]["sfir5_transport"]["sha256"] == protocol.sha_file(Path(t5.__file__))
