import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from evaluate import family_of, fit, grouped_interval
from policy import FEATURE_NAMES, Decision, visible_features


def vector(value):
    return (value,) + (0.0,) * (len(FEATURE_NAMES) - 1)


def test_runtime_policy_has_no_file_evaluator_or_metadata_dependency():
    source = Path(__file__).with_name("policy.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {
        item.name for node in ast.walk(tree) if isinstance(node, ast.Import) for item in node.names
    }
    assert modules <= {"__future__", "math", "re", "dataclasses"}
    assert not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"open", "eval", "exec"}
        for n in ast.walk(tree)
    )


def test_primary_features_have_no_alternate_output_or_hidden_attributes():
    value = visible_features(
        "| A | 12 |\ntext $x$",
        width=100,
        height=200,
        edge_density=None,
        near_white_ratio=0.9,
        render_entropy=1.1,
    )
    assert len(value) == len(FEATURE_NAMES)
    assert value[0] == 1 and value[3] == 0.5 and value[8] == 0.5
    assert value[9] == -1


def test_tree_learns_only_supplied_training_losses_and_predicts_numeric_vectors():
    rows = [(vector(0), (0.1, 0.8)) for _ in range(128)] + [
        (vector(1), (0.9, 0.1)) for _ in range(128)
    ]
    learned = fit(rows)
    assert learned.choose(vector(0)) == 0
    assert learned.choose(vector(1)) == 1
    assert learned.choose(vector(0.01)) == 1


def test_ties_prefer_the_primary_and_tiny_leaves_are_not_fitted():
    learned = fit([(vector(0), (0.2, 0.2)), (vector(1), (0.2, 0.2))])
    assert learned == Decision(0)


def test_grouping_keeps_pages_of_one_named_document_together():
    assert family_of("images/PPT_123_eng_page_003.png") == family_of(
        "images/PPT_123_eng_page_004.png"
    )
    assert family_of("folder/unrelated.pdf") != "PPT_123_eng"


def test_bootstrap_uses_groups_and_reproduces_a_constant_difference():
    assert grouped_interval([0.1, 0.1, 0.1], ["a", "a", "b"]) == pytest.approx([0.1, 0.1])


def test_malformed_feature_dimension_or_missing_tree_branch_is_refused():
    with pytest.raises(ValueError, match="VECTOR_MISMATCH"):
        Decision(0).choose(())
    with pytest.raises(ValueError, match="INCOMPLETE_SELECTOR"):
        Decision(0, 0, 0.5).choose(vector(0))
