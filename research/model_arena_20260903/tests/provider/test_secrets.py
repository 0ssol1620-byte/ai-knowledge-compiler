"""Secrets: redaction, refusal to serialize, and block-aware R2 lookup."""

from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path

import pytest
from arena.provider.safety import SecretLeak, assert_secret_free
from arena.provider.secrets import (
    R2Credentials,
    Secret,
    SecretUnavailable,
    load_secret,
    r2_credentials,
    runpod_api_key,
    runpod_api_key_source,
)
from tests.provider.conftest import (
    FAKE_ENDPOINT,
    FAKE_R2_ACCESS,
    FAKE_R2_SECRET,
    FAKE_RUNPOD_VALUE,
)


def test_secret_never_prints_its_value() -> None:
    held = Secret("abcdef0123456789abcdef", label="Runpod_B")
    for rendering in (str(held), repr(held), f"{held}", f"{held!r}", format(held, ">40")):
        assert "abcdef0123456789abcdef" not in rendering
        assert "redacted" in rendering.lower() or "value=<redacted>" in rendering
    assert held.reveal() == "abcdef0123456789abcdef"
    assert len(held) == 22


def test_secret_refuses_serialization_and_copying() -> None:
    held = Secret("abcdef0123456789abcdef", label="Runpod_B")
    with pytest.raises(TypeError):
        json.dumps({"key": held})
    with pytest.raises(TypeError):
        pickle.dumps(held)
    with pytest.raises(TypeError):
        copy.deepcopy(held)
    with pytest.raises(TypeError):
        held.for_json()


def test_secret_hash_does_not_expose_the_value() -> None:
    first = Secret("aaaaaaaaaaaaaaaaaaaaaa", label="x")
    second = Secret("bbbbbbbbbbbbbbbbbbbbbb", label="x")
    assert hash(first) == hash(second)  # same label and length only
    assert first != second


def test_load_secret_reads_a_unique_label(credential_file: Path) -> None:
    value = load_secret("Runpod_B", path=credential_file)
    assert value.reveal() == FAKE_RUNPOD_VALUE
    assert value.label == "Runpod_B"


def test_load_secret_refuses_an_ambiguous_label(credential_file: Path) -> None:
    # "Access Key ID" appears in both R2 blocks: guessing would be wrong.
    with pytest.raises(SecretUnavailable, match=r"appears \d+ times"):
        load_secret("Access Key ID", path=credential_file)


def test_load_secret_reports_a_missing_label_without_the_file(credential_file: Path) -> None:
    with pytest.raises(SecretUnavailable) as caught:
        load_secret("Nonexistent_Label", path=credential_file)
    assert FAKE_RUNPOD_VALUE not in str(caught.value)


def test_missing_credential_file_is_a_refusal(tmp_path: Path) -> None:
    with pytest.raises(SecretUnavailable, match="absent"):
        load_secret("Runpod_B", path=tmp_path / "nope.txt")


def test_runpod_api_key_falls_back_to_the_environment(tmp_path: Path) -> None:
    absent = tmp_path / "nope.txt"
    value = runpod_api_key(path=absent, env={"RUNPOD_API_KEY": "envfallback000000000000"})
    assert value.label == "RUNPOD_API_KEY"
    assert value.reveal() == "envfallback000000000000"


def test_runpod_api_key_refuses_when_neither_source_has_it(tmp_path: Path) -> None:
    with pytest.raises(SecretUnavailable, match="no RunPod credential"):
        runpod_api_key(path=tmp_path / "nope.txt", env={})


def test_runpod_api_key_source_names_the_surface(credential_file: Path) -> None:
    assert runpod_api_key_source(path=credential_file) == "Runpod_B"


def test_r2_account_block_is_selected_by_name(credential_file: Path) -> None:
    credentials = r2_credentials(block="account", path=credential_file)
    assert credentials.access_key_id.reveal() == FAKE_R2_ACCESS
    assert credentials.secret_access_key.reveal() == FAKE_R2_SECRET
    assert credentials.endpoint_url == FAKE_ENDPOINT


def test_r2_user_block_is_a_different_block(credential_file: Path) -> None:
    account = r2_credentials(block="account", path=credential_file)
    user = r2_credentials(block="user", path=credential_file)
    assert user.access_key_id.reveal() != account.access_key_id.reveal()
    assert user.endpoint_url.endswith("us.r2.cloudflarestorage.com")


def test_r2_credentials_repr_hides_the_keys(credential_file: Path) -> None:
    credentials = r2_credentials(path=credential_file)
    rendered = repr(credentials)
    assert FAKE_R2_ACCESS not in rendered
    assert FAKE_R2_SECRET not in rendered
    assert credentials.endpoint_url in rendered


def test_r2_credentials_reject_an_unknown_block(credential_file: Path) -> None:
    with pytest.raises(SecretUnavailable, match="unknown R2 block"):
        r2_credentials(block="nope", path=credential_file)


def test_r2_credentials_refuse_a_file_without_the_heading(tmp_path: Path) -> None:
    path = tmp_path / "partial.txt"
    path.write_text("Runpod_B: runpodfake0000000000000000\n", encoding="utf-8")
    with pytest.raises(SecretUnavailable, match="Cloudflare R2"):
        r2_credentials(path=path)


def test_r2_credentials_refuse_an_incomplete_block(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.txt"
    path.write_text(
        "Cloudflare R2:\n"
        "Account API Token: {\n"
        "Access Key ID: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "}\n",
        encoding="utf-8",
    )
    with pytest.raises(SecretUnavailable, match="Secret Access Key"):
        r2_credentials(path=path)


def test_credentials_never_pass_the_secret_free_guard(credential_file: Path) -> None:
    """The guard would catch a leak if any of these values reached a receipt."""

    credentials: R2Credentials = r2_credentials(path=credential_file)
    with pytest.raises(SecretLeak):
        assert_secret_free(
            {"oops": credentials.secret_access_key.reveal()}, context="deliberate leak"
        )


def test_only_credential_shaped_values_are_registered_for_exact_matching() -> None:
    """A low-entropy value would false-positive against legitimate content.

    The guard checks registered values by substring. Registering something like
    ``"a" * 22`` -- a substring of many legitimate revisions and digests --
    would raise SecretLeak on receipts that carry no credential at all, which
    fails closed in the wrong direction: it blocks the campaign while
    protecting nothing.
    """

    Secret("a" * 40, label="not-a-credential")  # too repetitive to register
    Secret("short0011", label="too-short")
    assert_secret_free({"model_revision": "a" * 40}, context="page receipt")
    assert_secret_free({"digest": "sha256:" + "b" * 64}, context="page receipt")

    # A real-shaped credential is registered and caught verbatim.
    Secret("r2fake9Access8Key7Id6For5Tests4Only3", label="Access Key ID")
    with pytest.raises(SecretLeak, match="credential this process loaded"):
        assert_secret_free(
            {"leaked": "prefix r2fake9Access8Key7Id6For5Tests4Only3 suffix"},
            context="page receipt",
        )
