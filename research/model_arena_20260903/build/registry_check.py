"""Read-only registry readiness check.

Usage::

    .venv/Scripts/python.exe research/model_arena_20260903/build/registry_check.py

Reports, without ever printing a token:

1. Whether the ``gh`` CLI has a token with ``write:packages`` (and, if the
   provider separates it, ``read:packages``) by parsing the
   ``X-OAuth-Scopes`` header from ``gh api -i user`` -- scopes only, per the
   lane brief ("print scopes only, never the token").
2. For each of the 11 GPU model_keys in ``build_plan.json``, whether an
   anonymous GET of ``ghcr.io/0ssol1620-byte/tavonel-arena/<model_key>:latest``
   returns 404 (not yet pushed -- expected in this build phase) or something
   else (already pushed, or a transport problem).

This is a plain script under ``build/`` (not a package under ``arena``), run
directly. Every network call is read-only: no push, no pod, no bucket.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

BUILD_DIR: Final = Path(__file__).resolve().parent
NAMESPACE_ROOT: Final = BUILD_DIR.parent
if str(NAMESPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(NAMESPACE_ROOT))
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from registry_resolve import resolve_digest  # noqa: E402

REQUIRED_SCOPES: Final = ("write:packages",)
RECOMMENDED_SCOPES: Final = ("read:packages",)
_SCOPES_HEADER_RE: Final = re.compile(r"^X-OAuth-Scopes:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
_HTTP_STATUS_RE: Final = re.compile(r"^HTTP/\d(?:\.\d)?\s+(\d{3})", re.MULTILINE)


def parse_oauth_scopes(gh_api_dash_i_output: str) -> tuple[str, ...] | None:
    """Extract the OAuth scope list from ``gh api -i <path>`` output.

    Returns ``None`` when no ``X-OAuth-Scopes`` header is present at all
    (e.g. a fine-grained PAT, which does not use OAuth scopes) rather than an
    empty tuple, so a caller can tell "no scopes header" apart from
    "scopes header present but empty".
    """
    match = _SCOPES_HEADER_RE.search(gh_api_dash_i_output)
    if match is None:
        return None
    raw = match.group(1).strip()
    if not raw:
        return ()
    return tuple(scope.strip() for scope in raw.split(",") if scope.strip())


def parse_http_status(gh_api_dash_i_output: str) -> int | None:
    match = _HTTP_STATUS_RE.search(gh_api_dash_i_output)
    return int(match.group(1)) if match else None


@dataclass(frozen=True, slots=True)
class ScopeReport:
    http_status: int | None
    scopes: tuple[str, ...] | None
    missing_required: tuple[str, ...]
    missing_recommended: tuple[str, ...]
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.missing_required


def classify_scopes(gh_api_dash_i_output: str, *, error: str | None = None) -> ScopeReport:
    if error is not None:
        return ScopeReport(
            http_status=None, scopes=None, missing_required=REQUIRED_SCOPES,
            missing_recommended=RECOMMENDED_SCOPES, error=error,
        )
    status = parse_http_status(gh_api_dash_i_output)
    scopes = parse_oauth_scopes(gh_api_dash_i_output)
    if status != 200:
        return ScopeReport(
            http_status=status, scopes=scopes, missing_required=REQUIRED_SCOPES,
            missing_recommended=RECOMMENDED_SCOPES,
            error=f"gh api user returned status {status!r}, expected 200",
        )
    if scopes is None:
        return ScopeReport(
            http_status=status, scopes=None, missing_required=REQUIRED_SCOPES,
            missing_recommended=RECOMMENDED_SCOPES,
            error="no X-OAuth-Scopes header present (fine-grained token, or scopes hidden)",
        )
    scope_set = set(scopes)
    missing_required = tuple(scope for scope in REQUIRED_SCOPES if scope not in scope_set)
    missing_recommended = tuple(scope for scope in RECOMMENDED_SCOPES if scope not in scope_set)
    return ScopeReport(
        http_status=status, scopes=scopes, missing_required=missing_required,
        missing_recommended=missing_recommended, error=None,
    )


def run_gh_scope_check() -> ScopeReport:
    """Invoke ``gh api -i user`` and classify the result. Never returns the
    token: only the parsed scope *names* ever leave this function."""
    try:
        completed = subprocess.run(
            ["gh", "api", "-i", "user"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return classify_scopes("", error=f"{exc.__class__.__name__}: could not run gh CLI")
    if completed.returncode != 0:
        error = f"gh exited {completed.returncode}: {_first_line(completed.stderr)}"
        return classify_scopes(completed.stdout, error=error)
    return classify_scopes(completed.stdout)


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else "(no stderr)"


@dataclass(frozen=True, slots=True)
class ManifestCheck:
    model_key: str
    ref: str
    already_pushed: bool | None  # None = inconclusive (network/transport issue)
    detail: str


def check_target_manifest(registry_target: str, *, tag: str = "latest") -> ManifestCheck:
    """Anonymous GET of registry_target:tag. 404 -> not yet pushed (expected
    in this build phase). 200 -> already pushed. Anything else (including a
    denied anonymous token, common for a brand-new/private GHCR namespace) is
    reported as inconclusive, never silently treated as "not pushed"."""
    model_key = registry_target.rsplit("/", 1)[-1]
    ref = f"{registry_target}:{tag}"
    lookup = resolve_digest(ref)
    if lookup.http_status == 404:
        return ManifestCheck(model_key, ref, already_pushed=False, detail="404: not yet pushed")
    if lookup.resolved and lookup.digest:
        return ManifestCheck(
            model_key, ref, already_pushed=True, detail=f"already pushed at {lookup.digest}"
        )
    return ManifestCheck(
        model_key, ref, already_pushed=None,
        detail=f"inconclusive ({lookup.method}: {lookup.detail})",
    )


def main() -> int:
    print("== GitHub token scopes (gh api -i user; scopes only, never the token) ==")
    scope_report = run_gh_scope_check()
    if scope_report.error:
        print(f"  UNKNOWN: {scope_report.error}")
    else:
        print(f"  scopes: {', '.join(scope_report.scopes or ())}")
        if scope_report.missing_required:
            print(f"  MISSING REQUIRED: {', '.join(scope_report.missing_required)}")
        else:
            print("  write:packages present (implies package read/write on classic PATs)")
        if scope_report.missing_recommended:
            print(
                f"  note: {', '.join(scope_report.missing_recommended)} not listed separately "
                "(classic write:packages tokens do not always enumerate read:packages, but "
                "typically grant it)"
            )

    build_plan_path = BUILD_DIR / "build_plan.json"
    if not build_plan_path.is_file():
        print(
            f"\n== Target manifests ==\n  no {build_plan_path} yet; "
            "run generate_build_plan.py first"
        )
        return 0 if scope_report.ok else 1

    plan = json.loads(build_plan_path.read_text(encoding="utf-8"))
    print("\n== Target manifests (ghcr.io, anonymous GET) ==")
    any_inconclusive = False
    for model_key, model_plan in sorted(plan.get("models", {}).items()):
        registry_target = model_plan.get("registry_target")
        if not registry_target:
            continue
        result = check_target_manifest(registry_target)
        print(f"  {model_key:24s} {result.detail}")
        if result.already_pushed is None:
            any_inconclusive = True

    if any_inconclusive:
        print(
            "\nnote: a brand-new GHCR namespace commonly denies anonymous token issuance "
            "until the first push happens and its visibility is set to public; "
            "'inconclusive' here does not mean 'already pushed'."
        )
    return 0 if scope_report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ManifestCheck",
    "ScopeReport",
    "check_target_manifest",
    "classify_scopes",
    "main",
    "parse_http_status",
    "parse_oauth_scopes",
    "run_gh_scope_check",
]
