"""``uninstall`` — remove ONLY artifacts this CLI generated.

Everything ``akc-desktop`` writes lives under the Tavonel home directory;
user workspaces are only ever *read*. Uninstall therefore deletes a computed
allow-list of paths under ``<home>`` and then proves the registered
workspaces were untouched by hashing their trees before/after.

Safety rules enforced here:

1. Every candidate path must resolve strictly inside the Tavonel home.
2. No candidate may resolve inside any registered workspace root (guards
   against pathological configs such as a world store placed under a
   watched folder).
3. The world store is removed only when it lives inside the home directory;
   otherwise it is reported as "left in place".
4. After deletion, every workspace tree hash must equal its pre-delete hash,
   or uninstall reports failure with a non-zero exit code.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import DesktopAppConfig

__all__ = ["UninstallPlan", "UninstallResult", "plan_uninstall", "execute_uninstall"]


class UninstallSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class UninstallPlan:
    files: tuple[Path, ...]
    directories: tuple[Path, ...]
    config_file: Path | None
    outside_home: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.files and not self.directories and self.config_file is None


@dataclass
class UninstallResult:
    removed_files: int = 0
    removed_directories: int = 0
    kept_outside_home: tuple[str, ...] = field(default_factory=tuple)
    workspaces_verified: list[str] = field(default_factory=list)


def hash_tree(root: Path) -> tuple[str, int]:
    """Order-independent digest of every regular file under root."""
    digest = hashlib.sha256()
    count = 0
    if not root.exists():
        return ("missing", 0)
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        count += 1
    return (digest.hexdigest(), count)


def plan_uninstall(config: DesktopAppConfig, *, purge_config: bool) -> UninstallPlan:
    home = config.home.resolve()
    if not home.exists():
        return UninstallPlan(files=(), directories=(), config_file=None, outside_home=())

    workspace_roots: list[Path] = []
    for ws in config.workspaces:
        try:
            workspace_roots.append(Path(ws.path).expanduser().resolve())
        except OSError:  # pragma: no cover - defensive
            continue

    candidates: list[Path] = [
        config.workspaces_meta_dir,
        config.runtime_dir,
        config.logs_dir / "ttfw.jsonl",
        config.mcp_dir,
    ]
    store = config.world_store.resolve() if config.world_store.exists() else None
    if store is not None:
        candidates.append(store)

    files: list[Path] = []
    directories: list[Path] = []
    outside: list[str] = []

    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.exists():
            continue
        if not _is_within(resolved, home):
            outside.append(str(resolved))
            continue
        if any(_is_within(resolved, ws_root) for ws_root in workspace_roots):
            # Rule 2: never delete anything that resolves inside a user
            # workspace, even if a bad config put an artifact dir there.
            outside.append(str(resolved))
            continue
        if resolved.is_dir():
            directories.append(resolved)
        else:
            files.append(resolved)

    config_file: Path | None = None
    if purge_config and config.config_path.exists():
        config_file = config.config_path.resolve()

    # Deeper dirs first so shutil.rmtree order does not matter for reporting.
    directories.sort(key=lambda p: len(p.parts), reverse=True)
    return UninstallPlan(
        files=tuple(files),
        directories=tuple(directories),
        config_file=config_file,
        outside_home=tuple(outside),
    )


def execute_uninstall(config: DesktopAppConfig, plan: UninstallPlan) -> UninstallResult:
    before: dict[Path, tuple[str, int]] = {}
    result = UninstallResult(kept_outside_home=plan.outside_home)

    for ws in config.workspaces:
        root = Path(ws.path).expanduser().resolve()
        before[root] = hash_tree(root)

    for path in plan.files:
        os.remove(path)
        result.removed_files += 1

    for directory in plan.directories:
        shutil.rmtree(directory)
        result.removed_directories += 1

    if plan.config_file is not None and plan.config_file.exists():
        os.remove(plan.config_file)
        result.removed_files += 1

    # Try to prune now-empty generated directories directly under home,
    # but never remove home itself nor anything with remaining content.
    for child in sorted(config.home.iterdir()) if config.home.exists() else []:
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()

    for ws in config.workspaces:
        root = Path(ws.path).expanduser().resolve()
        after = hash_tree(root)
        if after != before[root]:
            raise UninstallSafetyError(
                f"workspace tree changed during uninstall: {root} "
                f"(before {before[root][0][:12]}, after {after[0][:12]})"
            )
        result.workspaces_verified.append(ws.name)
    return result


def _is_within(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
    except ValueError:
        return False
    return True
