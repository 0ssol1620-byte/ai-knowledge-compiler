from __future__ import annotations

import pytest
from akc_cir.action_key import (
    ActionInput,
    CompilationActionKeyInput,
    RevisionBinding,
    compilation_action_key,
)


def _key(**overrides: object) -> str:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "action_type": "semantic.compile",
        "inputs": (
            ActionInput(role="document", artifact_hash="sha256:doc"),
            ActionInput(role="policy", artifact_hash="sha256:policy"),
        ),
        "components": (
            RevisionBinding(role="parser", name="ovis", revision="0.22.1+cu129"),
        ),
        "prompt_schemas": (
            RevisionBinding(role="system", name="semantic-compile", revision="sha256:prompt"),
        ),
        "policy_revision": "trust-policy-v1",
        "recipe_revision": "compile-recipe-v1",
        "permission_scope_hash": "sha256:permission",
        "deterministic_parameters": {"temperature": 0, "max_tokens": 4096},
    }
    values.update(overrides)
    return compilation_action_key(CompilationActionKeyInput(**values))  # type: ignore[arg-type]


def test_swapping_semantic_input_roles_changes_key() -> None:
    normal = _key()
    swapped = _key(
        inputs=(
            ActionInput(role="policy", artifact_hash="sha256:doc"),
            ActionInput(role="document", artifact_hash="sha256:policy"),
        )
    )
    assert normal != swapped


def test_tuple_construction_order_is_not_semantic_when_slots_match() -> None:
    first = ActionInput(role="page", ordinal=0, artifact_hash="sha256:a")
    second = ActionInput(role="page", ordinal=1, artifact_hash="sha256:b")
    assert _key(inputs=(first, second)) == _key(inputs=(second, first))


def test_repeated_input_ordinal_is_semantic() -> None:
    forward = _key(
        inputs=(
            ActionInput(role="page", ordinal=0, artifact_hash="sha256:a"),
            ActionInput(role="page", ordinal=1, artifact_hash="sha256:b"),
        )
    )
    reversed_operands = _key(
        inputs=(
            ActionInput(role="page", ordinal=0, artifact_hash="sha256:b"),
            ActionInput(role="page", ordinal=1, artifact_hash="sha256:a"),
        )
    )
    assert forward != reversed_operands


def test_duplicate_role_ordinal_slots_fail_closed() -> None:
    with pytest.raises(ValueError, match="role/ordinal"):
        CompilationActionKeyInput(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            action_type="semantic.compile",
            inputs=(
                ActionInput(role="document", ordinal=0, artifact_hash="sha256:a"),
                ActionInput(role="document", ordinal=0, artifact_hash="sha256:b"),
            ),
        )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("tenant_id", "tenant-b"),
        ("workspace_id", "workspace-b"),
        ("policy_revision", "trust-policy-v2"),
        ("recipe_revision", "compile-recipe-v2"),
        ("permission_scope_hash", "sha256:other-permission"),
    ],
)
def test_security_and_recipe_identity_changes_key(field: str, changed: object) -> None:
    assert _key() != _key(**{field: changed})


def test_component_name_and_revision_are_bound_together() -> None:
    assert _key() != _key(
        components=(RevisionBinding(role="parser", name="ovis", revision="0.22.2"),)
    )
    assert _key() != _key(
        components=(RevisionBinding(role="parser", name="other-parser", revision="0.22.1+cu129"),)
    )


def test_prompt_schema_role_and_revision_are_identity() -> None:
    assert _key() != _key(
        prompt_schemas=(
            RevisionBinding(role="system", name="semantic-compile", revision="sha256:other"),
        )
    )
    assert _key() != _key(
        prompt_schemas=(
            RevisionBinding(role="review", name="semantic-compile", revision="sha256:prompt"),
        )
    )


def test_parameter_mapping_order_is_canonical() -> None:
    assert _key(deterministic_parameters={"temperature": 0, "max_tokens": 4096}) == _key(
        deterministic_parameters={"max_tokens": 4096, "temperature": 0}
    )
