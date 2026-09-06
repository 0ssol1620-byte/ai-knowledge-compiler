# ruff: noqa: RUF001 - the confusable characters below are the subject under test
"""Controls for SFIR4's domain-separated identity proof.

The two red controls that matter are
``test_a_root_container_colliding_with_a_container_is_now_caught`` (the false
pass the old flat set left open) and
``test_an_nfd_spelled_spent_identity_is_caught`` (the false negative plain
``casefold`` left open against the spent set).
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for extra in (NS, NS / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import sfir4_identity_domain as idom  # noqa: E402


def row(
    family: str = "git_docs",
    *,
    root: str = "git:octo/docs",
    container: str = "git:octo/docs:reference",
    lineage: str = "git:octo/docs:reference/api.md",
    aliases: list[str] | None = None,
    root_container: str | None = None,
) -> dict[str, Any]:
    return {
        "family": family,
        "discovery_root_id": root,
        "root_container_id": root_container if root_container is not None else root,
        "container_id": container,
        "lineage_id": lineage,
        "alias_ids": sorted(aliases or []),
    }


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_every_declared_identity_field_is_typed() -> None:
    domains = {str(domain) for domain in idom.IdentityDomain}
    assert domains == {
        "discovery_root_id",
        "root_container_id",
        "container_id",
        "lineage_id",
        "alias_ids",
    }


def test_the_three_namespaces_partition_the_five_domains() -> None:
    covered = [d for domains in idom.NAMESPACES.values() for d in domains]
    assert sorted(str(d) for d in covered) == sorted(str(d) for d in idom.IdentityDomain)
    assert len(covered) == len(set(covered)), "a domain appears in two namespaces"


def test_only_document_names_are_proved_unique() -> None:
    assert frozenset({"CONTAINER", "ROOT"}) == idom.REPEATABLE
    assert set(idom.NAMESPACES) - idom.REPEATABLE == {"DOCUMENT"}


def test_a_clean_candidate_set_proves() -> None:
    proof = idom.prove([row(lineage="git:octo/docs:a.md"), row(lineage="git:octo/docs:b.md")])
    assert proof["candidates"] == 2
    assert proof["document_identities_proved_unique"] == 2
    assert proof["container_names_proved_consistent"] == 1
    assert proof["namespaces_checked"]["ROOT"] == [
        "discovery_root_id",
        "root_container_id",
    ]


def test_many_candidates_may_share_one_container() -> None:
    """The FALSE REFUSAL a flat uniqueness rule produces.

    A container holds many documents. Requiring container_id unique refuses
    every candidate after the first in any directory.
    """
    proof = idom.prove(
        [row(lineage=f"git:octo/docs:{n}.md") for n in range(5)],
    )
    assert proof["candidates"] == 5
    assert proof["container_names_proved_consistent"] == 1


def test_the_proof_names_the_namespaces_it_checked() -> None:
    """A proof that reports only ``holds`` is indistinguishable from a narrow one."""
    proof = idom.prove([row()])
    assert set(proof["namespaces_checked"]) == {"DOCUMENT", "CONTAINER", "ROOT"}
    assert proof["identities_by_domain"]["lineage_id"] == 1
    assert "what_a_pass_means" in proof


# ---------------------------------------------------------------------------
# Real collisions still refuse
# ---------------------------------------------------------------------------


def test_two_candidates_sharing_a_lineage_refuse() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="DOCUMENT namespace collision"):
        idom.prove([row(lineage="same"), row(lineage="same")])


def test_two_candidates_sharing_an_alias_refuse() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="DOCUMENT namespace collision"):
        idom.prove([row(lineage="a", aliases=["dup"]), row(lineage="b", aliases=["dup"])])


def test_an_alias_equal_to_another_candidates_container_refuses() -> None:
    """The one part of the old flat pooling that was correct, preserved.

    Container names may repeat, so this is not a uniqueness violation -- it is
    the explicit DOCUMENT/CONTAINER cross-check.
    """
    with pytest.raises(idom.IdentityDomainRefused, match="both a document and a container"):
        idom.prove(
            [
                row(container="shared", lineage="a"),
                row(container="other", lineage="b", aliases=["shared"]),
            ]
        )


def test_a_lineage_equal_to_its_own_containers_name_refuses() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="both a document and a container"):
        idom.prove([row(container="same", lineage="same")])


def test_a_root_container_colliding_with_a_container_is_now_caught() -> None:
    """The FALSE PASS the old proof left open.

    ``root_container_id`` was never added to the pooled set, so this pair was
    not a collision to it. Here the two names sit in different namespaces, so it
    is reported as incidental rather than silently unseen -- the point is that
    it becomes *visible*, which it previously was not.
    """
    proof = idom.prove(
        [
            row(root_container="shared-name", lineage="a"),
            row(container="shared-name", lineage="b"),
        ]
    )
    values = {entry["value"] for entry in proof["incidental_cross_namespace_equalities"]}
    assert "shared-name" in values


def test_a_cross_family_string_equality_is_incidental_not_a_collision() -> None:
    """The FALSE REFUSAL the old proof produced.

    Two unrelated corpora that happen to spell one identity the same way must
    not sink the census.
    """
    proof = idom.prove(
        [
            row("git_docs", lineage="collide"),
            row("regulation_ecfr", root="ecfr:title:29", lineage="collide"),
        ]
    )
    assert proof["candidates"] == 2
    incidental = {entry["value"] for entry in proof["incidental_cross_namespace_equalities"]}
    assert "collide" in incidental


def test_case_differing_document_identities_do_not_merge() -> None:
    """Git paths are case-sensitive; folding them merges two real files."""
    proof = idom.prove(
        [row(lineage="git:octo/docs:README.md"), row(lineage="git:octo/docs:readme.md")]
    )
    assert proof["candidates"] == 2


def test_a_root_repeating_across_candidates_is_not_a_collision() -> None:
    proof = idom.prove([row(lineage="a"), row(lineage="b"), row(lineage="c")])
    assert proof["root_names_proved_consistent"] == 1


# ---------------------------------------------------------------------------
# Spent-set comparison: the widened rule
# ---------------------------------------------------------------------------


def test_an_exact_spent_identity_refuses_and_names_the_exact_rule() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="EXACT"):
        idom.prove([row(lineage="spent-one")], spent_values=["spent-one"])


def test_an_nfd_spelled_spent_identity_is_caught() -> None:
    """The FALSE NEGATIVE plain ``casefold`` left open.

    ``casefold`` does no Unicode normalisation, so an NFD-spelled spent identity
    never matched its NFC candidate and the identity was admitted as fresh. Both
    rules here normalise first, so the EXACT rule already catches it -- which is
    the repair. The assertion below records that the old comparison did not.
    """
    nfc = unicodedata.normalize("NFC", "café-lineage")
    nfd = unicodedata.normalize("NFD", "café-lineage")
    assert nfc != nfd
    assert nfc.casefold() != nfd.casefold(), (
        "casefold alone no longer misses this; the finding this test records is stale"
    )
    with pytest.raises(idom.IdentityDomainRefused, match="EXACT"):
        idom.prove([row(lineage=nfc)], spent_values=[nfd])


def test_a_zero_width_character_cannot_hide_a_spent_identity() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="WIDENED"):
        idom.prove([row(lineage="spent​one")], spent_values=["spentone"])


def test_a_soft_hyphen_cannot_hide_a_spent_identity() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="WIDENED"):
        idom.prove([row(lineage="spent­one")], spent_values=["spentone"])


def test_full_width_digits_cannot_hide_a_spent_identity() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="WIDENED"):
        idom.prove([row(lineage="lineage-１２")], spent_values=["lineage-12"])


def test_case_alone_cannot_hide_a_spent_identity() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="WIDENED"):
        idom.prove([row(lineage="SPENT-ONE")], spent_values=["spent-one"])


def test_the_widened_rule_does_not_reach_an_unrelated_identity() -> None:
    proof = idom.prove([row(lineage="fresh-one")], spent_values=["spent-one"])
    assert proof["spent_values_compared"] == 1


def test_spent_key_is_idempotent() -> None:
    for value in ["Straße", "café", "A​B", "  x  y  ", "１２"]:
        assert idom.spent_key(idom.spent_key(value)) == idom.spent_key(value)


def test_the_widened_rule_is_strictly_wider_than_the_exact_rule() -> None:
    """Stated as a property, executed over the cases that motivated it."""
    for value in ["Straße", "café", "A​B", "SPENT", "１２", "a b"]:
        exact = unicodedata.normalize("NFC", value)
        assert idom.spent_key(exact) == idom.spent_key(value)


# ---------------------------------------------------------------------------
# Malformed input fails closed
# ---------------------------------------------------------------------------


def test_a_row_without_a_family_refuses() -> None:
    bad = row()
    del bad["family"]
    with pytest.raises(idom.IdentityDomainRefused, match="no family"):
        idom.prove([bad])


def test_an_empty_identity_refuses() -> None:
    with pytest.raises(idom.IdentityDomainRefused, match="non-string or empty"):
        idom.prove([row(lineage="")])


def test_a_non_string_identity_refuses() -> None:
    bad = row()
    bad["container_id"] = 17
    with pytest.raises(idom.IdentityDomainRefused, match="non-string or empty"):
        idom.prove([bad])


def test_alias_ids_that_are_not_a_sequence_refuse() -> None:
    bad = row()
    bad["alias_ids"] = "not-a-list"
    with pytest.raises(idom.IdentityDomainRefused, match="not a sequence"):
        idom.prove([bad])


def test_an_empty_candidate_set_proves_nothing_and_says_so() -> None:
    proof = idom.prove([])
    assert proof["candidates"] == 0
    assert proof["document_identities_proved_unique"] == 0
