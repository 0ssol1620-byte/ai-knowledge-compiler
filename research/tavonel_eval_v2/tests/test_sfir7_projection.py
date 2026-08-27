"""Hostile tests for the raw -> frame projection seam.

This seam is where a field lands in the wrong slot and the record still looks
real. `SourceRank` sat at column 33 of a 39-column header; the same class of
mistake one layer later swaps `language` into `spdx_license_id` and produces a
roster nobody can tell is wrong. So the controls here are mostly identity checks
and field mix-ups, not shape checks.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_frame as frame  # noqa: E402
import sfir7_projection as projection  # noqa: E402
from sfir7_catalog_parser import RawCatalogRecord  # noqa: E402


def _raw(**overrides) -> RawCatalogRecord:
    base = {
        "record_id": "1001",
        "host_uuid": "24038237",
        "host": "GitHub",
        "name_with_owner": "pypa/setuptools",
        "catalog_rank_value": 27,
        "created_utc": "2010-03-01 00:00:00 UTC",
        "last_activity_utc": "2019-12-30 00:00:00 UTC",
        "spdx_license_id": "MIT",
        "language": "Python",
        "fork": False,
        "status": "",
    }
    base.update(overrides)
    return RawCatalogRecord(**base)


# --- the happy path ----------------------------------------------------------


def test_a_clean_record_projects_and_keeps_the_publishers_spelling():
    projected, sidecar = projection.project(_raw())
    assert projected.namespace == "pypa"
    assert projected.name == "setuptools"
    assert projected.primary_language == "Python"
    # publisher spelling preserved, NOT canonicalised
    assert projected.host == "GitHub"
    assert projected.spdx_license_id == "MIT"
    assert sidecar.host_uuid == "24038237"
    assert sidecar.name_with_owner == "pypa/setuptools"


def test_lowercase_publisher_spellings_survive_the_projection_unchanged():
    """Reconciliation belongs in the comparator, not here. A receipt has to be
    able to show what the publisher wrote next to the family it was matched to."""
    projected, _ = projection.project(_raw(host="github", spdx_license_id="mit"))
    assert projected.host == "github"
    assert projected.spdx_license_id == "mit"
    # and the comparator still accepts them
    rule = frame.declared_rule(
        catalog_id="LIBRARIES_IO_OPEN_DATA_1_6_0",
        snapshot_sha256="sha256:" + "a" * 64,
        snapshot_date_utc="2020-01-12",
    )
    licence = next(p for p in rule.predicates if p.field == "spdx_license_id")
    host = next(p for p in rule.predicates if p.field == "host")
    assert frame._evaluate(licence, projected) is True
    assert frame._evaluate(host, projected) is True


# --- owner/repo is checked by reconstruction, never guessed ------------------


@pytest.mark.parametrize(
    "bad",
    ["setuptools", "a/b/c", "/setuptools", "pypa/", "", "pypa//setuptools", " / "],
)
def test_a_malformed_address_is_refused_rather_than_repaired(bad: str):
    with pytest.raises(projection.ProjectionRefused):
        projection.project(_raw(name_with_owner=bad))


def test_the_split_is_verified_by_reconstruction():
    namespace, name = projection.split_name_with_owner("pypa/setuptools")
    assert f"{namespace}/{name}" == "pypa/setuptools"


def test_a_whitespace_padded_address_survives_the_projection_verbatim():
    """The gap mutation testing found: no control used a padded address, so a
    projection that quietly stripped one changed nothing and the mutant lived.

    Trimming would send the census to `a/b` while the catalogue recorded
    `a / b` -- a different address, with the roster naming one repository and
    the requests going to another. The catalogue is the authority on what the
    address is, so the padding is preserved, not cleaned up.
    """
    for padded in ("pypa / setuptools", " a / b "):
        projected, sidecar = projection.project(_raw(name_with_owner=padded))
        assert f"{projected.namespace}/{projected.name}" == padded
        assert sidecar.name_with_owner == padded
    # leading/trailing padding on the whole string is preserved too
    projected, _ = projection.project(_raw(name_with_owner=" pypa/setuptools"))
    assert projected.namespace == " pypa"
    assert projected.name == "setuptools"


def test_no_trimming_or_case_conversion_happens_on_the_way_through():
    """A publisher value with unusual casing is an address we must send verbatim."""
    projected, sidecar = projection.project(_raw(name_with_owner="PyPA/SetupTools"))
    assert projected.namespace == "PyPA"
    assert projected.name == "SetupTools"
    assert sidecar.name_with_owner == "PyPA/SetupTools"


# --- field mix-ups: the SourceRank-at-column-33 lesson, one layer later ------


def test_a_projection_that_swaps_two_string_fields_is_refused(monkeypatch):
    """language -> spdx_license_id. Both strings, record still looks real."""
    real = frame.FrameCatalogRecord

    def swapped(**kwargs):
        kwargs["spdx_license_id"], kwargs["primary_language"] = (
            kwargs["primary_language"],
            kwargs["spdx_license_id"],
        )
        return real(**kwargs)

    monkeypatch.setattr(frame, "FrameCatalogRecord", swapped)
    with pytest.raises(projection.ProjectionRefused, match="projection changed"):
        projection.project(_raw())


def test_a_projection_that_swaps_the_two_dates_is_refused(monkeypatch):
    real = frame.FrameCatalogRecord

    def swapped(**kwargs):
        kwargs["created_utc"], kwargs["last_activity_utc"] = (
            kwargs["last_activity_utc"],
            kwargs["created_utc"],
        )
        return real(**kwargs)

    monkeypatch.setattr(frame, "FrameCatalogRecord", swapped)
    with pytest.raises(projection.ProjectionRefused, match="projection changed"):
        projection.project(_raw())


def test_a_projection_that_puts_the_rank_in_the_record_id_is_refused(monkeypatch):
    real = frame.FrameCatalogRecord

    def swapped(**kwargs):
        kwargs["record_id"] = str(kwargs["catalog_rank_value"])
        return real(**kwargs)

    monkeypatch.setattr(frame, "FrameCatalogRecord", swapped)
    with pytest.raises(projection.ProjectionRefused, match="record_id"):
        projection.project(_raw())


def test_the_lossless_check_is_independent_of_the_constructor():
    """Handed a mismatched pair directly, it must still refuse -- otherwise it is
    only re-reading what the constructor just wrote."""
    raw = _raw()
    wrong, _ = projection.project(_raw(catalog_rank_value=999))
    with pytest.raises(projection.ProjectionRefused, match="catalog_rank_value"):
        projection.require_lossless(raw, wrong)


# --- the selection surface stays exactly nine fields -------------------------


def test_the_withheld_fields_never_reach_the_selection_record():
    for withheld in projection.WITHHELD_FROM_SELECTION:
        assert withheld not in frame.CATALOG_FIELDS
        assert withheld in frame.PROVENANCE_ONLY_FIELDS


def test_the_selectable_field_set_is_exactly_the_nine_designed_blind():
    assert frame.CATALOG_FIELDS == frame.SELECTABLE_FIELDS
    assert len(frame.SELECTABLE_FIELDS) == 9
    assert not (frame.SELECTABLE_FIELDS & frame.PROVENANCE_ONLY_FIELDS)


def test_a_predicate_naming_a_provenance_field_is_refused():
    """fork and status are real publisher data and the blind rule did not use
    them. Reaching for one now is choosing a filter after seeing the catalogue."""
    rule = frame.declared_rule(
        catalog_id="LIBRARIES_IO_OPEN_DATA_1_6_0",
        snapshot_sha256="sha256:" + "a" * 64,
        snapshot_date_utc="2020-01-12",
    )
    sneaky = replace(
        rule,
        predicates=(
            *rule.predicates,
            frame.EligibilityPredicate(field="fork", op="eq", value=False, why="..."),
        ),
    )
    with pytest.raises(frame.SFIR7Refused):
        frame.assert_capacity_blind(sneaky)


def test_the_sidecar_carries_the_provenance_the_selection_may_not_see():
    _, sidecar = projection.project(_raw(fork=True, status="Unmaintained"))
    assert sidecar.fork is True
    assert sidecar.status == "Unmaintained"
    assert sidecar.host_uuid


# --- identity coherence ------------------------------------------------------


def _side(record_id: str, address: str, uuid: str) -> projection.ProvenanceSidecar:
    return projection.ProvenanceSidecar(
        record_id=record_id, name_with_owner=address, host_uuid=uuid, fork=False, status=""
    )


def test_a_duplicated_record_id_is_refused():
    with pytest.raises(projection.IdentityConflict, match="appears twice"):
        projection.require_identity_coherence(
            [_side("1", "a/b", "100"), _side("1", "c/d", "200")]
        )


def test_one_address_claimed_by_two_repository_ids_is_an_identity_conflict():
    """Two repositories wearing one address. A census asking that address cannot
    know which one answers, so the roster is refused rather than sampled."""
    with pytest.raises(projection.IdentityConflict, match="claimed by more than one"):
        projection.require_identity_coherence(
            [_side("1", "a/b", "100"), _side("2", "a/b", "200")]
        )


def test_one_repository_under_two_addresses_is_a_rename_not_a_conflict():
    """The case that must NOT refuse. Identity is the id; the address moved."""
    report = projection.require_identity_coherence(
        [_side("1", "old/name", "100"), _side("2", "new/name", "100")]
    )
    assert report["repositories_seen_under_more_than_one_address"] == 1
    assert report["rename_diagnostics"]["100"] == ["new/name", "old/name"]
    assert report["distinct_host_uuids"] == 1


def test_a_clean_roster_reports_no_conflicts_and_no_renames():
    report = projection.require_identity_coherence(
        [_side("1", "a/b", "100"), _side("2", "c/d", "200")]
    )
    assert report["records"] == 2
    assert report["repositories_seen_under_more_than_one_address"] == 0
    assert report["addresses_contested_by_two_repositories"] == 0


# --- live attestation --------------------------------------------------------


def test_a_live_response_from_a_different_repository_id_is_refused():
    """SFIR6's INC-V2-108 finding 4, closed. GET /repos/facebook/jest answers
    HTTP 200 from a different identity because GitHub follows a rename."""
    expected = _side("1", "facebook/jest", "15062869")
    with pytest.raises(projection.IdentityConflict, match="different repository"):
        projection.attest_live_identity(expected, 99999999)


def test_a_live_response_from_the_selected_repository_id_passes():
    expected = _side("1", "facebook/jest", "15062869")
    projection.attest_live_identity(expected, 15062869)
    projection.attest_live_identity(expected, "15062869")


def test_attestation_compares_the_id_and_not_the_path():
    """A renamed repository answering under a new address is still the same
    repository, and must not be refused for the rename alone."""
    expected = _side("1", "facebook/jest", "15062869")
    projection.attest_live_identity(expected, "15062869")
