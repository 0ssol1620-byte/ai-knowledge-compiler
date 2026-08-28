"""Controls for the SFIR9 execution closure.

The closure runs for real against this repository -- that is the completion
condition, not a simulation of it. The tampering controls run against a copied
tree, because they need bytes to be wrong and this repository's must not be.

The freeze manifest gets the most attention. It exists to answer the one question
the closure structurally cannot answer about itself, and a manifest that took the
closure's word for the closure tool's hash would answer nothing.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_execution_closure as closure_module  # noqa: E402
import sfir9_isolation_gate as gate  # noqa: E402
import sfir9_transport as transport  # noqa: E402


def _real_closure(**kwargs):
    return closure_module.closure(
        repository_root=REPO,
        import_origins=closure_module.import_origins(),
        **kwargs,
    )


def _copied_tree(tmp_path):
    """A checkout holding the real component bytes, with a committed-bytes reader."""
    tools = tmp_path / closure_module.TOOLS
    tools.mkdir(parents=True)
    committed: dict[str, bytes] = {}
    origins: dict[str, str] = {}
    for component in closure_module.COMPONENTS:
        raw = (REPO / component.relative_path).read_bytes()
        committed[component.relative_path] = raw
        (tmp_path / component.relative_path).write_bytes(raw)
        origins[component.module] = str(tools / f"{component.module}.py")
    committed[closure_module.CLOSURE_PATH] = (
        REPO / closure_module.CLOSURE_PATH
    ).read_bytes()
    return committed, origins


def _manifest_in_copy(tmp_path, committed, closure_result):
    return closure_module.freeze_manifest(
        closure_result,
        repository_root=tmp_path,
        read_committed_bytes=lambda _root, path: committed[path],
    )


def _verify_copy(tmp_path, committed, origins, **kwargs):
    return closure_module.closure(
        repository_root=tmp_path,
        import_origins=origins,
        read_committed_bytes=lambda _root, path: committed[path],
        **kwargs,
    )


# --------------------------------------------------------- the ten components


def test_the_closure_covers_the_ten_components():
    assert len(closure_module.COMPONENTS) == 10
    assert {c.name for c in closure_module.COMPONENTS} == set(gate.REQUIRED_COMPONENTS)


def test_the_component_lists_are_checked_against_each_other(monkeypatch):
    """Two lists maintained apart will disagree, usually at the worst moment."""
    closure_module.require_component_lists_agree()

    monkeypatch.setattr(
        gate, "REQUIRED_COMPONENTS", gate.REQUIRED_COMPONENTS[:-1]
    )
    with pytest.raises(closure_module.ClosureRefused) as caught:
        closure_module.require_component_lists_agree()
    assert caught.value.code == closure_module.LIST_DISAGREEMENT


def test_two_lists_of_the_same_length_can_still_disagree(monkeypatch):
    """A count comparison would pass this, and the study would be misaligned.

    Ten against ten, one name different: the closure would verify a component
    the gate never asked about, and skip one the gate requires.
    """
    swapped = ("selection_rule_v2", *gate.REQUIRED_COMPONENTS[1:])
    assert len(swapped) == len(gate.REQUIRED_COMPONENTS)

    monkeypatch.setattr(gate, "REQUIRED_COMPONENTS", swapped)
    with pytest.raises(closure_module.ClosureRefused) as caught:
        closure_module.require_component_lists_agree()
    assert caught.value.code == closure_module.LIST_DISAGREEMENT


def test_the_disagreement_check_runs_before_any_component_is_verified(monkeypatch):
    monkeypatch.setattr(gate, "REQUIRED_COMPONENTS", ("protocol",))
    with pytest.raises(closure_module.ClosureRefused) as caught:
        _real_closure()
    assert caught.value.code == closure_module.LIST_DISAGREEMENT


def test_the_closure_names_the_module_behind_each_component():
    for component in closure_module.COMPONENTS:
        assert component.relative_path.endswith(f"{component.module}.py")
        assert component.module.startswith("sfir9_")


# ---------------------------------------------- the real repository verifies


def test_the_closure_passes_against_this_repository():
    """The completion condition, run for real."""
    result = _real_closure()
    assert result["component_count"] == 10
    for record in result["components"]:
        assert record["committed_bytes_equal_working_bytes"] is True
        assert record["import_origin_is_the_verified_file"] is True
        assert record["sha256"].startswith("sha256:")
        assert len(record["git_blob_id"]) == 40


def test_every_component_reports_all_five_bindings():
    for record in _real_closure()["components"]:
        for key in (
            "relative_path",
            "sha256",
            "git_blob_id",
            "committed_bytes_equal_working_bytes",
            "import_origin",
        ):
            assert key in record


def test_the_closure_digest_is_stable_and_covers_the_components():
    first = _real_closure()
    second = _real_closure()
    assert first["closure_digest"] == second["closure_digest"]

    altered = dict(first)
    altered["components"] = first["components"][:-1]
    assert closure_module._digest(
        {k: v for k, v in altered.items() if k != "closure_digest"}
    ) != first["closure_digest"]


def test_the_closure_carries_the_upstream_binding_when_given_one():
    binding = transport.verify_upstream_binding(
        repository_root=REPO, import_origins=transport.import_origins()
    )
    result = _real_closure(upstream_binding=binding)
    assert result["upstream_binding"]["upstream_modules"]
    assert result["closure_digest"] != _real_closure()["closure_digest"]


# -------------------------------------------------------------- tampering


def test_a_component_whose_working_bytes_differ_from_its_commit_refuses(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    target = "research/tavonel_eval_v2/tools/sfir9_scorer.py"
    original = committed[target]
    # Same length, different bytes: a size comparison would not see it.
    (tmp_path / target).write_bytes(original.replace(b"scorer", b"scoreR", 1))

    with pytest.raises(closure_module.ClosureRefused) as caught:
        _verify_copy(tmp_path, committed, origins)
    assert caught.value.code == closure_module.BYTES_MISMATCH


def test_a_component_imported_from_elsewhere_refuses(tmp_path):
    """A correct hash does not establish which copy Python loaded."""
    committed, origins = _copied_tree(tmp_path)
    origins["sfir9_selection"] = "/some/other/tree/tools/sfir9_selection.py"
    with pytest.raises(closure_module.ClosureRefused) as caught:
        _verify_copy(tmp_path, committed, origins)
    assert caught.value.code == closure_module.ORIGIN_MISMATCH


def test_a_component_never_imported_refuses(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    del origins["sfir9_acceptance"]
    with pytest.raises(closure_module.ClosureRefused) as caught:
        _verify_copy(tmp_path, committed, origins)
    assert caught.value.code == closure_module.ORIGIN_MISMATCH


def test_a_component_file_that_is_absent_refuses(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    (tmp_path / "research/tavonel_eval_v2/tools/sfir9_transport.py").unlink()
    with pytest.raises(closure_module.ClosureRefused) as caught:
        _verify_copy(tmp_path, committed, origins)
    assert caught.value.code == closure_module.MISSING_COMPONENT


def test_the_list_check_runs_before_any_component_is_verified_in_a_copy(
    tmp_path, monkeypatch
):
    committed, origins = _copied_tree(tmp_path)
    monkeypatch.setattr(gate, "REQUIRED_COMPONENTS", ("protocol",))
    with pytest.raises(closure_module.ClosureRefused) as caught:
        _verify_copy(tmp_path, committed, origins)
    assert caught.value.code == closure_module.LIST_DISAGREEMENT


def test_the_reported_count_is_the_number_actually_verified(tmp_path):
    """Derived from the records, not from a number that happens to be ten."""
    committed, origins = _copied_tree(tmp_path)
    result = _verify_copy(tmp_path, committed, origins)
    assert result["component_count"] == len(result["components"])
    assert result["component_count"] == len(closure_module.COMPONENTS)


def test_the_closure_states_its_own_limit_in_a_copy(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    result = _verify_copy(tmp_path, committed, origins)
    assert "its own bytes" in result["what_this_does_not_certify"]
    assert "proves nothing" in result["what_this_does_not_certify"]


def test_a_clean_copy_verifies(tmp_path):
    """The refusals must be about the defect, not about being checked at all."""
    committed, origins = _copied_tree(tmp_path)
    assert _verify_copy(tmp_path, committed, origins)["component_count"] == 10


def test_the_closure_digest_moves_when_a_component_changes(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    before = _verify_copy(tmp_path, committed, origins)["closure_digest"]

    target = "research/tavonel_eval_v2/tools/sfir9_scorer.py"
    changed = committed[target] + b"\n# a change\n"
    committed[target] = changed
    (tmp_path / target).write_bytes(changed)

    after = _verify_copy(tmp_path, committed, origins)["closure_digest"]
    assert after != before


# ------------------------------------------------------- the freeze manifest


def test_the_closure_says_out_loud_what_it_cannot_certify():
    assert "its own bytes" in _real_closure()["what_this_does_not_certify"]


def test_the_manifest_records_the_closure_tools_own_bytes():
    result = _real_closure()
    manifest = closure_module.freeze_manifest(result, repository_root=REPO)
    tool = manifest["closure_tool"]

    on_disk = (REPO / closure_module.CLOSURE_PATH).read_bytes()
    assert tool["sha256"] == transport.sha256_of(on_disk)
    assert tool["git_blob_id"] == transport.git_blob_id_of(on_disk)
    assert manifest["closure_digest"] == result["closure_digest"]


def test_the_manifest_reads_the_tool_from_disk_rather_than_importing_it():
    """The manifest's account must not come from the module's account of itself."""
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    assert "without importing" in manifest["closure_tool"]["read_how"]

    source = (NS / "tools/sfir9_execution_closure.py").read_text(encoding="utf-8")
    body = source.split("def freeze_manifest(")[1].split("\ndef ")[0]
    assert "import_module" not in body
    assert "read_bytes()" in body


def test_a_good_manifest_verifies():
    result = _real_closure()
    manifest = closure_module.freeze_manifest(result, repository_root=REPO)
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=REPO, closure_result=result
    )
    assert verification["verified"] is True
    assert verification["problems"] == []


def test_a_manifest_pinning_a_different_tool_does_not_verify():
    """An edited closure tool reporting a clean closure is visible here."""
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    manifest["closure_tool"]["sha256"] = "sha256:" + "0" * 64
    verification = closure_module.verify_freeze_manifest(manifest, repository_root=REPO)
    assert verification["closure_tool_sha256_matches"] is False
    assert verification["verified"] is False


def test_a_manifest_pinning_a_different_blob_does_not_verify():
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    manifest["closure_tool"]["git_blob_id"] = "0" * 40
    verification = closure_module.verify_freeze_manifest(manifest, repository_root=REPO)
    assert verification["closure_tool_blob_matches"] is False
    assert verification["verified"] is False


def test_a_manifest_edited_after_writing_does_not_verify():
    """The manifest's own digest covers its contents."""
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    manifest["closure_digest"] = "sha256:" + "1" * 64
    verification = closure_module.verify_freeze_manifest(manifest, repository_root=REPO)
    assert verification["manifest_digest_intact"] is False
    assert verification["verified"] is False


def test_a_manifest_from_another_closure_does_not_verify():
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    other = _real_closure(upstream_binding={"upstream_modules": [{"module": "x"}]})
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=REPO, closure_result=other
    )
    assert verification["closure_digest_matches"] is False
    assert verification["verified"] is False


def test_the_closure_comparison_is_skipped_rather_than_assumed_when_absent():
    """No closure supplied is not the same as a matching one."""
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    verification = closure_module.verify_freeze_manifest(manifest, repository_root=REPO)
    assert verification["closure_digest_matches"] is None
    assert verification["verified"] is True


def test_the_manifest_verifies_a_tool_it_did_not_produce(tmp_path):
    """Written against one tree, checked against another holding the same bytes."""
    shutil.copytree(REPO / closure_module.TOOLS, tmp_path / closure_module.TOOLS)
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path
    )
    assert verification["closure_tool_sha256_matches"] is True


def test_the_manifest_notices_a_tool_edited_in_the_tree_it_is_checked_against(tmp_path):
    shutil.copytree(REPO / closure_module.TOOLS, tmp_path / closure_module.TOOLS)
    target = tmp_path / closure_module.CLOSURE_PATH
    target.write_bytes(target.read_bytes() + b"\n# edited\n")

    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path
    )
    assert verification["verified"] is False


def test_the_manifest_refuses_to_be_written_against_an_uncommitted_tool(tmp_path):
    committed, _ = _copied_tree(tmp_path)
    tool = tmp_path / closure_module.CLOSURE_PATH
    tool.write_bytes(tool.read_bytes() + b"\n# uncommitted\n")

    with pytest.raises(closure_module.ClosureRefused) as caught:
        closure_module.freeze_manifest(
            {"closure_digest": "sha256:x", "component_count": 10},
            repository_root=tmp_path,
            read_committed_bytes=lambda _root, path: committed[path],
        )
    assert caught.value.code == closure_module.BYTES_MISMATCH


# ------------------------------------- the manifest, checked without this repo
#
# These repeat the manifest controls above against a copied tree. The duplication
# is deliberate. A control that reads this repository cannot survive having this
# module mutated: the committed-versus-working check fails first, for a reason
# unrelated to whatever was mutated, so the control dies trivially and proves
# nothing. The copied-tree versions take committed and working bytes from the
# same (possibly mutated) source, so they still discriminate.


def test_the_manifest_records_the_tool_bytes_in_a_copied_tree(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    result = _verify_copy(tmp_path, committed, origins)
    manifest = _manifest_in_copy(tmp_path, committed, result)

    on_disk = (tmp_path / closure_module.CLOSURE_PATH).read_bytes()
    assert manifest["closure_tool"]["sha256"] == transport.sha256_of(on_disk)
    assert manifest["closure_tool"]["git_blob_id"] == transport.git_blob_id_of(on_disk)
    assert manifest["closure_digest"] == result["closure_digest"]
    assert manifest["component_count"] == 10


def test_a_good_manifest_verifies_in_a_copied_tree(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    result = _verify_copy(tmp_path, committed, origins)
    manifest = _manifest_in_copy(tmp_path, committed, result)

    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path, closure_result=result
    )
    assert verification["verified"] is True
    assert verification["problems"] == []


@pytest.mark.parametrize(
    "field,bad",
    [("sha256", "sha256:" + "0" * 64), ("git_blob_id", "0" * 40)],
)
def test_a_manifest_pinning_the_wrong_tool_fails_in_a_copied_tree(tmp_path, field, bad):
    committed, origins = _copied_tree(tmp_path)
    manifest = _manifest_in_copy(
        tmp_path, committed, _verify_copy(tmp_path, committed, origins)
    )
    manifest["closure_tool"][field] = bad
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path
    )
    assert verification["verified"] is False
    # Named specifically: editing the manifest also breaks its own digest, so a
    # bare `verified is False` would pass with this check removed entirely.
    field_flag = {
        "sha256": "closure_tool_sha256_matches",
        "git_blob_id": "closure_tool_blob_matches",
    }[field]
    assert verification[field_flag] is False
    assert verification["problems"], "a refusal that lists no problem is not a report"


def test_an_edited_manifest_fails_in_a_copied_tree(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    manifest = _manifest_in_copy(
        tmp_path, committed, _verify_copy(tmp_path, committed, origins)
    )
    manifest["closure_digest"] = "sha256:" + "1" * 64
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path
    )
    assert verification["manifest_digest_intact"] is False
    assert verification["verified"] is False


def test_a_manifest_from_another_closure_fails_in_a_copied_tree(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    result = _verify_copy(tmp_path, committed, origins)
    manifest = _manifest_in_copy(tmp_path, committed, result)
    other = _verify_copy(
        tmp_path, committed, origins, upstream_binding={"upstream_modules": [{"m": 1}]}
    )
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path, closure_result=other
    )
    assert verification["closure_digest_matches"] is False
    assert verification["verified"] is False


def test_an_absent_closure_result_is_skipped_not_assumed_in_a_copied_tree(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    manifest = _manifest_in_copy(
        tmp_path, committed, _verify_copy(tmp_path, committed, origins)
    )
    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path
    )
    assert verification["closure_digest_matches"] is None
    assert verification["verified"] is True


def test_the_manifest_notices_a_tool_edited_after_it_was_written(tmp_path):
    committed, origins = _copied_tree(tmp_path)
    manifest = _manifest_in_copy(
        tmp_path, committed, _verify_copy(tmp_path, committed, origins)
    )
    tool = tmp_path / closure_module.CLOSURE_PATH
    tool.write_bytes(tool.read_bytes() + b"\n# edited after the freeze\n")

    verification = closure_module.verify_freeze_manifest(
        manifest, repository_root=tmp_path
    )
    assert verification["closure_tool_sha256_matches"] is False
    assert verification["verified"] is False
    assert any("bytes" in problem for problem in verification["problems"])


def test_the_manifest_says_why_it_is_a_separate_artifact():
    manifest = closure_module.freeze_manifest(_real_closure(), repository_root=REPO)
    assert "cannot certify itself" in manifest["why_this_is_a_separate_artifact"]
