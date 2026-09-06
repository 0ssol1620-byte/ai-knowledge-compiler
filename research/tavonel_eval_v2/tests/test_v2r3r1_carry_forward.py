"""V2R3R1: exact carry-forward, semantic equivalence, and the execution boundary.

THREE CLAIMS ARE LOAD-BEARING HERE and each has a red direction:

  1. the inherited cohort is EXACTLY the parent's 300 -- widening, narrowing,
     reordering, a changed digest and a changed family label all refuse;
  2. the successor asks the parent's scientific question -- a moved threshold, a
     moved obligation and a moved pass rule all refuse;
  3. the real-cohort closure is unreachable from a test -- and that is proven by
     a NEGATIVE CONTROL, not by a convention.

CLAIM 3 IS THE ONE THIS CHAIN EXISTS BECAUSE OF. The parent chain died when a
stale test called `scorer.run()` after the chain had frozen: it traversed all 300
pairs and crashed in census aggregation. No outcome escaped, but only because the
output block happens to sit after `body = run()` -- luck about where the
exception landed, not a guarantee. So the boundary is tested by patching the
chain to EXPLODE and asserting the refusal arrives anyway: if the refusal is
real, nothing downstream of it ever runs.

NO TEST HERE READS AN OUTCOME. There is none to read. Every red direction is
produced from a copy of the chain in a temporary directory, and no test writes
into the real `receipts/`.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "acquisition"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import enumerate_v2r3r1_universe as enumerate_lane  # noqa: E402
import freeze_migration_closure_v2r3r1 as fz  # noqa: E402
import identity_change_migration_closure_v2r3r1 as scorer  # noqa: E402
import v2r3_effective_identity as eff  # noqa: E402
import v2r3r1_attestation as att  # noqa: E402
import v2r3r1_carry_forward as cf  # noqa: E402
import v2r3r1_semantics as sem  # noqa: E402

base = fz.base
FreezeRefused = fz.FreezeRefused
CarryForwardRefused = cf.CarryForwardRefused
SemanticsDiffer = sem.SemanticsDiffer
ClosureRefused = scorer.ClosureRefused
REAL_RECEIPTS = NS / "receipts"


# ---------------------------------------------------------------------------
# 1. exact carry-forward


def test_the_real_carry_forward_is_exact() -> None:
    body = cf.prove_exact_carry_forward()
    assert body["mode"] == "EXACT_SET"
    equality = body["equality"]
    assert equality["pair_count"] == 300
    assert equality["by_family"] == {"git_docs": 133, "regulation_ecfr": 104, "sec_edgar": 63}
    for delta in cf.DECLARED_DELTAS:
        assert equality[delta] == 0, delta
    assert body["payload_verification"]["payloads_rehashed"] == 1200


def test_every_declared_delta_is_actually_reported() -> None:
    """The ruling names eight. A report missing one would still read as all-zero."""
    equality = cf.prove_exact_carry_forward()["equality"]
    assert set(cf.DECLARED_DELTAS) <= set(equality)


def _rows() -> list[dict[str, Any]]:
    return cf.carry_rows(cf.load_parent())


def test_adding_a_pair_refuses() -> None:
    rows = _rows()
    extra = json.loads(json.dumps(rows[0]))
    extra["lineage_id"] = "invented:1:2:3"
    with pytest.raises(CarryForwardRefused, match="added_pairs"):
        cf.compare(rows, [*rows, extra])


def test_removing_a_pair_refuses() -> None:
    rows = _rows()
    with pytest.raises(CarryForwardRefused, match="removed_pairs"):
        cf.compare(rows, rows[:-1])


def test_reordering_refuses() -> None:
    rows = _rows()
    swapped = [rows[1], rows[0], *rows[2:]]
    with pytest.raises(CarryForwardRefused, match="reordered_pairs"):
        cf.compare(rows, swapped)


def test_a_changed_raw_digest_refuses() -> None:
    rows = _rows()
    tampered = json.loads(json.dumps(rows))
    tampered[7]["before"]["raw_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(CarryForwardRefused, match="changed_raw_digests"):
        cf.compare(rows, tampered)


def test_a_changed_canonical_digest_refuses() -> None:
    rows = _rows()
    tampered = json.loads(json.dumps(rows))
    tampered[11]["after"]["canonical_sha256"] = "sha256:" + "1" * 64
    with pytest.raises(CarryForwardRefused, match="changed_canonical_digests"):
        cf.compare(rows, tampered)


def test_a_changed_family_label_refuses() -> None:
    rows = _rows()
    tampered = json.loads(json.dumps(rows))
    tampered[3]["family"] = "wikipedia"
    with pytest.raises(CarryForwardRefused, match=r"changed_family_labels|composition"):
        cf.compare(rows, tampered)


def test_a_changed_revision_id_refuses() -> None:
    rows = _rows()
    tampered = json.loads(json.dumps(rows))
    tampered[5]["after_version"] = "1999-01-01"
    with pytest.raises(CarryForwardRefused, match="changed_revision_ids"):
        cf.compare(rows, tampered)


def test_a_field_outside_the_declared_deltas_still_refuses() -> None:
    """Seven deltas NAME what changed; `replaced_pairs` catches everything else.

    `canonical_digest_convention` is in none of the seven named comparisons, so
    if the delta list were field-by-field this would pass as all-zero. It does
    not, because `replaced_pairs` compares the row dicts whole.
    """
    rows = _rows()
    tampered = json.loads(json.dumps(rows))
    tampered[2]["before"]["canonical_digest_convention"] = "md5, obviously"
    named = {
        "changed_raw_digests",
        "changed_canonical_digests",
        "changed_family_labels",
        "changed_revision_ids",
    }
    with pytest.raises(CarryForwardRefused) as caught:
        cf.compare(rows, tampered)
    message = str(caught.value)
    assert "replaced_pairs" in message
    assert not any(f"'{delta}': 1" in message for delta in named), message


def test_a_missing_payload_refuses_and_offers_no_repair() -> None:
    rows = json.loads(json.dumps(_rows()[:2]))
    rows[0]["before"]["raw_path"] = "research/tavonel_eval_v2/artifacts/nope.raw"
    with pytest.raises(CarryForwardRefused, match="not the ones the parent froze"):
        cf.verify_payload_digests(rows)


def test_a_tampered_payload_refuses(tmp_path: Path) -> None:
    """A digest that no longer matches disk aborts the WHOLE carry-forward."""
    rows = json.loads(json.dumps(_rows()[:1]))
    fake_root = tmp_path / "root"
    for side in ("before", "after"):
        for field in ("raw_path", "canonical_path"):
            target = fake_root / rows[0][side][field]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"not the frozen bytes")
    with pytest.raises(CarryForwardRefused, match="mismatched"):
        cf.verify_payload_digests(rows, root=fake_root)


def test_a_regenerated_parent_manifest_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parent = cf.load_parent()
    fake = tmp_path / "v2r3_universe_candidates.json"
    body = json.loads(cf.PARENT_MANIFEST.read_text(encoding="utf-8"))
    body["regenerated"] = True
    fake.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(cf, "PARENT_MANIFEST", fake)
    with pytest.raises(CarryForwardRefused, match="has changed since its universe froze"):
        cf.load_parent_manifest(parent)


def test_the_candidate_manifest_corresponds_to_the_frozen_universe() -> None:
    parent = cf.load_parent()
    manifest = cf.load_parent_manifest(parent)
    body = cf.compare_candidates_to_frozen(manifest["pairs"], parent["pairs"])
    assert body["pairs"] == 300
    assert body["frozen_order_is_the_candidate_rows_sorted_by_rung_3_key"] is True
    #: 3 row fields + 2 sides x 4 side fields, per pair.
    assert body["fields_compared"] == 300 * (3 + 2 * 4)


def test_a_candidate_row_whose_recorded_digest_moved_refuses() -> None:
    parent = cf.load_parent()
    manifest = json.loads(json.dumps(cf.load_parent_manifest(parent)))
    manifest["pairs"][4]["before"]["raw_sha256_recorded"] = "sha256:" + "2" * 64
    with pytest.raises(CarryForwardRefused, match="no longer corresponds"):
        cf.compare_candidates_to_frozen(manifest["pairs"], parent["pairs"])


def test_a_reordered_candidate_manifest_refuses() -> None:
    """The two orders differ by construction, so order is tied, not ignored.

    The frozen order is rung 3's sort of the candidate rows. An id-keyed
    comparison alone would accept an arbitrary reshuffle, and `reordered_pairs`
    is one of the deltas the ruling requires to be zero.
    """
    parent = cf.load_parent()
    manifest = json.loads(json.dumps(cf.load_parent_manifest(parent)))
    rows = manifest["pairs"]
    rows[0]["lineage_id"], rows[1]["lineage_id"] = rows[1]["lineage_id"], rows[0]["lineage_id"]
    with pytest.raises(CarryForwardRefused, match=r"does not reproduce|no longer corresponds"):
        cf.compare_candidates_to_frozen(rows, parent["pairs"])


def test_the_frozen_universe_digest_equals_the_parents() -> None:
    """The strongest available evidence, and it is an OUTPUT comparison.

    Rung 3 re-hashed all 1,200 payloads, re-detected collisions and re-applied
    the exclusion policy over the parent's own candidate manifest. That it landed
    on the identical universe digest is what a switched-off filter could never
    have shown.
    """
    parent = cf.load_parent()
    frozen = base.latest_receipt("identity-change-migration-closure-v2r3r1-universe", REAL_RECEIPTS)
    assert frozen is not None, "V2R3R1's universe is not frozen"
    assert frozen["universe_sha256"] == parent["universe_sha256"]
    assert frozen["pair_count"] == 300


# ---------------------------------------------------------------------------
# 2. the successor asks the parent's question


def test_the_scientific_projection_is_identical() -> None:
    body = sem.prove_semantic_equivalence()
    assert body["held"] is True
    assert body["no_post_freeze_change_rule_identical"] is True
    assert body["scientific_projection_sha256"].startswith("sha256:")


def _successor_with(change: Any, tmp_path: Path) -> Path:
    successor = sem.load(sem.SUCCESSOR)
    change(successor)
    out = tmp_path / "successor.yaml"
    import yaml

    out.write_text(yaml.safe_dump(successor, allow_unicode=True), encoding="utf-8")
    return out


def test_a_moved_pass_rule_refuses(tmp_path: Path) -> None:
    def move(protocol: dict[str, Any]) -> None:
        protocol["pass_rule"] = {"violations_allowed": 1}

    with pytest.raises(SemanticsDiffer, match="/pass_rule"):
        sem.prove_semantic_equivalence(sem.PARENT, _successor_with(move, tmp_path))


def test_a_moved_cohort_floor_refuses(tmp_path: Path) -> None:
    def move(protocol: dict[str, Any]) -> None:
        protocol["cohort_sufficiency"]["minimum_admitted_pairs"] = 100

    with pytest.raises(SemanticsDiffer, match="minimum_admitted_pairs"):
        sem.prove_semantic_equivalence(sem.PARENT, _successor_with(move, tmp_path))


def test_a_moved_obligation_row_refuses(tmp_path: Path) -> None:
    def move(protocol: dict[str, Any]) -> None:
        protocol["effective_identity_disposition"]["mutated_for_this_test"] = True

    with pytest.raises(SemanticsDiffer, match="effective_identity_disposition"):
        sem.prove_semantic_equivalence(sem.PARENT, _successor_with(move, tmp_path))


def test_a_softened_no_preview_clause_refuses(tmp_path: Path) -> None:
    def move(protocol: dict[str, Any]) -> None:
        protocol["execution"]["no_preview"] = "a small preview is fine"

    with pytest.raises(SemanticsDiffer, match="/execution/no_preview"):
        sem.prove_semantic_equivalence(sem.PARENT, _successor_with(move, tmp_path))


def test_a_softened_no_post_freeze_change_rule_refuses(tmp_path: Path) -> None:
    """The rule the parent chain died on may not be relaxed by its successor."""

    def move(protocol: dict[str, Any]) -> None:
        protocol["freeze"]["no_post_freeze_change"]["rule"] = "amend it if you must"

    with pytest.raises(SemanticsDiffer, match="no_post_freeze_change"):
        sem.prove_semantic_equivalence(sem.PARENT, _successor_with(move, tmp_path))


def test_an_unclassified_new_block_refuses(tmp_path: Path) -> None:
    """A block in neither table is a failure, never a silent default.

    Absorbing whatever happens to differ is how a projection passes by
    construction.
    """

    def move(protocol: dict[str, Any]) -> None:
        protocol["a_brand_new_top_level_block"] = {"threshold": 0.5}

    with pytest.raises(SemanticsDiffer, match="never classified"):
        sem.prove_semantic_equivalence(sem.PARENT, _successor_with(move, tmp_path))


def test_the_administrative_split_is_declared_not_inferred() -> None:
    both = set(sem.SCIENTIFIC_BLOCKS) & set(sem.ADMINISTRATIVE_BLOCKS)
    assert not both, f"a block cannot be both: {both}"
    parent = sem.load(sem.PARENT)
    known = (
        set(sem.SCIENTIFIC_BLOCKS) | set(sem.ADMINISTRATIVE_BLOCKS) | set(sem.PARTIALLY_PROJECTED)
    )
    assert set(parent) <= known


# ---------------------------------------------------------------------------
# 3. the real-cohort closure is unreachable from a test


def test_a_bare_run_refuses_before_the_chain_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control. If the refusal is real, the explosion never fires.

    `fz.workspace` is the first thing `run()` would reach after the
    authorisation check. Patching it to raise turns "the boundary is first" from
    a claim about source order into an observation: an AssertionError here would
    mean the universe was already being opened.
    """

    def explode() -> Any:
        raise AssertionError("the chain was touched before the boundary refused")

    monkeypatch.setattr(scorer.fz, "workspace", explode)
    with pytest.raises(ClosureRefused, match="requires an ExecutionAuthorisation"):
        scorer.run()


def test_a_hand_built_authorisation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compared by identity precisely so a well-shaped forgery does not work."""

    def explode() -> Any:
        raise AssertionError("the chain was touched before the boundary refused")

    monkeypatch.setattr(scorer.fz, "workspace", explode)
    forged = scorer.ExecutionAuthorisation(
        gate={"gate": "require_v2r3r1_execution_preconditions"}, minted_by="me"
    )
    with pytest.raises(ClosureRefused, match="not minted by this process"):
        scorer.run(forged)


def test_minting_refuses_outside_the_one_shot_entry_point() -> None:
    with pytest.raises(ClosureRefused, match="one-shot measurement entry point"):
        scorer.authorise_one_shot(object())


def test_minting_refuses_while_a_test_runner_is_loaded() -> None:
    """Reached only from inside the entry point, so both halves are exercised."""
    assert any(name in sys.modules for name in scorer._TEST_RUNNERS)
    with (
        scorer._one_shot_entry_point(),
        pytest.raises(ClosureRefused, match="test runner is loaded"),
    ):
        scorer.authorise_one_shot(object())


def test_the_cli_does_nothing_without_the_execute_flag(capsys: Any) -> None:
    assert scorer.main([]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["state"] == "NOT_EXECUTED"


def _declared_cli_flags(module: Any) -> set[str]:
    """Every string literal passed to `add_argument`, from the AST.

    A substring scan of the source would match the prose explaining WHY there is
    no `--limit`, which is the opposite of the thing being checked.
    """
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "add_argument":
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                flags.add(argument.value)
    return flags


def test_the_scorer_has_no_limit_or_sample_flag() -> None:
    """A flag whose only use is to look first is a preview flag."""
    flags = _declared_cli_flags(scorer)
    assert flags == {"--write-receipt", "--execute"}, flags
    for forbidden in ("--limit", "--sample", "--preview", "--dry-run", "--force"):
        assert forbidden not in flags, forbidden


#: The real-cohort measurement modules. Matched on the IMPORTED MODULE, resolved
#: through whatever local name it was bound to -- not on the local name itself.
#: A scan keyed on the alias `scorer` flags `test_sfi2_scoring.py`, which imports
#: an entirely different study's scorer and runs it on a synthetic acquisition.
#: Flagging that would be a false positive, and a scan that cries wolf is one a
#: future reader silences.
_CLOSURE_MODULE_PREFIX = "identity_change_migration_closure"


def _closure_aliases(tree: ast.AST) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_CLOSURE_MODULE_PREFIX):
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            _CLOSURE_MODULE_PREFIX
        ):
            for alias in node.names:
                aliases.add(alias.asname or alias.name)
    return aliases


def _closure_calls(tree: ast.AST, aliases: set[str] | None = None) -> list[ast.Call]:
    """Calls that would read the real cohort.

    `.run(...)` always counts. `.main(...)` counts only when its argument list
    literally contains `--execute`, because without that flag `main` prints
    NOT_EXECUTED and touches nothing -- and the test that proves THAT has to be
    able to call it.
    """
    if aliases is None:
        aliases = _closure_aliases(tree) or {"scorer"}
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"run", "main"}:
            continue
        if getattr(func.value, "id", "") not in aliases:
            continue
        if func.attr == "main":
            literals = {
                element.value
                for argument in node.args
                if isinstance(argument, ast.List)
                for element in argument.elts
                if isinstance(element, ast.Constant)
            }
            if "--execute" not in literals:
                continue
        found.append(node)
    return found


def _guarded_lines(tree: ast.AST) -> set[int]:
    """Every line inside a `with pytest.raises(...)` block.

    Computed from the block's own line span rather than by looking at nearby
    text, so a call three lines below an unrelated `pytest.raises` is not
    mistaken for a guarded one.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if not isinstance(call, ast.Call):
                continue
            parts: list[str] = []
            target: Any = call.func
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                parts.append(target.id)
            if ".".join(reversed(parts)) == "pytest.raises":
                guarded.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return guarded


def test_no_test_in_this_suite_executes_the_closure() -> None:
    """An AST scan over every test file, kept as a second line of defence.

    The authorisation boundary is the real protection now, but this stays: it
    catches the mistake where it is WRITTEN rather than where it would have run,
    and the parent chain's whole failure was a call that looked harmless in the
    file it lived in.

    A call inside `with pytest.raises(...)` is allowed, because that is a
    refusal test and the refusal is the assertion. Guardedness is decided from
    the `with` block's line span, not from text near the call.
    """
    offenders: list[str] = []
    scanned = 0
    for path in sorted((NS / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _closure_aliases(tree)
        if not aliases:
            continue
        scanned += 1
        guarded = _guarded_lines(tree)
        for call in _closure_calls(tree, aliases):
            if call.lineno not in guarded:
                offenders.append(f"{path.name}:{call.lineno}")
    #: A scan that found no file importing a closure module is a scan that would
    #: have passed whatever the tests contained (INC-V2-044).
    assert scanned, "no test file imports a closure module, so this scan looked at nothing"
    assert not offenders, (
        "these tests call the closure outside a refusal assertion, so they would "
        f"execute it: {offenders}"
    )


def test_the_scan_that_watches_for_that_can_actually_see_it(tmp_path: Path) -> None:
    """The scan's own red direction. A scan that cannot find anything finds nothing."""
    unguarded = "def test_bad():\n    scorer.run()\n"
    tree = ast.parse(unguarded)
    calls = _closure_calls(tree)
    assert calls, "the scan cannot see a bare closure call"
    assert calls[0].lineno not in _guarded_lines(tree)

    wrapped = (
        "import pytest\n"
        "def test_good():\n"
        "    with pytest.raises(RuntimeError):\n"
        "        scorer.run()\n"
    )
    tree = ast.parse(wrapped)
    calls = _closure_calls(tree)
    assert calls, "the scan cannot see a guarded closure call either"
    assert calls[0].lineno in _guarded_lines(tree)

    #: And a call that merely SITS NEAR a `pytest.raises` is not guarded. This is
    #: the case a text-window heuristic gets wrong, and the reason guardedness is
    #: taken from the `with` block's own line span.
    adjacent = (
        "import pytest\n"
        "def test_sneaky():\n"
        "    with pytest.raises(RuntimeError):\n"
        "        pass\n"
        "    scorer.run()\n"
    )
    tree = ast.parse(adjacent)
    calls = _closure_calls(tree)
    assert calls and calls[0].lineno not in _guarded_lines(tree)


# ---------------------------------------------------------------------------
# 4. the census repair the parent chain died on


def test_the_scorer_aggregates_exactly_the_keys_the_surface_reports() -> None:
    """Built from a SYNTHETIC surface. No corpus is opened."""
    surface = eff.build_effective_surface({}, {}, "synthetic:source")
    produced = set(surface.as_dict())
    aggregated = {
        "matched_pairs",
        "matched_with_differing_raw_ids",
        "quarantine_overrides",
        "quarantine_members",
        "effective_census",
        "resolver_census",
        "quarantine_overrides_by_resolver_state",
    }
    assert aggregated <= produced, sorted(aggregated - produced)


def test_a_renamed_census_key_refuses_before_aggregating() -> None:
    """The repair itself. The parent chain died summing a key that did not exist.

    It died AFTER diffing all 300 pairs, which is the part that matters: a
    KeyError raised mid-aggregation has already read the whole cohort. This
    refuses on the shape, before the first sum.
    """
    extra = [{"census": {"matched_pairs": 1}}]
    with pytest.raises(ClosureRefused, match="does not report"):
        scorer._require_census_keys(extra, ("matched_pairs", "effective"))


def test_the_census_guard_names_both_sides_of_the_disagreement() -> None:
    extra = [{"census": {"matched_pairs": 1}}]
    with pytest.raises(ClosureRefused) as caught:
        scorer._require_census_keys(extra, ("matched_pairs", "quarantine_members"))
    message = str(caught.value)
    assert "quarantine_members" in message
    assert "matched_pairs" in message


def test_the_census_guard_passes_when_the_keys_are_present() -> None:
    scorer._require_census_keys([{"census": {"a": 1, "b": 2}}], ("a", "b"))


# ---------------------------------------------------------------------------
# 5. the gate consumes the attestations


#: The receipts directory's path RELATIVE TO THE REPO ROOT. A sandbox has to
#: mirror it, because an attestation binds its base receipt by repo-relative path
#: and `_verify_base_binding` resolves that against `ws.root`. A flat copy into
#: `tmp/receipts` makes every binding look superseded -- which is a red the test
#: did not ask for, and would have hidden the reds it did.
RECEIPTS_REL = REAL_RECEIPTS.relative_to(ROOT)


@pytest.fixture(scope="module")
def frozen_chain(tmp_path_factory: Any) -> Path:
    """A sandbox ROOT holding a copy of the real chain's receipts.

    Made once, never written back. Payload files are still read from the real
    tree -- they are read-only inputs and copying 1,200 of them per test would
    buy nothing.
    """
    sandbox = tmp_path_factory.mktemp("chain")
    target = sandbox / RECEIPTS_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REAL_RECEIPTS, target)
    #: The gate resolves every PINNED FILE against `ws.root` too -- the scorer
    #: modules, the protocol, the exclusion policy. A sandbox holding only
    #: receipts makes the gate refuse with "a frozen scorer module has
    #: disappeared", which is a red, but not the red the test asked for. Source
    #: directories are small; artifacts are not, and nothing here reads them
    #: through `ws.root`.
    for name in ("tools", "acquisition", "protocols", "source_fact_ir", "compiler", "docs"):
        source = NS / name
        if source.is_dir():
            shutil.copytree(source, sandbox / NS.relative_to(ROOT) / name)
    return sandbox


def _ws(sandbox: Path) -> Any:
    return fz.V2R3R1Workspace(
        root=sandbox,
        receipts=sandbox / RECEIPTS_REL,
        prior_receipts=REAL_RECEIPTS,
    )


def _copy(frozen_chain: Path, tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    shutil.copytree(frozen_chain, sandbox)
    return sandbox


#: The one pinned file that has legitimately moved since V2R3R1 froze, and the
#: only one this suite will tolerate moving.
#:
#: `tests/test_v2r3_contract_consistency.py` recomputed V2R3's
#: `realised_at_declaration` root counts against the LIVE tree. Those are, by the
#: block's own name, facts about the moment V2R3 declared -- so the recomputation
#: drifts the instant a successor frame lands, and V2R4's added 86 identities and
#: turned 875 into 961 without a single V2R3 number changing. The assertion was
#: split: declaration-time counts are re-derived over the modules that existed
#: THEN, and disjointness stayed LIVE against every frame including successors,
#: which is strictly stronger than what it replaced.
#:
#: There was no way to leave the file untouched. Making the old assertion true
#: again would have required V2R4's roots to be invisible to `root_identity`,
#: which is the one control that stops a future study declaring a spent
#: container -- the control whose absence let 7 CFR 273 into the V2R2 frame.
#: Recorded as INC-V2-075 rather than absorbed silently.
#:
#: NOTHING SCIENTIFIC MOVED. Both protocols, the state table, the effective
#: identity module, the quarantine oracle, the semantics checker and the compat
#: document all still hash to what V2R3R1 sealed, and this suite fails if any of
#: them stops doing so.
KNOWN_MOVED_PIN = "tests/test_v2r3_contract_consistency.py"


def test_every_scientific_pin_v2r3r1_froze_still_holds(frozen_chain: Path) -> None:
    """The frozen chain's pins, checked one by one rather than as a single verdict.

    `verify_all` refuses on the FIRST drifted pin, so a bare "it refuses" would
    say nothing about the other seven. This walks them, so a second file moving
    is a new red rather than being absorbed into an expected one.
    """
    import hashlib
    import json

    receipts = sorted(
        REAL_RECEIPTS.glob(
            "identity-change-migration-closure-v2r3r1-protocol-attestation--*.json"
        )
    )
    assert receipts, "no protocol attestation on disk; this control would be vacuous"

    moved = []
    for path in receipts:
        pinned = json.loads(path.read_text(encoding="utf-8"))["pinned_files"]
        assert KNOWN_MOVED_PIN in pinned, "the known-moved pin is not pinned at all"
        for name, digest in sorted(pinned.items()):
            target = NS / name
            assert target.is_file(), f"{name} is gone"
            current = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
            if current != digest:
                moved.append(name)

    assert set(moved) == {KNOWN_MOVED_PIN}, (
        f"pinned files moved that this suite does not know about: "
        f"{sorted(set(moved) - {KNOWN_MOVED_PIN})}. A frozen chain's proof was made "
        "about a different tree than the one that would run."
    )


def test_the_frame_and_universe_rungs_still_verify_intact(frozen_chain: Path) -> None:
    """The two rungs no successor could disturb, verified end to end."""
    ws = _ws(frozen_chain)
    frame = att.verify_frame(ws)
    universe = att.verify_universe(ws)
    assert frame["attestation"]
    assert universe["recomputed"]["intersections"] == {"v2r1": 0, "v2r2": 0}


def test_the_protocol_rung_refuses_and_names_the_file_that_moved(
    frozen_chain: Path,
) -> None:
    """Truthful about the current state, and still red for any OTHER reason.

    The refusal is the pin working, not the pin failing. What this asserts is
    that it refuses for the ONE recorded reason and names it -- a refusal citing
    a different file, or a silent pass, both turn this red.
    """
    with pytest.raises(FreezeRefused, match="attests files that have since changed") as caught:
        att.verify_protocol(_ws(frozen_chain))
    message = str(caught.value)
    assert KNOWN_MOVED_PIN in message
    for untouched in (
        "tools/v2r3r1_semantics.py",
        "tools/v2r3_state_table.py",
        "protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml",
    ):
        assert untouched not in message, f"{untouched} moved and it must not have"


@pytest.mark.parametrize(
    ("stem_key", "verifier"),
    [
        ("frame-attestation", att.verify_frame),
        ("protocol-attestation", att.verify_protocol),
        ("universe-attestation", att.verify_universe),
    ],
)
def test_deleting_a_companion_receipt_turns_the_gate_red(
    frozen_chain: Path, tmp_path: Path, stem_key: str, verifier: Any
) -> None:
    sandbox = _copy(frozen_chain, tmp_path)
    for path in (sandbox / RECEIPTS_REL).glob(
        f"identity-change-migration-closure-v2r3r1-{stem_key}--*.json"
    ):
        path.unlink()
    with pytest.raises(FreezeRefused, match="companion attestation is missing"):
        verifier(_ws(sandbox))


def test_editing_an_attested_source_file_turns_the_gate_red(
    frozen_chain: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pins are recomputed, not read back from the receipt."""
    receipts = _copy(frozen_chain, tmp_path)
    sandbox = tmp_path / "ns"
    sandbox.mkdir()
    (sandbox / "acquisition").mkdir()
    (sandbox / "tools").mkdir()
    for name in att.FRAME_PINS:
        target = sandbox / name
        target.write_text(
            (NS / name).read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8"
        )
    monkeypatch.setattr(att.att, "NS", sandbox)
    with pytest.raises(FreezeRefused, match="attests files that have since changed"):
        att.verify_frame(_ws(receipts))


def test_replacing_the_attested_base_receipt_turns_the_gate_red(
    frozen_chain: Path, tmp_path: Path
) -> None:
    """A later receipt for the same rung breaks the binding by run id."""
    sandbox = _copy(frozen_chain, tmp_path)
    receipts = sandbox / RECEIPTS_REL
    stem = "identity-change-migration-closure-v2r3r1-acquisition-frame-freeze"
    latest = sorted(receipts.glob(f"{stem}--*.json"))[-1]
    body = json.loads(latest.read_text(encoding="utf-8"))
    body["provenance"]["run_id"] = "99991231T235959Z-ffffffffffff"
    (receipts / f"{stem}--99991231T235959Z-ffffffffffff.json").write_text(
        json.dumps(body), encoding="utf-8"
    )
    with pytest.raises(FreezeRefused, match="superseded rung"):
        att.verify_frame(_ws(sandbox))


def test_a_parent_disposition_claiming_disclosure_turns_the_gate_red(
    frozen_chain: Path, tmp_path: Path
) -> None:
    sandbox = _copy(frozen_chain, tmp_path)
    stem = "identity-change-migration-closure-v2r3-non-disclosure"
    latest = sorted((sandbox / RECEIPTS_REL).glob(f"{stem}--*.json"))[-1]
    body = json.loads(latest.read_text(encoding="utf-8"))
    body["outcome_disclosure"] = "PARTIAL"
    latest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(FreezeRefused, match="not NONE_ESTABLISHED"):
        att.prove_parent_disposition(_ws(sandbox))


def test_a_parent_corpus_marked_spent_turns_the_gate_red(
    frozen_chain: Path, tmp_path: Path
) -> None:
    sandbox = _copy(frozen_chain, tmp_path)
    stem = "identity-change-migration-closure-v2r3-chain-disposition"
    latest = sorted((sandbox / RECEIPTS_REL).glob(f"{stem}--*.json"))[-1]
    body = json.loads(latest.read_text(encoding="utf-8"))
    body["corpus_status"] = "SPENT"
    latest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(FreezeRefused, match="Only unscored material"):
        att.prove_parent_disposition(_ws(sandbox))


def test_an_existing_measurement_turns_the_gate_red(frozen_chain: Path, tmp_path: Path) -> None:
    """The base gate REPORTS a prior measurement; this gate REFUSES on it."""
    sandbox = _copy(frozen_chain, tmp_path)
    (
        sandbox
        / RECEIPTS_REL
        / "identity-change-migration-closure-v2r3r1--20260101T000000Z-aaaaaaaaaaaa.json"
    ).write_text(json.dumps({"pair_count": 300}), encoding="utf-8")
    with pytest.raises(FreezeRefused) as caught:
        fz.require_v2r3r1_execution_preconditions(_ws(sandbox))
    message = str(caught.value)
    assert "already exists" in message
    assert "EXACTLY ONCE" in message


def test_importing_another_adapter_does_not_change_this_ones_bindings() -> None:
    """Import order is not a thing anybody should have to remember.

    The parent chain learned this twice: a permanent import-time rebind made 21
    of 24 V2R2 gate tests assert things about V2R1 and pass. Nothing is rebound
    at import here, so importing every adapter in the process changes nothing.
    """
    import freeze_migration_closure_v2r2  # noqa: F401
    import freeze_migration_closure_v2r3  # noqa: F401

    assert base.PROTOCOL != fz.PROTOCOL
    assert base.Workspace is not fz.V2R3R1Workspace
    with fz._bound():
        assert base.PROTOCOL == fz.PROTOCOL
        assert base.Workspace is fz.V2R3R1Workspace
    assert base.PROTOCOL != fz.PROTOCOL


def _called_attribute_names(module: Any) -> set[str]:
    """`a.b.c(...)` -> {"a.b.c"}, from the AST. Prose is not a call."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        target: Any = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
            called.add(".".join(reversed(parts)))
    return called


def test_the_gate_is_this_chains_gate_not_the_base_one() -> None:
    """Checked against CALLS, not against the source text.

    The scorer's docstring names both the base gate and the parent's precisely to
    explain why neither is used. A substring scan would read that explanation as
    the violation it warns about.
    """
    assert fz.STAGES["gate"] is fz.require_v2r3r1_execution_preconditions
    called = _called_attribute_names(scorer)
    assert "fz.require_v2r3r1_execution_preconditions" in called
    assert "base.require_execution_preconditions" not in called
    assert "fz.require_v2r3_execution_preconditions" not in called
    assert not any(name.endswith("require_v2r3_execution_preconditions") for name in called)


def test_the_enumerator_makes_no_network_call() -> None:
    source = Path(enumerate_lane.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in getattr(node, "names", ())
    }
    for forbidden in ("requests", "urllib", "http", "httpx", "socket", "aiohttp"):
        assert forbidden not in imported, forbidden
