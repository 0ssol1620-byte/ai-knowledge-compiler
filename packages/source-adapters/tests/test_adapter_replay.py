"""Seeded replay harness: 40 random create/edit/delete/rename sequences per adapter, 200 in all.

Every sequence is replayed against the real adapter (Git on a tmp repo, Obsidian on a tmp
vault, GitHub/Drive/Gmail against a local stub server) with the cursor round-tripped through
``Cursor.encoded()``/``decode()`` between polls. At one random round the *same* cursor is used
twice, simulating a crash before the cursor was committed. Asserted per sequence:

* the state folded from delivered events equals the ground truth after every poll;
* every ground-truth change in a round is named by an event of that round;
* a replayed poll repeats the first delivery exactly, as ``(source_id, kind, revision)``
  keys — and no key repeats outside a replay.

Finding for D06: ``ChangeEvent.event_hash`` commits to ``observed_at``, so it is not a replay
dedup key; ``(source_id, kind, revision)`` is (see ``test_event_hash_is_not_a_replay_key``) — except
Obsidian, whose revision is a content hash: a rename repeats the key at a new path, so a
dedup on the key alone would drop it (second finding for D06).
Real providers are not exercised here.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import threading
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from akc_source_adapters import GitAdapter, GitCursorInvalid, ObsidianVaultAdapter
from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult
from akc_source_adapters.github_adapter import GitHubAdapter
from akc_source_adapters.google import DriveAdapter, GmailAdapter, SourceCursorInvalid
from akc_source_adapters.google._common import GoogleAdapterError, StaticTokenProvider

SEEDS = range(40)
PROVIDERS = ("git", "obsidian", "github", "drive", "gmail")
ROUNDS = 5
OPS = ("create", "edit", "delete", "rename")
T0 = datetime(2026, 8, 1, tzinfo=UTC)


def _rng(seed: int) -> random.Random:
    # The repo's S311 ignore covers tests/** only, not packages/*/tests.
    return random.Random(seed)  # noqa: S311


def _stamp(n: int) -> str:
    return (T0 + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key(event: ChangeEvent) -> tuple[str, str, str]:
    return (event.source_id, event.kind, event.revision)


# -- stub server (one per module, models swapped per seed) ------------------------------


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        _, prefix, *rest = parts.path.split("/")
        model = self.server.models[prefix]  # type: ignore[attr-defined]
        code, body = model.handle("/" + "/".join(rest), parse_qs(parts.query))
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture(scope="module")
def server() -> Iterator[ThreadingHTTPServer]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.models = {}  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _base(httpd: ThreadingHTTPServer, prefix: str, model: object) -> str:
    httpd.models[prefix] = model  # type: ignore[attr-defined]
    return f"http://127.0.0.1:{httpd.server_address[1]}/{prefix}"


def _q(query: dict[str, list[str]], name: str, default: str = "") -> str:
    return query.get(name, [default])[0]


# -- models: a ground truth, a mutator, and how to fold the adapter's events ------------


class _Model:
    adapter: Any
    seq = 0

    def next_n(self) -> int:
        self.seq += 1
        return self.seq

    def begin_round(self) -> None:  # hook for per-round constraints
        pass

    def mutate(self, rng: random.Random) -> None:
        raise NotImplementedError

    def truth(self) -> dict[str, object]:
        raise NotImplementedError

    def entities(self, event: ChangeEvent) -> list[str]:
        raise NotImplementedError

    def fold(self, state: dict[str, object], event: ChangeEvent) -> None:
        raise NotImplementedError


def _pick_op(rng: random.Random, have: bool) -> str:
    return rng.choice(OPS) if have else "create"


class _ObsidianModel(_Model):
    def __init__(self, tmp: Path, seed: int) -> None:
        self.root, self.seed = tmp / "vault", seed
        self.root.mkdir()
        self.notes: dict[str, str] = {}
        self.adapter = ObsidianVaultAdapter(self.root, source_id="obsidian:replay")

    def _write(self, rel: str) -> None:
        text = f"# note {rel}\nseed {self.seed} write {self.next_n()}\n"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        self.notes[rel] = hashlib.sha256(text.encode()).hexdigest()

    def mutate(self, rng: random.Random) -> None:
        op = _pick_op(rng, bool(self.notes))
        new = f"{rng.choice(['', 'sub/'])}n{self.next_n()}.md"
        if op == "create":
            self._write(new)
            return
        old = rng.choice(sorted(self.notes))
        if op == "edit":
            self._write(old)
        else:
            if op == "rename":
                self._write(new)
                (self.root / old).replace(self.root / new)  # same bytes at the new path
                self.notes[new] = self.notes[old]
            else:
                (self.root / old).unlink()
            del self.notes[old]

    def truth(self) -> dict[str, object]:
        return dict(self.notes)

    def entities(self, event: ChangeEvent) -> list[str]:
        return [str(event.payload["path"])]

    def fold(self, state: dict[str, object], event: ChangeEvent) -> None:
        path = str(event.payload["path"])
        if event.kind == "note_deleted":
            state.pop(path, None)
        else:
            state[path] = event.revision.removeprefix("sha256:")


class _GitModel(_Model):
    """A scratch repo of loose commit objects: every ``git`` write here costs 0.3-1.2 s.

    The Git adapter reads commit metadata only, so each op is a commit on the empty tree whose
    subject names the op; file contents would add writes and no coverage.
    """

    def __init__(self, tmp: Path, seed: int) -> None:
        self.root, self.seed = tmp / "repo", seed
        self.head = ""
        self.init_repo()
        self.adapter = GitAdapter(self.root, source_id="git:replay")

    def init_repo(self) -> None:
        git_dir = self.root / ".git"
        (git_dir / "objects").mkdir(parents=True)
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        cfg = "[core]\n\trepositoryformatversion = 0\n"
        (git_dir / "config").write_text(cfg, encoding="utf-8")
        self.head = ""
        self.empty_tree = self._object("tree", b"")

    def git(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed executable, read-only queries
            ["git", "-C", str(self.root), *args],  # noqa: S607
            capture_output=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr.decode(errors="replace")
        return done.stdout.decode()

    def _object(self, kind: str, body: bytes) -> str:
        raw = f"{kind} {len(body)}".encode() + b"\0" + body
        sha = hashlib.sha1(raw).hexdigest()  # noqa: S324 - git object ids are sha1
        target = self.root / ".git" / "objects" / sha[:2] / sha[2:]
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(zlib.compress(raw))
        return sha

    def commit(self, subject: str) -> None:
        who = f"R <r@example.com> {1_785_000_000 + self.next_n()} +0000"
        parent = f"parent {self.head}\n" if self.head else ""
        body = f"tree {self.empty_tree}\n{parent}author {who}\ncommitter {who}\n\n{subject}\n"
        self.head = self._object("commit", body.encode())
        ref = self.root / ".git" / "refs" / "heads" / "main"
        ref.write_text(self.head + "\n", encoding="utf-8")

    def mutate(self, rng: random.Random) -> None:
        self.commit(f"{rng.choice(OPS)} {self.seed}/{self.next_n()}")

    def truth(self) -> dict[str, object]:
        out = self.git("log", "--format=%H%x1f%s")
        return dict(line.split("\x1f") for line in out.splitlines())

    def entities(self, event: ChangeEvent) -> list[str]:
        return [event.revision]

    def fold(self, state: dict[str, object], event: ChangeEvent) -> None:
        state[event.revision] = event.payload["subject"]


class _GitHubModel(_Model):
    def __init__(self, httpd: ThreadingHTTPServer) -> None:
        self.commits: list[dict[str, Any]] = []  # oldest first
        self.files: dict[str, str] = {}
        self.adapter = GitHubAdapter(
            "octo/docs", source_id="github:replay", api_base=_base(httpd, "github", self)
        )

    def _commit(self, *changes: tuple[str, str]) -> None:
        n = self.next_n()
        sha = hashlib.sha1(f"commit-{n}".encode()).hexdigest()  # noqa: S324 - fake sha
        self.commits.append({"sha": sha, "at": _stamp(n * 60), "files": list(changes)})
        for path, status in changes:
            if status == "removed":
                del self.files[path]
            else:
                self.files[path] = sha

    def mutate(self, rng: random.Random) -> None:
        op = _pick_op(rng, bool(self.files))
        new = f"docs/p{self.next_n()}.md"
        if op == "create":
            self._commit((new, "added"))
            return
        old = rng.choice(sorted(self.files))
        if op == "edit":
            self._commit((old, "modified"))
        elif op == "delete":
            self._commit((old, "removed"))
        else:
            self._commit((old, "removed"), (new, "added"))

    def truth(self) -> dict[str, object]:
        return dict(self.files)

    def entities(self, event: ChangeEvent) -> list[str]:
        if event.kind == "file_deleted":
            return [str(event.payload["path"])]
        p = event.payload
        return [*p["files_added"], *p["files_modified"], *p["files_removed"]]  # type: ignore[misc]

    def fold(self, state: dict[str, object], event: ChangeEvent) -> None:
        if event.kind == "file_deleted":
            state.pop(str(event.payload["path"]), None)
            return
        p = event.payload
        for path in (*p["files_added"], *p["files_modified"]):  # type: ignore[misc]
            state[path] = event.revision
        for path in p["files_removed"]:  # type: ignore[misc]
            state.pop(path, None)

    def handle(self, path: str, query: dict[str, list[str]]) -> tuple[int, Any]:
        if path.endswith("/commits"):
            since = _q(query, "since")
            newest_first = [c for c in reversed(self.commits) if not since or c["at"] >= since]
            return 200, [
                {
                    "sha": c["sha"],
                    "commit": {
                        "author": {"name": "R", "email": "r@example.com"},
                        "committer": {"date": c["at"]},
                        "message": f"commit {c['sha'][:7]}",
                    },
                }
                for c in newest_first
            ]
        sha = path.rsplit("/", 1)[1]
        for c in self.commits:
            if c["sha"] == sha:
                return 200, {"files": [{"filename": f, "status": s} for f, s in c["files"]]}
        return 404, {"message": "Not Found"}


class _DriveModel(_Model):
    # 2, not 3: a window holds 1-3 records, so only PAGE < 3 makes nextPageToken ever occur.
    PAGE = 2

    def __init__(self, httpd: ThreadingHTTPServer) -> None:
        self.files: dict[str, tuple[str, str]] = {}  # fileId -> (name, modifiedTime)
        self.log: list[dict[str, Any]] = []
        self.adapter = DriveAdapter(
            source_name="replay",
            token_provider=StaticTokenProvider("t"),
            api_base=_base(httpd, "drive", self),
            page_size=self.PAGE,
        )

    def _put(self, file_id: str, name: str) -> None:
        stamp = _stamp(self.next_n())
        self.files[file_id] = (name, stamp)
        meta = {"name": name, "mimeType": "text/markdown", "modifiedTime": stamp}
        self.log.append({"fileId": file_id, "removed": False, "file": meta})

    def mutate(self, rng: random.Random) -> None:
        op = _pick_op(rng, bool(self.files))
        name = rng.choice(["a.md", "b.md", "c.md"])  # collisions across fileIds are the point
        if op == "create":
            self._put(f"f{self.next_n()}", name)
            return
        file_id = rng.choice(sorted(self.files))
        if op == "edit":
            self._put(file_id, self.files[file_id][0])
        elif op == "rename":
            self._put(file_id, f"renamed-{self.next_n()}.md")
        else:
            del self.files[file_id]
            self.log.append({"fileId": file_id, "removed": True})

    def truth(self) -> dict[str, object]:
        return dict(self.files)

    def entities(self, event: ChangeEvent) -> list[str]:
        return [event.revision.split("@")[0]]

    def fold(self, state: dict[str, object], event: ChangeEvent) -> None:
        file_id = event.revision.split("@")[0]
        if event.kind == "file_removed":
            state.pop(file_id, None)
        else:
            state[file_id] = (event.payload["path"], event.payload["modifiedTime"])

    def handle(self, path: str, query: dict[str, list[str]]) -> tuple[int, Any]:
        start = int(_q(query, "pageToken", "0"))
        end = start + int(_q(query, "pageSize", "100"))
        body: dict[str, Any] = {"changes": self.log[start:end]}
        body["nextPageToken" if end < len(self.log) else "newStartPageToken"] = str(
            end if end < len(self.log) else len(self.log)
        )
        return 200, body


class _GmailModel(_Model):
    # 2, not 3: a round yields 1-3 history records, so only PAGE < 3 ever emits nextPageToken.
    PAGE = 2

    def __init__(self, httpd: ThreadingHTTPServer) -> None:
        self.messages: dict[str, set[str]] = {}
        self.history: list[tuple[int, dict[str, Any]]] = []
        self.hid = 1  # the mailbox is empty when the adapter takes its baseline
        self.touched: set[str] = set()
        self.adapter = GmailAdapter(
            source_name="replay",
            token_provider=StaticTokenProvider("t"),
            api_base=_base(httpd, "gmail", self),
            page_size=self.PAGE,
        )

    def begin_round(self) -> None:
        self.touched.clear()

    def _record(self, **record: Any) -> None:
        self.hid += 1
        self.history.append((self.hid, record))

    def _ref(self, mid: str) -> list[dict[str, Any]]:
        return [{"message": {"id": mid}}]

    def mutate(self, rng: random.Random) -> None:
        # ponytail: the adapter cannot survive a message that is deleted in the same poll
        # window as another event on it (pinned by the xfail test below), so touched ids stay.
        deletable = sorted(set(self.messages) - self.touched)
        op = _pick_op(rng, bool(self.messages))
        if op == "delete" and not deletable:
            op = "create"
        if op == "create":
            mid = f"m{self.next_n()}"
            self.messages[mid] = {"INBOX"}
            self._record(messagesAdded=self._ref(mid))
            self.touched.add(mid)
        elif op == "delete":
            mid = rng.choice(deletable)
            del self.messages[mid]
            self._record(messagesDeleted=self._ref(mid))
        else:
            mid = rng.choice(sorted(self.messages))
            self.messages[mid] ^= {"STARRED" if op == "edit" else "INBOX"}  # rename = archive
            self._record(labelsChanged=self._ref(mid))
            self.touched.add(mid)

    def truth(self) -> dict[str, object]:
        return {mid: tuple(sorted(labels)) for mid, labels in self.messages.items()}

    def entities(self, event: ChangeEvent) -> list[str]:
        return [str(event.payload["message_id"])]

    def fold(self, state: dict[str, object], event: ChangeEvent) -> None:
        mid = str(event.payload["message_id"])
        if event.kind == "message_removed":
            state.pop(mid, None)
        else:
            state[mid] = tuple(sorted(event.payload["labels"]))  # type: ignore[call-overload]

    def handle(self, path: str, query: dict[str, list[str]]) -> tuple[int, Any]:
        if path == "/profile":
            return 200, {"historyId": str(self.hid)}
        if path == "/history":
            after = [r for h, r in self.history if h > int(_q(query, "startHistoryId"))]
            start = int(_q(query, "pageToken", "0"))
            end = start + int(_q(query, "maxResults", "100"))
            body: dict[str, Any] = {"historyId": str(self.hid)}
            if after[start:end]:
                body["history"] = after[start:end]
            if end < len(after):
                body["nextPageToken"] = str(end)
            return 200, body
        mid = path.rsplit("/", 1)[1]
        if mid not in self.messages:
            return 404, {"error": "not found"}
        labels = sorted(self.messages[mid])
        return 200, {"id": mid, "labelIds": labels, "payload": {"headers": []}}


def _make(provider: str, seed: int, tmp: Path, httpd: ThreadingHTTPServer) -> _Model:
    factories: dict[str, Callable[[], _Model]] = {
        "git": lambda: _GitModel(tmp, seed),
        "obsidian": lambda: _ObsidianModel(tmp, seed),
        "github": lambda: _GitHubModel(httpd),
        "drive": lambda: _DriveModel(httpd),
        "gmail": lambda: _GmailModel(httpd),
    }
    return factories[provider]()


# -- the replay -----------------------------------------------------------------------


def _roundtrip(cursor: Cursor) -> Cursor:
    return Cursor.decode(cursor.encoded())


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_seeded_sequence_replays_without_loss_or_phantom_duplicates(
    provider: str, seed: int, tmp_path: Path, server: ThreadingHTTPServer
) -> None:
    rng = _rng(seed)
    model = _make(provider, seed, tmp_path, server)
    if provider != "gmail":  # gmail's baseline poll deliberately emits nothing: start empty
        for _ in range(2):
            model.mutate(rng)

    state: dict[str, object] = {}
    delivered: list[tuple[tuple[str, str, str], tuple[str, ...]]] = []
    first = model.adapter.fetch_changes(None)
    for event in first.events:
        model.fold(state, event)
    delivered += [(_key(e), tuple(model.entities(e))) for e in first.events]
    cursor = _roundtrip(first.cursor)
    assert state == model.truth()

    replay_round = rng.randrange(ROUNDS)
    for round_no in range(ROUNDS):
        before = model.truth()
        model.begin_round()
        for _ in range(rng.randint(1, 3)):
            model.mutate(rng)
        after = model.truth()

        result: FetchResult = model.adapter.fetch_changes(cursor)
        committed = result
        if round_no == replay_round:  # crash before the cursor was stored: same cursor again
            again = model.adapter.fetch_changes(_roundtrip(cursor))
            assert [_key(e) for e in again.events] == [_key(e) for e in result.events]
            committed = again if rng.random() < 0.5 else result

        for event in result.events:
            model.fold(state, event)
        delivered += [(_key(e), tuple(model.entities(e))) for e in result.events]
        changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
        named = {entity for e in result.events for entity in model.entities(e)}
        assert changed <= named, f"{provider} seed {seed} round {round_no} lost {changed - named}"
        assert state == after, f"{provider} seed {seed} round {round_no} diverged"
        cursor = _roundtrip(committed.cursor)

    # Keys alone collide legitimately for Obsidian: its revision is the content hash, so a
    # rename yields the same (source_id, kind, revision) at a new path. Entity disambiguates.
    assert len(delivered) == len(set(delivered)), "a delivery repeated outside a replay"


# -- failure paths --------------------------------------------------------------------


def test_rewritten_git_history_raises_cursor_invalid_never_restarts(tmp_path: Path) -> None:
    model = _GitModel(tmp_path, seed=0)
    model.mutate(_rng(0))
    cursor = model.adapter.fetch_changes(None).cursor
    assert cursor.state["head"]

    shutil.rmtree(model.root)  # the history is replaced wholesale, as after a force-push
    model.root.mkdir()
    model.init_repo()
    model.commit("rewritten root")

    with pytest.raises(GitCursorInvalid):
        model.adapter.fetch_changes(_roundtrip(cursor))


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason="GitAdapter keeps going from '<old>..HEAD' when the old object survives a reset; "
    "proposed delta: check 'git merge-base --is-ancestor <cursor sha> HEAD' and raise",
)
def test_reset_rewrite_with_surviving_object_raises_cursor_invalid(tmp_path: Path) -> None:
    model = _GitModel(tmp_path, seed=0)
    model.commit("create 0/1")
    model.commit("create 0/2")  # B: the cursor lands here
    cursor = model.adapter.fetch_changes(None).cursor

    model.head = model.git("rev-parse", "HEAD~1").strip()  # reset --hard HEAD~1
    (model.root / ".git" / "refs" / "heads" / "main").write_text(
        model.head + chr(10), encoding="utf-8"
    )
    model.commit("create 0/3")  # C replaces B; B's object is still in the store

    with pytest.raises(GitCursorInvalid):
        model.adapter.fetch_changes(_roundtrip(cursor))


@pytest.mark.xfail(
    strict=True,
    raises=GoogleAdapterError,
    reason="GmailAdapter GETs a message that was added and deleted in one history window, "
    "gets 404 and stalls the cursor forever; see proposed_deltas for gmail.py",
)
def test_gmail_add_then_delete_in_one_window_does_not_stall(server: ThreadingHTTPServer) -> None:
    model = _GmailModel(server)
    cursor = _roundtrip(model.adapter.fetch_changes(None).cursor)
    model._record(messagesAdded=model._ref("m1"))
    model._record(messagesDeleted=model._ref("m1"))  # m1 never existed in the store at poll time

    result = model.adapter.fetch_changes(cursor)  # must not raise
    assert {e.kind for e in result.events} <= {"message_removed"}


def test_legacy_drive_cursor_raises_cursor_invalid_before_any_request(
    server: ThreadingHTTPServer,
) -> None:
    model = _DriveModel(server)
    model.mutate(_rng(0))
    legacy = Cursor(
        provider="gdrive",
        source_id=model.adapter.source_id,
        state={"delta_token": "0", "files": {"a.md": "f1@2026-08-01T00:00:00Z"}},
    )
    with pytest.raises(SourceCursorInvalid):
        model.adapter.fetch_changes(_roundtrip(legacy))


def test_event_hash_is_not_a_replay_key(tmp_path: Path) -> None:
    ticks = iter(range(10))
    model = _ObsidianModel(tmp_path, seed=0)
    model.mutate(_rng(0))
    model.adapter = ObsidianVaultAdapter(
        model.root, source_id="obsidian:replay", clock=lambda: T0 + timedelta(seconds=next(ticks))
    )
    one = model.adapter.fetch_changes(None).events
    two = model.adapter.fetch_changes(None).events  # the same (absent) cursor, replayed
    assert [_key(e) for e in one] == [_key(e) for e in two]
    assert [e.event_hash for e in one] != [e.event_hash for e in two]


def test_the_harness_runs_two_hundred_cases() -> None:
    assert len(SEEDS) * len(PROVIDERS) == 200
