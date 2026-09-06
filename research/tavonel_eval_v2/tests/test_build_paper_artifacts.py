"""Tests for `paper/build_paper_artifacts.py`. LANE F, PAPER CLOSURE PROGRAM.

The absolute rule this generator exists to hold: never emit a number that was
not read out of a receipt or a protocol file, and never emit a placeholder
that looks like a result. These tests exercise that rule directly rather than
just checking the tables look plausible:

* Table 1 and Table 2 are checked against values independently recomputed
  from the same source files (`sources_sfir4.SOURCE_POOLS`/`declared_roots`,
  and a hand-traced reading of `SFIR4_CLAIM_CHAIN.yaml`'s `evidence_source`
  fields) -- not merely "non-empty".
* a fabricated `receipts/latest/*.json` pointer whose declared
  `points_to_file_sha256` does not match its target's real bytes is REFUSED,
  not silently followed.
* a missing required input (an absent receipts directory) is REFUSED, not
  skipped into a partial table.
* injecting a fake forbidden phrase into a fixture proves `assert_clean`
  actually fires, then the real generated tables are checked clean against
  the real `CLAIM_MATRIX.yaml` forbidden list.
* the cost table's `contributing_receipts` count is checked against an
  independent walk of `receipts/*.json`.
* the Mermaid figure is checked for its node count and that no node carries
  an invented state (only `SEALED sha256=...` or the `PENDING (...)` form
  this generator itself defines).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "paper"))
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS))

import build_paper_artifacts as bpa  # noqa: E402
import sfir4_execution as sfir4_execution_module  # noqa: E402
from acquisition import sources_sfir4 as sources_sfir4_module  # noqa: E402
from common import canonical_sha, sha_file  # noqa: E402

# ---------------------------------------------------------------------------
# Table 1 -- fully populated today, checked against an independent recompute


def test_table1_is_fully_populated_from_real_files_today() -> None:
    table = bpa.build_table1()
    assert len(table["rows"]) == len(sources_sfir4_module.FAMILIES) == 3

    by_family = {row["family"]: row for row in table["rows"]}
    for family in sources_sfir4_module.FAMILIES:
        row = by_family[family]
        # independently recomputed, not merely re-read from the same call
        assert row["authority"] == sources_sfir4_module.FAMILY_AUTHORITIES[family]
        assert row["declared_roots"] == len(sources_sfir4_module.declared_roots(family))
        assert isinstance(row["declared_roots"], int) and row["declared_roots"] > 0
        assert isinstance(row["per_root_candidate_cap"], int) and row["per_root_candidate_cap"] > 0
        assert "750" in row["capacity_criterion"]
        assert "600" in row["capacity_criterion"]
        # no cell is a placeholder
        assert row["authority"] and "PENDING" not in row["authority"]


def test_table1_per_root_cap_matches_source_pools_exactly() -> None:
    table = bpa.build_table1()
    by_family = {row["family"]: row for row in table["rows"]}
    pools = sources_sfir4_module.SOURCE_POOLS
    assert by_family["git_docs"]["per_root_candidate_cap"] == pools["git_docs"][
        "max_candidates_per_repository"
    ]
    assert by_family["regulation_ecfr"]["per_root_candidate_cap"] == pools["regulation_ecfr"][
        "max_candidates_per_title"
    ]
    assert by_family["encyclopedia_wikipedia"]["per_root_candidate_cap"] == pools[
        "encyclopedia_wikipedia"
    ]["max_candidates_per_category"]


# ---------------------------------------------------------------------------
# Table 2 -- every endpoint maps, UNMAPPED where the chain is silent


#: Hand-traced from paper/SFIR4_CLAIM_CHAIN.yaml's `evidence_source` field on
#: each link, reading only that field (not the `measured` narrative prose,
#: which is not where the chain declares a link's evidence binding). This is
#: the independent control the generator's own output is checked against.
EXPECTED_ENDPOINT_LINKS = {
    "E1_no_unclassified_changed_regions": ["L2"],
    "E2_no_recognized_but_unrepresented": ["L4", "L8"],
    "E3_no_silent_loss_in_a_complete_scope": [],
    "E4_no_reference_or_locator_only_clean_miss": [],
    "E5_no_confirmed_selective_stale_escape": ["L1", "L6", "L8"],
    "E6_exact_selective_vs_clean_equivalence": ["L1", "L6", "L8"],
    "E7_unresolved_fails_closed": ["L1", "L3", "L8"],
    "E8_no_rebuild_required_artifact_carried_without_execution": [],
    "E9_every_detected_typed_change_creates_a_rebuild_request": ["L2", "L5", "L8"],
}


def test_table2_maps_every_endpoint_against_an_independent_trace() -> None:
    table = bpa.build_table2()
    assert len(table["rows"]) == 9 == len(sfir4_execution_module.ENDPOINTS)

    by_endpoint = {row["endpoint"]: row for row in table["rows"]}
    assert set(by_endpoint) == set(sfir4_execution_module.ENDPOINTS)

    for endpoint, expected_links in EXPECTED_ENDPOINT_LINKS.items():
        row = by_endpoint[endpoint]
        if expected_links:
            assert row["claim_links"] == sorted(expected_links), endpoint
        else:
            assert row["claim_links"] == "UNMAPPED", endpoint


def test_table2_veto_is_e8_and_every_other_row_is_primary() -> None:
    table = bpa.build_table2()
    veto_rows = [row for row in table["rows"] if row["role"] == "VETO"]
    assert len(veto_rows) == 1
    assert veto_rows[0]["endpoint"] == sfir4_execution_module.VETO_ENDPOINT
    assert veto_rows[0]["endpoint"].startswith("E8_")
    primary_rows = [row for row in table["rows"] if row["role"] == "PRIMARY"]
    assert {row["endpoint"] for row in primary_rows} == set(
        sfir4_execution_module.PRIMARY_ENDPOINTS
    )


def test_table2_unmapped_endpoints_say_unmapped_not_a_guess() -> None:
    """A control that the UNMAPPED string itself appears -- a row silently
    getting `claim_links: []` instead would look like "checked, found
    nothing" rather than "the chain never declared a binding here", and a
    reader skimming the table needs the difference to be visible."""
    table = bpa.build_table2()
    by_endpoint = {row["endpoint"]: row for row in table["rows"]}
    assert by_endpoint["E3_no_silent_loss_in_a_complete_scope"]["claim_links"] == "UNMAPPED"
    assert by_endpoint["E8_no_rebuild_required_artifact_carried_without_execution"][
        "claim_links"
    ] == "UNMAPPED"
    # and no row is ever a bare empty list, which would look like "mapped to nothing"
    for row in table["rows"]:
        assert row["claim_links"] != []


def test_table2_range_mention_does_not_leak_into_a_binding() -> None:
    """L7's evidence_source reads '...SFIR4's analysis floor (E1-E9) is scoped
    to diff/dependency/recompilation, not to publication' -- a range naming
    the whole protocol's endpoint span, immediately followed by an explicit
    disclaimer that L7 has no SFIR4 endpoint behind it at all. A naive 'does
    the endpoint's short code appear in this text' scan matches E1 and E9
    here and would wrongly bind L7 to both. Confirm L7 is absent from every
    endpoint's claim_links."""
    table = bpa.build_table2()
    for row in table["rows"]:
        links = row["claim_links"]
        if links != "UNMAPPED":
            assert "L7" not in links, row["endpoint"]


# ---------------------------------------------------------------------------
# Table 3 -- baselines: real sweep is non-empty; the NO BASELINE fallback
# is exercised directly against a fixture with nothing to find


def test_table3_finds_the_declared_gpu_successor_baseline_today() -> None:
    table = bpa.build_table3()
    assert table["declared_arms"] is not None
    assert set(table["declared_arms"]["arms"]) == {"TYPED_REPRESENTATION", "TEXT_ONLY_BASELINE"}
    assert "declared, not measured" in table["declared_arms"]["status"]


def test_table3_sfir4_itself_declares_no_baseline() -> None:
    table = bpa.build_table3()
    assert "declare no baseline arm" in table["note"]


def test_table3_no_baseline_declared_fallback_is_the_honest_single_row(tmp_path: Path) -> None:
    empty_protocols = tmp_path / "protocols"
    empty_protocols.mkdir()
    (empty_protocols / "SOME_PROTOCOL.yaml").write_text("schema: test\n", encoding="utf-8")

    table = bpa.build_table3(protocols_dir=empty_protocols, preflight_module=None)
    assert table["rows"] == [
        {
            "status": "NO BASELINE DECLARED",
            "checked_protocols": [bpa.safe_rel(empty_protocols / "SOME_PROTOCOL.yaml")],
        }
    ]


# ---------------------------------------------------------------------------
# pointer verification -- fail closed on a fabricated / missing / mismatched
# pointer, and on a missing required input


def _write_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_a_fabricated_pointer_with_a_wrong_digest_is_refused(tmp_path: Path) -> None:
    root = tmp_path
    receipts = root / "research" / "tavonel_eval_v2" / "receipts"
    target = receipts / "fixture-stem--20260101T000000Z-deadbeef.json"
    _write_json(target, {"schema": "fixture", "verdict": "PASS"})

    real_sha = sha_file(target)
    fabricated_sha = "sha256:" + "0" * 64
    assert fabricated_sha != real_sha

    _write_json(
        receipts / "latest" / "fixture-stem.json",
        {
            "schema": bpa.POINTER_SCHEMA,
            "points_to": "research/tavonel_eval_v2/receipts/"
            "fixture-stem--20260101T000000Z-deadbeef.json",
            "points_to_file_sha256": fabricated_sha,
        },
    )

    with pytest.raises(bpa.GenerationRefused, match="digest mismatch"):
        bpa.resolve_receipt("fixture-stem", receipts_dir=receipts, root=root)


def test_a_pointer_naming_a_target_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    root = tmp_path
    receipts = root / "research" / "tavonel_eval_v2" / "receipts"
    _write_json(
        receipts / "latest" / "ghost-stem.json",
        {
            "schema": bpa.POINTER_SCHEMA,
            "points_to": "research/tavonel_eval_v2/receipts/ghost-stem--nope.json",
            "points_to_file_sha256": "sha256:" + "1" * 64,
        },
    )
    with pytest.raises(bpa.GenerationRefused, match="does not exist"):
        bpa.resolve_receipt("ghost-stem", receipts_dir=receipts, root=root)


def test_a_correct_pointer_resolves_cleanly(tmp_path: Path) -> None:
    root = tmp_path
    receipts = root / "research" / "tavonel_eval_v2" / "receipts"
    target = receipts / "good-stem--20260101T000000Z-cafef00d.json"
    _write_json(target, {"schema": "fixture", "verdict": "PASS"})
    real_sha = sha_file(target)
    _write_json(
        receipts / "latest" / "good-stem.json",
        {
            "schema": bpa.POINTER_SCHEMA,
            "points_to": "research/tavonel_eval_v2/receipts/"
            "good-stem--20260101T000000Z-cafef00d.json",
            "points_to_file_sha256": real_sha,
        },
    )
    found = bpa.resolve_receipt("good-stem", receipts_dir=receipts, root=root)
    assert found is not None
    assert found["sha256"] == real_sha
    assert found["via"] == "pointer"
    assert found["body"]["verdict"] == "PASS"


def test_a_legacy_bare_receipt_whose_self_hash_does_not_recompute_is_refused(
    tmp_path: Path,
) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    bare = receipts / "legacy-stem.json"
    # a self-declared hash that does not match a canonical hash of the rest
    body = {"schema": "fixture", "verdict": "PASS", "receipt_sha256": "sha256:" + "9" * 64}
    _write_json(bare, body)
    with pytest.raises(bpa.GenerationRefused, match="self-hash does not recompute"):
        bpa.resolve_receipt("legacy-stem", receipts_dir=receipts, root=tmp_path)


def test_a_legacy_bare_receipt_whose_self_hash_does_recompute_resolves(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    bare = receipts / "legacy-stem.json"
    body = {"schema": "fixture", "verdict": "PASS"}
    body["receipt_sha256"] = canonical_sha(body)
    _write_json(bare, body)
    found = bpa.resolve_receipt("legacy-stem", receipts_dir=receipts, root=tmp_path)
    assert found is not None
    assert found["via"] == "legacy_bare"
    assert found["body"]["verdict"] == "PASS"


def test_a_missing_receipts_directory_is_refused_not_silently_skipped(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(bpa.GenerationRefused, match="missing"):
        bpa.build_table5(receipts_dir=missing)


def test_a_missing_charter_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(bpa.GenerationRefused, match="missing"):
        bpa.build_table1(charter_path=tmp_path / "no_such_charter.yaml")


# ---------------------------------------------------------------------------
# forbidden phrases -- prove the check fires on an injected phrase, then that
# the real generated tables are clean against the real list


def test_assert_clean_fires_on_an_injected_forbidden_phrase() -> None:
    forbidden = [("F-99-FIXTURE", "this exact fixture phrase must never appear")]
    with pytest.raises(bpa.GenerationRefused, match="forbidden phrase"):
        bpa.assert_clean(
            "some generated text containing THIS EXACT FIXTURE PHRASE MUST NEVER APPEAR here",
            forbidden,
            where="fixture table",
        )


def test_assert_clean_passes_clean_text() -> None:
    forbidden = [("F-99-FIXTURE", "this exact fixture phrase must never appear")]
    bpa.assert_clean("nothing suspicious in here", forbidden, where="fixture table")


def test_real_generated_tables_contain_no_real_forbidden_phrase() -> None:
    forbidden = bpa.load_forbidden_phrases()
    assert len(forbidden) >= 5  # CLAIM_MATRIX.yaml currently declares F-01..F-05

    table1 = bpa.build_table1()
    table2 = bpa.build_table2()
    table3 = bpa.build_table3()
    table5 = bpa.build_table5()
    figure5 = bpa.build_figure5()

    for name, artifact in (
        ("table1", table1),
        ("table2", table2),
        ("table3", table3),
        ("table5", table5),
        ("figure5", figure5),
    ):
        # must not raise
        bpa.assert_clean(json.dumps(artifact, ensure_ascii=False), forbidden, where=name)


# ---------------------------------------------------------------------------
# Table 5 -- cost table reports its contributing-receipt count, checked
# against an independent walk of the same directory


def test_table5_reports_contributing_receipt_count_alongside_the_sum() -> None:
    table = bpa.build_table5()

    gpu_count = 0
    gpu_sum = 0.0
    cost_count = 0
    cost_sum = 0.0
    scanned = 0
    for path in sorted(bpa.RECEIPTS_DIR.glob("*.json")):
        scanned += 1
        body = json.loads(path.read_text(encoding="utf-8"))
        if "gpu_seconds" in body:
            gpu_count += 1
            gpu_sum += body["gpu_seconds"]
        if "estimated_cost_usd" in body:
            cost_count += 1
            cost_sum += body["estimated_cost_usd"]

    assert table["receipts_scanned"] == scanned
    assert table["gpu_seconds"]["contributing_receipts"] == gpu_count
    assert table["gpu_seconds"]["sum"] == gpu_sum
    assert table["estimated_cost_usd"]["contributing_receipts"] == cost_count
    assert table["estimated_cost_usd"]["sum"] == cost_sum
    # a zero sum must still carry a nonzero contributing count to be legible
    # as "measured zero" rather than "nothing found"
    assert table["gpu_seconds"]["contributing_receipts"] > 0
    assert table["estimated_cost_usd"]["contributing_receipts"] > 0


def test_table5_refuses_a_non_numeric_gpu_seconds_field(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_json(receipts / "bad.json", {"gpu_seconds": "not a number"})
    with pytest.raises(bpa.GenerationRefused, match="gpu_seconds is not numeric"):
        bpa.build_table5(receipts_dir=receipts)


def test_table5_refuses_a_non_numeric_cost_field(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_json(receipts / "bad.json", {"estimated_cost_usd": "0.1536 x 2.5 = 0.38"})
    with pytest.raises(bpa.GenerationRefused, match="estimated_cost_usd is not numeric"):
        bpa.build_table5(receipts_dir=receipts)


# ---------------------------------------------------------------------------
# Figure 5 -- parses as text, has the expected node count, invents no state


def test_figure5_mermaid_has_nine_nodes_and_eight_edges() -> None:
    figure = bpa.build_figure5()
    mermaid = figure["mermaid"]
    assert mermaid.startswith("flowchart TD")
    assert len(figure["nodes"]) == 9 == len(bpa.FIGURE5_ORDER)

    node_lines = [
        line for line in mermaid.splitlines() if "-->" not in line and "flowchart" not in line
    ]
    assert len(node_lines) == 9
    edge_lines = [line for line in mermaid.splitlines() if "-->" in line]
    assert len(edge_lines) == 8


def test_figure5_every_node_id_appears_in_the_mermaid_text_in_declared_order() -> None:
    figure = bpa.build_figure5()
    mermaid = figure["mermaid"]
    positions = [mermaid.index(f"{node_id}[") for node_id in bpa.FIGURE5_ORDER]
    assert positions == sorted(positions)


def test_figure5_no_node_carries_an_invented_state() -> None:
    """Every node's `state` is either the literal SEALED-with-sha form this
    generator writes, or the PENDING(...) form -- never a bare word like
    'DONE', 'READY', 'PASS', or any state string this generator did not
    itself construct from a real digest or a written reason."""
    figure = bpa.build_figure5()
    for node in figure["nodes"]:
        state = node["state"]
        if state.startswith("SEALED"):
            assert state.startswith("SEALED sha256=sha256:")
            assert len(state) > len("SEALED sha256=sha256:")
        else:
            assert state.startswith("PENDING (no receipt yet: ")
            assert state.endswith(")")


def test_figure5_execution_node_is_sealed_against_the_real_committed_receipt() -> None:
    """The one node this tree currently has real evidence for: the legacy
    bare receipt at receipts/sfir4-execution-closure.json. Checked against an
    independently computed file hash, not merely "starts with SEALED"."""
    figure = bpa.build_figure5()
    by_id = {node["id"]: node for node in figure["nodes"]}
    execution_node = by_id["execution"]
    real_path = bpa.RECEIPTS_DIR / "sfir4-execution-closure.json"
    if not real_path.is_file():
        pytest.skip("receipts/sfir4-execution-closure.json is not present in this checkout")
    assert execution_node["state"] == f"SEALED sha256={sha_file(real_path)}"
    assert execution_node["stem"] == "sfir4-execution-closure"


def test_figure5_stages_with_no_fixed_path_convention_are_pending_not_guessed() -> None:
    figure = bpa.build_figure5()
    by_id = {node["id"]: node for node in figure["nodes"]}
    for node_id in ("charter_freeze", "live_capacity_census", "capacity_seal", "roster_freeze"):
        node = by_id[node_id]
        assert node["stem"] is None
        assert "not located by a fixed filename convention" in node["state"]


# ---------------------------------------------------------------------------
# full generate() + reproducibility.json, on disk, once


def test_generate_writes_all_artifacts_and_a_hashed_reproducibility_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "generated"
    monkeypatch.setattr(bpa, "GENERATED_DIR", output_dir)

    result = bpa.generate(write=True)
    assert set(result) >= {
        "table1_source_families",
        "table2_primary_endpoints",
        "table3_baselines",
        "table5_efficiency_cost",
        "figure5_evidence_chain",
    }

    for name in (
        "table1_source_families.json",
        "table2_primary_endpoints.json",
        "table3_baselines.json",
        "table5_efficiency_cost.json",
        "figure5_evidence_chain.mmd",
        "reproducibility.json",
    ):
        assert (output_dir / name).is_file(), name

    reproducibility = json.loads((output_dir / "reproducibility.json").read_text(encoding="utf-8"))
    assert reproducibility["schema"] == "tavonel.v2.paper_artifacts_reproducibility.v1"
    # write_hashed's own convention: self-hash over every other key
    bare = {k: v for k, v in reproducibility.items() if k != "receipt_sha256"}
    assert canonical_sha(bare) == reproducibility["receipt_sha256"]
    # every cited input actually hashes to the pinned digest, right now
    assert reproducibility["claim_matrix"]["sha256"] == sha_file(bpa.CLAIM_MATRIX_PATH)
    assert reproducibility["table1_source_families"]["charter"]["sha256"] == sha_file(
        bpa.SFIR4_CHARTER_PATH
    )


# --- generated artifacts must hash the same on every platform ---------------


def _generate_into(tmp_path, monkeypatch):
    out = tmp_path / "generated"
    monkeypatch.setattr(bpa, "GENERATED_DIR", out)
    bpa.generate(write=True)
    return out


def test_every_hashed_artifact_is_written_with_lf_on_every_platform(tmp_path, monkeypatch):
    """`Path.write_text` translates \n to the platform separator, so the same
    generator emits byte-different files on Windows and Linux for identical
    content. `build_reproducibility` hashes these exact files with `sha_file`,
    so without this the manifest whose whole purpose is to certify a rebuild
    would disagree with itself across platforms over line endings alone.

    This is the hazard `.gitattributes` closes for the committed tree
    (`* -text -eol`), reappearing in artifacts git never sees because they are
    never committed.
    """
    out = _generate_into(tmp_path, monkeypatch)
    hashed = [
        "table1_source_families.json",
        "table2_primary_endpoints.json",
        "table3_baselines.json",
        "table5_efficiency_cost.json",
        "figure5_evidence_chain.mmd",
    ]
    for name in hashed:
        raw = (out / name).read_bytes()
        assert raw, name
        assert b"\r\n" not in raw, f"{name} carries CRLF; its digest is platform-dependent"


def test_reproducibility_digests_match_the_bytes_actually_on_disk(tmp_path, monkeypatch):
    """The manifest is only worth its name if its digests describe the files as
    written, not the strings as built. Hashing before the platform touched the
    bytes would pass a self-consistency check and still fail a real rebuild."""
    out = _generate_into(tmp_path, monkeypatch)
    manifest = json.loads((out / "reproducibility.json").read_text(encoding="utf-8"))

    def entries(node: Any):
        if isinstance(node, dict):
            if "path" in node and "sha256" in node:
                yield node
            for value in node.values():
                yield from entries(value)
        elif isinstance(node, list):
            for value in node:
                yield from entries(value)

    checked = 0
    for entry in entries(manifest):
        target = bpa.ROOT / entry["path"]
        assert target.is_file(), f"{entry['path']} is pinned but absent from disk"
        assert entry["sha256"] == sha_file(target), entry["path"]
        checked += 1
    assert checked > 20, f"only {checked} pinned inputs -- the manifest reached almost nothing"


def test_the_manifests_own_bytes_are_never_hashed_by_any_caller():
    """`reproducibility.json` goes through the shared `common.write_hashed`,
    which still uses `write_text` and so is CRLF on Windows. That is inert here
    and this control is what keeps it inert: the manifest's integrity comes from
    `receipt_sha256` over canonical JSON, not from its file bytes, so nothing
    may start pinning it with `sha_file` without this turning red.

    Fixing `common.write_hashed` itself is deliberately NOT done here -- every
    receipt in the study flows through it, and changing the bytes of all of them
    is not a change to make inside a paper-artifact commit.
    """
    source = (bpa.NS / "paper" / "build_paper_artifacts.py").read_text(encoding="utf-8")
    assert "write_hashed(GENERATED_DIR / \"reproducibility.json\"" in source
    assert "sha_file(GENERATED_DIR / \"reproducibility.json\"" not in source


# --- Figure 5 must not publish the opposite of what its receipt says --------


def _closure_receipt(tmp_path, *, verdict, head_commit):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "sfir4-execution-closure.json").write_text(
        json.dumps(
            {
                "schema": "tavonel.sfir4.execution_closure.v1",
                "verdict": verdict,
                "head_commit": head_commit,
                "generated_at": "2026-08-26T23:36:17.614784+00:00",
            }
        ),
        encoding="utf-8",
    )
    return receipts


def _execution_node(figure):
    return next(node for node in figure["nodes"] if node["id"] == "execution")


def test_a_refusing_receipt_renders_its_verdict_into_the_diagram(tmp_path):
    """SEALED means a receipt EXISTS. The JSON always carried the verdict, but
    the mermaid label -- the thing that goes in the paper -- did not, so a stage
    whose receipt said REFUSE appeared in the figure as a plain SEALED box. A
    reader seeing SEALED reads "this stage passed", which is the opposite of
    what the receipt says."""
    receipts = _closure_receipt(tmp_path, verdict="REFUSE", head_commit="0" * 40)
    figure = bpa.build_figure5(receipts_dir=receipts, root=bpa.ROOT)
    assert _execution_node(figure)["receipt_verdict"] == "REFUSE"
    assert "receipt verdict: REFUSE" in figure["mermaid"]


def test_a_passing_receipt_also_renders_its_verdict(tmp_path):
    """The paired case: the verdict is shown either way, so its presence is not
    itself a signal and its absence cannot be mistaken for a pass."""
    receipts = _closure_receipt(tmp_path, verdict="PASS", head_commit="0" * 40)
    figure = bpa.build_figure5(receipts_dir=receipts, root=bpa.ROOT)
    assert "receipt verdict: PASS" in figure["mermaid"]


def test_a_receipt_describing_another_commit_is_marked_stale(tmp_path):
    receipts = _closure_receipt(tmp_path, verdict="PASS", head_commit="0" * 40)
    figure = bpa.build_figure5(receipts_dir=receipts, root=bpa.ROOT)
    node = _execution_node(figure)
    assert node["describes_current_head"] is False
    assert "STALE: describes commit 0000" in figure["mermaid"]


def test_a_receipt_describing_the_current_commit_is_not_marked_stale(tmp_path):
    """The negative that makes the marker mean something. Without it, a STALE
    label unconditionally attached to every node would satisfy the test above
    and tell a reader nothing."""
    head = bpa.current_head(bpa.ROOT)
    assert head, "this control needs a real git checkout to be meaningful"
    receipts = _closure_receipt(tmp_path, verdict="PASS", head_commit=head)
    figure = bpa.build_figure5(receipts_dir=receipts, root=bpa.ROOT)
    assert _execution_node(figure)["describes_current_head"] is True
    assert "STALE" not in figure["mermaid"]


def test_staleness_is_unknown_rather_than_fresh_when_git_cannot_be_asked(tmp_path):
    """`current_head` returns None when git cannot answer, and a receipt whose
    staleness is UNKNOWN must not be rendered as fresh -- silence about a
    question nobody could ask is not a negative answer."""
    receipts = _closure_receipt(tmp_path, verdict="PASS", head_commit="0" * 40)
    no_repo = tmp_path / "no_repo"
    no_repo.mkdir()
    assert bpa.current_head(no_repo) is None
    figure = bpa.build_figure5(receipts_dir=receipts, root=no_repo)
    assert _execution_node(figure)["describes_current_head"] is None
    assert "STALE" not in figure["mermaid"]


# --- Table 4: a table about denominators must not misstate its own ----------


def _ledger(tmp_path, text):
    path = tmp_path / "incident_ledger.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_table4_counts_entries_and_separates_incidents_from_stop_the_line(tmp_path):
    ledger = _ledger(
        tmp_path,
        "## INC-V2-001 - a thing\n\n**Class:** alpha.\n\n"
        "## INC-V2-002 - another\n\n**Class:** beta.\n\n"
        "## STOP-V2-001 - halt\n\nprose only\n",
    )
    table = bpa.build_table4(ledger_path=ledger)
    assert table["entries_total"] == 3
    assert table["incidents"] == 2
    assert table["stop_the_line"] == 1


def test_table4_reports_the_denominator_not_just_the_distribution(tmp_path):
    """Two of three entries declare a class. A table that printed only
    {'alpha': 1, 'beta': 1} would read as a summary of all three."""
    ledger = _ledger(
        tmp_path,
        "## INC-V2-001 - a\n\n**Class:** alpha.\n\n"
        "## INC-V2-002 - b\n\n**Class:** beta.\n\n"
        "## INC-V2-003 - c\n\nprose only, no structured header\n",
    )
    field = bpa.build_table4(ledger_path=ledger)["fields"]["class"]
    assert field["coverage"] == "2/3"
    assert field["entries_declaring_it"] == 2
    assert field["entries_not_declaring_it"] == 1


def test_table4_publishes_its_parsers_disagreement_instead_of_hiding_it(tmp_path):
    """The self-check counts raw label occurrences WITHOUT the parser it checks.
    A regex over prose written by hand across a hundred entries will miss forms
    nobody anticipated, and the failure is silent -- a missed entry reads exactly
    like an entry that never declared the field. Here the value is deliberately
    unparseable by the value pattern (it is all asterisks), so the label is
    present and the parse is not."""
    ledger = _ledger(
        tmp_path,
        "## INC-V2-001 - a\n\n**Class:** alpha.\n\n"
        "## INC-V2-002 - b\n\n**Class:** ****\n",
    )
    field = bpa.build_table4(ledger_path=ledger)["fields"]["class"]
    assert field["raw_occurrences_of_the_label"] == 2
    assert field["entries_declaring_it"] == 1
    assert field["parser_agrees_with_a_raw_label_count"] is False
    assert field["unparsed"] == 1
    assert bpa.build_table4(ledger_path=ledger)["parser_fully_agrees"] is False


def test_table4_accepts_both_separators_the_ledger_actually_uses(tmp_path):
    """The ledger uses an ASCII hyphen AND a middle dot between trailing fields.
    Accepting only the hyphen parsed 11 of 15 GPU-seconds declarations and lost
    four invisibly. Both forms are asserted so neither can regress alone."""
    ledger = _ledger(
        tmp_path,
        "## INC-V2-001 - hyphen\n\n**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.\n\n"
        "## INC-V2-002 - middot\n\n"
        "**GPU seconds:** 0 \u00b7 **Cost:** $0 \u00b7 **IP gate:** CLOSED.\n",
    )
    table = bpa.build_table4(ledger_path=ledger)
    assert table["fields"]["gpu_seconds"]["values"] == {"0": 2}
    assert table["fields"]["cost"]["values"] == {"$0": 2}
    assert table["parser_fully_agrees"] is True


def test_table4_against_the_real_ledger_agrees_with_an_independent_count():
    """The real thing. The raw counts here are computed in the test, not read
    from the table, so a parser that drifts fails rather than reporting its own
    drift as the truth."""
    import re as _re

    table = bpa.build_table4()
    text = bpa.LEDGER_PATH.read_text(encoding="utf-8")
    assert table["entries_total"] == len(_re.findall(r"^## (?:INC|STOP)-V2-\d+", text, _re.M))
    assert table["incidents"] + table["stop_the_line"] == table["entries_total"]
    for key, label in bpa._FIELD_LABELS.items():
        if key not in table["fields"]:
            continue
        raw = len(_re.findall(r"\*\*" + _re.escape(label) + r":\*\*", text))
        assert table["fields"][key]["entries_declaring_it"] == raw, key
    assert table["parser_fully_agrees"] is True


def test_table4_reports_zero_gpu_and_zero_cost_consistently_with_table5():
    """Two independent readings of the same fact -- Table 5 sums the receipts,
    Table 4 reads the ledger's declarations. They must not disagree about
    whether any GPU work has happened."""
    table4 = bpa.build_table4()
    table5 = bpa.build_table5()
    assert set(table4["fields"]["gpu_seconds"]["values"]) == {"0"}
    assert table5["gpu_seconds"]["sum"] == 0
    assert table5["estimated_cost_usd"]["sum"] == 0


# --- Table 6: the capacity series, per study and per family -----------------


def _capacity_receipt(tmp_path, stem, body):
    receipts = tmp_path / "receipts"
    receipts.mkdir(exist_ok=True)
    (receipts / f"{stem}.json").write_text(json.dumps(body), encoding="utf-8")
    return receipts


CRITERION = {
    "formula": "Q_f=min(1000,floor(0.8*C_f))",
    "minimum_C_per_family": 750,
    "minimum_Q_per_family": 600,
    "requires_every_family": True,
}


def test_table6_reads_each_study_from_its_own_receipt_not_from_its_predecessor() -> None:
    """The whole point of SFIR6 is that it is not a rescoring of SFIR5. If this
    table read one file and labelled both studies from it, the paper's central
    methodological claim would be false in its own table."""
    table = bpa.build_table6()
    paths = {study["study"]: study["receipt"]["path"] for study in table["studies"]}
    assert "sfir5" in paths["SFIR5"]
    assert "sfir6" in paths["SFIR6"]
    assert paths["SFIR5"] != paths["SFIR6"]


def test_table6_every_cell_matches_the_receipt_byte_for_byte() -> None:
    """Independently re-read both receipts and compare, rather than trusting
    the builder's own copy of them."""
    table = bpa.build_table6()
    for label, stem in bpa.CAPACITY_STUDIES:
        body = json.loads((bpa.RECEIPTS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        rows = {
            row["family"]: row
            for study in table["studies"]
            if study["study"] == label
            for row in study["rows"]
        }
        assert set(rows) == set(body["families"])
        for family, block in body["families"].items():
            for field in ("C", "Q", "roots_declared", "roots_complete", "verdict"):
                assert rows[family][field] == block[field], (label, family, field)


def test_table6_carries_the_real_sfir6_result_today() -> None:
    """A regression guard on the numbers this paper section prints. Every value
    here is asserted against the receipt in the same breath, so the test cannot
    drift into asserting a number nobody can source."""
    body = json.loads(
        (bpa.RECEIPTS_DIR / "sfir6-capacity-outcome.json").read_text(encoding="utf-8")
    )
    assert body["state"] == "CAPACITY_CRITERION_APPLIED_AND_FAILED"
    rows = {
        row["family"]: row
        for study in bpa.build_table6()["studies"]
        if study["study"] == "SFIR6"
        for row in study["rows"]
    }
    assert (rows["git_docs"]["C"], rows["git_docs"]["Q"]) == (293, 234)
    assert rows["git_docs"]["verdict"] == "SHORTFALL_MEASURED"
    assert (rows["regulation_ecfr"]["C"], rows["regulation_ecfr"]["Q"]) == (859, 687)
    assert rows["encyclopedia_wikipedia"]["C"] == 2152
    assert rows["encyclopedia_wikipedia"]["verdict"] == "MEASURED_NOT_SEALABLE"
    assert rows["encyclopedia_wikipedia"]["is_sealable"] is False


def test_table6_does_not_render_a_field_sfir5s_schema_never_had_as_false(tmp_path) -> None:
    """`is_sealable` became a distinction only when SFIR6 produced a set that
    enumerated and then failed the identity proof. Rendering SFIR5's silence as
    `false` would attribute a verdict to a study that never made one."""
    rows = {
        row["family"]: row
        for study in bpa.build_table6()["studies"]
        if study["study"] == "SFIR5"
        for row in study["rows"]
    }
    for row in rows.values():
        assert row["is_sealable"] == bpa.NOT_IN_SCHEMA
        assert row["is_sealable"] is not False


def test_table6_pending_when_a_study_receipt_is_absent_rather_than_omitting_the_study(
    tmp_path,
) -> None:
    """A study missing from a replication table reads as a study that never ran."""
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    table = bpa.build_table6(receipts_dir=receipts, root=tmp_path)
    assert [study["study"] for study in table["studies"]] == ["SFIR5", "SFIR6"]
    for study in table["studies"]:
        assert study["state"].startswith("PENDING (no receipt yet:")
        assert study["rows"] == []


def test_table6_flags_a_q_that_does_not_re_derive_from_the_receipts_own_formula(
    tmp_path,
) -> None:
    """The re-derivation is a CHECK on the receipt, never the published value:
    a receipt whose Q disagrees with its own declared formula must surface as a
    disagreement, not be quietly corrected into agreement."""
    receipts = _capacity_receipt(
        tmp_path,
        "sfir5-capacity-outcome",
        {
            "protocol_id": "X",
            "state": "S",
            "criterion": CRITERION,
            "families": {
                "f": {
                    "C": 1000,
                    "Q": 999,  # floor(0.8*1000) = 800, so this must NOT agree
                    "roots_declared": 1,
                    "roots_complete": 1,
                    "root_states": {},
                    "verdict": "V",
                    "is_a_measurement": True,
                    "meets_C": True,
                    "meets_Q": True,
                }
            },
        },
    )
    row = bpa.build_table6(receipts_dir=receipts, root=tmp_path)["studies"][0]["rows"][0]
    assert row["Q"] == 999  # published verbatim
    assert row["q_recomputes_from_the_receipts_own_formula"] is False


def test_table6_q_cap_binds_only_where_the_receipt_says_it_does() -> None:
    """`encyclopedia_wikipedia` at SFIR6 is the first family whose C makes the
    min(1000, ...) term bind. floor(0.8*2152)=1721, and the receipt's Q is 1000."""
    rows = {
        row["family"]: row
        for study in bpa.build_table6()["studies"]
        if study["study"] == "SFIR6"
        for row in study["rows"]
    }
    wiki = rows["encyclopedia_wikipedia"]
    assert wiki["Q"] == 1000 < int(0.8 * wiki["C"])
    assert wiki["q_recomputes_from_the_receipts_own_formula"] is True


def test_table6_replication_block_is_sfir6s_own_and_not_recomputed_here() -> None:
    body = json.loads(
        (bpa.RECEIPTS_DIR / "sfir6-capacity-outcome.json").read_text(encoding="utf-8")
    )
    assert bpa.build_table6()["replication_of_sfir5_by_sfir6"] == body["replication_of_sfir5"]


def test_table6_names_its_thresholds_as_preregistered_not_calibrated() -> None:
    text = table6_text = bpa.build_table6()["thresholds_are_preregistered_not_calibrated"]
    assert "pre-registered" in text
    assert "calibrated result" in table6_text


# --- Table 7: the SFIR5/SFIR6-era incidents ---------------------------------


def test_table7_lists_exactly_the_six_incidents_the_section_cites() -> None:
    table = bpa.build_table7()
    assert [row["id"] for row in table["rows"]] == list(bpa.TABLE7_INCIDENT_IDS)
    assert table["rows_selected"] == 6


def test_table7_reports_its_denominator_against_the_whole_ledger() -> None:
    table7 = bpa.build_table7()
    table4 = bpa.build_table4()
    assert table7["entries_in_the_ledger"] == table4["entries_total"]
    assert table7["coverage"] == f"6/{table4['entries_total']}"


def test_table7_refuses_an_id_the_ledger_does_not_contain(tmp_path) -> None:
    """A named entry that has gone missing must be a refusal. Silently emitting
    five rows under a heading that promises six is the exact failure mode this
    generator exists to prevent."""
    ledger = _ledger(tmp_path, "## INC-V2-106 - only this one\n\n**Class:** a.\n")
    with pytest.raises(bpa.GenerationRefused) as error:
        bpa.build_table7(ledger_path=ledger)
    assert "INC-V2-107" in str(error.value)


def test_table7_does_not_truncate_a_field_that_wraps_onto_a_second_line(tmp_path) -> None:
    """Table 4's line-bounded parser is right for counting and wrong for
    printing: it renders INC-V2-106's Class as '... producing' and stops
    mid-sentence. A half-sentence in a paper table reads as the whole value."""
    ledger = _ledger(
        tmp_path,
        "## INC-V2-106 - t\n\n**Class:** an adapter whose every request is refused,\n"
        "producing zeros that read as measurements.\n"
        "**Disposition:** CAUSE ESTABLISHED.\n"
        "**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.\n\n"
        "prose below the header, with a **bold run** that is not a field.\n"
        + "".join(
            f"## {name} - t\n\n**Class:** c.\n" for name in bpa.TABLE7_INCIDENT_IDS[1:]
        ),
    )
    row = bpa.build_table7(ledger_path=ledger, receipts_dir=bpa.RECEIPTS_DIR)["rows"][0]
    assert row["class"] == (
        "an adapter whose every request is refused, producing zeros that read as measurements"
    )
    assert row["disposition"] == "CAUSE ESTABLISHED"
    assert row["gpu_seconds"] == "0"
    assert row["cost"] == "$0"
    assert row["ip_gate"] == "CLOSED"
    # the bold run in the prose below the header block is not a field
    assert "bold_run" not in row
    assert "bold run" not in row["ip_gate"]


def test_table7_reports_a_missing_header_field_as_undeclared_not_as_zero(tmp_path) -> None:
    ledger = _ledger(
        tmp_path,
        "".join(f"## {name} - t\n\nprose only, no header\n" for name in bpa.TABLE7_INCIDENT_IDS),
    )
    row = bpa.build_table7(ledger_path=ledger, receipts_dir=bpa.RECEIPTS_DIR)["rows"][0]
    assert row["gpu_seconds"] == bpa.NOT_DECLARED_IN_LEDGER_ENTRY
    assert row["class"] == bpa.NOT_DECLARED_IN_LEDGER_ENTRY


def test_table7_separates_receipt_corroboration_from_ledger_only_entries() -> None:
    """Two of the six are named in SFIR6's outcome receipt as well as in the
    ledger; INC-V2-111 is a procedural slip with no receipt at all. Flattening
    the two would present a narrative record as sealed evidence."""
    rows = {row["id"]: row for row in bpa.build_table7()["rows"]}
    assert rows["INC-V2-111"]["named_by_receipt"] == "ledger only"
    assert rows["INC-V2-108"]["named_by_receipt"] == "ledger only"
    for name in ("INC-V2-106", "INC-V2-107", "INC-V2-109", "INC-V2-110"):
        mentions = rows[name]["named_by_receipt"]
        assert isinstance(mentions, list) and mentions
        for mention in mentions:
            body = json.loads(
                (bpa.ROOT / mention["receipt"]).read_text(encoding="utf-8")
            )
            assert name in body[mention["field"]]


# --- the markdown renderings must not invent, blank or drift ----------------


def test_markdown_renderings_derive_every_cell_from_the_dict_they_are_given() -> None:
    """No second read of a receipt: a markdown table and its JSON sibling
    cannot drift apart if the markdown never touches the source."""
    table6 = bpa.build_table6()
    text = bpa.render_table6_markdown(table6)
    for study in table6["studies"]:
        for row in study["rows"]:
            assert f"`{row['verdict']}`" in text
            assert f"| {row['C']} | {row['Q']} |" in text


def test_markdown_never_renders_an_absence_as_a_blank_cell() -> None:
    """A blank cell in a capacity table reads as zero."""
    assert bpa._cell(None) == "null"
    assert bpa._cell([]) == "(none)"
    assert bpa._cell(False) == "false"
    for text in (
        bpa.render_table6_markdown(bpa.build_table6()),
        bpa.render_table7_markdown(bpa.build_table7()),
    ):
        for line in text.splitlines():
            if line.startswith("|") and not set(line) <= set("|- "):
                assert "|  |" not in line, line


def test_markdown_escapes_a_pipe_so_it_cannot_split_a_row() -> None:
    assert bpa._cell("a|b") == "a" + chr(92) + "|b"


def test_table6_markdown_states_the_thresholds_are_not_calibrated() -> None:
    text = bpa.render_table6_markdown(bpa.build_table6())
    assert "pre-registered" in text
    assert "not a calibrated result" in text or "no cell here is a calibrated result" in text


def test_table7_markdown_states_its_denominator() -> None:
    table7 = bpa.build_table7()
    text = bpa.render_table7_markdown(table7)
    assert table7["coverage"] in text
    assert str(table7["entries_in_the_ledger"]) in text


def test_generate_writes_the_two_new_tables_in_both_forms(tmp_path, monkeypatch) -> None:
    out = _generate_into(tmp_path, monkeypatch)
    for name in (
        "table6_sfir_capacity_series.json",
        "table6_sfir_capacity_series.md",
        "table7_sfir_incidents.json",
        "table7_sfir_incidents.md",
    ):
        path = out / name
        assert path.is_file(), name
        assert b"\r\n" not in path.read_bytes(), f"{name} must be LF on every platform"


def test_reproducibility_pins_the_capacity_receipts_and_the_ledger(tmp_path, monkeypatch) -> None:
    out = _generate_into(tmp_path, monkeypatch)
    manifest = json.loads((out / "reproducibility.json").read_text(encoding="utf-8"))
    pinned = {
        entry["path"]: entry["sha256"]
        for entry in manifest["table6_sfir_capacity_series"]["capacity_receipts"]
    }
    assert len(pinned) == 2
    for path, digest in pinned.items():
        assert sha_file(bpa.ROOT / path) == digest
    ledger = manifest["table7_sfir_incidents"]["ledger"]
    assert sha_file(bpa.ROOT / ledger["path"]) == ledger["sha256"]
    assert manifest["table7_sfir_incidents"]["incident_ids"] == list(bpa.TABLE7_INCIDENT_IDS)
