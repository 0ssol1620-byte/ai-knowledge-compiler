"""Controls for SFIR9 identity.

The property under defence is that a repository's identity survives everything
the host can change about it, and that nothing the host can change about it can
be mistaken for the identity. A rename must not move it, a case difference must
not move it, and an address must never be accepted where a number is required.

The candidate controls defend the other half of SFIR8's J1: a candidate found by
an uninterrupted traversal and the same candidate found after a resume must have
the same identity. Discovery order changes under segmentation, so it is excluded
by construction and asserted here rather than assumed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_identity_logic as identity  # noqa: E402

SHA_A = "a" * 40
SHA_B = "b" * 40


def _root(**overrides):
    body = dict(host_uuid="12345", catalogue_address="old-org/old-name")
    body.update(overrides)
    return identity.RepositoryIdentity.frozen(**body)


# ---------------------------------------------------- an address is not an id


@pytest.mark.parametrize("value", ["facebook/react", "old-org/old-name", "a/b"])
def test_an_address_offered_as_an_identity_refuses(value):
    with pytest.raises(identity.IdentityRefused) as caught:
        identity.normalize_host_uuid(value)
    assert caught.value.code == identity.ADDRESS_AS_IDENTITY
    assert "790" in str(caught.value)


@pytest.mark.parametrize("value", ["", "  ", "12a45", "0", "-1", "12.5", "1e5"])
def test_a_value_that_is_not_a_decimal_id_refuses(value):
    with pytest.raises(identity.IdentityRefused):
        identity.normalize_host_uuid(value)


@pytest.mark.parametrize("value", [None, 12.5, [], {}, True, b"12345", object()])
def test_a_value_of_the_wrong_type_refuses(value):
    """Refused by the decimal pattern, which is the only thing that refuses.

    There is deliberately no type check in front of it. Each of these
    stringifies to something the pattern rejects, so a separate isinstance guard
    could never fire, and one that cannot fire is not a guard.
    """
    with pytest.raises(identity.IdentityRefused) as caught:
        identity.normalize_host_uuid(value)
    assert caught.value.code == identity.MALFORMED_IDENTITY


@pytest.mark.parametrize(
    "value,code",
    [
        ("facebook/react", identity.ADDRESS_AS_IDENTITY),
        ("a/b", identity.ADDRESS_AS_IDENTITY),
        ("", identity.MALFORMED_IDENTITY),
        ("   ", identity.MALFORMED_IDENTITY),
        ("12a45", identity.MALFORMED_IDENTITY),
        ("0", identity.MALFORMED_IDENTITY),
    ],
)
def test_each_refusal_carries_the_code_that_names_what_went_wrong(value, code):
    """The code is what an operator acts on, so it is pinned per input class.

    An empty string is malformed rather than an address: it is not a name that
    was mistaken for an identity, it is nothing at all, and reporting it as an
    address would send a reader looking for a rename that never happened.
    """
    with pytest.raises(identity.IdentityRefused) as caught:
        identity.normalize_host_uuid(value)
    assert caught.value.code == code


def test_an_integer_and_its_string_are_the_same_repository():
    """Two call sites must not disagree about whether they matched."""
    assert identity.normalize_host_uuid(12345) == identity.normalize_host_uuid("12345")
    assert identity.normalize_host_uuid(" 12345 ") == "12345"


def test_a_well_formed_id_passes_the_same_check():
    assert identity.normalize_host_uuid("12345") == "12345"


# ----------------------------------------------------------- attestation


def test_the_matching_id_attests():
    assert _root().attest("12345").host_uuid == "12345"
    assert _root().attest(12345).host_uuid == "12345"


def test_a_different_id_refuses_however_real_the_repository_is():
    with pytest.raises(identity.IdentityRefused) as caught:
        _root().attest("99999")
    assert caught.value.code == identity.IDENTITY_MISMATCH
    assert "HTTP 200 from a real repository is not" in str(caught.value)


def test_an_address_cannot_attest_an_identity():
    with pytest.raises(identity.IdentityRefused) as caught:
        _root().attest("someone-else/repo")
    assert caught.value.code == identity.ADDRESS_AS_IDENTITY


# --------------------------------------------------- renames do not move it


def test_adopting_the_live_name_does_not_change_the_identity():
    before = _root()
    after = before.adopt("new-org/new-name")
    assert after.host_uuid == before.host_uuid
    assert identity.same_repository(before, after)


def test_a_rename_is_a_property_of_the_addresses():
    assert _root().adopt("new-org/new-name").renamed() is True
    assert _root().adopt("old-org/old-name").renamed() is False


def test_a_case_only_difference_is_not_a_rename():
    """Hosts are case-insensitive about owner and name; the study must be too."""
    assert _root().adopt("Old-Org/Old-Name").renamed() is False


def test_an_unresolved_root_is_not_reported_as_renamed():
    assert _root().renamed() is False


def test_two_repositories_with_the_same_address_are_not_the_same_repository():
    """The case the identity gate exists for: same path, different repository."""
    a = identity.RepositoryIdentity.frozen(host_uuid="1", catalogue_address="a/b")
    b = identity.RepositoryIdentity.frozen(host_uuid="2", catalogue_address="a/b")
    assert identity.same_repository(a, b) is False


def test_one_repository_under_two_addresses_is_one_repository():
    a = identity.RepositoryIdentity.frozen(host_uuid="1", catalogue_address="old/name")
    b = identity.RepositoryIdentity.frozen(host_uuid="1", catalogue_address="new/name")
    assert identity.same_repository(a, b) is True


@pytest.mark.parametrize("address", ["noslash", "too/many/slashes", "", None, 7])
def test_an_unusable_canonical_address_refuses(address):
    with pytest.raises(identity.IdentityRefused):
        _root().adopt(address)


# ------------------------------------------------------- candidate identity


def _candidate(**overrides):
    body = dict(repository_numeric_id="12345", path="README.md", blob_sha=SHA_A)
    body.update(overrides)
    return identity.CandidateIdentity.of(**body)


def test_a_candidate_is_repository_path_and_content():
    assert _candidate().key() == ("12345", "README.md", SHA_A)


def test_discovery_order_is_not_part_of_the_identity():
    """Segmentation changes the order; it must not change what was found.

    This is the half of SFIR8's J1 that lives in the identity layer. If order
    participated, a resumed traversal would report different candidates from an
    uninterrupted one purely because it was interrupted.
    """
    fields = set(identity.CandidateIdentity.__dataclass_fields__)
    assert "discovery_sequence" not in fields
    assert "discovery_order" not in fields
    assert fields == {"repository_numeric_id", "path", "blob_sha"}


def test_the_root_address_is_not_part_of_the_identity():
    """A rename mid-traversal must not fork one candidate into two."""
    assert "catalogue_address" not in identity.CandidateIdentity.__dataclass_fields__
    assert "root_id" not in identity.CandidateIdentity.__dataclass_fields__


@pytest.mark.parametrize(
    "changed",
    [
        {"repository_numeric_id": "54321"},
        {"path": "docs/README.md"},
        {"blob_sha": SHA_B},
    ],
)
def test_every_component_of_the_identity_participates(changed):
    assert _candidate(**changed).key() != _candidate().key()


@pytest.mark.parametrize("sha", ["a" * 39, "a" * 41, "g" * 40, "", None, "A" * 39])
def test_a_blob_sha_that_is_not_a_full_sha_refuses(sha):
    with pytest.raises(identity.IdentityRefused):
        _candidate(blob_sha=sha)


def test_an_uppercase_sha_is_the_same_content():
    assert _candidate(blob_sha="A" * 40).key() == _candidate(blob_sha=SHA_A).key()


@pytest.mark.parametrize("path", ["", None, 7])
def test_a_missing_path_refuses(path):
    with pytest.raises(identity.IdentityRefused):
        _candidate(path=path)


def test_a_candidate_cannot_be_identified_by_an_address():
    with pytest.raises(identity.IdentityRefused) as caught:
        _candidate(repository_numeric_id="facebook/react")
    assert caught.value.code == identity.ADDRESS_AS_IDENTITY


# ------------------------------------------------------------- set digests


def test_the_set_digest_ignores_order():
    forward = [_candidate(), _candidate(path="a.py"), _candidate(path="b.py")]
    assert identity.candidate_set_digest(forward) == identity.candidate_set_digest(
        list(reversed(forward))
    )


def test_the_set_digest_notices_a_missing_candidate():
    full = [_candidate(), _candidate(path="a.py")]
    assert identity.candidate_set_digest(full) != identity.candidate_set_digest(full[:1])


def test_the_order_digest_does_not_ignore_order():
    """Two questions, two answers. Collapsing them would hide one of them."""
    forward = [_candidate(), _candidate(path="a.py")]
    assert identity.candidate_order_digest(forward) != identity.candidate_order_digest(
        list(reversed(forward))
    )


def test_the_two_digests_are_not_the_same_function():
    """They agree on a sequence already in sorted order, and only on that.

    The first version of this control used such a sequence and failed, which is
    the correct behaviour rather than a defect: a set digest sorts, so on input
    that is already sorted it computes over exactly the same material as the
    order digest. Distinguishing the two functions needs input where the order
    and the sorted order differ.
    """
    sorted_order = [_candidate(path="README.md"), _candidate(path="a.py")]
    assert identity.candidate_set_digest(sorted_order) == identity.candidate_order_digest(
        sorted_order
    )

    other_order = list(reversed(sorted_order))
    assert identity.candidate_set_digest(other_order) != identity.candidate_order_digest(
        other_order
    )


def test_an_empty_set_still_digests():
    assert identity.candidate_set_digest([]).startswith("sha256:")


# ------------------------------------------------------- spent exclusions


def test_a_spent_record_names_the_study_that_spent_it():
    spent = identity.spent_set([{"host_uuid": "1", "spent_by_study": "SFIR7"}])
    assert spent[0].as_dict()["spent_by_study"] == "SFIR7"
    assert spent[0].as_dict()["reason"] == identity.SPENT
    assert spent[0].as_dict()["value_bearing"] is False


def test_the_only_reason_is_that_the_identity_was_looked_at():
    assert identity.SPENT == "SPENT_DEVELOPMENT_ROOT"
    proof = identity.exclusion_proof(
        identity.spent_set([{"host_uuid": "1", "spent_by_study": "SFIR7"}])
    )
    assert proof["reason"] == identity.SPENT
    assert "second selection criterion" in proof["why_only_one_reason"]


def test_the_forbidden_exclusion_list_names_what_the_earlier_studies_produced():
    """Asserted explicitly, because the parametrized control cannot do it.

    A test that iterates the set it is checking narrows exactly as far as the
    set does: delete a field and the case testing that field disappears with it,
    and everything stays green.
    """
    assert {
        "candidate_count",
        "tree_size",
        "traversal_difficulty",
        "completion_status",
        "rename_status",
        "provider_charge",
        "network_hops",
        "source_rank",
    } <= identity.FORBIDDEN_EXCLUSION_FIELDS


@pytest.mark.parametrize("forbidden", sorted(identity.FORBIDDEN_EXCLUSION_FIELDS))
def test_an_exclusion_record_carrying_an_observation_refuses(forbidden):
    """The back door: an exclusion list is still an input to selection."""
    with pytest.raises(identity.IdentityRefused) as caught:
        identity.spent_set(
            [{"host_uuid": "1", "spent_by_study": "SFIR7", forbidden: 400}]
        )
    assert caught.value.code == identity.OBSERVATION_IN_PROOF


def test_a_clean_record_passes_the_same_check():
    assert len(identity.spent_set([{"host_uuid": "1", "spent_by_study": "SFIR8"}])) == 1


@pytest.mark.parametrize("study", ["SFIR9", "SFI2", "", None, "sfir7"])
def test_a_proof_must_name_a_study_that_actually_spends_roots(study):
    with pytest.raises(identity.IdentityRefused):
        identity.spent_set([{"host_uuid": "1", "spent_by_study": study}])


def test_the_spending_studies_are_the_development_ones():
    assert identity.SPENDING_STUDIES == ("SFIR7", "SFIR8")


def test_the_proof_digest_ignores_the_order_records_arrive_in():
    forward = identity.spent_set(
        [
            {"host_uuid": "1", "spent_by_study": "SFIR7"},
            {"host_uuid": "2", "spent_by_study": "SFIR8"},
        ]
    )
    backward = identity.spent_set(
        [
            {"host_uuid": "2", "spent_by_study": "SFIR8"},
            {"host_uuid": "1", "spent_by_study": "SFIR7"},
        ]
    )
    a = identity.exclusion_proof(forward)
    b = identity.exclusion_proof(backward)
    assert a["digest"] == b["digest"]
    assert a["host_uuids"] == b["host_uuids"]


def test_the_proof_digest_notices_a_dropped_exclusion():
    two = identity.spent_set(
        [
            {"host_uuid": "1", "spent_by_study": "SFIR7"},
            {"host_uuid": "2", "spent_by_study": "SFIR7"},
        ]
    )
    one = identity.spent_set([{"host_uuid": "1", "spent_by_study": "SFIR7"}])
    assert identity.exclusion_proof(two)["digest"] != identity.exclusion_proof(one)["digest"]
    assert identity.exclusion_proof(two)["count"] == 2


def test_the_proof_digest_notices_which_study_spent_it():
    """A record that lost its provenance is not a proof."""
    seven = identity.spent_set([{"host_uuid": "1", "spent_by_study": "SFIR7"}])
    eight = identity.spent_set([{"host_uuid": "1", "spent_by_study": "SFIR8"}])
    assert identity.exclusion_proof(seven)["digest"] != identity.exclusion_proof(eight)["digest"]


def test_an_exclusion_cannot_be_identified_by_an_address():
    with pytest.raises(identity.IdentityRefused) as caught:
        identity.spent_set([{"host_uuid": "facebook/react", "spent_by_study": "SFIR7"}])
    assert caught.value.code == identity.ADDRESS_AS_IDENTITY


# --------------------------------------------------- historical independence


def test_nothing_here_reads_the_historical_chain():
    """Checked in the source, not promised in the docstring.

    The isolation gate is the authority on this for the study as a whole; this
    control keeps the specific failure -- a fresh component quietly importing the
    drifted historical identity module -- from being introduced here.
    """
    source = (NS / "tools/sfir9_identity_logic.py").read_text(encoding="utf-8")
    for forbidden in (
        "import root_identity",
        "frozen-instrument-integrity",
        "verify_frozen_instrument_integrity",
        "650766c4",
    ):
        assert forbidden not in source


def test_no_receipt_is_read_at_import_time():
    """A module that reads a receipt to load has made that receipt a prerequisite."""
    source = (NS / "tools/sfir9_identity_logic.py").read_text(encoding="utf-8")
    assert "open(" not in source
    assert "read_text" not in source
    assert "read_bytes" not in source
