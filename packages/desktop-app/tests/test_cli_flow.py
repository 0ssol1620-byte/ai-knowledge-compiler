"""End-to-end CLI flow tests, isolated from the real ``~/.tavonel``.

Every test drives the CLI through :func:`akc_desktop_app.cli.main` with
``--config-home`` pointed at a pytest tmp dir, so nothing here can touch the
developer's actual Tavonel home or any real workspace.

Flow under test (task spec):

1. ``init``      -> config.json created with workspace + world store + MCP
                    stdio registration; watcher.json + snippet on disk;
                    time-to-first-world milestones appended.
2. config check  -> strict schema, stable ids, re-init idempotent.
3. ``status``    -> human output names the workspace; ``--json`` parses and
                    detects a published world once one appears in the store.
4. ``serve``     -> minimal wiring proof via injected fake watcher/MCP.
5. ``uninstall`` -> removes ONLY generated artifacts; original workspace is
                    byte-for-byte untouched (asserted by tree comparison).
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from akc_desktop_app.cli import EXIT_OK, EXIT_USAGE, main
from akc_desktop_app.config import load_config
from akc_desktop_app.serve import run_serve
from akc_desktop_app.uninstall import hash_tree


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    """Tavonel home redirected into tmp (never the developer's ~/.tavonel)."""
    target = tmp_path / "tavonel-home"
    target.mkdir()
    return target


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A fake user workspace with a couple of ordinary documents."""
    ws = tmp_path / "atlas-demo"
    (ws / "notes").mkdir(parents=True)
    (ws / "notes" / "kickoff.md").write_text("# kickoff\n", encoding="utf-8")
    (ws / "budget.csv").write_text("item,cost\ntest,1\n", encoding="utf-8")
    return ws


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- 1. init --


def test_init_registers_workspace_and_writes_all_artifacts(home: Path, workspace: Path) -> None:
    code, out, err = _run(
        "init", str(workspace), "--name", "atlas-demo", "--config-home", str(home)
    )
    assert code == EXIT_OK, err
    assert "등록 완료" in out

    # config.json exists and carries the workspace + world store + MCP stdio.
    config_path = home / "config.json"
    assert config_path.is_file()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert len(raw["workspaces"]) == 1
    entry = raw["workspaces"][0]
    assert entry["name"] == "atlas-demo"
    assert Path(entry["path"]).resolve() == workspace.resolve()
    assert len(entry["collection_id"]) == 36          # uuid4
    assert len(entry["source_root_id"]) == 36         # uuid5, deterministic
    assert raw["world_store_path"] == str(home / "world-state")
    assert raw["mcp"] == {"transport": "stdio", "port": None}

    # Per-workspace watcher config was generated (valid JSON, has roots).
    watcher = json.loads(
        (home / "workspaces" / "atlas-demo" / "watcher.json").read_text(encoding="utf-8")
    )
    assert watcher["collection_id"] == entry["collection_id"]
    assert watcher["roots"][0]["source_root_id"] == entry["source_root_id"]

    # MCP client registration snippet points at the local stdio server.
    snippet = json.loads(
        (home / "mcp" / "claude-desktop-snippet.json").read_text(encoding="utf-8")
    )
    server = snippet["mcpServers"]["akc-local-mcp"]
    assert server["args"] == ["-m", "akc_local_mcp"]
    assert server["env"]["AKC_LOCAL_MCP_WORLD_STATE_DIR"] == str(home / "world-state")

    # Onboarding guidance suggests the Health Scan and the first compile.
    assert "Health Scan" in out
    assert str(home / "world-state") in out

    # Time-to-first-world milestones were logged at init time.
    ttfw_lines = (home / "logs" / "ttfw.jsonl").read_text(encoding="utf-8").splitlines()
    phases = [json.loads(line)["phase"] for line in ttfw_lines]
    assert phases[0] == "init_started"
    assert "init_completed" in phases


def test_re_init_same_workspace_is_idempotent(home: Path, workspace: Path) -> None:
    first, _, _ = _run("init", str(workspace), "--config-home", str(home))
    assert first == EXIT_OK
    before = json.loads((home / "config.json").read_text(encoding="utf-8"))

    second, out, _ = _run("init", str(workspace), "--config-home", str(home))
    assert second == EXIT_OK
    assert "이미 등록된 워크스페이스입니다" in out
    after = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert after["workspaces"] == before["workspaces"]


def test_init_rejects_missing_directory(home: Path, tmp_path: Path) -> None:
    code, _, err = _run("init", str(tmp_path / "nope"), "--config-home", str(home))
    assert code == EXIT_USAGE
    assert "오류" in err


def test_generated_config_round_trips_through_strict_loader(home: Path, workspace: Path) -> None:
    code, _, err = _run("init", str(workspace), "--config-home", str(home))
    assert code == EXIT_OK, err
    config = load_config(home)
    assert len(config.workspaces) == 1
    assert config.world_store == home / "world-state"
    assert config.mcp.transport == "stdio"


# -------------------------------------------------------------- 3. status --


def test_status_lists_workspace_and_detects_published_world(home: Path, workspace: Path) -> None:
    _run("init", str(workspace), "--config-home", str(home))

    code, plain, err = _run("status", "--config-home", str(home))
    assert code == EXIT_OK, err
    assert "atlas-demo" in plain
    assert str(home) in plain
    assert "발행된 월드: (아직 없음)" in plain
    assert "time-to-first-world" in plain

    # Publish a world directly into the configured store (as compiler would).
    world_dir = home / "world-state" / "w-0001"
    world_dir.mkdir(parents=True)
    (world_dir / "manifest.json").write_text('{"world_id": "w-0001"}', encoding="utf-8")

    code, payload, err = _run("status", "--json", "--config-home", str(home))
    assert code == EXIT_OK, err
    data = json.loads(payload)
    assert [w["world_id"] for w in data["worlds"]] == ["w-0001"]
    assert data["ttfw"]["seconds_to_first_world"] is not None
    assert data["ttfw"]["seconds_to_first_world"] >= 0
    assert data["artifacts"]["logs_exist"] is True

    # The world_detected milestone was recorded idempotently.
    ttfw = (home / "logs" / "ttfw.jsonl").read_text(encoding="utf-8").splitlines()
    detected = [json.loads(line) for line in ttfw if '"world_detected"' in line]
    assert len(detected) == 1


def test_status_with_empty_config_still_succeeds(home: Path) -> None:
    code, plain, err = _run("status", "--config-home", str(home))
    assert code == EXIT_OK, err
    assert "(없음" in plain


# --------------------------------------------------------------- 4. serve --


class FakeWatcher:
    """Records start/stop so we can prove serve wiring without watchdog."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self, timeout: float = 5.0) -> None:
        self.calls.append("stop")


def test_run_serve_starts_watcher_then_mcp_then_stops(home: Path, workspace: Path) -> None:
    _run("init", str(workspace), "--config-home", str(home))
    config = load_config(home)

    watcher = FakeWatcher()
    mcp_calls: list[str] = []
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run_serve(
            config,
            out=out,
            err=err,
            watcher_factory=lambda: watcher,
            mcp_runner=lambda: mcp_calls.append("mcp"),
        )

    assert code == EXIT_OK
    assert watcher.calls == ["start", "stop"]  # stopped even on normal return
    assert mcp_calls == ["mcp"]
    assert "stdio" in err.getvalue()


def test_run_serve_dry_run_never_touches_stdio(home: Path, workspace: Path) -> None:
    _run("init", str(workspace), "--config-home", str(home))
    config = load_config(home)

    watcher = FakeWatcher()
    mcp_calls: list[str] = []
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run_serve(
            config,
            out=out,
            err=err,
            dry_run=True,
            watcher_factory=lambda: watcher,
            mcp_runner=lambda: mcp_calls.append("mcp"),
        )

    assert code == EXIT_OK
    assert "dry-run" in out.getvalue()
    assert watcher.calls == ["start", "stop"]
    assert mcp_calls == []  # stdio server never started


# ----------------------------------------------------------- 5. uninstall --


def _workspace_snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_uninstall_removes_home_artifacts_and_leaves_workspace_byte_identical(
    home: Path, workspace: Path
) -> None:
    _run("init", str(workspace), "--config-home", str(home))
    # User keeps working after init: new files must survive uninstall too.
    (workspace / "later.txt").write_text("added after init", encoding="utf-8")
    before = _workspace_snapshot(workspace)
    assert (home / "config.json").is_file()

    code, out, err = _run(
        "uninstall", "--purge-config", "--yes", "--config-home", str(home)
    )
    assert code == EXIT_OK, err
    assert "제거 완료" in out
    assert "원본 무영향 확인: atlas-demo" in out

    # Everything generated under the Tavonel home is gone...
    assert not (home / "config.json").exists()
    assert not (home / "workspaces").exists()
    assert not (home / "mcp").exists()
    assert not (home / "runtime").exists()
    assert not (home / "logs" / "ttfw.jsonl").exists()
    assert not (home / "world-state").exists()

    # ...and the original workspace is byte-for-byte identical.
    assert _workspace_snapshot(workspace) == before
    digest_after = hash_tree(workspace)
    assert digest_after[0] != "missing"


def test_uninstall_refuses_to_delete_world_store_inside_workspace(
    home: Path, workspace: Path
) -> None:
    _run("init", str(workspace), "--config-home", str(home))

    # Pathological admin config: world store placed inside the watched root.
    config_path = home / "config.json"
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["world_store_path"] = str(workspace / "world-state")
    (workspace / "world-state").mkdir()
    (workspace / "world-state" / "w-x").mkdir()
    (workspace / "world-state" / "w-x" / "manifest.json").write_text("{}", encoding="utf-8")
    config_path.write_text(json.dumps(raw), encoding="utf-8")

    before = _workspace_snapshot(workspace)
    code, out, err = _run("uninstall", "--purge-config", "--yes", "--config-home", str(home))
    assert code == EXIT_OK, err
    # The store inside the workspace was skipped, not deleted.
    assert "skip" in out
    assert (workspace / "world-state" / "w-x" / "manifest.json").is_file()
    assert _workspace_snapshot(workspace) == before


def test_uninstall_dry_run_deletes_nothing(home: Path, workspace: Path) -> None:
    _run("init", str(workspace), "--config-home", str(home))
    before_home = sorted(p.name for p in home.rglob("*"))

    code, out, _ = _run("uninstall", "--dry-run", "--config-home", str(home))
    assert code == EXIT_OK
    assert "dry-run" in out
    assert sorted(p.name for p in home.rglob("*")) == before_home
