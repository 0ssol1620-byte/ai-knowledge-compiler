"""SFI3_ROOT_RESERVATION_V1 -- the contract that broke a circular gate.

V2R4's INVARIANT_8 briefly required disjointness from *every lineage id in SFI3's
frozen acquisition*. The serial order is V2R4 PASS -> SFI3 acquisition -> SFI3
PASS -> four-link -> GPU, so that receipt cannot exist when V2R4 needs it: V2R4
waited on SFI3's acquisition and SFI3 waited on V2R4's PASS.

The repair reserves SFI3's source CONTAINERS in advance, from root identity
metadata alone, and has V2R4 choose outside them. This file guards the two ways
that repair could go wrong:

    the reservation reads more than identity   -- it would spend SFI3's material
    the separation proof cannot actually fail  -- it would prove nothing

`test_the_module_opens_no_sfi3_content` is the first of those, checked
structurally rather than by reading the docstring.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import replace_sfi3_roots as replacement  # noqa: E402
import sfi3_root_reservation as res  # noqa: E402
import sources_sfi3  # noqa: E402
import verify_sfi3_reservation_binding as binding  # noqa: E402


@pytest.fixture(scope="module")
def reservation():
    return res.build()


# ---------------------------------------------------------------------------
# the reservation is identity metadata, and only identity metadata


def test_the_reservation_covers_every_declared_sfi3_root(reservation):
    declared = reservation["declared_roots"]
    assert len(declared[res.FAMILY_GIT]) == len(sources_sfi3.GIT_ROOTS)
    assert len(declared[res.FAMILY_ECFR]) == len(sources_sfi3.ECFR_ROOTS)
    assert len(declared[res.FAMILY_WIKIPEDIA]) == len(sources_sfi3.WIKIPEDIA_CATEGORY_ROOTS)
    assert declared[res.FAMILY_SEC] == [], "SFI3 declares no SEC roots"


def test_the_reservation_also_covers_the_predeclared_replacement_pool(reservation):
    """Reserving only the declared roots leaves a hole the size of the policy.

    Eleven git roots and one Wikipedia category have already been replaced once.
    A later replacement drawn from outside the pool would put SFI3 into a
    container V2R4 was never told to avoid.
    """
    pool = reservation["replacement_pool"]
    assert len(pool[res.FAMILY_GIT]) == len(replacement.GIT_CANDIDATE_ROOTS)
    assert len(pool[res.FAMILY_ECFR]) == len(replacement.ECFR_CANDIDATE_ROOTS)
    assert len(pool[res.FAMILY_WIKIPEDIA]) == len(replacement.WIKIPEDIA_CANDIDATE_ROOTS)

    held = res.reserved(reservation)
    for family in (res.FAMILY_GIT, res.FAMILY_ECFR, res.FAMILY_WIKIPEDIA):
        assert set(pool[family]) <= held[family]


def test_candidates_already_promoted_are_recorded_not_refused(reservation):
    """The overlap is a fact about a replacement round that happened, not a defect.

    An earlier draft of `build` refused on it, which made the reservation
    unbuildable against the only state it was ever going to see.
    """
    promoted = reservation["already_promoted_from_the_pool"]
    assert promoted[res.FAMILY_GIT], "the 2026-08-23 git replacements are not visible"
    assert set(promoted[res.FAMILY_GIT]) <= set(reservation["declared_roots"][res.FAMILY_GIT])


def test_the_module_opens_no_sfi3_content():
    """Identity metadata only, checked on the syntax tree.

    A docstring saying "no root is expanded" is not a constraint. What this walks
    for is any call that would fetch, list, expand or open SFI3 material, and any
    attribute read outside the four declared root tuples.
    """
    tree = ast.parse(Path(res.__file__).read_text(encoding="utf-8"))

    #: Nothing that could reach a source. An earlier version of this check listed
    #: bare call names including `get`, which matches every dict lookup in the
    #: module -- a check so broad it could only ever be red. What actually
    #: distinguishes reading identity from opening content is the DEPENDENCY.
    forbidden_imports = {
        "requests",
        "httpx",
        "urllib",
        "urllib.request",
        "http_pool",
        "payload_cache",
        "fetch_corpus",
        "fetch_chains",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    reachable = sorted(
        name
        for name in imported
        if name in forbidden_imports or name.startswith("fetch_")
    )
    assert not reachable, f"the module can reach a source through {reachable}"

    #: And the only SFI3 attributes it reads are the four root tuples plus the
    #: protocol id. An expansion would have to go through one of these names.
    allowed = {"GIT_ROOTS", "ECFR_ROOTS", "WIKIPEDIA_CATEGORY_ROOTS", "SEC_ROOTS", "PROTOCOL_ID"}
    read = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sources_sfi3"
    }
    assert read <= allowed, f"the module reads {sorted(read - allowed)} from sources_sfi3"

    #: Same rule for the replacement module: candidate tuples only.
    allowed_candidates = {
        "GIT_CANDIDATE_ROOTS",
        "ECFR_CANDIDATE_ROOTS",
        "WIKIPEDIA_CANDIDATE_ROOTS",
    }
    read_candidates = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "replacement"
    }
    assert read_candidates <= allowed_candidates, (
        f"the module reads {sorted(read_candidates - allowed_candidates)} from replace_sfi3_roots"
    )


def test_the_reservation_carries_no_outcome_shaped_field(reservation):
    """No pair counts, no change outcomes, no transitions, no payload.

    A reservation that carried any of them would be a preview of SFI3's result,
    which is the thing the whole serial order exists to prevent.
    """
    #: The DATA keys only. Scanning the whole body would trip on the prose field
    #: that explains what the reservation does not carry -- the same blindness
    #: that made the first version of the launcher's endpoint check wrong, and
    #: worth naming twice because it has now been made twice.
    data_keys = {
        "declared_roots",
        "replacement_pool",
        "reserved_counts",
        "already_promoted_from_the_pool",
        "families_with_no_unused_candidate",
    }
    text = json.dumps({key: reservation[key] for key in data_keys}).lower()
    for forbidden in (
        "qualifying_pair",
        "change_outcome",
        "transition",
        "revision_content",
        "payload",
        "verdict",
        "violation",
        "pairs_scored",
    ):
        assert forbidden not in text, f"the reservation carries {forbidden!r}"

    #: And the body has no key beyond what this contract declares, so a later
    #: edit cannot smuggle an outcome in under a name this list never learned.
    known = data_keys | {
        "schema",
        "reservation_id",
        "sfi3_protocol_id",
        "frame_module",
        "frame_module_sha256",
        "replacement_module",
        "replacement_module_sha256",
        "decidable_families",
        "undecidable_families",
        "read_for",
        "what_this_does_not_carry",
        "what_exhausted_means",
        "no_post_v2r4_widening",
        "why_it_is_not_an_invariant_8_population",
        "content_digest",
        "built",
    }
    assert set(reservation) <= known, f"unexpected keys: {sorted(set(reservation) - known)}"


# ---------------------------------------------------------------------------
# verify -- a stored reservation still describes what SFI3 declares


def test_a_freshly_built_reservation_verifies(reservation):
    held = res.verify(reservation)
    assert held["held"] is True
    assert held["sfi3_protocol_id"] == sources_sfi3.PROTOCOL_ID


def test_a_moved_frame_module_is_refused(reservation):
    stale = {**reservation, "frame_module_sha256": "sha256:" + "0" * 64}
    with pytest.raises(res.ReservationRefused, match="no longer describes"):
        res.verify(stale)


def test_a_moved_replacement_module_is_refused(reservation):
    stale = {**reservation, "replacement_module_sha256": "sha256:" + "0" * 64}
    with pytest.raises(res.ReservationRefused, match="no longer describes"):
        res.verify(stale)


def test_a_changed_container_set_is_refused(reservation):
    stale = {**reservation, "content_digest": "sha256:" + "1" * 64}
    with pytest.raises(res.ReservationRefused, match="no longer describes"):
        res.verify(stale)


def test_a_reservation_for_another_protocol_is_refused(reservation):
    other = {**reservation, "sfi3_protocol_id": "SOURCE_FACT_IR_HELDOUT_V4"}
    with pytest.raises(res.ReservationRefused, match="different SFI3 protocol"):
        res.verify(other)


def test_a_foreign_schema_is_refused():
    with pytest.raises(res.ReservationRefused, match="not an SFI3 root reservation"):
        res.verify({"schema": "something.else.v1"})


def test_verify_rederives_rather_than_reading_the_stored_copy(reservation, monkeypatch):
    """Both sides of the comparison are not the same object.

    A `verify` that compared the stored reservation against itself would agree on
    every input, including a forged one.
    """
    monkeypatch.setattr(
        res, "declared_roots", lambda: {family: [] for family in reservation["declared_roots"]}
    )
    with pytest.raises(res.ReservationRefused, match="no longer describes"):
        res.verify(reservation)


# ---------------------------------------------------------------------------
# the separation proof -- and every direction it must refuse


def test_a_study_outside_the_reservation_is_separate(reservation):
    held = res.require_separation(
        reservation=reservation,
        families={
            res.FAMILY_GIT: ["some-owner/some-repo"],
            res.FAMILY_ECFR: ["49-1002"],
            res.FAMILY_SEC: [],
        },
        study="V2R4",
    )
    assert held["held"] is True
    assert held["families_checked"] == sorted(
        [res.FAMILY_GIT, res.FAMILY_ECFR, res.FAMILY_SEC]
    )
    assert "no root on either side was expanded" in held["decided_on"]


def test_a_declared_sfi3_root_collides(reservation):
    taken = reservation["declared_roots"][res.FAMILY_GIT][0]
    with pytest.raises(res.ReservationRefused, match="reserved for SFI3"):
        res.require_separation(
            reservation=reservation,
            families={res.FAMILY_GIT: [taken]},
            study="V2R4",
        )


def test_a_replacement_candidate_sfi3_has_not_used_yet_still_collides(reservation):
    """The reservation is the UNION, not the declared set.

    A container that is only a candidate today is still one SFI3 may land on
    tomorrow, after an availability failure. Reserving only what SFI3 currently
    uses would leave exactly the recovery path unprotected.
    """
    declared = set(reservation["declared_roots"][res.FAMILY_GIT])
    unused = [c for c in reservation["replacement_pool"][res.FAMILY_GIT] if c not in declared]
    assert unused, "no unused git candidate to test with"
    with pytest.raises(res.ReservationRefused, match="only a replacement candidate"):
        res.require_separation(
            reservation=reservation,
            families={res.FAMILY_GIT: [unused[0]]},
            study="V2R4",
        )


def test_an_undecidable_family_fails_closed(reservation):
    """Wikipedia membership is not decidable from metadata, so it is not decided.

    "We could not tell" and "they do not overlap" are different answers, and only
    one of them is a proof. Deciding it would mean expanding an SFI3 category --
    spending another study's prospective material to buy an argument here.
    """
    with pytest.raises(res.ReservationRefused, match="not decidable from identity metadata"):
        res.require_separation(
            reservation=reservation,
            families={res.FAMILY_WIKIPEDIA: ["Category:Something Else Entirely"]},
            study="V2R4",
        )


def test_an_undecidable_family_fails_closed_even_when_obviously_disjoint(reservation):
    """The refusal is about decidability, not about the particular value.

    A category name nothing reserves still cannot be shown not to CONTAIN a
    reserved article, which is the membership question that matters.
    """
    with pytest.raises(res.ReservationRefused):
        res.require_separation(
            reservation=reservation,
            families={res.FAMILY_WIKIPEDIA: []},
            study="V2R4",
        )


def test_a_family_the_reservation_says_nothing_about_is_refused(reservation):
    with pytest.raises(res.ReservationRefused, match="says nothing"):
        res.require_separation(
            reservation=reservation,
            families={"a_family_nobody_declared": ["x"]},
            study="V2R4",
        )


def test_the_separation_proof_verifies_the_reservation_first(reservation):
    """A separation proved against a reservation that has moved proves nothing."""
    stale = {**reservation, "content_digest": "sha256:" + "2" * 64}
    with pytest.raises(res.ReservationRefused, match="no longer describes"):
        res.require_separation(
            reservation=stale, families={res.FAMILY_SEC: []}, study="V2R4"
        )


def test_sec_is_free_for_v2r4_by_the_empty_set(reservation):
    """SFI3 declares no SEC roots, so every SEC container is available.

    Worth an explicit test because it is the one family where the correct answer
    is unconditional, and an implementation that special-cased it wrongly would
    look identical to one that got it right by accident.
    """
    assert res.reserved(reservation)[res.FAMILY_SEC] == set()
    held = res.require_separation(
        reservation=reservation,
        families={res.FAMILY_SEC: ["33214-10-K", "40000-10-Q"]},
        study="V2R4",
    )
    assert held["held"] is True


# ---------------------------------------------------------------------------
# the reverse direction -- SFI3 stays inside what it reserved


def test_sfi3s_own_declared_roots_are_inside_its_reservation(reservation):
    """The check SFI3's freeze runs before it reads a fresh payload.

    Without it the reservation constrains only V2R4, and SFI3 could quietly draw
    from a container it never reserved -- the same overlap from the other side.
    """
    held = res.require_within_reservation(
        reservation=reservation, families=reservation["declared_roots"]
    )
    assert held["held"] is True


def test_an_sfi3_root_outside_the_reservation_is_refused(reservation):
    escaping = {
        res.FAMILY_GIT: [*reservation["declared_roots"][res.FAMILY_GIT], "brand/new-repo"]
    }
    with pytest.raises(res.ReservationRefused, match="leave the reservation"):
        res.require_within_reservation(reservation=reservation, families=escaping)


def test_no_post_v2r4_widening_is_declared(reservation):
    assert "never widened" in reservation["no_post_v2r4_widening"]
    assert "circular gate" in reservation["why_it_is_not_an_invariant_8_population"]


# ---------------------------------------------------------------------------
# the CLI


def test_build_writes_no_receipt(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        res, "write_immutable", lambda stem, *a, **k: calls.append(stem) or {"receipt": "x"}
    )
    assert res.main(["build"]) == 0
    assert calls == []


def test_freeze_with_no_receipt_returns_the_body_without_writing(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        res, "write_immutable", lambda stem, *a, **k: calls.append(stem) or {"receipt": "x"}
    )
    body = res.freeze(no_receipt=True)
    assert calls == []
    assert body["reservation_id"] == res.RESERVATION_ID


def test_verify_refuses_when_no_reservation_is_named_or_found(monkeypatch, capsys):
    monkeypatch.setattr(res, "latest_reservation", lambda receipts=None: None)
    assert res.main(["verify"]) == 4
    assert "no reservation receipt" in capsys.readouterr().out


def _land_exact_binding(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(binding, "ROOT", tmp_path)
    reservation_path = tmp_path / "reservation.json"
    reservation_path.write_text(json.dumps(res.build()), encoding="utf-8")
    handoff = {
        "schema": "V2R4_SFI3_RESERVATION_HANDOFF_V1",
        "reservation": {
            "receipt": "reservation.json",
            "file_sha256": binding.sha_file(reservation_path),
        },
    }
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    monkeypatch.setattr(
        binding.handoff_contract,
        "verify",
        lambda body: {"held": True, "handoff_id": body["schema"]},
    )
    return handoff_path


def test_exact_handoff_verifies_actual_sfi3_roots_before_payload(tmp_path, monkeypatch):
    handoff = _land_exact_binding(tmp_path, monkeypatch)
    held = binding.verify_binding(
        handoff_receipt=handoff,
        handoff_sha256=binding.sha_file(handoff),
    )
    assert held["held"] is True
    assert held["reservation_id"] == res.RESERVATION_ID
    assert held["actual_root_counts"] == {
        family: len(values) for family, values in sorted(res.declared_roots().items())
    }
    assert "no payload or revision" in held["decision_basis"]


def test_wrong_exact_handoff_digest_refuses(tmp_path, monkeypatch):
    handoff = _land_exact_binding(tmp_path, monkeypatch)
    with pytest.raises(binding.BindingRefused, match="handoff file digest mismatch"):
        binding.verify_binding(
            handoff_receipt=handoff,
            handoff_sha256="sha256:" + "0" * 64,
        )


def test_actual_root_outside_reservation_refuses(tmp_path, monkeypatch):
    handoff = _land_exact_binding(tmp_path, monkeypatch)
    roots = res.declared_roots()
    roots[res.FAMILY_GIT] = [*roots[res.FAMILY_GIT], "outside/reservation"]
    with pytest.raises(binding.BindingRefused, match="leave the reservation"):
        binding.verify_binding(
            handoff_receipt=handoff,
            handoff_sha256=binding.sha_file(handoff),
            actual_roots=roots,
        )
