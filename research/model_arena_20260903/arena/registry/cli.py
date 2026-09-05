"""`python -m arena.registry resolve|validate`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from arena.constants import NAMESPACE_ROOT
from arena.registry.errors import RegistryError
from arena.registry.evaluators import (
    EVALUATOR_REPOSITORIES,
    OBSERVED_HEADS,
    OLMOCR_TOOLKIT_REPOSITORY,
    GitRefResolver,
    LiveGitRefResolver,
    RecordedGitRefResolver,
    resolve_evaluators,
)
from arena.registry.http import (
    CachedFetcher,
    FixtureStore,
    HttpFetcher,
    JsonFetcher,
    OfflineFetcher,
)
from arena.registry.models import resolve_models
from arena.registry.serialize import write_json_atomic
from arena.registry.validate import validate_evaluator_registry, validate_model_registry

MODEL_REGISTRY_FILENAME = "model_registry.json"
EVALUATOR_REGISTRY_FILENAME = "evaluator_registry.json"

DEFAULT_FIXTURES = NAMESPACE_ROOT / "tests" / "registry" / "fixtures"


def _recorded_ref_resolver() -> RecordedGitRefResolver:
    heads = {url: OBSERVED_HEADS[key] for key, url in EVALUATOR_REPOSITORIES.items()}
    heads[OLMOCR_TOOLKIT_REPOSITORY] = OBSERVED_HEADS["_olmocr_toolkit"]
    return RecordedGitRefResolver(heads)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arena.registry",
        description=(
            "Resolve and validate the arena model and evaluator registries. Reads only "
            "public huggingface.co / api.github.com endpoints and git ls-remote."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser(
        "resolve", help="write model_registry.json and evaluator_registry.json"
    )
    resolve.add_argument(
        "--offline",
        action="store_true",
        help="replay recorded fixtures instead of reading the network",
    )
    resolve.add_argument(
        "--fixtures",
        type=Path,
        default=None,
        help=(
            "fixture directory. With --offline it is read; without it, every live "
            "response is recorded there. Defaults to tests/registry/fixtures."
        ),
    )
    resolve.add_argument(
        "--out-dir",
        type=Path,
        default=NAMESPACE_ROOT,
        help="where the two registry files are written (default: the namespace root)",
    )
    resolve.add_argument(
        "--use-recorded",
        action="store_true",
        help=(
            "live mode only: serve a URL from its recorded fixture when one exists "
            "instead of re-reading it. A URL with no fixture is still fetched live and "
            "a live failure still fails the run."
        ),
    )
    resolve.add_argument(
        "--no-record",
        action="store_true",
        help="live mode only: do not record responses into the fixture directory",
    )

    resolve.add_argument(
        "--strict-core",
        action="store_true",
        help=(
            "treat a mismatch with lane A1's arena/core/schemas as fatal. Off by "
            "default: the mismatch is always printed as an INTERFACE CONFLICT, but "
            "it does not block the lanes that need the registry."
        ),
    )

    validate = sub.add_parser("validate", help="validate both registry files")
    validate.add_argument("--out-dir", type=Path, default=NAMESPACE_ROOT)
    validate.add_argument("--strict-core", action="store_true")
    return parser


def _make_fetchers(
    *, offline: bool, fixtures: Path, record: bool, use_recorded: bool
) -> tuple[JsonFetcher, GitRefResolver]:
    store = FixtureStore(fixtures)
    if offline:
        return OfflineFetcher(store), _recorded_ref_resolver()
    live = HttpFetcher(record_to=store if record else None)
    fetcher: JsonFetcher = CachedFetcher(store, live) if use_recorded else live
    return fetcher, LiveGitRefResolver()


def command_resolve(args: argparse.Namespace) -> int:
    fixtures: Path = args.fixtures or DEFAULT_FIXTURES
    fetcher, ref_resolver = _make_fetchers(
        offline=bool(args.offline),
        fixtures=fixtures,
        record=not args.no_record,
        use_recorded=bool(args.use_recorded),
    )
    out_dir: Path = args.out_dir

    if args.offline:
        method = "recorded_fixture_replay"
    elif args.use_recorded:
        method = "official_huggingface_and_github_api_read_only_with_recorded_cache"
    else:
        method = "official_huggingface_and_github_api_read_only"
    models_document = resolve_models(fetcher, resolution_method=method)
    evaluators_document = resolve_evaluators(ref_resolver)

    model_path = out_dir / MODEL_REGISTRY_FILENAME
    evaluator_path = out_dir / EVALUATOR_REGISTRY_FILENAME
    model_sha = write_json_atomic(model_path, models_document)
    evaluator_sha = write_json_atomic(evaluator_path, evaluators_document)

    print(f"wrote {model_path} ({models_document['model_count']} models) {model_sha}")
    print(
        f"wrote {evaluator_path} "
        f"({evaluators_document['evaluator_count']} evaluators) {evaluator_sha}"
    )
    if args.offline:
        print("mode: offline fixture replay; no network was read")
    else:
        print(f"mode: live read-only; fixtures {'not ' if args.no_record else ''}recorded")
        if isinstance(fetcher, CachedFetcher) and fetcher.cache_hits:
            print(f"served from recorded fixtures: {len(fetcher.cache_hits)} URL(s)")
            for url in fetcher.cache_hits:
                print(f"  cached: {url}")

    changed = [
        key
        for key, record in models_document["models"].items()
        if record.get("revision_changed_since_2026_08") is True
    ]
    if changed:
        print(f"revision moved since the 2026-08 registry: {sorted(changed)}")

    return command_validate(args)


def command_validate(args: argparse.Namespace) -> int:
    out_dir: Path = args.out_dir
    reports = [
        validate_model_registry(out_dir / MODEL_REGISTRY_FILENAME),
        validate_evaluator_registry(out_dir / EVALUATOR_REGISTRY_FILENAME),
    ]
    for report in reports:
        print(report.render())
    if not all(report.ok for report in reports):
        return 1
    if getattr(args, 'strict_core', False) and not all(report.core_ok for report in reports):
        print(
            "--strict-core: lane A1's arena/core/schemas rejected the records above",
            file=sys.stderr,
        )
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            return command_resolve(args)
        return command_validate(args)
    except RegistryError as error:
        print(f"registry error: {error}", file=sys.stderr)
        return 2


__all__ = [
    "EVALUATOR_REGISTRY_FILENAME",
    "MODEL_REGISTRY_FILENAME",
    "build_parser",
    "command_resolve",
    "command_validate",
    "main",
]
