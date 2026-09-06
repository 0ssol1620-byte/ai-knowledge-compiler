"""Every check in the V2 universe enumeration, proven able to come back RED.

This study's most-repeated defect -- INC-V2-036, INC-V2-044, INC-V2-048, and
half a dozen before them -- is a check that reports a clean result because it is
watching nothing. So almost every test below injects a violation and asserts the
enumeration notices. The handful of green-direction tests exist only to show
that the red ones are discriminating: a suite that could only ever go red would
prove no more than a hardcoded FAIL.

Three of these are the ones the lane brief names specifically:

* `test_disjointness_proof_goes_red_when_a_v1_lineage_is_injected` -- the proof
  itself must fail on an overlap, not merely the filter that prevents one;
* `test_collision_group_excludes_the_member_that_still_verifies` -- dropping only
  the failing member is exactly the convenient reading INC-V2-046 forbids, and
  the test asserts the surviving member verifies *and* is still excluded;
* `test_zero_eligible_pairs_is_a_blocking_finding` -- an empty universe is a
  reported shortfall, never a clean empty result.

Nothing here writes to a receipt, opens an SFI3 artifact, or imports `akc_cir`.
Payload fixtures live under `tmp_path` and the module's ROOT is redirected there,
so no test can touch a spent artifact even by accident.
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
for _sub in ("tools", "acquisition"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import enumerate_v2_universe as enumerator  # noqa: E402

REAL_MANIFEST = ("receipts/p2-chain-manifest.json", "chains")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _write_payload(root: Path, relative: str, text: str) -> str:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return relative


def _sha(root: Path, relative: str) -> str:
    return "sha256:" + hashlib.sha256((root / relative).read_bytes()).hexdigest()


def make_side(
    root: Path,
    slug: str,
    which: str,
    *,
    body: str = "hello",
    raw_present: bool = True,
    canonical_present: bool = True,
    record_raw_digest: str | None = "correct",
    record_canonical_digest: str | None = None,
) -> enumerator.Side:
    """One side of a fixture pair, with every failure mode reachable by argument."""
    raw_rel = f"fixture/raw/{slug}/{which}.md"
    canonical_rel = f"fixture/canonical/{slug}/{which}.json"
    if raw_present:
        _write_payload(root, raw_rel, body)
    if canonical_present:
        _write_payload(root, canonical_rel, json.dumps({"units": [], "body": body}))

    if record_raw_digest == "correct":
        raw_digest: str | None = _sha(root, raw_rel) if raw_present else None
    elif record_raw_digest == "wrong":
        raw_digest = "sha256:" + "0" * 64
    else:
        raw_digest = None

    canonical_digest: str | None
    if record_canonical_digest == "file_bytes":
        canonical_digest = _sha(root, canonical_rel)
    elif record_canonical_digest == "canonical_form":
        from common import canonical_sha

        canonical_digest = canonical_sha(json.loads((root / canonical_rel).read_text("utf-8")))
    elif record_canonical_digest == "wrong":
        canonical_digest = "sha256:" + "1" * 64
    else:
        canonical_digest = None

    return enumerator.Side(
        raw_path=raw_rel if raw_present else "",
        raw_sha256_recorded=raw_digest,
        canonical_path=canonical_rel if canonical_present else None,
        canonical_sha256_recorded=canonical_digest,
    )


def make_pair(
    root: Path,
    lineage: str,
    *,
    family: str = "git_docs",
    slug: str | None = None,
    cache_slug: str | None = None,
    natural: bool = True,
    **side_kwargs: Any,
) -> enumerator.Candidate:
    slug = slug or lineage.replace("/", "-").replace(":", "-")
    return enumerator.Candidate(
        lineage_id=lineage,
        family=family,
        before_version="v0",
        after_version="v1",
        manifest="fixture",
        cache_slug=cache_slug if cache_slug is not None else slug,
        natural=natural,
        before=make_side(root, slug, "before", **side_kwargs),
        after=make_side(root, slug, "after", **side_kwargs),
    )


def run(monkeypatch: pytest.MonkeyPatch, root: Path, rows: list[enumerator.Candidate]) -> dict:
    """Run the whole enumeration over fixture rows, against the REAL exclusion sets."""
    monkeypatch.setattr(enumerator, "ROOT", root)
    return enumerator.enumerate_universe(
        sources=(REAL_MANIFEST,),
        reader=lambda resolved: [(resolved[0][0], rows)],
    )


def categories(body: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in body["excluded"]:
        out.setdefault(row["category"], []).append(row["lineage_id"])
    return out


def lineages(body: dict) -> set[str]:
    return {row["lineage_id"] for row in body["pairs"]}


CLEAN = "git:fixture-lane-c/repo:docs/clean.md"
OTHER = "git:fixture-lane-c/repo:docs/other.md"


# --------------------------------------------------------------------------
# the green anchor -- present so the red tests below are known to discriminate
# --------------------------------------------------------------------------


def test_a_clean_disjoint_pair_survives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, CLEAN)])
    assert lineages(body) == {CLEAN}
    assert body["pair_count"] == 1
    assert body["disjointness"]["all_hold"] is True
    assert body["sfi3"]["holds"] is True
    assert body["pairs"][0]["outcome_visibility"] == "NEVER_MEASURED"


# --------------------------------------------------------------------------
# disjointness
# --------------------------------------------------------------------------


def test_an_injected_v1_lineage_is_excluded_and_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = sorted(enumerator.v1_closure_lineages()[0])[0]
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, victim), make_pair(tmp_path, CLEAN)])
    assert victim not in lineages(body)
    assert categories(body)["V1_CLOSURE_LINEAGE"] == [victim]
    assert lineages(body) == {CLEAN}


def test_disjointness_proof_goes_red_when_a_v1_lineage_is_injected() -> None:
    """The proof must fail on an overlap, not merely the filter that prevents one.

    A proof that can only report `holds: True` because nothing upstream ever
    hands it an overlap is INC-V2-036's guard: its failure is structurally
    impossible and it measures nothing. So the overlap is handed to it directly.
    """
    v1_ids, meta = enumerator.v1_closure_lineages()
    victim = sorted(v1_ids)[0]
    proof = enumerator._disjointness_proof(frozenset({victim}), {"from_v1": (v1_ids, meta)})
    assert proof["from_v1"]["holds"] is False
    assert proof["from_v1"]["overlap"] == [victim]
    assert proof["all_hold"] is False

    clean = enumerator._disjointness_proof(frozenset({CLEAN}), {"from_v1": (v1_ids, meta)})
    assert clean["all_hold"] is True


def test_the_enumeration_refuses_rather_than_reporting_a_broken_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the filter and the proof ever disagree, that is refused, not reported.

    A universe that shipped with `holds: False` written into it would be a
    finding nobody had to act on. The runner has no such path.
    """

    def broken(selected: Any, sets: dict) -> dict:
        proof = {label: {"holds": False, "overlap": ["injected"]} for label in sets}
        proof["all_hold"] = False
        return proof

    monkeypatch.setattr(enumerator, "_disjointness_proof", broken)
    monkeypatch.setattr(enumerator, "ROOT", tmp_path)
    with pytest.raises(enumerator.EnumerationRefused):
        enumerator.enumerate_universe(
            sources=(REAL_MANIFEST,),
            reader=lambda r: [(r[0][0], [make_pair(tmp_path, CLEAN)])],
        )


def test_spent_and_forensic_and_retrospective_lineages_are_each_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retro = sorted(enumerator.retrospective_lineage_ids()[0])[0]
    forensic = sorted(enumerator.confirmed_defect_lineages()[0])[0]
    body = run(
        monkeypatch,
        tmp_path,
        [make_pair(tmp_path, retro), make_pair(tmp_path, forensic), make_pair(tmp_path, CLEAN)],
    )
    dropped = categories(body)
    assert retro in dropped["RETROSPECTIVE_538_COHORT"]
    assert forensic in dropped["RETROSPECTIVE_538_COHORT"] + dropped.get("SFI2_FORENSIC_14", [])
    assert lineages(body) == {CLEAN}


def test_an_identity_measured_lineage_is_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lineage P0/P0b/P0c/P2 already read identity outcomes on cannot come back."""
    measured = enumerator.identity_measured_lineages()[0]
    v1_ids = enumerator.v1_closure_lineages()[0]
    spent = frozenset(enumerator.sources_sfi3.spent_lineages())
    retro = enumerator.retrospective_lineage_ids()[0]
    only_identity = sorted(measured - v1_ids - spent - retro)
    assert only_identity, "the registry must contain a lineage no earlier category claims"
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, only_identity[0])])
    assert categories(body)["IDENTITY_OUTCOME_ALREADY_MEASURED"] == [only_identity[0]]
    assert body["pairs"] == []


# --------------------------------------------------------------------------
# cache-key collisions -- the INC-V2-046 rule
# --------------------------------------------------------------------------


def test_collision_group_excludes_the_member_that_still_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping only the member whose digest fails is the convenient reading.

    Two distinct lineages write to one cached path. One still verifies against
    the digest its manifest recorded and the other does not. Nothing on disk says
    which holds the right bytes, so BOTH are excluded. This test asserts the
    surviving member verifies -- so a digest-only filter would have kept it --
    and is excluded anyway.
    """
    monkeypatch.setattr(enumerator, "ROOT", tmp_path)
    slug = "shared-cache-dir"
    good = make_pair(tmp_path, CLEAN, slug=slug, record_raw_digest="correct")
    bad = make_pair(tmp_path, OTHER, slug=slug, record_raw_digest="wrong")

    # the surviving member really does verify: a digest-driven filter keeps it
    assert enumerator.verify_side(good.before)[1] is None
    assert enumerator.verify_side(bad.before)[1] == "PAYLOAD_DIGEST_MISMATCH"

    body = run(monkeypatch, tmp_path, [good, bad])
    assert body["pairs"] == []
    assert set(categories(body)["CACHE_KEY_COLLISION_GROUP"]) == {CLEAN, OTHER}
    assert "PAYLOAD_DIGEST_MISMATCH" not in categories(body)


def test_a_collision_whose_members_both_verify_is_still_a_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The detector INC-V2-046 did not have: structural, before any digest check."""
    monkeypatch.setattr(enumerator, "ROOT", tmp_path)
    slug = "both-verify"
    rows = [
        make_pair(tmp_path, CLEAN, slug=slug, record_raw_digest="correct"),
        make_pair(tmp_path, OTHER, slug=slug, record_raw_digest="correct"),
    ]
    for row in rows:
        assert enumerator.verify_side(row.before)[1] is None
    body = run(monkeypatch, tmp_path, rows)
    assert body["pairs"] == []
    assert set(categories(body)["CACHE_KEY_COLLISION_GROUP"]) == {CLEAN, OTHER}


def test_the_slug_detector_fires_when_the_paths_differ(tmp_path: Path) -> None:
    """Two readings of one collision, so it survives a change in path spelling."""
    rows = [
        make_pair(tmp_path, CLEAN, slug="dir-a", cache_slug="truncated"),
        make_pair(tmp_path, OTHER, slug="dir-b", cache_slug="truncated"),
    ]
    found = enumerator.collision_groups(rows)
    assert set(found) == {CLEAN, OTHER}
    detectors = {item["detector"] for entry in found.values() for item in entry["collisions"]}
    assert detectors == {"cache_slug"}


def test_distinct_lineages_with_distinct_caches_are_not_a_collision(tmp_path: Path) -> None:
    rows = [
        make_pair(tmp_path, CLEAN, slug="dir-a"),
        make_pair(tmp_path, OTHER, slug="dir-b"),
    ]
    assert enumerator.collision_groups(rows) == {}


def test_the_real_p4i_collision_groups_are_still_detected() -> None:
    """The three groups INC-V2-046 named, found by the structural detector."""
    resolved = enumerator.resolve_sources((("artifacts/development/p4i_cohort.json", "cohort"),))
    rows = enumerator.read_candidates(resolved)[0][1]
    found = enumerator.collision_groups(rows)
    assert len(found) == 6
    groups = {
        tuple(item["group"]) for entry in found.values() for item in entry["collisions"]
    }
    assert len(groups) == 3
    for group in groups:
        assert len(group) == 2


# --------------------------------------------------------------------------
# an empty universe
# --------------------------------------------------------------------------


def test_zero_eligible_pairs_is_a_blocking_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty universe is a reported shortfall, never a clean empty result."""
    victim = sorted(enumerator.v1_closure_lineages()[0])[0]
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, victim)])
    assert body["pair_count"] == 0
    codes = {finding["code"]: finding["severity"] for finding in body["findings"]}
    assert codes["NO_ELIGIBLE_MATERIAL"] == "BLOCKING"


def test_an_empty_universe_makes_the_tool_exit_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = {
        "findings": enumerator.findings_for([], {}),
        "pair_count": 0,
        "families": {},
        "outcome_visibility": {},
        "universe_sha256": "sha256:0",
        "sufficiency": {"verdict": "FOUNDER_RULING_REQUIRED"},
        "excluded": [],
    }
    monkeypatch.setattr(enumerator, "enumerate_universe", lambda *a, **k: dict(empty))
    monkeypatch.setattr(enumerator, "MANIFEST_PATH", tmp_path / "manifest.json")
    assert enumerator.main(["--no-receipt"]) == 5


def test_a_non_empty_universe_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exit code is a measurement, not a constant: it must reach 0 too."""
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, CLEAN)])
    monkeypatch.setattr(enumerator, "enumerate_universe", lambda *a, **k: body)
    monkeypatch.setattr(enumerator, "MANIFEST_PATH", tmp_path / "manifest.json")
    assert enumerator.main(["--no-receipt"]) == 0


# --------------------------------------------------------------------------
# cache integrity of a single side
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"record_raw_digest": "wrong"}, "PAYLOAD_DIGEST_MISMATCH"),
        ({"raw_present": False}, "PAYLOAD_MISSING"),
        ({"canonical_present": False}, "CANONICAL_MISSING"),
        ({"record_canonical_digest": "wrong"}, "CANONICAL_DIGEST_MISMATCH"),
    ],
)
def test_each_cache_integrity_failure_is_named_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kwargs: dict, expected: str
) -> None:
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, CLEAN, **kwargs)])
    assert body["pairs"] == []
    assert categories(body)[expected] == [CLEAN]
    assert enumerator.EXCLUSION_REASONS[expected]


@pytest.mark.parametrize("convention", ["file_bytes", "canonical_form"])
def test_both_canonical_digest_conventions_are_accepted_and_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, convention: str
) -> None:
    """Two conventions exist on disk. Accepting only one would exclude real pairs."""
    body = run(
        monkeypatch, tmp_path, [make_pair(tmp_path, CLEAN, record_canonical_digest=convention)]
    )
    assert lineages(body) == {CLEAN}
    assert body["pairs"][0]["before"]["canonical_digest_convention"] == convention


def test_a_side_with_no_recorded_canonical_digest_carries_the_computed_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never invent a digest to satisfy a schema: absent is recorded as absent."""
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, CLEAN)])
    side = body["pairs"][0]["before"]
    assert side["canonical_sha256_recorded"] is None
    assert side["canonical_digest_convention"] is None
    assert side["canonical_file_sha256"].startswith("sha256:")


# --------------------------------------------------------------------------
# SFI3
# --------------------------------------------------------------------------


def test_a_lineage_inside_an_sfi3_git_root_is_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = enumerator.sources_sfi3.GIT_ROOTS[0]
    victim = f"git:{root['owner']}/{root['repo']}:docs/anything.md"
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, victim)])
    assert categories(body)["SFI3_ROOT_CONTAINER"] == [victim]


def test_a_lineage_inside_an_sfi3_ecfr_root_is_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    title, part, _ = enumerator.sources_sfi3.ECFR_ROOTS[0]
    victim = f"ecfr:{title}:{part}:{part}.1"
    body = run(
        monkeypatch, tmp_path, [make_pair(tmp_path, victim, family="regulation_ecfr")]
    )
    assert categories(body)["SFI3_ROOT_CONTAINER"] == [victim]


def test_a_neighbouring_ecfr_part_is_not_swept_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root test is on (title, part), not on the title. Both directions matter."""
    title, part, _ = enumerator.sources_sfi3.ECFR_ROOTS[0]
    neighbour = f"ecfr:{title}:{int(part) + 90001}:1.1"
    body = run(
        monkeypatch, tmp_path, [make_pair(tmp_path, neighbour, family="regulation_ecfr")]
    )
    assert lineages(body) == {neighbour}


def test_the_wikipedia_family_is_excluded_as_unprovable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SFI3's Wikipedia roots are categories, so membership needs an expansion."""
    victim = "wikipedia:en:Fixture Lane C"
    body = run(
        monkeypatch,
        tmp_path,
        [make_pair(tmp_path, victim, family="encyclopedia_wikipedia")],
    )
    assert categories(body)["SFI3_DISJOINTNESS_UNPROVABLE_WITHOUT_EXPANSION"] == [victim]
    assert body["sfi3"]["holds"] is True


def test_the_enumeration_refuses_if_an_sfi3_frame_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = tmp_path / "sfi3_lineages.json"
    frame.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(enumerator, "SFI3_FRAME", frame)
    with pytest.raises(enumerator.EnumerationRefused):
        enumerator.enumerate_universe(sources=(REAL_MANIFEST,), reader=lambda r: [(r[0][0], [])])


def test_no_sfi3_acquisition_or_payload_path_appears_in_the_tool() -> None:
    """The prohibition is checked against the source, not against a promise.

    The only SFI3 path the tool may name is the frame it refuses to run beside.
    A string check is crude; it is also the check that would have caught a later
    edit adding one, which a reviewer's attention would not.
    """
    source = Path(enumerator.__file__).read_text(encoding="utf-8")
    forbidden = (
        "sfi3_acquisition",
        "sfi3/",
        "canonical_sfi3",
        "raw_sfi3",
        "sfi3_expansion",
        "sfi3_cache",
    )
    for needle in forbidden:
        assert needle not in source, needle
    # The one SFI3 path the tool may name is the frame it refuses to run beside.
    assert enumerator.SFI3_FRAME.name == "sfi3_lineages.json"
    named = [line for line in source.splitlines() if "sfi3_lineages.json" in line]
    assert [line for line in named if line.strip().startswith("SFI3_FRAME =")]
    assert len(named) == 2, named  # the constant, and the docstring that explains it


def test_the_real_run_leaves_sfi3_unacquired() -> None:
    assert not enumerator.SFI3_FRAME.exists()


# --------------------------------------------------------------------------
# ordering, dedup and row shape
# --------------------------------------------------------------------------


def test_a_constructed_control_pair_is_not_a_revision_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, CLEAN, natural=False)])
    assert categories(body)["NOT_A_NATURAL_REVISION_PAIR"] == [CLEAN]


def test_dedup_keeps_the_first_occurrence_and_names_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = make_pair(tmp_path, CLEAN, slug="first")
    second = make_pair(tmp_path, CLEAN, slug="second")
    body = run(monkeypatch, tmp_path, [first, second])
    assert body["pair_count"] == 1
    assert body["pairs"][0]["before"]["raw_path"].endswith("first/before.md")
    assert categories(body)["DUPLICATE_LINEAGE_OF_AN_EARLIER_MANIFEST"] == [CLEAN]


def test_every_emitted_category_is_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A category the table does not declare would carry no reason. Refuse the drift."""
    victim = sorted(enumerator.v1_closure_lineages()[0])[0]
    rows = [
        make_pair(tmp_path, CLEAN, natural=False),
        make_pair(tmp_path, victim),
        make_pair(tmp_path, OTHER, raw_present=False),
    ]
    body = run(monkeypatch, tmp_path, rows)
    declared = {name for name, _ in enumerator.EXCLUSION_ORDER}
    assert set(categories(body)) <= declared
    assert {entry["category"] for entry in body["exclusion_categories"]} == declared


def test_the_chain_adapter_reads_adjacent_steps_and_one_lineage_per_chain() -> None:
    """The founder asked whether the P2 material is usable. This is what it holds."""
    resolved = enumerator.resolve_sources((REAL_MANIFEST,))
    rows = enumerator.read_candidates(resolved)[0][1]
    manifest = json.loads((NS / REAL_MANIFEST[0]).read_text(encoding="utf-8"))
    assert len(rows) == manifest["step_count"]
    assert len({row.lineage_id for row in rows}) == manifest["chain_count"]
    for row in rows:
        assert row.before.raw_path and row.after.raw_path
        assert row.before_version != row.after_version


# --------------------------------------------------------------------------
# selection independence
# --------------------------------------------------------------------------


def test_the_tool_imports_no_change_predicate() -> None:
    """Selection cannot call a predicate it never imports. Checked by AST walk."""
    tree = ast.parse(Path(enumerator.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for forbidden in ("akc_cir", "semantic_diff", "change_facets", "expected_change_status"):
        assert forbidden not in imported, forbidden


def test_the_power_note_cannot_move_the_selected_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The published V1 rate describes the cohort. It must not be able to pick it.

    Changing the rate changes the power note and must leave the universe digest
    byte-identical. If selection ever read the rate, this goes red.
    """
    rows = [make_pair(tmp_path, CLEAN), make_pair(tmp_path, OTHER)]
    before = run(monkeypatch, tmp_path, rows)
    monkeypatch.setattr(enumerator, "V1_VIOLATED_LINEAGES", 400)
    after = run(monkeypatch, tmp_path, rows)

    assert before["universe_sha256"] == after["universe_sha256"]
    assert lineages(before) == lineages(after)

    def power(body: dict) -> float:
        return next(
            finding["probability_of_observing_at_least_one"]
            for finding in body["findings"]
            if finding["code"] == "EMPIRICAL_POWER_NOTE"
        )

    assert power(before) != power(after)


def test_outcome_visibility_is_recorded_not_used_to_exclude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A burn taken for another question is surfaced, never silently decided."""
    burned = sorted(enumerator.unrelated_outcome_lineages()[0]["VBC1_VALUE_BEARING_PROBE"])
    v1_ids = enumerator.v1_closure_lineages()[0]
    spent = frozenset(enumerator.sources_sfi3.spent_lineages())
    retro = enumerator.retrospective_lineage_ids()[0]
    survivors = [
        lineage
        for lineage in burned
        if lineage.startswith("git:") and lineage not in v1_ids | spent | retro
    ]
    assert survivors
    body = run(monkeypatch, tmp_path, [make_pair(tmp_path, survivors[0])])
    assert lineages(body) == {survivors[0]}
    row = body["pairs"][0]
    assert row["outcome_visibility"] == "OUTCOME_VISIBLE_IN_ANOTHER_MEASUREMENT"
    assert row["measured_by"] == ["VBC1_VALUE_BEARING_PROBE"]
    codes = {finding["code"] for finding in body["findings"]}
    assert "NO_NEVER_MEASURED_MATERIAL" in codes


# --------------------------------------------------------------------------
# the real enumeration
# --------------------------------------------------------------------------


def test_the_real_enumeration_is_deterministic() -> None:
    first = enumerator.enumerate_universe()
    second = enumerator.enumerate_universe()
    assert first["universe_sha256"] == second["universe_sha256"]
    assert first["pairs"] == second["pairs"]
    assert first["excluded"] == second["excluded"]


def test_the_real_enumeration_proves_every_declared_disjointness() -> None:
    body = enumerator.enumerate_universe()
    proof = body["disjointness"]
    assert proof["all_hold"] is True
    for label in (
        "from_the_514_v1_closure_lineages",
        "from_the_538_pair_retrospective_cohort",
        "from_the_14_sfi2_forensic_cases",
        "from_the_spent_sfi1_sfi2_lineages",
        "from_lineages_an_identity_measurement_already_read",
    ):
        assert proof[label]["overlap"] == []
        assert proof[label]["distinct_lineages"] > 0
    assert body["sfi3"]["holds"] is True
    assert body["sfi3"]["payload_opened"] is False
    assert body["cache_integrity"]["historical_artifacts_rewritten"] is False


def test_the_real_enumeration_excludes_both_members_of_every_p4i_collision() -> None:
    body = enumerator.enumerate_universe()
    dropped = {
        row["lineage_id"]
        for row in body["excluded"]
        if row["category"] == "CACHE_KEY_COLLISION_GROUP"
    }
    assert len(dropped) == 6
    for group in body["cache_integrity"]["collision_groups"]:
        assert set(group["group"]) <= dropped
