"""TrackedBuildContext — catching what a build consumed but never declared.

§29.2 Consumption completeness. A receipt that lists only declared inputs is
a promise kept about half the truth: builders open files nobody listed, poke
the environment, ask the clock, and roll dice. These tests run deliberately
under-declared dummy builders and check that every one of those appetites
ends up in the receipt — file reads with hashes, environment variable NAMES
and never values, nondeterminism flags, mid-build imports — and that a
receipt written without any tracking still loads, seals, and verifies exactly
as it did before the sections existed.
"""

from __future__ import annotations

import builtins
import datetime as datetime_module
import importlib
import io
import json
import os
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_cir import (
    ENV_ACCESS_ALL,
    BuildReceipt,
    DeclaredInput,
    HiddenInputs,
    TrackedBuildContext,
    tracked_build,
)
from akc_cir.base import sha256_digest

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

SECRET_ENV_KEY = "AKC_TBC_TEST_SECRET"
SECRET_ENV_VALUE = "hunter2-do-not-archive-7f3a"


@pytest.fixture
def secret_file(tmp_path: Path) -> Path:
    """A file a builder will read without ever declaring."""
    target = tmp_path / "side_notes.txt"
    payload = b"undeclared corpus fragment\n"
    target.write_bytes(payload)
    return target


@pytest.fixture
def secret_env() -> None:
    os.environ[SECRET_ENV_KEY] = SECRET_ENV_VALUE
    try:
        yield
    finally:
        os.environ.pop(SECRET_ENV_KEY, None)


# --------------------------------------------------------------------------
# Files: an undeclared read is still a read
# --------------------------------------------------------------------------


def test_a_secretly_read_file_is_captured_with_its_hash(secret_file: Path) -> None:
    def builder() -> int:
        with open(secret_file, encoding="utf-8") as handle:
            return len(handle.read())

    with TrackedBuildContext() as tracked:
        builder()

    files = tracked.observation().hidden_inputs().files
    assert [item.path for item in files] == [str(secret_file)]
    assert files[0].sha256 == sha256_digest(secret_file.read_bytes())


def test_repeated_reads_of_one_file_are_recorded_once(secret_file: Path) -> None:
    def builder() -> int:
        total = 0
        for _ in range(3):
            with open(secret_file, encoding="utf-8") as handle:
                total += len(handle.read())
        return total + len(Path(secret_file).read_text(encoding="utf-8"))

    with TrackedBuildContext() as tracked:
        builder()

    assert len(tracked.observation().files) == 1


def test_write_only_opens_are_not_consumption(tmp_path: Path) -> None:
    target = tmp_path / "scratch.txt"

    def builder() -> None:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("output, not intake\n")

    with TrackedBuildContext() as tracked:
        builder()

    assert tracked.observation().files == ()


# --------------------------------------------------------------------------
# Environment: names only, values never
# --------------------------------------------------------------------------


def test_env_access_records_the_key_name_and_never_the_value(
    secret_env: None,
) -> None:
    def builder() -> str:
        return os.environ[SECRET_ENV_KEY]

    with TrackedBuildContext() as tracked:
        leaked = builder()

    assert leaked == SECRET_ENV_VALUE  # the builder saw it; the receipt must not
    observation = tracked.observation()
    assert SECRET_ENV_KEY in observation.env_keys
    rendered = json.dumps(observation.hidden_inputs().model_dump(mode="json"))
    assert SECRET_ENV_VALUE not in rendered


def test_get_contains_and_missing_key_probes_are_all_tracked(
    secret_env: None,
) -> None:
    def builder() -> bool:
        found = os.environ.get(SECRET_ENV_KEY) is not None
        probed = SECRET_ENV_KEY in os.environ
        defaulted = os.getenv("AKC_TBC_NEVER_SET_KEY", "absent")
        return found and probed and defaulted == "absent"

    with TrackedBuildContext() as tracked:
        builder()

    keys = tracked.observation().env_keys
    assert SECRET_ENV_KEY in keys
    assert "AKC_TBC_NEVER_SET_KEY" in keys  # even probing a missing key leaks intent


def test_wholesale_iteration_is_marked_not_enumerated(secret_env: None) -> None:
    def builder() -> int:
        return len(sorted(os.environ))

    with TrackedBuildContext() as tracked:
        builder()

    assert ENV_ACCESS_ALL in tracked.observation().env_keys
    # The marker means "everything"; pretending otherwise would be fiction.
    assert len(tracked.observation().env_keys) >= 1


# --------------------------------------------------------------------------
# Nondeterminism: clock and dice
# --------------------------------------------------------------------------


def test_clock_and_dice_use_flags_non_determinism(secret_file: Path) -> None:
    def builder() -> float:
        stamp = time.time()
        roll = random.randint(0, 100)
        # Through the datetime MODULE attribute: a from-import taken before
        # the block would hold the original class — that blind spot is
        # documented, not tested around.
        moment = datetime_module.datetime.now(tz=UTC)
        return stamp + roll + moment.timestamp()

    with TrackedBuildContext() as tracked:
        builder()

    non_determinism = tracked.observation().non_determinism()
    assert non_determinism.flagged
    names = {source.source for source in non_determinism.sources}
    assert {"time.time", "random.randint", "datetime.datetime.now"} <= names
    counts = {source.source: source.calls for source in non_determinism.sources}
    assert counts["time.time"] == 1


def test_a_clean_builder_flags_nothing(tmp_path: Path) -> None:
    def builder() -> int:
        return sum(range(10))

    with TrackedBuildContext(track_files=False, track_imports=False) as tracked:
        builder()

    observation = tracked.observation()
    assert observation.clean
    assert observation.files == ()
    assert observation.env_keys == ()
    assert not observation.non_determinism().flagged


# --------------------------------------------------------------------------
# Mid-build imports
# --------------------------------------------------------------------------


def test_an_import_during_the_build_is_recorded(tmp_path: Path) -> None:
    module_name = "_akc_tbc_probe_module_under_test"
    (tmp_path / f"{module_name}.py").write_text("VALUE = 41\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        with TrackedBuildContext() as tracked:
            module = importlib.import_module(module_name)
            assert module.VALUE == 41
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)

    assert module_name in tracked.observation().imported_modules


# --------------------------------------------------------------------------
# Deep tracing is opt-in and stays out of the way by default
# --------------------------------------------------------------------------


def test_settrace_is_off_by_default_and_on_when_asked(secret_file: Path) -> None:
    def builder() -> int:
        with open(secret_file, encoding="utf-8") as handle:
            return len(handle.read())

    with TrackedBuildContext() as tracked:
        builder()
    assert tracked.trace_sample == ()

    with TrackedBuildContext(use_settrace=True) as traced:
        builder()
    assert traced.trace_sample  # call sites were witnessed


# --------------------------------------------------------------------------
# Receipt integration: seal covers the whole story
# --------------------------------------------------------------------------


def _receipt_for(paths: tuple[Path, ...]) -> BuildReceipt:
    return BuildReceipt(
        created_at=NOW,
        builder_id="tbc-test-builder",
        declared_inputs=tuple(
            DeclaredInput(path=str(path), sha256=sha256_digest(path.read_bytes()))
            for path in paths
        ),
    )


def test_declared_files_do_not_reappear_as_hidden(secret_file: Path, tmp_path: Path) -> None:
    declared = tmp_path / "declared.txt"
    declared.write_bytes(b"properly declared input\n")

    def builder() -> int:
        return len(Path(secret_file).read_text(encoding="utf-8")) + len(
            declared.read_text(encoding="utf-8")
        )

    with TrackedBuildContext() as tracked:
        builder()

    stamped = tracked.observation().attach_to(_receipt_for((declared,)))
    assert [item.path for item in stamped.hidden_inputs.files] == [str(secret_file)]


def test_tracked_build_stamps_hidden_inputs_then_seals(
    secret_file: Path, secret_env: None
) -> None:
    def builder() -> int:
        probe = os.environ[SECRET_ENV_KEY]
        return len(Path(secret_file).read_text(encoding="utf-8")) + len(probe)

    result, receipt = tracked_build("tbc-test-builder", builder, created_at=NOW)

    assert receipt.sealed
    assert receipt.verify_seal()
    assert [item.path for item in receipt.hidden_inputs.files] == [str(secret_file)]
    assert receipt.hidden_inputs.files[0].sha256 == sha256_digest(
        secret_file.read_bytes()
    )
    assert SECRET_ENV_KEY in receipt.hidden_inputs.env_keys
    assert SECRET_ENV_VALUE not in receipt.model_dump_json()
    assert not receipt.non_determinism.flagged
    assert result > 0


def test_tampering_with_a_sealed_receipt_breaks_verification(
    secret_file: Path,
) -> None:
    def builder() -> int:
        return len(Path(secret_file).read_text(encoding="utf-8"))

    _, receipt = tracked_build("tbc-test-builder", builder, created_at=NOW)
    forged = receipt.model_copy(update={"hidden_inputs": HiddenInputs()})
    assert not forged.verify_seal()


# --------------------------------------------------------------------------
# Backward compatibility: receipts from before tracking existed
# --------------------------------------------------------------------------


def test_legacy_receipt_without_tracking_sections_loads_and_verifies() -> None:
    legacy_payload = {
        "created_at": "2026-07-01T08:00:00+00:00",
        "builderId": "legacy-builder",
        "declaredInputs": [
            {"path": "corpus/old.md", "sha256": sha256_digest(b"old bytes")}
        ],
    }

    receipt = BuildReceipt.model_validate(legacy_payload)

    assert receipt.hidden_inputs == HiddenInputs()
    sealed = receipt.seal()
    assert sealed.verify_seal()
    # Additive sections ride along empty instead of breaking old consumers.
    assert '"hiddenInputs"' in sealed.model_dump_json()


# --------------------------------------------------------------------------
# Hygiene: the watchers leave no residue behind
# --------------------------------------------------------------------------


def test_every_hook_is_restored_after_normal_and_erroring_exits(
    secret_file: Path,
) -> None:
    original_open = builtins.open
    original_io_open = io.open
    original_environ = os.environ
    original_time = time.time
    original_random = random.random
    original_datetime_class = datetime_module.datetime

    with pytest.raises(RuntimeError, match="build failed"), TrackedBuildContext():
        raise RuntimeError("build failed")

    with TrackedBuildContext():
        open(secret_file, encoding="utf-8").close()

    assert builtins.open is original_open
    assert io.open is original_io_open
    assert os.environ is original_environ
    assert time.time is original_time
    assert random.random is original_random
    assert datetime_module.datetime is original_datetime_class
