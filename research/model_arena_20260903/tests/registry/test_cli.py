"""End-to-end CLI behaviour, driven entirely from recorded fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arena.constants import GPU_MODEL_KEYS, MODEL_KEYS
from arena.registry.cli import (
    EVALUATOR_REGISTRY_FILENAME,
    MODEL_REGISTRY_FILENAME,
    build_parser,
    main,
)
from arena.registry.models import HEX40

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _resolve_offline(out_dir: Path) -> int:
    return main(
        [
            "resolve",
            "--offline",
            "--fixtures",
            str(FIXTURE_DIR),
            "--out-dir",
            str(out_dir),
        ]
    )


@pytest.fixture(scope="module")
def resolved(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("registry_out")
    assert _resolve_offline(out_dir) == 0
    return out_dir


def test_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_offline_resolve_writes_both_files(resolved: Path) -> None:
    assert (resolved / MODEL_REGISTRY_FILENAME).is_file()
    assert (resolved / EVALUATOR_REGISTRY_FILENAME).is_file()


def test_offline_resolve_covers_every_model_key(resolved: Path) -> None:
    document = json.loads((resolved / MODEL_REGISTRY_FILENAME).read_text(encoding="utf-8"))
    assert set(document["models"]) == set(MODEL_KEYS)
    assert document["model_count"] == 12


def test_every_gpu_model_is_pinned_to_a_40_hex_revision(resolved: Path) -> None:
    document = json.loads((resolved / MODEL_REGISTRY_FILENAME).read_text(encoding="utf-8"))
    for key in GPU_MODEL_KEYS:
        record = document["models"][key]
        assert HEX40.match(record["revision"]), key
        assert record["weights"] is not None
        assert HEX40.match(record["weights"]["revision"]), key


def test_offline_resolve_is_byte_for_byte_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    assert _resolve_offline(first) == 0
    assert _resolve_offline(second) == 0
    for name in (MODEL_REGISTRY_FILENAME, EVALUATOR_REGISTRY_FILENAME):
        left = json.loads((first / name).read_text(encoding="utf-8"))
        right = json.loads((second / name).read_text(encoding="utf-8"))
        # generated_at is wall-clock; everything else must match exactly.
        left.pop("generated_at")
        right.pop("generated_at")
        for container in ("models", "evaluators"):
            for record in list(left.get(container, {}).values()):
                record.pop("resolved_at", None)
                record.pop("upstream_head_verified_at", None)
            for record in list(right.get(container, {}).values()):
                record.pop("resolved_at", None)
                record.pop("upstream_head_verified_at", None)
        assert left == right, name


def test_validate_subcommand_passes_on_the_resolved_files(resolved: Path) -> None:
    assert main(["validate", "--out-dir", str(resolved)]) == 0


def test_validate_fails_closed_on_a_tampered_record(resolved: Path, tmp_path: Path) -> None:
    document = json.loads((resolved / MODEL_REGISTRY_FILENAME).read_text(encoding="utf-8"))
    document["models"]["glm_ocr"]["full_run_eligible"] = True
    tampered = tmp_path / MODEL_REGISTRY_FILENAME
    tampered.write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / EVALUATOR_REGISTRY_FILENAME).write_text(
        (resolved / EVALUATOR_REGISTRY_FILENAME).read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert main(["validate", "--out-dir", str(tmp_path)]) == 1


def test_validate_reports_a_missing_file_as_a_registry_error(tmp_path: Path) -> None:
    assert main(["validate", "--out-dir", str(tmp_path)]) == 2


def test_offline_resolve_with_an_empty_fixture_dir_fails_closed(tmp_path: Path) -> None:
    assert (
        main(
            [
                "resolve",
                "--offline",
                "--fixtures",
                str(tmp_path / "no-fixtures"),
                "--out-dir",
                str(tmp_path),
            ]
        )
        == 2
    )


def test_written_files_are_sorted_and_two_space_indented(resolved: Path) -> None:
    for name in (MODEL_REGISTRY_FILENAME, EVALUATOR_REGISTRY_FILENAME):
        text = (resolved / name).read_text(encoding="utf-8")
        assert text.endswith("}\n")
        assert text.splitlines()[1].startswith('  "')
        keys = list(json.loads(text))
        assert keys == sorted(keys)
