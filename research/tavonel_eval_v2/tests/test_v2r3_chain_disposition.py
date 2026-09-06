"""The non-disclosure proof must be able to say no.

Every leg here has a RED direction. A four-leg proof whose legs cannot fail is
four ways of saying the same thing, and the thing it says is nothing
(INC-V2-036). The founder ruling made the 300-pair carry-forward conditional on
this proof specifically, so the proof failing correctly matters more than it
passing.

NOTHING HERE READS A V2R3 OUTCOME, because none exists. Every red direction is
produced from a synthetic file in a temporary directory, and the module's own
paths are repointed at it. No test writes into `receipts/`.
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

import v2r3_chain_disposition as cd  # noqa: E402

DisclosureFound = cd.DisclosureFound


# ---------------------------------------------------------------------------
# green: the real tree, as it stands


def test_the_real_tree_passes_all_four_legs() -> None:
    body = cd.prove_non_disclosure()
    assert body["outcome_disclosure"] == "NONE_ESTABLISHED"
    assert body["carry_forward"] == "PERMITTED"
    assert all(leg["held"] for leg in body["legs"].values())
    assert set(body["legs"]) == {
        "no_result_receipt",
        "no_persisted_outcome",
        "no_output_path_before_return",
        "no_frame_inspection",
    }


def test_the_chain_receipts_are_the_only_v2r3_receipts_under_the_measurement_stem() -> None:
    leg = cd.prove_non_disclosure()["legs"]["no_result_receipt"]
    assert leg["result_receipts"] == []
    #: Eight freeze/attestation receipts, and after this module has run, its own
    #: two. Never a ninth kind.
    for name in leg["chain_receipts"]:
        assert any(name.startswith(f"{stem}--") for stem in cd.CHAIN_STEMS), name


def test_a_prior_runs_graded_result_is_not_attributed_to_v2r3() -> None:
    """V1/V2R1/V2R2 results carry every outcome key and are preserved.

    An earlier version of the sweep matched outcome keys as substrings across
    the whole tree and refused on all three of them plus V2R3's own protocol
    receipt, which mentions an invariant by name in a prose field. A sweep that
    cannot pass is not a sweep.
    """
    spent = sorted((NS / "receipts").glob("identity-change-migration-closure-v2r1--*.json"))
    assert spent, "V2R1's spent result receipt is missing"
    body = json.loads(spent[-1].read_text(encoding="utf-8"))
    assert cd._outcome_dict_keys(body), "the spent result carries outcome keys, as it must"
    assert not cd._is_v2r3(spent[-1], body)


def test_a_prose_mention_of_an_outcome_key_is_not_a_hit(tmp_path: Path) -> None:
    receipt = tmp_path / "identity-change-migration-closure-v2r3-note.json"
    receipt.write_text(
        json.dumps(
            {
                "protocol_id": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3",
                "what_this_seals": (
                    "the run will grade INVARIANT_6_ambiguous_identity_stays_unresolved"
                ),
            }
        ),
        encoding="utf-8",
    )
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert cd._is_v2r3(receipt, body)
    assert cd._outcome_dict_keys(body) == []


# ---------------------------------------------------------------------------
# red: leg 1 and leg 2


def _sweep_in(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Point the persisted-outcome sweep at a temporary tree only."""
    monkeypatch.setattr(cd, "NS", root)
    monkeypatch.setattr(cd, "SWEPT", ("receipts",))
    (root / "receipts").mkdir(parents=True, exist_ok=True)


def test_a_file_carrying_the_result_schema_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sweep_in(monkeypatch, tmp_path)
    (tmp_path / "receipts" / "scratch.json").write_text(
        json.dumps({"schema": cd.RESULT_SCHEMA}), encoding="utf-8"
    )
    with pytest.raises(DisclosureFound, match="result schema"):
        cd._no_persisted_outcome()


def test_a_nested_result_body_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A result embedded inside another envelope is still a result."""
    _sweep_in(monkeypatch, tmp_path)
    (tmp_path / "receipts" / "wrapper.json").write_text(
        json.dumps({"note": "hi", "inner": [{"schema": cd.RESULT_SCHEMA}]}), encoding="utf-8"
    )
    with pytest.raises(DisclosureFound, match="result schema"):
        cd._no_persisted_outcome()


def test_naming_the_result_schema_as_a_search_term_is_not_a_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This module's OWN attestation names the schema it searched for.

    A substring sweep flags that proof as the disclosure it had just disproved --
    a check that can only come back one way once it has run once. So the id is
    matched where a result carries it, as the value of a `schema` key.
    """
    _sweep_in(monkeypatch, tmp_path)
    (tmp_path / "receipts" / "v2r3-proof.json").write_text(
        json.dumps({"schema": cd.SCHEMA_NON_DISCLOSURE, "result_schema": cd.RESULT_SCHEMA}),
        encoding="utf-8",
    )
    body = cd._no_persisted_outcome()
    assert body["hits"] == []


def test_the_result_schema_leg_is_unscoped_by_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result hidden in a non-JSON file under an innocent name is still a result."""
    _sweep_in(monkeypatch, tmp_path)
    (tmp_path / "receipts" / "notes-about-nothing.txt").write_text(
        f"schema was {cd.RESULT_SCHEMA}", encoding="utf-8"
    )
    with pytest.raises(DisclosureFound, match="result schema"):
        cd._no_persisted_outcome()


def test_a_v2r3_json_with_an_outcome_key_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sweep_in(monkeypatch, tmp_path)
    (tmp_path / "receipts" / "v2r3-scratch.json").write_text(
        json.dumps({"effective_census": {"EFFECTIVE_NEW": 4}}), encoding="utf-8"
    )
    with pytest.raises(DisclosureFound, match="outcome keys"):
        cd._no_persisted_outcome()


def test_a_nested_outcome_key_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sweep_in(monkeypatch, tmp_path)
    (tmp_path / "receipts" / "v2r3-nested.json").write_text(
        json.dumps({"a": [{"b": {"violation_count": 0}}], "protocol_id": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(DisclosureFound, match=r"violation_count"):
        cd._no_persisted_outcome()


def test_a_receipt_under_the_measurement_stem_that_the_chain_does_not_explain_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cd, "NS", tmp_path)
    (tmp_path / "receipts").mkdir()
    (
        tmp_path / "receipts" / f"{cd.MEASUREMENT_STEM}--20260826T000000Z-aaaaaaaaaaaa.json"
    ).write_text("{}", encoding="utf-8")
    with pytest.raises(DisclosureFound, match="not part of the aborted freeze chain"):
        cd._no_result_receipt()


# ---------------------------------------------------------------------------
# red: leg 3, the load-bearing one


#: A minimal scorer with the shape the AST leg asserts. Built by substituting a
#: single marker line rather than by `str.format`, because the real shape is
#: full of braces and formatting it turns dict literals into placeholders.
_SCORER_SHAPE = """
def measure_extra_clauses(a, b):
    return {"census": {}}


def run():
    RUN_BODY
    return {"x": 1}


def _require_census_keys(extra, keys):
    return None


def _sum_maps(maps):
    return {}


def main(argv=None):
    body = run()
    six = body["x"]
    print(six)
    return 0
"""


def _scorer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, run_body: str) -> None:
    fake = tmp_path / "identity_change_migration_closure_v2r3.py"
    fake.write_text(_SCORER_SHAPE.replace("RUN_BODY", run_body), encoding="utf-8")
    monkeypatch.setattr(cd, "SCORER", fake)
    monkeypatch.setattr(cd, "NS", tmp_path)


def test_the_ast_leg_passes_on_a_silent_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scorer(tmp_path, monkeypatch, run_body="pass")
    leg = cd._prove_no_output_before_return()
    assert leg["held"]
    assert leg["outcome_print_lines"]


def test_a_print_inside_run_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scorer(tmp_path, monkeypatch, run_body='print("violations", 3)')
    with pytest.raises(DisclosureFound, match=r"run\(\) contains output statements"):
        cd._prove_no_output_before_return()


def test_a_write_inside_measure_extra_clauses_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "identity_change_migration_closure_v2r3.py"
    fake.write_text(
        "import pathlib\n"
        "def measure_extra_clauses(a, b):\n"
        "    pathlib.Path('x').write_text('census')\n"
        "    return {}\n"
        "def run():\n    return {'x': 1}\n"
        "def main(argv=None):\n    body = run()\n    print(body)\n    return 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cd, "SCORER", fake)
    monkeypatch.setattr(cd, "NS", tmp_path)
    with pytest.raises(DisclosureFound, match="measure_extra_clauses"):
        cd._prove_no_output_before_return()


def test_a_main_that_never_assigns_run_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "identity_change_migration_closure_v2r3.py"
    fake.write_text(
        "def measure_extra_clauses(a, b):\n    return {}\n"
        "def run():\n    return {'x': 1}\n"
        "def main(argv=None):\n    run()\n    return 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cd, "SCORER", fake)
    monkeypatch.setattr(cd, "NS", tmp_path)
    with pytest.raises(DisclosureFound, match="does not assign the result of run"):
        cd._prove_no_output_before_return()


def test_a_scorer_missing_run_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "identity_change_migration_closure_v2r3.py"
    fake.write_text("def main(argv=None):\n    return 0\n", encoding="utf-8")
    monkeypatch.setattr(cd, "SCORER", fake)
    monkeypatch.setattr(cd, "NS", tmp_path)
    with pytest.raises(DisclosureFound, match="no longer defines"):
        cd._prove_no_output_before_return()


def test_the_real_scorers_run_is_silent_and_its_output_follows_the_assignment() -> None:
    """The claim, made about the file that actually crashed."""
    leg = cd._prove_no_output_before_return()
    assert leg["silent_functions"]["run"]["output_calls"] == 0
    assert leg["silent_functions"]["measure_extra_clauses"]["output_calls"] == 0
    assert min(leg["outcome_print_lines"]) > leg["run_assigned_in_main_at_line"]
    assert leg["scorer_sha256"].startswith("sha256:")


# ---------------------------------------------------------------------------
# red: leg 4


def _declaration(**overrides: Any) -> dict[str, Any]:
    return {**cd.DEFAULT_OPERATOR_DECLARATION, **overrides}


def test_showlocals_in_pytest_config_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-ra --showlocals"\n', encoding="utf-8"
    )
    monkeypatch.setattr(cd, "ROOT", tmp_path)
    with pytest.raises(DisclosureFound, match="showlocals"):
        cd._no_frame_inspection(_declaration())


def test_short_l_flag_also_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-ra -l"\n', encoding="utf-8"
    )
    monkeypatch.setattr(cd, "ROOT", tmp_path)
    with pytest.raises(DisclosureFound, match=r"'-l'"):
        cd._no_frame_inspection(_declaration())


def test_a_missing_pytest_block_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    monkeypatch.setattr(cd, "ROOT", tmp_path)
    with pytest.raises(DisclosureFound, match=r"no \[tool\.pytest\.ini_options\] block"):
        cd._no_frame_inspection(_declaration())


def test_an_attached_debugger_refuses() -> None:
    with pytest.raises(DisclosureFound, match="debugger was attached"):
        cd._no_frame_inspection(_declaration(debugger_attached=True))


def test_an_inspected_outcome_frame_refuses() -> None:
    with pytest.raises(DisclosureFound, match="inspected outcome frames"):
        cd._no_frame_inspection(_declaration(frames_inspected=["extra", "pair_results"]))


def test_an_inspected_harmless_frame_does_not_refuse() -> None:
    """`ws` is not outcome-bearing. Refusing on it would make the leg unusable."""
    leg = cd._no_frame_inspection(_declaration(frames_inspected=["ws", "protocol"]))
    assert leg["held"]


def test_an_incomplete_operator_declaration_refuses() -> None:
    with pytest.raises(DisclosureFound, match="declaration is incomplete"):
        cd._no_frame_inspection({"declared_by": "someone"})


def test_the_real_config_carries_no_locals_flag() -> None:
    assert "--showlocals" not in cd._pytest_addopts().split()
    assert "-l" not in cd._pytest_addopts().split()


# ---------------------------------------------------------------------------
# The successor's name contains the predecessor's
#
# `_is_v2r3` originally matched `"v2r3" in name`, which was correct for every
# artefact that existed when it was written and wrong the moment V2R3R1 ran.
# The successor GRADED, so its receipt carries outcome keys by right; the
# substring match reported that legitimate result as the predecessor's leaked
# one, and the whole non-disclosure sweep went red on it.
#
# The boundary is load-bearing in both directions, so both are tested.
# ---------------------------------------------------------------------------


def test_a_v2r3_artefact_is_still_attributed_to_v2r3():
    """The direction that must not be lost. Narrowing must not blind the sweep."""
    assert cd._is_v2r3(
        Path("receipts/identity-change-migration-closure-v2r3--20260101T000000Z-a.json"), {}
    )
    assert cd._is_v2r3(Path("x.json"), {"protocol_id": "...CLOSURE_V2R3"})
    assert cd._is_v2r3(Path("x.json"), {"schema": "tavonel.v2....v2r3_result.v1"})


def test_a_v2r3r1_artefact_is_not_attributed_to_v2r3():
    assert not cd._is_v2r3(
        Path("receipts/identity-change-migration-closure-v2r3r1--20260825T213041Z-f.json"), {}
    )
    assert not cd._is_v2r3(Path("x.json"), {"protocol_id": "...CLOSURE_V2R3R1"})


def test_naming_v2r3_as_a_parent_is_not_membership():
    """Every V2R3R1 receipt names V2R3 as its parent.

    A predicate that read a parent reference as membership would capture the
    entire successor chain by design, which is the failure this test pins.
    """
    assert not cd._is_v2r3(
        Path("receipts/whatever.json"),
        {"protocol_id": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1", "parent_protocol": "V2R3"},
    )


def test_the_boundary_is_a_token_not_a_substring():
    assert cd._names_v2r3_itself("closure-v2r3-universe")
    assert cd._names_v2r3_itself("closure_v2r3")
    assert not cd._names_v2r3_itself("closure-v2r3r1-universe")
    assert not cd._names_v2r3_itself("v2r30")


def test_the_successor_receipt_on_disk_is_not_swept_as_a_disclosure():
    """The actual artefact that turned the suite red, on the real tree."""
    found = sorted(
        (cd.NS / "receipts").glob("identity-change-migration-closure-v2r3r1--*.json")
    )
    assert found, "no V2R3R1 measurement receipt to check against"
    for path in found:
        body = json.loads(path.read_text(encoding="utf-8"))
        assert not cd._is_v2r3(path, body), path.name
