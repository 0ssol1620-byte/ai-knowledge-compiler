"""Watch what a builder consumes while it runs — not what it admits to.

§29.2 Consumption completeness. A receipt lists the inputs someone remembered
to declare; this context manager stands next to the builder and records what
it actually did: which files it opened for reading (hashed at capture time),
which environment variables it consulted (names only — values are secrets and
are never captured), whether the clock or the dice were asked, and which
modules got imported mid-build. Afterward the observation stamps onto a
:class:`~akc_cir.build_receipt.BuildReceipt`, so the seal covers the whole
consumption story instead of only the declared part of it.

How it watches, without slowing the build down:

``builtins.open`` AND ``io.open`` are wrapped for the duration of the block.
They are different entry points — ``io.open`` is a pure-Python function that
drives ``_io.FileIO`` directly, and pathlib's read_text/read_bytes go through
it — so both pass through the same recording chokepoint. Hashing reopens
through the *original* builtins open, which cannot recurse back into either
wrapper.
``os.environ`` is swapped for a delegating mapping whose ``__getitem__``
records key names. ``os.getenv``, ``.get``, ``in``, ``items()`` all route
through it, so per-key attribution holds; wholesale iteration or ``copy()``
is recorded once as :data:`ENV_ACCESS_ALL`, because once everything is copied
out, per-key attribution is a fiction.
The usual nondeterminism sources (``time.*``, ``random.*``,
``datetime.datetime.now/utcnow/today``, ``uuid.uuid4``) are wrapped with
counting pass-throughs.
A ``sys.meta_path`` finder records modules imported during the build.
``sys.settrace`` can watch every call in the process, but it taxes every
function call the interpreter makes, so deep tracing is opt-in only
(``use_settrace=True``); its sample lands on ``trace_sample`` as diagnostics,
not in the receipt.

Blind spots, stated plainly: C extensions that open files or read the
environment below the Python layer are invisible to the wrappers; code that
bound ``from os import environ`` before the block keeps the real mapping;
threads are observed only through the same process-wide wrappers. This is a
net under a build that runs on this machine, not a sandbox boundary.

Usage::

    with TrackedBuildContext() as tracked:
        artifact = builder(declared)
    receipt = tracked.observation().attach_to(draft_receipt).seal()

or, for the common shape::

    result, receipt = tracked_build("my-builder", builder_run)
"""

from __future__ import annotations

import builtins
import contextlib
import functools
import io
import os
import random
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from importlib.machinery import ModuleSpec
from types import ModuleType, TracebackType
from typing import Any, Literal

from .base import sha256_digest
from .build_receipt import (
    BuildReceipt,
    DeclaredInput,
    HiddenInputs,
    NonDeterminism,
    NonDeterminismSource,
    ObservedFile,
)

__all__ = [
    "ENV_ACCESS_ALL",
    "BuildObservation",
    "TrackedBuildContext",
    "tracked_build",
]

#: Recorded once when a builder iterates or copies os.environ wholesale: the
#: whole environment was consumed, so no honest per-key list exists.
ENV_ACCESS_ALL = "<all-env-keys>"

_MAX_TRACE_ENTRIES = 2048

_TIME_SOURCES = (
    "time",
    "time_ns",
    "monotonic",
    "monotonic_ns",
    "perf_counter",
    "perf_counter_ns",
)
_RANDOM_SOURCES = (
    "random",
    "randint",
    "randrange",
    "uniform",
    "choice",
    "choices",
    "shuffle",
    "sample",
)


def _is_read_mode(mode: str) -> bool:
    """True when an open() mode can read ('r', '', 'rb', 'r+', 'w+', ...)."""
    return "r" in mode or "+" in mode


class _TrackedEnviron(MutableMapping[str, str]):
    """Delegating stand-in for ``os.environ`` that records key names read."""

    def __init__(
        self, real: MutableMapping[str, str], sink: Callable[[str], None]
    ) -> None:
        self._real = real
        self._sink = sink

    def __getitem__(self, key: str) -> str:
        self._sink(key)
        return self._real[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._real[key] = value

    def __delitem__(self, key: str) -> None:
        del self._real[key]

    def __iter__(self) -> Iterator[str]:
        self._sink(ENV_ACCESS_ALL)
        return iter(self._real)

    def __len__(self) -> int:
        return len(self._real)

    def copy(self) -> dict[str, str]:
        self._sink(ENV_ACCESS_ALL)
        return dict(self._real)

    def __repr__(self) -> str:
        return repr(self._real)


class _ImportRecorder:
    """meta_path finder that notes top-level module names being imported.

    It always returns ``None``, deferring every import to the rest of the
    path machinery; its entire job is witnessing the request.
    """

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink
        self.active = False

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if self.active:
            self._sink(fullname.split(".", 1)[0])
        return None


class _TracedDateTime(datetime):
    """datetime.datetime subclass counting now/utcnow/today consultations.

    Subclassing (rather than proxying) keeps ``isinstance`` checks and every
    other datetime consumer working unchanged while the swap is in place.
    The bodies call the ORIGINAL class object directly: this module's
    ``datetime`` binding still points at it even while the datetime module's
    attribute has been swapped, so no re-entrant counting occurs.
    """

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        _TRACKED_DATETIME_SINK("datetime.datetime.now")
        return datetime.now(tz)

    @classmethod
    def utcnow(cls) -> datetime:  # type: ignore[override]
        _TRACKED_DATETIME_SINK("datetime.datetime.utcnow")
        return datetime.utcnow()

    @classmethod
    def today(cls) -> datetime:  # type: ignore[override]
        _TRACKED_DATETIME_SINK("datetime.datetime.today")
        return datetime.today()


def _noop_sink(name: str) -> None:
    """Default sink before a tracked region installs the real one."""


_TRACKED_DATETIME_SINK: Callable[[str], None] = _noop_sink


@dataclass(frozen=True)
class BuildObservation:
    """What one tracked build actually consumed, deduplicated and sorted.

    Sorted so two identical builds of the same builder produce byte-identical
    observations — a receipt section that jitters run to run would itself be
    nondeterminism smuggled into an anti-nondeterminism ledger.
    """

    files: tuple[ObservedFile, ...] = ()
    env_keys: tuple[str, ...] = ()
    imported_modules: tuple[str, ...] = ()
    sources: tuple[NonDeterminismSource, ...] = ()

    @property
    def clean(self) -> bool:
        """True when nothing was consumed beyond what was declared."""
        return not (self.files or self.env_keys or self.imported_modules or self.sources)

    def hidden_inputs(self) -> HiddenInputs:
        return HiddenInputs(
            files=self.files,
            env_keys=tuple(self.env_keys),
            imported_modules=self.imported_modules,
        )

    def non_determinism(self) -> NonDeterminism:
        return NonDeterminism(sources=self.sources)

    def attach_to(self, receipt: BuildReceipt) -> BuildReceipt:
        """Stamp this observation onto a receipt, minus already-declared files."""
        declared_paths = {os.path.abspath(item.path) for item in receipt.declared_inputs}
        undeclared = tuple(
            item for item in self.files if os.path.abspath(item.path) not in declared_paths
        )
        return receipt.model_copy(
            update={
                "hidden_inputs": HiddenInputs(
                    files=undeclared,
                    env_keys=self.env_keys,
                    imported_modules=self.imported_modules,
                ),
                "non_determinism": self.non_determinism(),
            }
        )


class TrackedBuildContext:
    """Context manager that observes a build's consumption as it happens.

    All trackers default on; each can be declined by flag. ``use_settrace``
    defaults off on purpose — it instruments every function call in the
    process and is reserved for audits that have accepted the tax.
    """

    def __init__(
        self,
        *,
        track_files: bool = True,
        track_env: bool = True,
        track_nondeterminism: bool = True,
        track_imports: bool = True,
        use_settrace: bool = False,
    ) -> None:
        self._track_files = track_files
        self._track_env = track_env
        self._track_nondeterminism = track_nondeterminism
        self._track_imports = track_imports
        self._use_settrace = use_settrace

        self._lock = threading.Lock()
        self._active = False
        self._files: dict[str, ObservedFile] = {}
        self._env_keys: set[str] = set()
        self._modules: set[str] = set()
        self._source_calls: dict[str, int] = {}
        self._trace_sample: dict[str, None] = {}

        self._original_open: Callable[..., Any] = builtins.open
        self._restores: list[tuple[Any, str, Any]] = []
        self._import_recorder: _ImportRecorder | None = None
        self._previous_trace: Callable[..., Any] | None = None

    # -- public surface ----------------------------------------------------

    def observation(self) -> BuildObservation:
        """Snapshot of everything recorded so far, sorted and deduplicated."""
        with self._lock:
            files = tuple(sorted(self._files.values(), key=lambda item: item.path))
            env_keys = tuple(sorted(self._env_keys))
            modules = tuple(sorted(self._modules))
            sources = tuple(
                sorted(
                    (
                        NonDeterminismSource(source=name, calls=calls)
                        for name, calls in self._source_calls.items()
                    ),
                    key=lambda item: item.source,
                )
            )
        return BuildObservation(
            files=files,
            env_keys=env_keys,
            imported_modules=modules,
            sources=sources,
        )

    @property
    def trace_sample(self) -> tuple[str, ...]:
        """Distinct call sites seen while ``use_settrace`` was on (capped)."""
        return tuple(sorted(self._trace_sample))

    # -- context management --------------------------------------------------

    def __enter__(self) -> TrackedBuildContext:
        if self._active:
            raise RuntimeError("TrackedBuildContext is already active")
        self._active = True
        try:
            if self._track_files:
                self._install_open_tracker()
            if self._track_env:
                self._install_env_tracker()
            if self._track_nondeterminism:
                self._install_nondeterminism_trackers()
            if self._track_imports:
                self._install_import_recorder()
            if self._use_settrace:
                self._install_tracer()
        except BaseException:
            self._uninstall()
            self._active = False
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self._uninstall()
        self._active = False
        return False  # never swallow a failing build

    # -- install / uninstall ---------------------------------------------------

    def _record_restore(self, namespace: Any, attr: str, original: Any) -> None:
        self._restores.append((namespace, attr, original))

    def _install_open_tracker(self) -> None:
        original = builtins.open

        def tracked_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            fobj = original(file, mode, *args, **kwargs)
            self._record_file_open(fobj, mode)
            return fobj

        functools.update_wrapper(tracked_open, original)
        builtins.open = tracked_open
        self._record_restore(builtins, "open", original)
        self._original_open = original

        # io.open is NOT builtins.open under another name: it is a separate
        # pure-Python function that drives _io.FileIO directly, and pathlib's
        # read_text/read_bytes go through it. Wrapping only builtins.open
        # would leave every pathlib read invisible.
        original_io_open = io.open

        def tracked_io_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            fobj = original_io_open(file, mode, *args, **kwargs)
            self._record_file_open(fobj, mode)
            return fobj

        functools.update_wrapper(tracked_io_open, original_io_open)
        io.open = tracked_io_open
        self._record_restore(io, "open", original_io_open)

    def _record_file_open(self, fobj: Any, mode: str) -> None:
        if not _is_read_mode(mode):
            return  # writes are production side effects, not consumption
        name = getattr(fobj, "name", None)
        if not isinstance(name, (str, os.PathLike)):
            return
        abspath = os.path.abspath(os.fspath(name))
        with self._lock:
            if abspath in self._files:
                return
        digest: str | None
        try:
            # Reopen through the ORIGINAL open: no recursion into our own
            # wrapper, so hashing cannot pollute the record it feeds.
            with self._original_open(abspath, "rb") as raw:
                digest = sha256_digest(raw.read())
        except OSError:
            digest = None
        with self._lock:
            self._files.setdefault(
                abspath, ObservedFile(path=abspath, sha256=digest)
            )

    def _install_env_tracker(self) -> None:
        real = os.environ

        def sink(key: str) -> None:
            with self._lock:
                self._env_keys.add(key)

        # setattr, not assignment: `os.environ = ...` is ruff B003 territory
        # (it cannot tell a swap-with-restore from clearing the environment).
        setattr(os, "environ", _TrackedEnviron(real, sink))  # noqa: B010
        self._record_restore(os, "environ", real)

    def _install_nondeterminism_trackers(self) -> None:
        def sink(name: str) -> None:
            with self._lock:
                self._source_calls[name] = self._source_calls.get(name, 0) + 1

        def wrap(module: ModuleType, attr: str) -> None:
            original = getattr(module, attr)

            def counter(*args: Any, **kwargs: Any) -> Any:
                sink(f"{module.__name__}.{attr}")
                return original(*args, **kwargs)

            functools.update_wrapper(counter, original)
            setattr(module, attr, counter)
            self._record_restore(module, attr, original)

        for source in _TIME_SOURCES:
            wrap(time, source)
        for source in _RANDOM_SOURCES:
            wrap(random, source)
        wrap(uuid, "uuid4")

        global _TRACKED_DATETIME_SINK
        _TRACKED_DATETIME_SINK = sink
        import datetime as datetime_module

        datetime_module.datetime = _TracedDateTime  # type: ignore[misc]
        self._record_restore(datetime_module, "datetime", datetime_module.datetime)

    def _install_import_recorder(self) -> None:
        recorder = _ImportRecorder(self._record_module)
        recorder.active = True
        sys.meta_path.insert(0, recorder)
        self._import_recorder = recorder

    def _record_module(self, top_level_name: str) -> None:
        with self._lock:
            self._modules.add(top_level_name)

    def _install_tracer(self) -> None:

        def tracer(frame: Any, event: str, arg: Any) -> Any:
            if event == "call" and len(self._trace_sample) < _MAX_TRACE_ENTRIES:
                code = frame.f_code
                key = f"{code.co_filename}:{code.co_firstlineno} {code.co_name}"
                # No lock here on purpose: the tracer fires from inside
                # _record_file_open's own hash read, which already holds the
                # lock — acquiring it again would deadlock the build. Dict
                # operations are GIL-atomic, so the cap races at worst.
                self._trace_sample.setdefault(key)
            return tracer

        self._previous_trace = sys.gettrace()
        sys.settrace(tracer)

    def _uninstall(self) -> None:
        if self._use_settrace:
            sys.settrace(self._previous_trace)
            self._previous_trace = None
        if self._import_recorder is not None:
            with contextlib.suppress(ValueError):  # already tidied by a nesting peer
                sys.meta_path.remove(self._import_recorder)
            self._import_recorder.active = False
            self._import_recorder = None
        global _TRACKED_DATETIME_SINK
        _TRACKED_DATETIME_SINK = _noop_sink
        for namespace, attr, original in reversed(self._restores):
            setattr(namespace, attr, original)
        self._restores.clear()


def tracked_build[T](
    builder_id: str,
    build: Callable[[], T],
    *,
    declared_inputs: Iterable[DeclaredInput] = (),
    created_at: datetime | None = None,
    output_sha256: str | None = None,
    **context_options: Any,
) -> tuple[T, BuildReceipt]:
    """Run ``build()`` under tracking and return ``(result, sealed receipt)``.

    The hidden-input sections are stamped on *before* sealing, so the seal's
    digest covers them. If ``build()`` raises, the exception propagates and
    no receipt exists — a failed build does not get to look finished.
    """
    declared = tuple(declared_inputs)
    with TrackedBuildContext(**context_options) as tracked:
        result = build()
    draft = BuildReceipt(
        builder_id=builder_id,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        declared_inputs=declared,
        output_sha256=output_sha256,
    )
    receipt = tracked.observation().attach_to(draft)
    return result, receipt.seal()
