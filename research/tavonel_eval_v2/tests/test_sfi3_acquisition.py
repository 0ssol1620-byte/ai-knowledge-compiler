"""SFI3 acquisition frame and expansion tool. Fixtures only — no network, no cohort.

Every test here runs against synthetic lineage lists and receipts written into
`tmp_path`. Nothing fetches, nothing canonicalises, nothing classifies and
nothing touches a real cohort lineage: `SOURCE_FACT_IR_HELDOUT_V1` was demoted
for exactly that failure mode, and a smoke test that executes against real
lineages would spend the very corpus SFI3 exists to be held out from.

The one place real artifacts are named is the disjointness check against
`sources_sfi1` / `sources_sfi2` / `sources_vbc2` / `sources_p4i`'s declared
roots, which reads those modules' module-level tuples — importing a sibling
module and comparing literals, not fetching anything. `sources_sfi3` itself
also reads one real receipt at import time (SFI2's E5/E6 forensic set) for the
same reason: it is an identity list, not a revision body.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition"):
    if str(NS / _sub) not in sys.path:
        sys.path.insert(0, str(NS / _sub))
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import freeze_sfi3_lineages as expand  # noqa: E402
import sfi3_worker as worker  # noqa: E402
import sources_p4i as p4i  # noqa: E402
import sources_sfi1 as sfi1  # noqa: E402
import sources_sfi2 as sfi2  # noqa: E402
import sources_sfi3 as frame_module  # noqa: E402
import sources_vbc2 as vbc2  # noqa: E402

# --- fixtures -----------------------------------------------------------------


def _lineage(lineage_id: str, family: str = "git_docs") -> dict[str, Any]:
    return {
        "lineage_id": lineage_id,
        "family": family,
        "suffix": ".md",
        "licence": "MIT",
    }


def _write_frame(path: Path, lineages: list[dict[str, Any]]) -> Path:
    path.write_text(
        json.dumps({"lineage_count": len(lineages), "lineages": lineages}),
        encoding="utf-8",
    )
    return path


def _write_sfi1_frame(path: Path, lineage_ids: list[str]) -> Path:
    path.write_text(
        json.dumps({"candidates": len(lineage_ids), "lineages": [
            _lineage(lineage_id) for lineage_id in lineage_ids
        ]}),
        encoding="utf-8",
    )
    return path


def _write_sfi1_acquisition(path: Path, *, admitted: list[str], rejected: list[str]) -> Path:
    path.write_text(
        json.dumps(
            {
                "admitted": [{"lineage_id": lineage_id} for lineage_id in admitted],
                "rejected": [
                    {"lineage_id": lineage_id, "code": "TOO_FEW_REVISIONS"}
                    for lineage_id in rejected
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_sfi2_frame(path: Path, lineage_ids: list[str]) -> Path:
    path.write_text(
        json.dumps({"candidates": len(lineage_ids), "lineages": [
            _lineage(lineage_id) for lineage_id in lineage_ids
        ]}),
        encoding="utf-8",
    )
    return path


def _write_sfi2_acquisition(
    path: Path, *, admitted: list[str], rejected: list[str]
) -> Path:
    path.write_text(
        json.dumps(
            {
                "admitted": [
                    {"lineage_id": lineage_id, "family": "git_docs",
                     "facts": {"after": ["irrelevant content"]}}
                    for lineage_id in admitted
                ],
                "rejected": [
                    {"lineage_id": lineage_id, "family": "git_docs", "code": "TOO_FEW_REVISIONS"}
                    for lineage_id in rejected
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_forensic_receipt(path: Path, lineage_ids: list[str]) -> Path:
    """A fixture standing in for `receipts/latest/sfi2-native-provenance.json`,
    already resolved to the immutable body shape (not the pointer)."""
    path.write_text(
        json.dumps(
            {
                "rebuild": {
                    "E5_confirmed_selective_stale_escape": {
                        "confirmed": [
                            {"lineage_id": lineage_id} for lineage_id in lineage_ids
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_forensic_pointer(path: Path, points_to: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "tavonel.v2.receipt_pointer.v1",
                "note": "NOT EVIDENCE. Cite the file it names, never this one.",
                "points_to": str(points_to.relative_to(frame_module.ROOT)).replace("\\", "/"),
            }
        ),
        encoding="utf-8",
    )
    return path


# --- 1. the V3 frame's roots are disjoint from every predecessor's, computed --


def test_git_roots_are_disjoint_from_predecessors() -> None:
    def keys(roots: Any) -> set[tuple[str, str]]:
        return {(root["owner"], root["repo"]) for root in roots}

    sfi3_git = keys(frame_module.GIT_ROOTS)
    assert sfi3_git, "the SFI3 git roots are empty; nothing to check disjointness of"
    assert sfi3_git.isdisjoint(keys(sfi1.GIT_ROOTS))
    assert sfi3_git.isdisjoint(keys(sfi2.GIT_ROOTS))
    assert sfi3_git.isdisjoint(keys(vbc2.GIT_ROOTS))
    assert sfi3_git.isdisjoint(keys(p4i.GIT_REPOSITORIES_ALL))


def test_ecfr_roots_are_disjoint_from_predecessors() -> None:
    def keys(roots: Any) -> set[tuple[str, str]]:
        return {(title, part) for title, part, _ in roots}

    sfi3_ecfr = keys(frame_module.ECFR_ROOTS)
    assert sfi3_ecfr
    assert sfi3_ecfr.isdisjoint(keys(sfi1.ECFR_ROOTS))
    assert sfi3_ecfr.isdisjoint(keys(sfi2.ECFR_ROOTS))
    assert sfi3_ecfr.isdisjoint(keys(vbc2.ECFR_ROOTS))
    assert sfi3_ecfr.isdisjoint(keys(p4i.ECFR_PARTS_ALL))


def test_wikipedia_category_roots_are_disjoint_from_predecessors() -> None:
    sfi3_categories = set(frame_module.WIKIPEDIA_CATEGORY_ROOTS)
    assert sfi3_categories
    assert sfi3_categories.isdisjoint(set(sfi1.WIKIPEDIA_CATEGORY_ROOTS))
    assert sfi3_categories.isdisjoint(set(sfi2.WIKIPEDIA_CATEGORY_ROOTS))
    assert sfi3_categories.isdisjoint(set(vbc2.WIKIPEDIA_CATEGORY_ROOTS))


def test_no_root_list_has_an_internal_duplicate() -> None:
    """A root repeated within SFI3's own declaration would silently overweight it."""
    git_keys = [(root["owner"], root["repo"]) for root in frame_module.GIT_ROOTS]
    ecfr_keys = [(title, part) for title, part, _ in frame_module.ECFR_ROOTS]
    assert len(git_keys) == len(set(git_keys))
    assert len(ecfr_keys) == len(set(ecfr_keys))
    assert len(frame_module.WIKIPEDIA_CATEGORY_ROOTS) == len(
        set(frame_module.WIKIPEDIA_CATEGORY_ROOTS)
    )


# --- 2. the spent set unions everything SFI2 spent, SFI2's own frame and
#        executor, and the fourteen E5/E6 forensic cases -----------------------


def test_spent_lineages_unions_sfi2_inheritance_frame_acquisition_and_forensic(
    tmp_path: Path,
) -> None:
    """Computed from fixtures standing in for SFI2's two artifacts and the
    E5/E6 forensic receipt.

    The fixture frame lists five candidate identities; the fixture acquisition
    admits two and rejects two of them (the fifth was never reached by the
    executor but was still listed, so it must still be spent). None of the ids
    overlap `sources_sfi2.spent_lineages()`'s own contribution or the forensic
    fourteen, so the union can be checked precisely.
    """
    sfi2_frame_ids = [
        "git:fixture/sfi2-listed-one:docs/a.md",
        "git:fixture/sfi2-listed-two:docs/b.md",
        "git:fixture/sfi2-admitted-one:docs/c.md",
        "git:fixture/sfi2-admitted-two:docs/d.md",
        "git:fixture/sfi2-rejected-one:docs/e.md",
    ]
    frame_fixture = _write_sfi2_frame(tmp_path / "sfi2_lineages.json", sfi2_frame_ids)
    acquisition_fixture = _write_sfi2_acquisition(
        tmp_path / "sfi2_acquisition.json",
        admitted=["git:fixture/sfi2-admitted-one:docs/c.md",
                  "git:fixture/sfi2-admitted-two:docs/d.md"],
        rejected=["git:fixture/sfi2-rejected-one:docs/e.md"],
    )
    forensic_ids = [f"git:fixture/e5e6-{index}:docs/case.md" for index in range(14)]
    forensic_fixture = _write_forensic_receipt(
        tmp_path / "sfi2-native-provenance.json", forensic_ids
    )
    #: tiny stand-ins for SFI1's real ~100MB frame and executor output, so this
    #: test does not have to read them to exercise the union.
    sfi1_frame_ids = ["git:fixture/sfi1-listed:docs/z.md"]
    sfi1_frame_fixture = _write_sfi1_frame(tmp_path / "sfi1_lineages.json", sfi1_frame_ids)
    sfi1_acquisition_fixture = _write_sfi1_acquisition(
        tmp_path / "sfi1_acquisition.json", admitted=["git:fixture/sfi1-listed:docs/z.md"],
        rejected=[],
    )

    spent = frame_module.spent_lineages(
        sfi1_frame=sfi1_frame_fixture,
        sfi1_acquisition=sfi1_acquisition_fixture,
        sfi2_frame=frame_fixture,
        sfi2_acquisition=acquisition_fixture,
        sfi2_forensic_receipt=forensic_fixture,
    )

    #: every id SFI2's frame listed, admitted or not
    assert set(sfi2_frame_ids) <= spent
    #: the fourteen SFI2 E5/E6 forensic diagnostic cases
    assert set(forensic_ids) <= spent
    #: the original four SFI1 forensic cases, reused through sfi2
    assert set(sfi1.FORENSIC_LINEAGES) <= spent
    #: SFI1's own frame, substituted above, is present in the union too
    assert set(sfi1_frame_ids) <= spent
    #: sources_sfi2.spent_lineages()'s own contribution (SFH1 + VBC2, the real,
    #: cheap part of it) is present too
    assert sfi1.spent_lineages() <= spent


def test_spent_lineages_raises_rather_than_silently_shrinking(tmp_path: Path) -> None:
    """A missing SFI2 artifact must raise, not quietly produce a smaller spent set."""
    sfi1_frame_fixture = _write_sfi1_frame(tmp_path / "sfi1_lineages.json", [])
    sfi1_acquisition_fixture = _write_sfi1_acquisition(
        tmp_path / "sfi1_acquisition.json", admitted=[], rejected=[]
    )
    real_acquisition = _write_sfi2_acquisition(
        tmp_path / "sfi2_acquisition.json", admitted=[], rejected=[]
    )
    real_forensic = _write_forensic_receipt(tmp_path / "forensic.json", [])

    missing_frame = tmp_path / "does-not-exist-frame.json"
    with pytest.raises(FileNotFoundError):
        frame_module.spent_lineages(
            sfi1_frame=sfi1_frame_fixture,
            sfi1_acquisition=sfi1_acquisition_fixture,
            sfi2_frame=missing_frame,
            sfi2_acquisition=real_acquisition,
            sfi2_forensic_receipt=real_forensic,
        )

    real_frame = _write_sfi2_frame(tmp_path / "sfi2_lineages.json", [])
    missing_acquisition = tmp_path / "does-not-exist-acquisition.json"
    with pytest.raises(FileNotFoundError):
        frame_module.spent_lineages(
            sfi1_frame=sfi1_frame_fixture,
            sfi1_acquisition=sfi1_acquisition_fixture,
            sfi2_frame=real_frame,
            sfi2_acquisition=missing_acquisition,
            sfi2_forensic_receipt=real_forensic,
        )

    missing_forensic = tmp_path / "does-not-exist-forensic.json"
    with pytest.raises(FileNotFoundError):
        frame_module.spent_lineages(
            sfi1_frame=sfi1_frame_fixture,
            sfi1_acquisition=sfi1_acquisition_fixture,
            sfi2_frame=real_frame,
            sfi2_acquisition=real_acquisition,
            sfi2_forensic_receipt=missing_forensic,
        )


def test_the_frame_built_from_a_spent_derived_listing_excludes_everything_spent(
    tmp_path: Path,
) -> None:
    """The adversarial case: the candidate frame is built from the spent ids
    themselves. If the exclusion works the eligible set is necessarily empty of
    them; if it does not this fails rather than passing because a fixture
    happened to avoid the overlap."""
    sfi2_frame_ids = ["git:fixture/listed:docs/a.md"]
    sfi1_frame_fixture = _write_sfi1_frame(tmp_path / "sfi1_lineages.json", [])
    sfi1_acquisition_fixture = _write_sfi1_acquisition(
        tmp_path / "sfi1_acquisition.json", admitted=[], rejected=[]
    )
    frame_fixture = _write_sfi2_frame(tmp_path / "sfi2_lineages.json", sfi2_frame_ids)
    acquisition_fixture = _write_sfi2_acquisition(
        tmp_path / "sfi2_acquisition.json", admitted=[], rejected=[]
    )
    forensic_fixture = _write_forensic_receipt(tmp_path / "forensic.json", [])
    spent = frame_module.spent_lineages(
        sfi1_frame=sfi1_frame_fixture,
        sfi1_acquisition=sfi1_acquisition_fixture,
        sfi2_frame=frame_fixture,
        sfi2_acquisition=acquisition_fixture,
        sfi2_forensic_receipt=forensic_fixture,
    )

    listing = _write_frame(
        tmp_path / "candidate_frame.json",
        [
            *(_lineage(lineage_id) for lineage_id in sorted(spent)[:50]),
            _lineage("git:fresh/repo:docs/never-seen.md"),
        ],
    )
    built = frame_module.build_frame(listing, spent=spent)
    eligible = {row["lineage_id"] for row in built["lineages"]}
    assert eligible & spent == set()
    assert "git:fresh/repo:docs/never-seen.md" in eligible


def test_the_forensic_receipt_pointer_is_followed(tmp_path: Path) -> None:
    """`receipts/latest/*.json` is a mutable convenience pointer, not the
    evidence itself. The loader must follow `points_to` rather than reading
    the pointer's own (empty) body."""
    real_receipt_dir = tmp_path / "receipts"
    real_receipt_dir.mkdir()
    pointed_body = real_receipt_dir / "sfi2-native-provenance--fixture.json"
    _write_forensic_receipt(pointed_body, ["git:fixture/pointed-at:docs/a.md"])

    original_root = frame_module.ROOT
    try:
        frame_module.ROOT = tmp_path
        pointer = _write_forensic_pointer(tmp_path / "pointer.json", pointed_body)
        result = frame_module._load_sfi2_e5e6_forensic_lineages(pointer)
    finally:
        frame_module.ROOT = original_root

    assert result == ("git:fixture/pointed-at:docs/a.md",)


# --- 3. order_key is deterministic, takes a string, salt changes the order ----


def test_order_key_is_deterministic_and_takes_a_string() -> None:
    lineage_id = "git:example/one:docs/a.md"
    digest = frame_module.order_key(lineage_id)
    assert isinstance(digest, str)
    assert digest == frame_module.order_key(lineage_id)
    #: a dict would raise inside hashlib well before comparison — this is the
    #: bug the freeze tool's own docstring warns against repeating
    with pytest.raises((TypeError, AttributeError)):
        frame_module.order_key({"lineage_id": lineage_id})  # type: ignore[arg-type]


def test_order_key_uses_a_salt_distinct_from_every_predecessors() -> None:
    assert frame_module.ORDER_SALT != sfi1.ORDER_SALT
    assert frame_module.ORDER_SALT != sfi2.ORDER_SALT
    lineage_id = "git:example/one:docs/a.md"
    assert frame_module.order_key(lineage_id) != sfi1.order_key(lineage_id)
    assert frame_module.order_key(lineage_id) != sfi2.order_key(lineage_id)


def test_a_different_salt_produces_a_different_frame_order(tmp_path: Path) -> None:
    listing = _write_frame(
        tmp_path / "frame.json",
        [_lineage(f"git:example/repo:docs/{index}.md") for index in range(40)],
    )
    house = [
        row["lineage_id"]
        for row in frame_module.build_frame(listing, spent=frozenset())["lineages"]
    ]
    other = [
        row["lineage_id"]
        for row in frame_module.build_frame(listing, spent=frozenset(), salt=":other-salt")[
            "lineages"
        ]
    ]
    assert sorted(house) == sorted(other)
    assert house != other
    #: same salt, same order, run twice
    assert house == [
        row["lineage_id"]
        for row in frame_module.build_frame(listing, spent=frozenset())["lineages"]
    ]


def test_expansion_tool_sorts_lineage_ids_not_lineage_rows() -> None:
    """The V1 bug this tool must not repeat: `key=frame.order_key` on a list of
    dicts raises TypeError because order_key takes a lineage_id string."""
    rows = [_lineage(f"git:example/repo:docs/{index}.md") for index in range(10)]
    with pytest.raises(TypeError):
        sorted(rows, key=frame_module.order_key)
    #: the correct call, as used in freeze_sfi3_lineages.main()
    sorted(rows, key=lambda row: frame_module.order_key(row["lineage_id"]))


# --- 4. quotas are literal module constants with a declared basis, floor >=200


def test_the_sampling_constants_are_literals() -> None:
    literal = frame_module.sampling_constants_are_literal()
    assert literal == {name: True for name in literal}, literal
    assert set(literal) >= {
        "FAMILY_QUOTA",
        "FAMILY_SHARE",
        "PRIMARY_TARGET",
        "FLOOR",
        "MAX_PAYLOAD_BYTES",
    }


def test_the_floor_is_at_least_200_as_the_founder_requires() -> None:
    assert frame_module.FLOOR >= 200
    assert frame_module.FAMILIES_REQUIRED >= 3


def test_the_quotas_are_read_only_and_carry_a_declared_basis() -> None:
    with pytest.raises(TypeError):
        frame_module.FAMILY_QUOTA["git_docs"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        frame_module.FAMILY_SHARE["git_docs"] = 1.0  # type: ignore[index]

    basis = frame_module.QUOTA_BASIS
    assert basis["basis"]
    assert "pass yield" in basis["explicitly_not_basis"]
    assert "outcome" in basis["explicitly_not_basis"]
    assert "forbidden" in basis["redistribution"]
    assert set(frame_module.FAMILY_QUOTA) == set(frame_module.FAMILY_SHARE)
    assert sum(frame_module.FAMILY_QUOTA.values()) == frame_module.PRIMARY_TARGET
    assert len(frame_module.FAMILY_QUOTA) == frame_module.FAMILIES_REQUIRED


def test_no_sampling_constant_is_computed_from_an_outcome() -> None:
    """Structural check: no sampling constant may reference an outcome-bearing
    name. A literal cannot reference anything, so this only fires if someone
    replaces a literal with a computation."""
    outcome_words = (
        "verdict",
        "gates",
        "summary",
        "by_state",
        "result_digest",
        "pass_yield",
        "admitted",
        "receipt",
    )
    names = (
        "FAMILY_QUOTA",
        "FAMILY_SHARE",
        "PRIMARY_TARGET",
        "FLOOR",
        "FAMILIES_REQUIRED",
        "MAX_PAYLOAD_BYTES",
    )
    tree = ast.parse(Path(frame_module.__file__).read_text(encoding="utf-8"))
    checked = 0
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        )
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in names:
                continue
            checked += 1
            for child in ast.walk(node.value):
                if isinstance(child, ast.Name):
                    assert child.id == "MappingProxyType", child.id
                if isinstance(child, ast.Attribute):
                    pytest.fail(f"{target.id} reads an attribute: {ast.dump(child)}")
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    lowered = child.value.lower()
                    for word in outcome_words:
                        assert word not in lowered, f"{target.id} mentions {word!r}"
    assert checked == len(names)


def test_quotas_are_not_tuned_against_sfi2s_observed_yield() -> None:
    """The reachability note may cite SFI2's yield; the quotas themselves must
    equal SFI2's unmoved, exactly as SFI2 asserted its quotas equalled SFI1's."""
    assert dict(frame_module.FAMILY_QUOTA) == dict(sfi2.FAMILY_QUOTA)
    assert dict(frame_module.FAMILY_SHARE) == dict(sfi2.FAMILY_SHARE)
    assert frame_module.PRIMARY_TARGET == sfi2.PRIMARY_TARGET
    assert frame_module.FLOOR == sfi2.FLOOR
    assert frame_module.FAMILIES_REQUIRED == sfi2.FAMILIES_REQUIRED


def test_the_frame_is_sized_generously_not_the_quotas(tmp_path: Path) -> None:
    """The expansion tool's caps must be at or above SFI2's, so a comfortable
    floor margin comes from candidate supply, never from a moved quota."""
    for family in ("git_docs", "regulation_ecfr", "encyclopedia_wikipedia"):
        assert expand.CANDIDATE_CAP[family] >= 700


def test_the_unexercised_family_is_declared_rather_than_absent() -> None:
    assert "sec_edgar" not in frame_module.FAMILY_QUOTA
    assert "sec_edgar" in frame_module.UNEXERCISED_FAMILIES
    assert frame_module.SEC_ROOTS == ()
    assert "network" in frame_module.UNEXERCISED_FAMILIES["sec_edgar"]


def test_the_payload_bound_publishes_its_basis_and_insensitivity_and_is_carried_forward() -> (
    None
):
    low, high = frame_module.MAX_PAYLOAD_INSENSITIVE_RANGE
    assert low < frame_module.MAX_PAYLOAD_BYTES < high
    assert high >= 3 * low
    assert "distribution" in frame_module.MAX_PAYLOAD_BASIS
    assert "outcome" in frame_module.MAX_PAYLOAD_NOT_BASIS
    assert frame_module.MAX_PAYLOAD_BYTES == sfi2.MAX_PAYLOAD_BYTES
    assert frame_module.MAX_PAYLOAD_INSENSITIVE_RANGE == sfi2.MAX_PAYLOAD_INSENSITIVE_RANGE


# --- 5. an unsealed frame raises rather than returning nothing ----------------


def test_an_unsealed_frame_raises_rather_than_returning_nothing(tmp_path: Path) -> None:
    with pytest.raises(frame_module.FrameNotFrozen) as raised:
        frame_module.build_frame(tmp_path / "not-sealed.json", spent=frozenset())
    assert "Refusing to return an empty frame" in str(raised.value)


def test_frame_accessor_propagates_the_same_refusal(tmp_path: Path) -> None:
    with pytest.raises(frame_module.FrameNotFrozen):
        frame_module.frame(tmp_path / "not-sealed.json", spent=frozenset())


# --- 6. every non-admitted lineage carries a failure code ---------------------


def test_every_frame_exclusion_carries_a_declared_failure_code(tmp_path: Path) -> None:
    spent = frozenset({"git:spent/repo:docs/old.md"})
    listing = _write_frame(
        tmp_path / "frame.json",
        [
            _lineage("git:spent/repo:docs/old.md", "git_docs"),
            _lineage(sfi1.FORENSIC_LINEAGES[0], "encyclopedia_wikipedia"),
            _lineage(frame_module.SFI2_E5E6_FORENSIC_LINEAGES[0], "git_docs"),
            _lineage("sec:0000000000:10-K", "sec_edgar"),
            _lineage("git:fresh/repo:docs/new.md", "git_docs"),
        ],
    )
    built = frame_module.build_frame(listing, spent=spent)

    assert len(built["lineages"]) + len(built["dropped"]) == 5
    assert {row["code"] for row in built["dropped"]} == {
        frame_module.SPENT,
        frame_module.FORENSIC,
        frame_module.UNDECLARED_FAMILY,
    }
    for row in built["dropped"]:
        assert row["code"] in frame_module.FAILURE_CODES
        assert row["lineage_id"]


def test_failure_codes_cover_every_way_the_expansion_tool_drops_a_candidate() -> None:
    """freeze_sfi3_lineages only ever emits LISTING_FAILED or NOT_FRESH at
    expansion time; both must be representable in the frame's coded vocabulary
    (NOT_FRESH becomes SPENT once it reaches build_frame's own exclusion, and
    LISTING_FAILED is a first-class frame failure code)."""
    assert expand.LISTING_FAILED in frame_module.FAILURE_CODES
    assert frame_module.SPENT in frame_module.FAILURE_CODES


# --- 7. frame_digest is stable and changes when the frame changes -------------


def test_frame_digest_is_stable_across_runs(tmp_path: Path) -> None:
    listing = _write_frame(
        tmp_path / "frame.json",
        [_lineage(f"git:example/repo:docs/{index}.md") for index in range(25)],
    )
    first = frame_module.frame_digest(
        frame_module.build_frame(listing, spent=frozenset())["lineages"]
    )
    second = frame_module.frame_digest(
        frame_module.build_frame(listing, spent=frozenset())["lineages"]
    )
    assert first == second


def test_frame_digest_changes_when_the_frame_changes(tmp_path: Path) -> None:
    rows = [_lineage(f"git:example/repo:docs/{index}.md") for index in range(25)]
    base = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(tmp_path / "a.json", rows), spent=frozenset()
        )["lineages"]
    )

    added = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(
                tmp_path / "b.json", [*rows, _lineage("git:example/repo:docs/extra.md")]
            ),
            spent=frozenset(),
        )["lineages"]
    )
    assert added != base

    removed = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(tmp_path / "c.json", rows), spent=frozenset({rows[0]["lineage_id"]})
        )["lineages"]
    )
    assert removed != base

    reordered = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(tmp_path / "d.json", rows), spent=frozenset(), salt=":other-salt"
        )["lineages"]
    )
    assert reordered != base, "the digest must pin the order, not only the membership"


def test_quota_digest_pins_the_sampling_constants() -> None:
    assert frame_module.quota_digest() == frame_module.quota_digest()
    assert frame_module.quota_digest().startswith("sha256:")
    #: SFI3's quotas equal SFI2's (test above), but the salt and protocol id
    #: differ, so nothing here asserts the two digests are equal or unequal —
    #: only that this module's own digest is stable.


# --- 8. the expansion tool refuses to run with no protocol freeze receipt -----


def test_the_expansion_tool_refuses_with_no_protocol_freeze_receipt(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    empty_receipts_root = tmp_path / "no-receipts-here"
    empty_receipts_root.mkdir()
    monkeypatch.setattr(expand, "NS", empty_receipts_root)
    assert expand.main() == 3
    assert "not frozen" in capsys.readouterr().err


def test_the_expansion_tool_proceeds_past_the_guard_once_a_freeze_receipt_exists(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Only the guard is under test here — not a real expansion. The walk
    functions are monkeypatched to empty so nothing fetches; if the guard were
    broken this would either raise on the missing receipt or attempt a real
    fetch, and both are avoided by construction."""
    receipts_root = tmp_path / "receipts"
    receipts_root.mkdir()
    (receipts_root / "sfi3-protocol-freeze--fixture.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(expand, "NS", tmp_path)
    monkeypatch.setattr(expand, "OUT", tmp_path / "artifacts" / "sfi3_lineages.json")
    monkeypatch.setattr(expand, "spent", lambda: set())
    monkeypatch.setattr(expand, "git_lineages", lambda used: ([], []))
    monkeypatch.setattr(expand, "ecfr_lineages", lambda used: ([], []))
    monkeypatch.setattr(expand, "wikipedia_lineages", lambda used: ([], []))
    #: `rel()` resolves against the real repository ROOT, which tmp_path is not
    #: under; stubbed so this test stays hermetic rather than writing under the
    #: real repository tree.
    monkeypatch.setattr(expand, "rel", lambda path: str(path))
    monkeypatch.setattr(expand, "sha_file", lambda path: "sha256:fixture")

    def _fake_write_immutable(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        return {"receipt": "fixture"}

    monkeypatch.setattr(expand, "write_immutable", _fake_write_immutable)

    assert expand.main() == 0
    written = json.loads(expand.OUT.read_text(encoding="utf-8"))
    assert written["candidates"] == 0
    assert written["protocol_id"] == frame_module.PROTOCOL_ID


# --- 9. freeze_sfi3_lineages.py exists but this suite never executes it -------


def test_this_suite_never_calls_expand_main_against_real_network_or_receipts() -> None:
    """Documentation-as-assertion: every call to `expand.main()` above either
    hits the guard (no receipt, returns 3 before any walk) or has all three
    walk functions monkeypatched to return empty lists (no fetch). This test
    exists so a future edit that adds a real invocation is visible in a diff
    review, not just in reading every other test carefully."""
    real_freeze_receipts = sorted((NS / "receipts").glob("sfi3-protocol-freeze--*.json"))
    assert real_freeze_receipts == [], (
        "a real sfi3-protocol-freeze receipt exists; the orchestrator has already frozen "
        "the protocol. This suite must still never call expand.main() against it — that "
        "is the freeze step's job, run once, outside any test."
    )


def test_worker_refuses_without_an_exact_reservation_handoff():
    with pytest.raises(worker.reservation_binding.BindingRefused, match="requires --handoff"):
        worker.main([])


def test_worker_verifies_reservation_binding_before_protocol_or_payload(monkeypatch):
    calls: list[str] = []

    def verified(**_kwargs: Any) -> dict[str, Any]:
        calls.append("binding")
        return {"held": True}

    class StopBeforePayload(RuntimeError):
        pass

    def stop_at_protocol() -> dict[str, Any]:
        calls.append("protocol")
        raise StopBeforePayload

    monkeypatch.setattr(worker.reservation_binding, "verify_binding", verified)
    monkeypatch.setattr(worker, "require_frozen_protocol", stop_at_protocol)
    with pytest.raises(StopBeforePayload):
        worker.main(
            [
                "--handoff",
                "receipts/exact-handoff.json",
                "--handoff-sha256",
                "sha256:" + "a" * 64,
            ]
        )
    assert calls == ["binding", "protocol"]


def test_worker_declaration_remains_payload_free_without_binding(capsys):
    assert worker.main(["--declare"]) == 0
    assert "declaration only" in capsys.readouterr().out
