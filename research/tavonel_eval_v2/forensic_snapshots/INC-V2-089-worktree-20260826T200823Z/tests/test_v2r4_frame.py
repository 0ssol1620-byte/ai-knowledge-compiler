"""The V2R4 acquisition frame, its probe, its enumerator and its freeze ladder.

What these tests are for is not "the frame parses". It is the four properties a
frame can be wrong about in a way no later rung would catch:

  * it declares material an earlier study already spent
  * it declares material SFI3 is holding, which nothing yet on disk can reveal
  * it declares a quota its own probed containers cannot supply
  * it says its supply was checked when the check was a transcription

Every red control below drives one of those, and each is verified to fail for the
reason it names rather than for an unrelated one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import enumerate_v2r4_universe as enumerator  # noqa: E402
import fetch_v2r4_corpus as fetcher  # noqa: E402
import freeze_migration_closure_v2r4 as freezer  # noqa: E402
import probe_v2r4_roots as probe  # noqa: E402
import root_identity as ri  # noqa: E402
import sfi3_root_reservation as reservation  # noqa: E402
import sources_v2r4 as frame  # noqa: E402
import v2r4_attestation as att  # noqa: E402

SELF = "sources_v2r4"


# ---------------------------------------------------------------------------
# the frame declares what it says it declares


def test_the_protocol_the_frame_names_is_this_chains_protocol():
    assert frame.PROTOCOL_ID == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4"
    assert frame.ORDER_SALT == ":icmc-v2r4"


def test_the_order_salt_is_not_a_predecessors():
    """Two studies over overlapping sources must not walk them in one sequence."""
    seen = set()
    for name in ("sources_v2r1", "sources_v2r2", "sources_v2r3"):
        module = __import__(name)
        seen.add(module.ORDER_SALT)
    assert frame.ORDER_SALT not in seen


def test_the_floor_is_not_lowered():
    """Carried forward from the founder ruling, and explicitly not moved."""
    import sources_v2r3

    assert frame.FLOOR == sources_v2r3.FLOOR == 200
    assert frame.FAMILIES_REQUIRED == sources_v2r3.FAMILIES_REQUIRED == 3


def test_the_quota_sums_to_the_target_and_the_shares_sum_to_exactly_one():
    """One authoritative declaration, and a rendering of it.

    V2R2 declared quota and share by hand and they disagreed -- its shares summed
    to 0.99 against a quota that summed to its target. Exact rationals, so a test
    that allowed "close" is not needed and does not exist.
    """
    assert sum(frame.FAMILY_QUOTA.values()) == frame.PRIMARY_TARGET
    assert sum(frame.family_share_fractions().values()) == 1


def test_every_declared_family_has_a_quota_and_a_floor():
    assert set(frame.FAMILY_QUOTA) == set(frame.FAMILIES)
    assert set(frame.FAMILY_FLOOR) == set(frame.FAMILIES)
    assert sum(frame.FAMILY_FLOOR.values()) <= frame.FLOOR


def test_wikipedia_is_declared_and_excluded_never_silently_dropped():
    assert "encyclopedia_wikipedia" not in frame.FAMILIES
    why = frame.EXCLUDED_FAMILIES["encyclopedia_wikipedia"]
    assert "SFI3" in why
    assert "category" in why


# ---------------------------------------------------------------------------
# capacity: a quota its own containers cannot supply is short by construction


def test_probed_capacity_covers_every_family_quota():
    caps = frame.CONTAINER_CAP
    assert (
        len(frame.GIT_ROOTS) * caps["git_docs"] >= frame.FAMILY_QUOTA["git_docs"]
    )
    assert (
        len(frame.ECFR_ROOTS) * caps["regulation_ecfr"]
        >= frame.FAMILY_QUOTA["regulation_ecfr"]
    )


def test_every_declared_git_root_carries_its_probed_document_count():
    """"Supply was checked" is a number a reader can re-derive, not a claim."""
    for owner, repo, _prefix, _branch, _licence in frame.GIT_ROOTS:
        container = f"{owner}/{repo}"
        assert container in frame.PROBED_DOCUMENTS, container
        assert frame.PROBED_DOCUMENTS[container] >= probe.MIN_DOCUMENTS


def test_probed_documents_declares_nothing_that_is_not_a_declared_root():
    """A probed count with no root is a leftover; a root with no count is a claim."""
    declared = {f"{owner}/{repo}" for owner, repo, _p, _b, _l in frame.GIT_ROOTS}
    assert set(frame.PROBED_DOCUMENTS) == declared


def test_every_declared_ecfr_part_carries_its_probed_section_count():
    for title, part, _subject in frame.ECFR_ROOTS:
        container = f"{title}-{part}"
        assert container in frame.PROBED_MULTI_VERSION_SECTIONS, container
        assert (
            frame.PROBED_MULTI_VERSION_SECTIONS[container]
            >= probe.MIN_MULTI_VERSION_SECTIONS
        )


def test_no_ecfr_part_carries_an_empty_label():
    """The eCFR's own label, copied. An empty one means it was never fetched."""
    for title, part, subject in frame.ECFR_ROOTS:
        assert subject.strip(), f"{title}-{part} has no label"


def test_a_container_that_was_probed_and_not_declared_is_named():
    """A dropped candidate is a decision, and it is on the record."""
    assert frame.PROBED_AND_NOT_DECLARED
    why = frame.PROBED_AND_NOT_DECLARED["ClickHouse/ClickHouse"]
    assert "TRUNCATED" in why
    assert "not replaced" in why or "not declared" in why
    declared = {f"{owner}/{repo}" for owner, repo, _p, _b, _l in frame.GIT_ROOTS}
    assert set(frame.PROBED_AND_NOT_DECLARED) & declared == set()


# ---------------------------------------------------------------------------
# screen 1: nothing an earlier study declared


def test_the_frame_declares_no_root_any_earlier_study_declared():
    prior = ri.prior_root_identities(exclude_modules={SELF})
    mine = ri.read_module_roots(SELF)
    assert mine["unverifiable"] == []
    assert prior["unverifiable_count"] == 0
    assert mine["identities"] & prior["identities"] == frozenset()


def test_the_sec_start_is_strictly_above_every_spent_cik():
    """Container disjointness for the family that is declared as a rule."""
    import json
    import re

    start = frame.SEC_ISSUER_RULE["start_after_cik"]
    highest = 0
    for stem in (
        "identity-change-migration-closure-v2r1-universe",
        "identity-change-migration-closure-v2r2-universe",
        "identity-change-migration-closure-v2r3-universe",
        "identity-change-migration-closure-v2r3r1-universe",
    ):
        for path in sorted((NS / "receipts").glob(f"{stem}--*.json")):
            body = json.loads(path.read_text(encoding="utf-8"))
            for row in body.get("pairs", ()):
                match = re.match(r"sec:(\d+):", str(row["lineage_id"]))
                if match:
                    highest = max(highest, int(match.group(1)))
    assert highest > 0, "no spent SEC CIK was found; the comparison would be vacuous"
    assert start >= highest


def test_the_root_disjointness_proof_names_this_study_and_not_the_parent():
    """The defect this test exists for shipped in the first draft of the rung.

    V2R3's proof hardcodes `sources_v2r3`, so delegating to it would return a
    true statement about the WRONG study under a rung that claims to be about
    V2R4 -- the same class as the 21 of 24 V2R2 gate tests that asserted things
    about V2R1 and passed.
    """
    proof = att.prove_root_disjointness()
    assert proof["module"] == SELF
    assert proof["clashes"] == 0
    assert proof["roots_declared"] == len(ri.read_module_roots(SELF)["identities"])


def test_a_root_an_earlier_study_declared_turns_the_proof_red(monkeypatch):
    real = ri.read_module_roots(SELF)
    stolen = next(iter(ri.prior_root_identities(exclude_modules={SELF})["identities"]))

    def clashing(name: str) -> dict[str, Any]:
        body = dict(real)
        body["identities"] = real["identities"] | {stolen}
        return body

    monkeypatch.setattr(att.ri, "read_module_roots", clashing)
    with pytest.raises(att.FreezeRefused, match="an earlier study already declared"):
        att.prove_root_disjointness()


def test_an_uninterpretable_root_shape_blocks_rather_than_passing(monkeypatch):
    """UNVERIFIABLE is never assumed disjoint. That assumption is how 7 CFR 273
    entered the V2R2 frame."""
    real = ri.read_module_roots(SELF)

    def unreadable(name: str) -> dict[str, Any]:
        return {**real, "unverifiable": [{"module": name, "entry": "a shape nobody reads"}]}

    monkeypatch.setattr(att.ri, "read_module_roots", unreadable)
    with pytest.raises(att.FreezeRefused, match="cannot interpret"):
        att.prove_root_disjointness()


# ---------------------------------------------------------------------------
# screen 2: nothing SFI3 is holding -- including its replacement pool


def test_the_frame_declares_no_container_reserved_for_sfi3():
    proof = att.prove_sfi3_separation()
    assert proof["held"] is True
    assert proof["reservation_id"] == reservation.RESERVATION_ID
    assert proof["containers_checked"]["git_docs"] == len(frame.GIT_ROOTS)
    assert proof["containers_checked"]["regulation_ecfr"] == len(frame.ECFR_ROOTS)


def test_a_root_in_sfi3s_replacement_pool_is_refused_even_though_sfi3_has_not_used_it(
    monkeypatch,
):
    """The control that screen 1 CANNOT provide.

    A replacement candidate is not declared anywhere yet, so `root_identity` sees
    nothing. SFI3 may still land there after an availability failure, and a V2R4
    root sitting in the pool would silently narrow SFI3's escape route.
    """
    pool = reservation.replacement_pool()[reservation.FAMILY_GIT]
    assert pool, "the pool is empty; this control would be vacuous"
    candidate = sorted(pool)[0]

    prior = ri.prior_root_identities(exclude_modules={SELF})["identities"]
    owner, repo = candidate.split("/")
    assert not any(
        entry[0] == "git" and entry[1] == owner and entry[2] == repo for entry in prior
    ), "the candidate is already declared, so screen 1 would catch it and this proves nothing"

    families = dict(frame.declared_containers())
    families["git_docs"] = [*families["git_docs"], candidate]
    monkeypatch.setattr(frame, "declared_containers", lambda: families)
    with pytest.raises(reservation.ReservationRefused, match="reserved for SFI3"):
        att.prove_sfi3_separation()


def test_declaring_a_wikipedia_root_fails_closed_rather_than_being_reported_clean(
    monkeypatch,
):
    """"We could not tell" and "they do not overlap" are different answers."""
    families = {**frame.declared_containers(), "encyclopedia_wikipedia": ["Some_Article"]}
    monkeypatch.setattr(frame, "declared_containers", lambda: families)
    with pytest.raises(reservation.ReservationRefused, match="not decidable"):
        att.prove_sfi3_separation()


def test_a_family_the_reservation_says_nothing_about_is_refused(monkeypatch):
    families = {**frame.declared_containers(), "a_family_nobody_reserved": ["x"]}
    monkeypatch.setattr(frame, "declared_containers", lambda: families)
    with pytest.raises(reservation.ReservationRefused, match="says nothing about"):
        att.prove_sfi3_separation()


def test_sec_is_reported_as_checked_and_empty_not_as_absent():
    """A family the reservation covers and finds empty is not a family it skipped."""
    containers = frame.declared_containers()
    assert containers["sec_edgar"] == []
    assert reservation.FAMILY_SEC in reservation.reserved()


# ---------------------------------------------------------------------------
# the probe asks nothing it is forbidden to ask


def test_the_probe_names_the_questions_section_f_forbids():
    forbidden = set(probe.FORBIDDEN_QUESTIONS)
    for phrase in (
        "revision content",
        "qualifying change counts",
        "ambiguity counts",
        "quarantine counts",
        "invariant outcomes",
        "facet transitions",
    ):
        assert phrase in forbidden


def test_the_probe_screens_before_it_reaches_the_network(monkeypatch):
    """A spent or reserved container is never even asked about."""
    calls: list[str] = []
    monkeypatch.setattr(
        probe, "get_json", lambda url, **kw: calls.append(url) or {}
    )
    state = probe.screens()
    reserved_repo = sorted(state["reserved"][reservation.FAMILY_GIT])[0]
    owner, repo = reserved_repo.split("/")
    keep, dropped = probe.screen_git([(owner, repo, "docs", "main")], state=state)
    assert keep == []
    assert dropped[0]["why"] == "inside SFI3_ROOT_RESERVATION_V1"
    assert calls == []


def test_a_part_with_section_history_but_no_live_container_is_not_declarable():
    """Title 39 part 3004 has 20 multi-version sections and is not in the CFR.

    Supply counted from version history is not proof the container is usable,
    which is the one question a capacity probe exists to answer. This is a LIVE
    call, deliberately: a fixture would prove only that the fixture says so.

    An unreachable eCFR SKIPS with the reason rather than failing, because "the
    source was down" and "the probe is wrong" are different findings. It does not
    skip silently and it does not pass: a control that reports green without
    running is worse than one that reports why it could not.
    """
    state = probe.screens()
    try:
        rows = {
            row["container"]: row for row in probe.probe_ecfr_title("39", state=state)
        }
    except OSError as error:  # network, DNS, TLS, timeout
        pytest.skip(f"the eCFR is unreachable, so the probe could not be exercised: {error}")

    dead = rows.get("39-3004")
    assert dead is not None, "the part no longer reports supply; the control is vacuous"
    assert dead["declarable"] is False
    assert "no longer present" in dead["why"]

    #: The part is not in the frame, and that assertion needs no network at all.
    assert "39-3004" not in {f"{t}-{p}" for t, p, _s in frame.ECFR_ROOTS}


def test_no_declared_part_is_one_the_probe_marked_undeclarable():
    """The offline half of the control above, so a skip does not lose everything."""
    declared = {f"{title}-{part}" for title, part, _s in frame.ECFR_ROOTS}
    assert declared, "no parts declared; the check would be vacuous"
    assert set(frame.PROBED_MULTI_VERSION_SECTIONS) == declared


# ---------------------------------------------------------------------------
# INC-V2-076: a truncated read that reported itself as complete


def test_the_probe_refuses_a_truncated_versions_response(monkeypatch):
    """A partial supply reading that reports itself as complete is the defect.

    The endpoint pages at 1,000 rows and declares the truth in `meta`. Handing
    the probe a response whose meta says 3,350 rows exist while returning 10 must
    RAISE -- not return 10 and let a ranking rule treat it as the population.
    """
    monkeypatch.setattr(
        probe,
        "get_json",
        lambda url, **kw: {
            "content_versions": [{"type": "section", "identifier": "1.1", "date": "2024-01-01"}]
            * 10,
            "meta": {"result_count": "3350", "total_pages": "1"},
        },
    )
    with pytest.raises(probe.ProbeRefused, match="truncated response"):
        probe.title_versions("2")


def test_the_probe_follows_every_page_the_meta_declares(monkeypatch):
    """Four pages declared, four pages read, and the rows are concatenated."""
    seen: list[str] = []

    def paged(url, **kw):
        seen.append(url)
        return {
            "content_versions": [
                {"type": "section", "identifier": f"p{len(seen)}", "date": "2024-01-01"}
            ],
            "meta": {"result_count": "4", "total_pages": "4"},
        }

    monkeypatch.setattr(probe, "get_json", paged)
    rows = probe.title_versions("2")
    assert len(rows) == 4
    assert len(seen) == 4
    assert [url for url in seen if "page=" in url] == [
        seen[0] + "?page=2",
        seen[0] + "?page=3",
        seen[0] + "?page=4",
    ]


def test_a_single_page_title_issues_one_call(monkeypatch):
    """No spurious page 2 when the meta says there is only one."""
    calls: list[str] = []

    def once(url, **kw):
        calls.append(url)
        return {"content_versions": [], "meta": {"result_count": "0", "total_pages": "1"}}

    monkeypatch.setattr(probe, "get_json", once)
    assert probe.title_versions("3") == []
    assert len(calls) == 1


def test_no_declared_part_needs_more_than_one_fetcher_page():
    """The acquisition fetcher does not paginate, so the frame must not need it.

    A part the fetcher can only half-read would have its traversal restricted to
    whatever page 1 held -- deterministic, but NOT the traversal this frame
    declares. The base is V2R2 tooling and is not edited, so the constraint lives
    in the frame, and the six parts that failed it are excluded BY NAME.
    """
    excluded = set(frame.PROBED_AND_NOT_DECLARED)
    declared = {f"{title}-{part}" for title, part, _s in frame.ECFR_ROOTS}
    assert excluded & declared == set()
    oversized = {
        container
        for container, why in frame.PROBED_AND_NOT_DECLARED.items()
        if "follow pagination" in why
    }
    assert oversized, "no oversized part is recorded; this control would be vacuous"
    assert oversized <= excluded


def test_the_frame_records_why_pagination_is_followed():
    """The reasoning is in the frame, not only in a commit message."""
    probe_block = frame.AVAILABILITY_PROBE
    assert "why_pagination_is_followed" in probe_block
    assert "INC-V2-076" in probe_block["why_pagination_is_followed"]
    assert "every_declared_part_is_readable_in_one_fetcher_page" in probe_block


def test_the_probe_module_opens_no_revision_content():
    """An AST check, not a text scan.

    Scanning the source for forbidden words trips on the prose EXPLAINING the
    prohibition, which this module has a great deal of. The imports are what
    decide whether it can open a payload.
    """
    import ast

    tree = ast.parse(Path(probe.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("payload_cache", "fetch_v2r2_corpus", "fetch_v2r4_corpus", "canonical_document"):
        assert banned not in imported


# ---------------------------------------------------------------------------
# the enumerator excludes what V2R3R1 spent


def test_the_enumerator_excludes_the_three_hundred_v2r3r1_measured():
    spent = enumerator.v2r3_lineage_spent_set()
    assert spent["lineage_count"] == 300
    assert spent["union_across_both_chains"] is True
    assert len(spent["sources_present"]) >= 2


def test_the_enumerator_reads_lineage_ids_and_no_verdict():
    spent = enumerator.v2r3_lineage_spent_set()
    assert "lineage ids only" in spent["read_for"]
    for row in spent["_ids"]:
        assert isinstance(row, str)


def test_nothing_v2r3_excluded_is_dropped_by_v2r4():
    """This study is not narrower than its predecessor anywhere."""
    parent_ids = {entry["id"] for entry in enumerator._PARENT_EXCLUDED_SETS()}
    mine = {entry["id"] for entry in enumerator.excluded_sets()}
    assert parent_ids <= mine
    assert "v2r3_and_v2r3r1_spent_300" in mine


def test_an_absent_predecessor_universe_refuses_rather_than_excluding_nothing(
    monkeypatch, tmp_path
):
    """A disjointness proof against an empty set proves nothing."""
    monkeypatch.setattr(enumerator, "NS", tmp_path)
    (tmp_path / "receipts").mkdir()
    with pytest.raises(RuntimeError, match="cannot be subtracted"):
        enumerator.v2r3_lineage_spent_set()


def test_the_enumerator_writes_into_this_chains_corpus_and_not_a_predecessors():
    assert enumerator.OUR_REL.endswith("v2r4_corpus")
    assert enumerator.CORPUS.name == "v2r4_corpus"
    assert "v2r4" in enumerator.SCHEMA


# ---------------------------------------------------------------------------
# the ladder refuses when a rung it depends on is missing
#
# THESE WERE WRITTEN AGAINST A MOMENT AND NOW TEST A MECHANISM. Four controls
# here asserted "nothing is frozen yet" and passed for as long as that sentence
# happened to be true. The chain then legitimately froze rungs 0, 1 and 3 and
# acquired its corpus, and all four went red -- not because a guard broke, but
# because the world moved past the state they had pinned. INC-V2-079.
#
# A control written against a calendar expires and then fails for the wrong
# reason, which is worse than not existing: it costs a real investigation and
# teaches the reader to expect red. Each is now driven by an EMPTY RECEIPTS
# DIRECTORY, so the refusal is caused by the absence the guard exists to catch
# and stays true at every point in the chain's life.


def _bare(tmp_path: Path) -> Any:
    """A workspace whose receipts directory is empty, at any point in the chain.

    `prior_receipts` still points at the real one: the predecessors' receipts are
    not what these controls are about, and hiding them would make a refusal
    ambiguous between "this rung is missing" and "the whole tree is missing".
    """
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    return freezer.V2R4Workspace(receipts=receipts)


def test_the_fetcher_refuses_without_a_rung_zero_receipt(tmp_path):
    empty = tmp_path / "receipts"
    empty.mkdir()
    with pytest.raises(fetcher.FrameNotFrozen, match="no rung-0 V2R4"):
        fetcher.require_frozen_frame(receipts=empty)


def test_exactly_one_v2r4_measurement_closed_the_chain(tmp_path):
    """The founder-ratified V2R4 result exists once and cannot be rescored."""
    ws = freezer.workspace()
    stem = freezer.base.stem_for(freezer.base.load_protocol(ws.protocol), "measurement")
    assert sorted(path.name for path in ws.receipts.glob(f"{stem}--*.json")) == [
        "identity-change-migration-closure-v2r4--20260826T064947Z-e6cab21d2c93.json"
    ]


def test_the_pre_acquisition_guard_still_fires_on_an_untouched_chain(monkeypatch, tmp_path):
    """The guard that rungs 0 and 1 shut on, driven where its answer is the one
    it was written for. Asserting it against the live tree tested the calendar.

    `CORPUS` is a module global rather than a workspace field, so an empty
    receipts directory alone does not make a chain untouched -- the acquired
    material is the other half of what this guard reads."""
    monkeypatch.setattr(freezer, "CORPUS", tmp_path / "v2r4_corpus")
    ready, blocking = freezer._nothing_has_been_measured(_bare(tmp_path))
    assert ready is True, blocking
    assert blocking == []


def test_the_pre_acquisition_guard_reports_what_blocks_it_on_the_live_chain():
    """And on the live tree it must be CLOSED, naming both reasons. A guard that
    answered the same way before and after acquisition would not be a guard."""
    ready, blocking = freezer._nothing_has_been_measured(freezer.workspace())
    assert ready is False
    assert any("acquired material exists" in reason for reason in blocking)
    assert any("universe" in reason for reason in blocking)


def test_the_freezer_seals_every_attestation_rung_the_protocol_declares():
    import yaml

    stems = yaml.safe_load(freezer.PROTOCOL.read_text(encoding="utf-8"))["freeze"]["stems"]
    declared = {key for key in stems if key.endswith("_attestation")}
    assert declared == set(freezer.COMPANIONS)
    assert set(att.RUNGS) == declared


def test_the_freezer_points_at_this_chain_and_not_a_predecessors():
    assert freezer.PROTOCOL.name.endswith("V2R4.yaml")
    assert freezer.FRAME_MODULE.name == "sources_v2r4.py"
    assert freezer.CORPUS.name == "v2r4_corpus"
    assert freezer.MEASUREMENT_GLOB.startswith("identity-change-migration-closure-v2r4--")
    assert freezer.workspace().protocol == freezer.PROTOCOL


def test_importing_the_adapter_does_not_rebind_the_shared_base():
    """A permanent rebind makes correctness depend on which adapter imported last."""
    import freeze_migration_closure_v2r1 as base

    assert base.PROTOCOL != freezer.PROTOCOL
    assert base.FRAME_MODULE != freezer.FRAME_MODULE


def test_the_bindings_are_restored_even_when_a_rung_raises():
    import freeze_migration_closure_v2r1 as base

    before = {name: getattr(base, name) for name in freezer._bindings()}
    with pytest.raises(RuntimeError, match="deliberate"), freezer._bound():
        assert base.PROTOCOL == freezer.PROTOCOL
        raise RuntimeError("deliberate")
    assert {name: getattr(base, name) for name in freezer._bindings()} == before


def test_every_overridden_stage_existed_in_the_base():
    freezer._require_every_overridden_stage_exists()


def _protocol() -> dict[str, Any]:
    import yaml

    return yaml.safe_load(freezer.PROTOCOL.read_text(encoding="utf-8"))


def test_the_declared_attestation_rungs_and_the_companion_table_agree():
    assert freezer._require_every_declared_companion_is_wired(_protocol()) == set(
        freezer.COMPANIONS
    )


def test_a_companion_table_with_a_rung_the_protocol_never_declared_refuses(monkeypatch):
    monkeypatch.setitem(freezer.COMPANIONS, "an_extra_attestation", (None, None))
    with pytest.raises(freezer.FreezeRefused, match="wired not declared"):
        freezer._require_every_declared_companion_is_wired(_protocol())


def test_a_protocol_rung_the_companion_table_never_wired_refuses():
    protocol = _protocol()
    protocol["freeze"]["stems"]["a_fifth_attestation"] = "some-stem"
    with pytest.raises(freezer.FreezeRefused, match="declared not wired"):
        freezer._require_every_declared_companion_is_wired(protocol)


def test_the_wiring_check_does_not_run_at_import():
    """An import-time protocol read makes every importer inherit disk state.

    The check reads the protocol it is HANDED, so it cannot be reaching for one
    at import. Verified structurally: the module body must not call it.
    """
    import ast

    tree = ast.parse(Path(freezer.__file__).read_text(encoding="utf-8"))
    called_at_module_level = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "_require_every_declared_companion_is_wired" not in called_at_module_level
    assert "require_protocol_binding" not in called_at_module_level


def test_the_protocol_is_bound_by_digest_and_not_merely_named():
    """`PROTOCOL` is a PATH. Until a digest is compared, it is a filename.

    Rung 1 has frozen, so the binding now SUCCEEDS -- and the thing to check is
    that it compares a digest against the file on disk rather than a name.
    """
    receipt = freezer.require_protocol_binding()
    assert receipt["protocol_sha256"] == att.att._sha_file(freezer.PROTOCOL)


def test_the_binding_refuses_when_rung_one_is_missing(tmp_path):
    with pytest.raises(freezer.FreezeRefused, match="rung 1 is missing"):
        freezer.require_protocol_binding(_bare(tmp_path))


def test_the_binding_refuses_when_the_protocol_file_has_moved(monkeypatch, tmp_path):
    """The half a name comparison cannot catch: same filename, different bytes."""
    forged = tmp_path / freezer.PROTOCOL.name
    forged.write_text(
        freezer.PROTOCOL.read_text(encoding="utf-8") + "\n# a byte that was not sealed\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(freezer, "PROTOCOL", forged)
    monkeypatch.setattr(freezer.base, "PROTOCOL", forged)
    with pytest.raises(freezer.FreezeRefused):
        freezer.require_protocol_binding(freezer.V2R4Workspace(protocol=forged))


def test_the_gate_refuses_when_a_required_rung_is_missing(tmp_path):
    """Named for the mechanism. The original named rung 1, and when rung 1 froze
    it started matching rung 3's message instead -- a test that passed for one
    reason and then failed for another, both of them correct behaviour."""
    with pytest.raises(freezer.FreezeRefused, match="rung 1 is missing"):
        freezer.require_v2r4_execution_preconditions(_bare(tmp_path))


def test_the_gate_reports_ready_on_the_fully_sealed_live_chain():
    """The measurement preserves the READY precondition; the live gate is shut.

    THIS TEST IS THE FOURTH INSTANCE OF THE CLASS ABOVE, and it was written in the
    repair FOR that class. Its first version asserted `rung 3 is missing` --
    true when the scorer was unfrozen, false twenty minutes later when rung 4
    sealed. Naming a specific unfrozen rung on a chain that is still being built
    pins a moment however carefully the name is chosen; the only live assertion
    that does not expire is the one about the chain's FINAL state.

    So: the one authoritative measurement records every rung sealed and READY,
    while asking the gate again now refuses because the measurement already
    exists.  This proves both the historical authority and the no-rescore guard.
    """
    receipt = next(
        freezer.workspace().receipts.glob(
            "identity-change-migration-closure-v2r4--20260826T064947Z-e6cab21d2c93.json"
        )
    )
    recorded = json.loads(receipt.read_text(encoding="utf-8"))["preconditions"]
    assert recorded["state"] == "READY"
    assert set(recorded["companion_attestations"]) == set(freezer.COMPANIONS)
    assert [row["name"] for row in recorded["chain"]] == [
        "protocol",
        "universe",
        "scorer_acceptance",
        "exclusions",
    ]
    with pytest.raises(freezer.FreezeRefused, match="EXACTLY ONCE"):
        freezer.require_v2r4_execution_preconditions()


def test_freezing_the_frame_refuses_once_material_has_been_acquired(monkeypatch, tmp_path):
    """The frame is sealed BEFORE acquisition, or the freeze records rather than
    constrains."""
    corpus = tmp_path / "v2r4_corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(freezer, "CORPUS", corpus)
    with pytest.raises(freezer.FreezeRefused, match="already holds acquired material"):
        freezer.freeze_acquisition_frame()


# ---------------------------------------------------------------------------
# rung 3a: the spent-disjointness proof covers EVERY spent cohort
#
# INC-V2-077. The first draft delegated to V2R3's proof, which iterates V2R3's
# spent list -- v2r1 and v2r2, the only cohorts that existed when it was written.
# The sealed receipt reported `holds` over the two OLDEST cohorts and was silent
# on the 300 lineages V2R3R1 measured: the nearest, most recently drawn, most
# likely to overlap material in the programme.
#
# Nothing was contaminated -- every intersection is empty, checked. What was
# wrong is the SCOPE of the sealed sentence. Silence is not disjointness, and a
# delegated proof cannot fail loudly because nothing it asserts is false.


def test_the_spent_disjointness_proof_names_all_four_cohorts_not_the_parents_two():
    ws = freezer.workspace()
    proof = att.prove_spent_disjointness(ws)
    assert {row["study"] for row in proof["sources"]} == {"v2r1", "v2r2", "v2r3", "v2r3r1"}
    assert proof["cohorts_checked"] == 4
    assert set(proof["intersections"]) == {"v2r1", "v2r2", "v2r3", "v2r3r1"}


def test_the_proof_does_not_inherit_the_parents_spent_list():
    """The green above would still pass if this module simply re-exported the
    parent's constant and the parent had grown two entries. It has not."""
    import v2r3_attestation as parent

    assert att.SPENT_UNIVERSE_STEMS is not parent.SPENT_UNIVERSE_STEMS
    assert {row[0] for row in parent.SPENT_UNIVERSE_STEMS} == {"v2r1", "v2r2"}
    assert {row[0] for row in att.SPENT_UNIVERSE_STEMS} == {
        "v2r1",
        "v2r2",
        "v2r3",
        "v2r3r1",
    }


def test_the_nearest_spent_cohort_is_the_one_the_delegated_proof_omitted():
    """V2R3R1 is not just another entry. Its 300 lineages were carried forward
    from V2R3 unscored and MEASURED there, and they are drawn from the families
    V2R4 draws from."""
    ws = freezer.workspace()
    proof = att.prove_spent_disjointness(ws)
    nearest = {row["study"]: row for row in proof["sources"]}["v2r3r1"]
    assert nearest["spent_lineages"] == 300
    assert nearest["intersection"] == 0


def test_an_overlap_with_any_spent_cohort_turns_the_proof_red(monkeypatch):
    """Red control on the proof itself, driven through the cohort it was silent
    about -- a control aimed only at v2r1 would have passed against the defect."""
    ws = freezer.workspace()
    real_latest = att.base.latest_receipt

    universe = real_latest(
        att.base.stem_for(att.base.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    stolen = str(universe["pairs"][0]["lineage_id"])

    real_read = Path.read_text

    def contaminated(self: Path, *args: Any, **kwargs: Any) -> str:
        text = real_read(self, *args, **kwargs)
        if "v2r3r1-universe--" not in self.name:
            return text
        import json as _json

        body = _json.loads(text)
        body["pairs"] = [*list(body["pairs"])[:-1], {"lineage_id": stolen}]
        return _json.dumps(body)

    monkeypatch.setattr(Path, "read_text", contaminated)
    with pytest.raises(att.FreezeRefused, match="V2R3R1"):
        att.prove_spent_disjointness(ws)


def test_a_spent_cohort_whose_size_has_moved_turns_the_proof_red(monkeypatch):
    ws = freezer.workspace()
    monkeypatch.setattr(
        att,
        "SPENT_UNIVERSE_STEMS",
        (("v2r3r1", "identity-change-migration-closure-v2r3r1-universe", 299),),
    )
    with pytest.raises(att.FreezeRefused, match="not the 299"):
        att.prove_spent_disjointness(ws)


def test_a_named_cohort_with_no_receipt_on_disk_blocks_rather_than_passing(monkeypatch):
    """An unprovable disjointness is not an assumed one."""
    ws = freezer.workspace()
    monkeypatch.setattr(
        att,
        "SPENT_UNIVERSE_STEMS",
        (("v2r9", "identity-change-migration-closure-v2r9-universe", 1),),
    )
    with pytest.raises(att.FreezeRefused, match="is not on disk"):
        att.prove_spent_disjointness(ws)


def test_the_sealed_attestation_covers_every_cohort_the_proof_now_computes():
    """The chain in force, not the code. A repair that was written and never
    re-sealed leaves the same receipt on disk as no repair at all."""
    ws = freezer.workspace()
    result = att.verify_universe(ws)
    assert set(result["recomputed"]["intersections"]) == {
        "v2r1",
        "v2r2",
        "v2r3",
        "v2r3r1",
    }


def test_a_sealed_attestation_covering_fewer_cohorts_is_refused_with_a_sentence(
    monkeypatch,
):
    """A `zip(..., strict=True)` catches this as a bare ValueError, and a
    non-strict zip compares the cohorts they share and reports agreement."""
    ws = freezer.workspace()
    real = att._read

    def narrowed(stem_key: str, workspace: Any) -> dict[str, Any]:
        receipt = real(stem_key, workspace)
        if stem_key != "universe_attestation":
            return receipt
        body = dict(receipt)
        proof = dict(body["spent_disjointness"])
        proof["sources"] = [
            row for row in proof["sources"] if row["study"] in {"v2r1", "v2r2"}
        ]
        body["spent_disjointness"] = proof
        return body

    monkeypatch.setattr(att, "_read", narrowed)
    with pytest.raises(att.FreezeRefused, match="different set of spent cohorts"):
        att.verify_universe(ws)
