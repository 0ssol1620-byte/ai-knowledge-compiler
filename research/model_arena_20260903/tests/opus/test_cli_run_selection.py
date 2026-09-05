"""``python -m arena.opus run`` selects from ``source_manifest.jsonl`` by
default (DEFECT 1): the whole campaign, never the 50-page canary block.

These tests never touch a real ``claude`` executable or the real
``source_manifest.jsonl``: ``cmd_run``'s downstream ``_run`` call is stubbed
out so only the selection wiring is exercised.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from arena.opus import cli as opus_cli
from arena.opus.selection import CanarySelection, PageSpec


def _run_args(*, execute: bool = True, limit: int | None = None,
              case_key: list[str] | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        command="run",
        workers=2,
        limit=limit,
        timeout=600,
        effort="high",
        claude=None,
        execute=execute,
        case_key=case_key,
    )


def test_run_without_execute_never_selects_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _boom(*_args: object, **_kwargs: object) -> CanarySelection:
        nonlocal called
        called = True
        raise AssertionError("selection must not run before --execute is given")

    monkeypatch.setattr(opus_cli, "select_source_manifest_pages", _boom)
    monkeypatch.setattr(opus_cli, "select_canary_pages", _boom)

    exit_code = opus_cli.cmd_run(_run_args(execute=False))

    assert exit_code == opus_cli.EXIT_USAGE
    assert called is False


def test_run_selects_from_the_source_manifest_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_spec = PageSpec(
        case_key="omnidocbench-aaa",
        sample_id="omnidoc:images/a",
        benchmark="omnidoc",
        benchmark_revision="rev",
        image_path=object(),  # type: ignore[arg-type]
        manifest_input_sha256="sha256:" + "a" * 64,
        staged_source_sha256="sha256:" + "1" * 64,
        media_type="image",
        page_index=0,
        source_relative_path="images/a.png",
    )
    fake_selection = CanarySelection(
        specs=(fake_spec,),
        source="source_manifest.jsonl",
        detail="fake selection for the test",
    )

    calls: list[int | None] = []

    def _fake_select_source_manifest_pages(limit: int | None, **_kwargs: object) -> CanarySelection:
        calls.append(limit)
        return fake_selection

    def _canary_selection_forbidden(*_args: object, **_kwargs: object) -> CanarySelection:
        raise AssertionError("`run` must not fall back to the canary selection (DEFECT 1)")

    run_calls: list[dict[str, object]] = []

    def _fake_run(args: argparse.Namespace, *, job_kind: str, specs: object,
                  selection_source: str, selection_detail: str) -> int:
        run_calls.append(
            {
                "job_kind": job_kind,
                "specs": list(specs),  # type: ignore[arg-type]
                "selection_source": selection_source,
                "selection_detail": selection_detail,
            }
        )
        return opus_cli.EXIT_OK

    monkeypatch.setattr(
        opus_cli, "select_source_manifest_pages", _fake_select_source_manifest_pages
    )
    monkeypatch.setattr(opus_cli, "select_canary_pages", _canary_selection_forbidden)
    monkeypatch.setattr(opus_cli, "_run", _fake_run)

    exit_code = opus_cli.cmd_run(_run_args(execute=True, limit=None))

    assert exit_code == opus_cli.EXIT_OK
    assert calls == [None]
    assert len(run_calls) == 1
    assert run_calls[0]["job_kind"] == "inference"
    assert run_calls[0]["specs"] == [fake_spec]
    assert run_calls[0]["selection_source"] == "source_manifest.jsonl"


def test_run_honours_limit_and_passes_it_to_the_source_manifest_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int | None] = []

    def _fake_select_source_manifest_pages(limit: int | None, **_kwargs: object) -> CanarySelection:
        calls.append(limit)
        return CanarySelection(specs=(), source="source_manifest.jsonl", detail="d")

    monkeypatch.setattr(
        opus_cli, "select_source_manifest_pages", _fake_select_source_manifest_pages
    )
    monkeypatch.setattr(opus_cli, "_run", lambda *a, **k: opus_cli.EXIT_OK)

    opus_cli.cmd_run(_run_args(execute=True, limit=7))

    assert calls == [7]


def test_run_case_key_override_skips_the_manifest_selection_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> CanarySelection:
        raise AssertionError("--case-key must override the manifest selection, not blend with it")

    monkeypatch.setattr(opus_cli, "select_source_manifest_pages", _boom)

    resolved: list[list[str]] = []

    def _fake_resolve_case_keys(keys: list[str]) -> list[PageSpec]:
        resolved.append(list(keys))
        return []

    monkeypatch.setattr(opus_cli, "resolve_case_keys", _fake_resolve_case_keys)
    monkeypatch.setattr(opus_cli, "_run", lambda *a, **k: opus_cli.EXIT_OK)

    opus_cli.cmd_run(_run_args(execute=True, case_key=["omnidocbench-aaa"]))

    assert resolved == [["omnidocbench-aaa"]]


def _fake_page(case_key: str) -> PageSpec:
    return PageSpec(
        case_key=case_key,
        sample_id=f"omnidoc:images/{case_key}",
        benchmark="omnidoc",
        benchmark_revision="rev",
        image_path=object(),  # type: ignore[arg-type]
        manifest_input_sha256="sha256:" + "a" * 64,
        staged_source_sha256="sha256:" + "1" * 64,
        media_type="image",
        page_index=0,
        source_relative_path=f"images/{case_key}.png",
    )


def test_run_skips_pages_that_already_have_a_receipt(
    monkeypatch: pytest.MonkeyPatch, isolated_run_root: Path
) -> None:
    """D63: a restarted `run` (e.g. with more workers after a kill) never pays
    for a page whose receipt is already on disk."""
    done, todo = _fake_page("omnidocbench-done"), _fake_page("omnidocbench-todo")
    receipts = isolated_run_root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f"{done.case_key}.json").write_text("{}", encoding="utf-8")
    selection = CanarySelection(
        specs=(done, todo), source="source_manifest.jsonl", detail="fake"
    )
    monkeypatch.setattr(opus_cli, "select_source_manifest_pages", lambda *_a, **_k: selection)
    run_calls: list[dict[str, object]] = []

    def _fake_run(args: argparse.Namespace, *, job_kind: str, specs: object,
                  selection_source: str, selection_detail: str) -> int:
        run_calls.append({"specs": list(specs), "detail": selection_detail})  # type: ignore[arg-type]
        return opus_cli.EXIT_OK

    monkeypatch.setattr(opus_cli, "_run", _fake_run)

    assert opus_cli.cmd_run(_run_args(execute=True)) == opus_cli.EXIT_OK
    assert run_calls[0]["specs"] == [todo]
    assert "1 page(s) already have a receipt" in str(run_calls[0]["detail"])


def test_run_with_everything_receipted_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, isolated_run_root: Path
) -> None:
    done = _fake_page("omnidocbench-done")
    receipts = isolated_run_root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f"{done.case_key}.json").write_text("{}", encoding="utf-8")
    selection = CanarySelection(specs=(done,), source="source_manifest.jsonl", detail="fake")
    monkeypatch.setattr(opus_cli, "select_source_manifest_pages", lambda *_a, **_k: selection)

    def _never(*_a: object, **_k: object) -> int:
        raise AssertionError("_run must not be called when nothing is left")

    monkeypatch.setattr(opus_cli, "_run", _never)
    assert opus_cli.cmd_run(_run_args(execute=True)) == opus_cli.EXIT_OK
