"""``~/.tavonel/config.json`` — the single on-disk home for akc-desktop state.

Layout under the Tavonel home (default ``~/.tavonel``, override with the
``TAVONEL_HOME`` environment variable for tests and portable installs)::

    ~/.tavonel/
      config.json                     # this file: workspaces, world store, mcp
      workspaces/<slug>/watcher.json  # generated per-workspace watcher config
      workspaces/<slug>/health-report.json
      runtime/                        # watcher journal + event sink (serve)
      logs/ttfw.jsonl                 # time-to-first-world milestone log
      mcp/claude-desktop-snippet.json # MCP client registration snippet
      world-state/                    # default world store (published worlds)

The file is JSON only (no YAML dependency), written atomically, and validated
strictly: unknown keys are rejected so typos fail loudly instead of silently
disabling a workspace.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

ENV_TAVONEL_HOME = "TAVONEL_HOME"
CONFIG_FILE_NAME = "config.json"

#: Baseline exclude globs applied to every watched root. Slash-aware
#: gitignore-style patterns as understood by the desktop-watcher matcher.
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    "~$*",  # MS Office lock files
    "*.tmp",
    "~*",  # editor backups
    ".git/**",
    "Thumbs.db",
    ".DS_Store",
)

_UUID36 = re.compile(r"^[0-9a-f-]{36}$")


class ConfigError(ValueError):
    pass


def default_home() -> Path:
    """Resolve the Tavonel home directory (env override > ~/.tavonel)."""
    raw = os.environ.get(ENV_TAVONEL_HOME, "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".tavonel"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_collection_id() -> str:
    return str(uuid.uuid4())


def derive_source_root_id(name: str, path: str) -> str:
    """Deterministic source_root_id so re-init keeps journal continuity."""
    posix = Path(path).expanduser().resolve().as_posix()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tavonel://workspace/{name}/{posix}"))


def slugify(name: str, taken: set[str] | None = None) -> str:
    """Filesystem-safe lowercase slug; suffix -2, -3 ... on collision."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "workspace"
    used = taken or set()
    candidate = slug
    counter = 2
    while candidate in used:
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


@dataclass(frozen=True)
class McpTransport:
    """MCP exposure settings. stdio is the Personal Pro default."""

    transport: str = "stdio"  # "stdio" | "tcp"
    port: int | None = None   # only meaningful for tcp

    def to_dict(self) -> dict[str, object]:
        return {"transport": self.transport, "port": self.port}


@dataclass(frozen=True)
class WorkspaceEntry:
    name: str
    path: str                      # absolute path, native separators
    collection_id: str             # uuid4, stable across restarts
    source_root_id: str            # uuid5 of name+path, journal continuity
    registered_at: str             # ISO-8601 UTC
    exclude_globs: tuple[str, ...] = ()  # extra globs beyond defaults

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "collection_id": self.collection_id,
            "source_root_id": self.source_root_id,
            "registered_at": self.registered_at,
            "exclude_globs": list(self.exclude_globs),
        }


@dataclass(frozen=True)
class DesktopAppConfig:
    """In-memory view of config.json plus derived paths."""

    home: Path
    schema_version: int = SCHEMA_VERSION
    workspaces: tuple[WorkspaceEntry, ...] = ()
    world_store_path: Path | None = None  # None -> <home>/world-state
    mcp: McpTransport = field(default_factory=McpTransport)
    default_exclude_globs: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS

    # -- paths -------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.home / CONFIG_FILE_NAME

    @property
    def runtime_dir(self) -> Path:
        return self.home / "runtime"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def mcp_dir(self) -> Path:
        return self.home / "mcp"

    @property
    def workspaces_meta_dir(self) -> Path:
        return self.home / "workspaces"

    @property
    def world_store(self) -> Path:
        return self.world_store_path if self.world_store_path else self.home / "world-state"

    @property
    def ttfw_log(self) -> Path:
        return self.logs_dir / "ttfw.jsonl"

    def workspace_slug(self, entry: WorkspaceEntry) -> str:
        """Stable per-entry directory name under workspaces_meta_dir.

        Workspace names are unique keys in ``workspaces``, so first-writer
        wins and later collisions get deterministic -2/-3 suffixes.
        """
        taken: set[str] = set()
        for ws in self.workspaces:
            slug = slugify(ws.name, taken)
            taken.add(slug)
            if ws.name == entry.name:
                return slug
        return slugify(entry.name)

    def effective_exclude_globs(self, entry: WorkspaceEntry) -> tuple[str, ...]:
        merged: list[str] = []
        for glob in (*self.default_exclude_globs, *entry.exclude_globs):
            if glob not in merged:
                merged.append(glob)
        return tuple(merged)

    def find_workspace(self, name_or_path: str) -> WorkspaceEntry | None:
        for entry in self.workspaces:
            if entry.name == name_or_path:
                return entry
        try:
            resolved = str(Path(name_or_path).expanduser().resolve())
        except OSError:  # pragma: no cover - resolve rarely fails on Windows
            return None
        for entry in self.workspaces:
            try:
                if str(Path(entry.path).resolve()) == resolved:
                    return entry
            except OSError:  # pragma: no cover
                continue
        return None

    # -- serialization -------------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workspaces": [ws.to_dict() for ws in self.workspaces],
            "world_store_path": str(self.world_store),
            "mcp": self.mcp.to_dict(),
            "default_exclude_globs": list(self.default_exclude_globs),
        }

    @classmethod
    def empty(cls, home: Path | None = None) -> DesktopAppConfig:
        return cls(home=home if home is not None else default_home())

    @classmethod
    def from_dict(cls, data: object, home: Path) -> DesktopAppConfig:
        if not isinstance(data, dict):
            raise ConfigError("config root must be a JSON object")
        allowed = {
            "schema_version",
            "workspaces",
            "world_store_path",
            "mcp",
            "default_exclude_globs",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ConfigError(f"unknown config keys: {unknown}")

        version = data.get("schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ConfigError(
                f"unsupported config schema_version {version!r} (expected {SCHEMA_VERSION})"
            )

        raw_workspaces = data.get("workspaces", [])
        if not isinstance(raw_workspaces, list):
            raise ConfigError("'workspaces' must be a list")
        workspaces = tuple(
            _parse_workspace(item, index) for index, item in enumerate(raw_workspaces)
        )

        raw_store = data.get("world_store_path")
        if raw_store is not None and (not isinstance(raw_store, str) or not raw_store.strip()):
            raise ConfigError("'world_store_path' must be null or a non-empty string")
        store = Path(raw_store).expanduser() if isinstance(raw_store, str) else None

        raw_mcp = data.get("mcp", {})
        if not isinstance(raw_mcp, dict):
            raise ConfigError("'mcp' must be an object")
        unknown_mcp = sorted(set(raw_mcp) - {"transport", "port"})
        if unknown_mcp:
            raise ConfigError(f"unknown 'mcp' keys: {unknown_mcp}")
        transport = raw_mcp.get("transport", "stdio")
        if transport not in {"stdio", "tcp"}:
            raise ConfigError("'mcp.transport' must be 'stdio' or 'tcp'")
        port = raw_mcp.get("port")
        if port is not None and (
            isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
        ):
            raise ConfigError("'mcp.port' must be an integer in [1, 65535]")
        if transport == "stdio" and port is not None:
            raise ConfigError("'mcp.port' is only valid when transport is 'tcp'")

        raw_globs = data.get("default_exclude_globs", list(DEFAULT_EXCLUDE_GLOBS))
        if not isinstance(raw_globs, list) or any(not isinstance(g, str) for g in raw_globs):
            raise ConfigError("'default_exclude_globs' must be a list of strings")

        return cls(
            home=home,
            schema_version=SCHEMA_VERSION,
            workspaces=workspaces,
            world_store_path=store,
            mcp=McpTransport(transport=transport, port=port),
            default_exclude_globs=tuple(raw_globs),
        )


def _parse_workspace(item: object, index: int) -> WorkspaceEntry:
    if not isinstance(item, dict):
        raise ConfigError(f"workspaces[{index}] must be an object")
    allowed = {
        "name",
        "path",
        "collection_id",
        "source_root_id",
        "registered_at",
        "exclude_globs",
    }
    unknown = sorted(set(item) - allowed)
    if unknown:
        raise ConfigError(f"workspaces[{index}] unknown keys: {unknown}")
    for key in ("name", "path", "collection_id", "source_root_id", "registered_at"):
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"workspaces[{index}].{key} must be a non-empty string")
    if not _UUID36.match(str(item["collection_id"])):
        raise ConfigError(f"workspaces[{index}].collection_id must be a lowercase uuid")
    if not _UUID36.match(str(item["source_root_id"])):
        raise ConfigError(f"workspaces[{index}].source_root_id must be a lowercase uuid")
    globs = item.get("exclude_globs", [])
    if not isinstance(globs, list) or any(not isinstance(g, str) for g in globs):
        raise ConfigError(f"workspaces[{index}].exclude_globs must be a list of strings")
    return WorkspaceEntry(
        name=str(item["name"]),
        path=str(item["path"]),
        collection_id=str(item["collection_id"]),
        source_root_id=str(item["source_root_id"]),
        registered_at=str(item["registered_at"]),
        exclude_globs=tuple(globs),
    )


def load_config(home: Path | None = None) -> DesktopAppConfig:
    """Load config.json; a missing file yields an empty default config."""
    resolved_home = home if home is not None else default_home()
    path = resolved_home / CONFIG_FILE_NAME
    if not path.exists():
        return DesktopAppConfig.empty(resolved_home)
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    return DesktopAppConfig.from_dict(data, resolved_home)


def save_config(config: DesktopAppConfig) -> Path:
    """Atomically write config.json (temp file + os.replace)."""
    config.home.mkdir(parents=True, exist_ok=True)
    path = config.config_path
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    return path
