from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))
sys.path.insert(0, str(NS / "tools"))

import freeze_sfir4_protocol as freeze  # noqa: E402
import probe_sfir4_capacity as probe  # noqa: E402
import sfir4_core_conformance as conformance  # noqa: E402
import sfir4_execution as sx  # noqa: E402
import sfir4_execution_closure as closure  # noqa: E402
import sfir4_isolated_env as isolation  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
import sfir4_worker as worker  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402


@pytest.fixture
def recoverable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for a tracked execution closure.

    The real gate refuses today, because ``research/tavonel_eval_v2/`` is
    untracked -- that is INC-V2-089's root cause and it is a true finding, not a
    test-environment quirk. A test that exercises the freeze LOGIC has to get
    past it, and it must do so visibly rather than by the gate being weak.
    ``test_freeze_refuses_while_the_execution_closure_is_untracked`` runs the
    real gate and is the control that this fixture is not hiding a regression.
    """
    monkeypatch.setattr(closure, "require_recoverable", lambda: {"verdict": "PASS"})
    monkeypatch.setattr(freeze.closure, "require_recoverable", lambda: {"verdict": "PASS"})


def test_the_research_tree_is_committed_and_byte_identical_to_head() -> None:
    """What commit 2886919 actually established, asserted rather than assumed.

    Every file of the SFIR4 closure that lives in the research tree is committed
    and its blob is byte-for-byte the working tree. This is the property the
    tree-local ``.gitattributes`` exists to hold: the repository root sets
    ``* text=auto eol=lf`` and would otherwise rewrite CRLF on check-in, leaving
    every freeze digest naming bytes git will not return.
    """
    body = closure.gate()
    assert body["totals"]["uncommitted"] == 0, body["untracked"]
    assert body["totals"]["unresolved_imports"] == 0, body["unresolved_imports"]
    research = [
        name
        for name in body["manifest"]
        if name.startswith("research/tavonel_eval_v2/")
    ]
    divergent_research = [
        row["path"]
        for row in body["divergent_from_head"]
        if row["path"].startswith("research/tavonel_eval_v2/")
    ]
    assert research, "the closure reached nothing in the research tree"
    assert divergent_research == [], divergent_research


def test_the_protected_core_is_recoverable_from_head() -> None:
    """The gate, unmocked, against the repository as it actually is.

    This control was written asserting REFUSE, because the SFIR4 closure reaches
    three ``akc_cir`` modules that carried 982 uncommitted lines: committed-at-
    HEAD is not the same as recoverable, and while those differed a fresh clone
    reconstructed a different instrument than a freeze would pin. It said that
    when the work landed the correct response was to assert PASS, never to drop
    the byte-identity check or narrow the closure so the Protected Core fell
    outside it. The work landed in ``4823d5d`` and this is that inversion, made
    on the same closure, with the same byte-identity check.

    It is deliberately still an assertion about ``akc_cir`` in particular. A
    later change that moved the Protected Core out of the closure would satisfy
    a bare ``verdict == PASS`` while removing the property this control exists
    to hold, so the reach is asserted separately from the verdict.
    """
    body = closure.gate()
    reached = [path for path in body["manifest"] if "akc_cir" in path]
    assert reached, "the closure no longer reaches the Protected Core"
    assert body["totals"]["divergent_from_head"] == 0, body["divergent_from_head"]
    assert body["totals"]["uncommitted"] == 0, body["uncommitted"]
    assert body["verdict"] == "PASS", body["why"]
    # Fail-closed callers now proceed rather than raising, which is the whole
    # point of the landing; asserting they do not raise is what makes this a
    # test of the gate and not of the verdict string alone.
    closure.require_recoverable()


def _candidate(family: str, index: int) -> dict:
    roots = sources.declared_roots(family)
    root = roots[index % len(roots)]
    if family == "git_docs":
        item = {
            "repository": root,
            "path": f"docs/{index}.md",
            "commit_before": f"{index + 1:040x}",
            "commit_after": f"{index + 1001:040x}",
            "timestamp_before": "2026-08-25T00:00:00Z",
            "timestamp_after": "2026-08-26T00:00:00Z",
        }
    elif family == "regulation_ecfr":
        # A real eCFR section designator is `<part>.<n>` -- `1.1`, `170.3` --
        # never a bare integer. The fixture emitted `str(index + 1)`, which the
        # locator grammar correctly refuses and which the versioner API has
        # never served; it went unnoticed while nothing in the freeze path
        # resolved a candidate's locator. The roster's resolution-identity
        # proof does, so the fixture now generates what eCFR actually emits.
        part = str(index // 100 + 1)
        item = {
            "title": root,
            "part": part,
            "section": f"{part}.{index + 1}",
            "version_before": "2026-08-25",
            "version_after": "2026-08-26",
            "timestamp_before": "2026-08-25T00:00:00Z",
            "timestamp_after": "2026-08-26T00:00:00Z",
        }
    else:
        item = {
            "category": root,
            "page_id": index + 1,
            "title": f"Article {index}",
            "aliases": [],
            "redirect": False,
            "revision_before": str(index + 1),
            "revision_after": str(index + 1001),
            "timestamp_before": "2026-08-25T00:00:00Z",
            "timestamp_after": "2026-08-26T00:00:00Z",
        }
    made = probe._candidate(family, item)
    assert made is not None
    return made[0]


def _fixture():
    families = {}
    arithmetic = {}
    for family in sources.FAMILIES:
        candidates = [_candidate(family, index) for index in range(750)]
        dispositions = [
            {
                "discovery_root_id": sources.discovery_root_id(family, root),
                "state": "COMPLETE",
            }
            for root in sources.declared_roots(family)
        ]
        families[family] = {"root_dispositions": dispositions, "candidates": candidates}
        arithmetic[family] = {
            "complete_roots": len(dispositions),
            "excluded_or_unavailable_roots": 0,
            "candidates_from_complete_roots": 750,
            "candidates_from_incomplete_roots": 0,
        }
    capacity = {
        "state": "CAPACITY_PASS",
        "formula": "Q_f=min(1000,floor(0.8*C_f))",
        "C": {family: 750 for family in sources.FAMILIES},
        "Q": {family: 600 for family in sources.FAMILIES},
        "root_disposition_arithmetic": arithmetic,
    }
    spent = {"container_ids": [], "lineage_ids": [], "alias_ids": []}
    metadata = {
        "schema": protocol.CAPACITY_INPUT_SCHEMA,
        "protocol_id": protocol.PROTOCOL_ID,
        "families": families,
    }
    return capacity, spent, metadata


def test_roster_is_deterministic_capacity_bound_and_immutable(tmp_path, monkeypatch, recoverable):
    capacity, spent, metadata = _fixture()
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(
        freeze,
        "_verified_inputs",
        lambda *_args: ({}, capacity, spent, metadata_path, metadata),
    )
    destination = tmp_path / "roster.json"
    freeze.freeze_roster(tmp_path, {}, {}, {}, destination, "2026-08-27T00:00:00Z")
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["Q"] == capacity["Q"]
    assert all(len(body["families"][family]) == 600 for family in sources.FAMILIES)
    for family in sources.FAMILIES:
        expected = sorted(
            metadata["families"][family]["candidates"],
            key=lambda row: freeze._candidate_order(family, row),
        )[:600]
        assert body["families"][family] == expected
    with pytest.raises(protocol.SFIR4Refused, match="existing immutable"):
        freeze.freeze_roster(tmp_path, {}, {}, {}, destination, "2026-08-27T00:00:01Z")


def test_roster_refuses_candidate_from_incomplete_root():
    capacity, spent, metadata = _fixture()
    family = "git_docs"
    root = metadata["families"][family]["root_dispositions"][0]["discovery_root_id"]
    metadata["families"][family]["root_dispositions"][0]["state"] = (
        "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    )
    capacity["root_disposition_arithmetic"][family] = {
        "complete_roots": len(sources.declared_roots(family)) - 1,
        "excluded_or_unavailable_roots": 1,
        "candidates_from_complete_roots": 750,
        "candidates_from_incomplete_roots": 0,
    }
    assert any(
        row["discovery_root_id"] == root for row in metadata["families"][family]["candidates"]
    )
    with pytest.raises(protocol.SFIR4Refused, match="incomplete root contributed"):
        freeze._selected_roster(capacity, spent, metadata)


def test_execution_manifest_closes_freezer_and_current_tree(tmp_path):
    manifest_path = tmp_path / "sfir4-execution-manifest.json"
    body = sx.write_execution_manifest(manifest_path, "2026-08-27T00:00:00Z")
    assert "tools/freeze_sfir4_protocol.py" in body["components"]
    assert freeze._verify_execution_manifest(sx.ROOT, manifest_path) == body


def test_protocol_freeze_binds_roster_manifest_and_exact_execution_policy(
    tmp_path, monkeypatch, recoverable
):
    capacity, spent, metadata = _fixture()
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    selected, capabilities = freeze._selected_roster(capacity, spent, metadata)
    charter_ref = {"path": "charter.json", "sha256": "sha256:charter"}
    capacity_ref = {"path": "capacity.json", "sha256": "sha256:capacity"}
    spent_ref = {"path": "spent.json", "sha256": "sha256:spent"}
    roster_ref = {"path": "roster.json", "sha256": "sha256:roster"}
    capacity.update(
        {
            "charter": charter_ref,
            "spent_identity_authority": spent_ref,
            "metadata": protocol.exact_ref(tmp_path, metadata_path),
        }
    )
    roster = {
        "state": "LINEAGE_ROSTER_FROZEN",
        "charter": charter_ref,
        "capacity": capacity_ref,
        "spent_identity_authority": spent_ref,
        "metadata": protocol.exact_ref(tmp_path, metadata_path),
        "Q": capacity["Q"],
        "families": selected,
        "capability_exercising_counts": capabilities,
    }
    monkeypatch.setattr(
        freeze,
        "_verified_inputs",
        lambda *_args: ({}, capacity, spent, metadata_path, metadata),
    )
    monkeypatch.setattr(protocol, "verify_authority", lambda *_args: roster)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    manifest = {
        "schema": sx.EXECUTION_TOOLCHAIN_SCHEMA,
        "content_digest": "sha256:manifest",
    }
    monkeypatch.setattr(freeze, "_verify_execution_manifest", lambda *_args: manifest)
    source_protocol = NS / "protocols" / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4.yaml"
    protocol_path = tmp_path / source_protocol.name
    protocol_path.write_bytes(source_protocol.read_bytes())
    destination = tmp_path / "protocol-freeze.json"
    freeze.freeze_protocol(
        tmp_path,
        protocol_path,
        charter_ref,
        capacity_ref,
        roster_ref,
        spent_ref,
        manifest_path,
        destination,
        "2026-08-27T00:00:00Z",
    )
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["acquisition_authorized"] is True
    assert body["scoring_authorized"] is False
    assert body["score_exactly_once"] is True
    assert body["execution_manifest"]["content_digest"] == "sha256:manifest"


def test_worker_default_and_maximum_are_two():
    import inspect

    import sfir4_worker

    assert sfir4_worker.MAX_WORKERS == 2
    workers = inspect.signature(sfir4_worker.produce_observation_batch).parameters["workers"]
    assert workers.default == 2


# ---------------------------------------------------------------------------
# The pre-freeze audit finding: the freeze asked whether SOME akc_cir had the
# right symbols, never which one would load
# ---------------------------------------------------------------------------


def test_the_freeze_gate_asks_all_three_questions() -> None:
    """Recoverable, conformant, AND the core that will actually load.

    Both freeze paths used to call ``conformance.require_conformant()`` with no
    expected root, so the branch that checks WHERE ``akc_cir`` resolved never
    ran, and ``sfir4_isolated_env`` -- written for exactly the shared-venv
    absolute-path ``.pth`` that resolves the core out of the shared working tree
    -- had zero call sites anywhere in the pipeline. A receipt would have
    recorded ``isolated_git_checkout`` while the interpreter imported whatever a
    developer had open.

    Asserted on the source text rather than by monkeypatching, because what went
    wrong was an omitted call, and a test that patches the three functions would
    pass whether or not the freeze paths call them.
    """
    source = (NS / "tools" / "freeze_sfir4_protocol.py").read_text(encoding="utf-8")
    # The indented, newline-terminated form counts CALL SITES; the bare name
    # also appears in the definition line.
    assert source.count("    _require_reproducible_instrument()" + chr(10)) == 2, (
        "both freeze_roster and freeze_protocol must run the gate"
    )
    assert "closure.require_recoverable()" in source
    assert "conformance.require_conformant(EXPECTED_CORE_ROOT)" in source
    assert "isolation.require_isolated(EXPECTED_CORE_ROOT)" in source
    assert "conformance.require_conformant()" not in source, (
        "a bare call skips the which-core-resolved check entirely"
    )


def test_the_expected_core_root_is_derived_from_this_checkout() -> None:
    """Derived, not configured: there is no value anyone can set to make a
    freeze run from one checkout expect another checkout's Protected Core."""
    assert NS.parents[1] / "packages" / "cir-python" / "src" == freeze.EXPECTED_CORE_ROOT
    assert (freeze.EXPECTED_CORE_ROOT / "akc_cir" / "__init__.py").is_file()


def test_the_gate_passes_against_the_checkout_it_is_running_in() -> None:
    """The happy path, so the controls above are not asserting a broken gate."""
    freeze._require_reproducible_instrument()


def test_conformance_refuses_a_core_resolved_from_somewhere_else() -> None:
    with pytest.raises(conformance.ConformanceRefused):
        conformance.require_conformant(Path("/nowhere/that/exists"))


def test_isolation_refuses_a_core_resolved_from_somewhere_else() -> None:
    with pytest.raises(isolation.IsolationRefused):
        isolation.require_isolated(Path("/nowhere/that/exists"))


def test_the_isolation_gate_is_inside_the_recoverable_closure() -> None:
    """A gate a fresh clone might not have is not a gate.

    ``sfir4_isolated_env.py`` was absent from the closure's verification entry
    points, so nothing required it to be committed at all.
    """
    body = closure.gate()
    reached = [path for path in body["manifest"] if "sfir4_isolated_env" in path]
    assert len(reached) == 2, reached


# ---------------------------------------------------------------------------
# The pre-freeze audit finding: the roster never proved what it documented
# ---------------------------------------------------------------------------


def test_two_candidates_that_read_the_same_payload_pair_are_refused(
    recoverable: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinct identifiers are not distinct reads.

    Every eCFR section of one part shares a request URL and is isolated locally
    afterwards, so two candidates can carry different `lineage_id`s, satisfy the
    identity-domain proof, and still fetch the same bytes.
    `payload_resolution_identity` is the value that separates them, and its
    docstring claimed a roster proves distinctness over it while the function
    had no call sites anywhere.
    """
    capacity, spent, metadata = _fixture()
    rows = metadata["families"]["regulation_ecfr"]["candidates"]
    assert len(rows) >= 2, "the fixture must produce at least two eCFR candidates"
    rows[1]["payload_ref"] = dict(rows[0]["payload_ref"])

    # `_validate_candidate` derives each locator from the candidate's own
    # title/part/section/revision and refuses any mismatch, so it catches this
    # edit first -- correctly. Suspending it is what reaches the roster's own
    # cross-check, which is the thing under test here. Without this the control
    # would pass while asserting nothing about the code it names.
    monkeypatch.setattr(protocol, "_validate_candidate", lambda *args, **kwargs: None)
    with pytest.raises(protocol.SFIR4Refused, match="distinct identifiers are not distinct reads"):
        freeze._selected_roster(capacity, spent, metadata)


def test_a_candidate_whose_two_sides_read_one_payload_is_refused(
    recoverable: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A before/after pair that resolves to one payload is not a revision.

    Also upstream-unreachable today -- `_validate_candidate` requires the two
    revisions to differ and derives the locators from them -- so the same
    suspension applies, for the same reason.
    """
    capacity, spent, metadata = _fixture()
    rows = metadata["families"]["regulation_ecfr"]["candidates"]
    rows[0]["payload_ref"]["after"] = rows[0]["payload_ref"]["before"]
    monkeypatch.setattr(protocol, "_validate_candidate", lambda *args, **kwargs: None)
    with pytest.raises(protocol.SFIR4Refused, match="reads the same bytes on both sides"):
        freeze._selected_roster(capacity, spent, metadata)


def test_the_upstream_derivation_is_what_actually_establishes_injectivity(
    recoverable: None,
) -> None:
    """Say where the property really comes from, so the cross-check above is not
    mistaken for the proof.

    `_validate_candidate` rejects a candidate whose `payload_ref` is not the
    exact derivation of its own fields. That is what makes two candidates with
    different `lineage_id`s unable to share a resolution identity.
    """
    capacity, spent, metadata = _fixture()
    rows = metadata["families"]["regulation_ecfr"]["candidates"]
    rows[1]["payload_ref"] = dict(rows[0]["payload_ref"])
    with pytest.raises(protocol.SFIR4Refused, match="payload locator scheme or revision binding"):
        freeze._selected_roster(capacity, spent, metadata)


def test_the_fixture_roster_passes_the_resolution_identity_proof(
    recoverable: None,
) -> None:
    """The paired control, so neither refusal above can be satisfied by a check
    that refuses everything."""
    capacity, spent, metadata = _fixture()
    selected, _ = freeze._selected_roster(capacity, spent, metadata)
    assert set(selected) == set(sources.FAMILIES)


def test_every_selected_candidate_resolves_through_sfir4s_own_grammar(
    recoverable: None,
) -> None:
    """The fixture emits what the live endpoints emit.

    An eCFR section designator is `<part>.<n>`; the fixture used to emit a bare
    integer, which the grammar refuses and which the versioner API has never
    served. Nothing caught it while no freeze-path code resolved a locator.
    """
    _, _, metadata = _fixture()
    for family, block in metadata["families"].items():
        for row in block["candidates"]:
            for side in ("before", "after"):
                identity = worker.payload_resolution_identity(family, row["payload_ref"][side])
                assert identity.startswith("https://"), identity
