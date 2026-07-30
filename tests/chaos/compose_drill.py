"""Bounded, recoverable Docker Compose outage drill for local synthetic data."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = (ROOT / "docker-compose.dev.yml").resolve()
PROJECT_NAME = "akc-dev"
CONFIRMATION = "AKC_DEV_SYNTHETIC_CHAOS"
TARGETS = frozenset({"api", "postgres"})


@dataclass(frozen=True)
class Probe:
    ok: bool
    status: int | None
    duration_ms: int


def validate_guardrails(
    *, target: str, base_url: str, environment: str, confirmation: str, outage: int
) -> None:
    if target not in TARGETS:
        raise ValueError(f"target must be one of {sorted(TARGETS)}")
    if environment.casefold() not in {"development", "test"}:
        raise ValueError("chaos drill is restricted to development/test")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("chaos drill target must be a loopback HTTP origin")
    if confirmation != CONFIRMATION:
        raise ValueError(f"--confirm must equal {CONFIRMATION}")
    if outage < 1 or outage > 30:
        raise ValueError("outage must be between 1 and 30 seconds")


def probe(url: str, timeout: float = 2.0) -> Probe:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("probe URL must remain on loopback HTTP")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(  # noqa: S310  # nosec B310
            url, timeout=timeout
        ) as response:
            response.read(1024)
            status = response.status
            ok = 200 <= status < 300
    except (OSError, urllib.error.URLError):
        status = None
        ok = False
    return Probe(ok=ok, status=status, duration_ms=round((time.monotonic() - started) * 1000))


def compose_command(docker: str, *arguments: str) -> list[str]:
    return [
        docker,
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--file",
        str(COMPOSE_FILE),
        *arguments,
    ]


def run_compose(docker: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        compose_command(docker, *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def wait_for_recovery(url: str, timeout: int = 60) -> tuple[bool, int]:
    deadline = time.monotonic() + timeout
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        if probe(url).ok:
            return True, attempts
        time.sleep(1)
    return False, attempts


def execute(target: str, base_url: str, outage: int) -> dict[str, object]:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker executable not found")
    services = set(run_compose(docker, "config", "--services").stdout.split())
    if target not in services or not {"api", "postgres"}.issubset(services):
        raise RuntimeError("expected akc-dev Compose services are unavailable")

    live_url = f"{base_url.rstrip('/')}/health/live"
    ready_url = f"{base_url.rstrip('/')}/health/ready"
    before = {"live": asdict(probe(live_url)), "ready": asdict(probe(ready_url))}
    if not before["live"]["ok"] or not before["ready"]["ok"]:
        raise RuntimeError("API must be healthy before the drill")

    paused = False
    during: dict[str, object] = {}
    try:
        run_compose(docker, "pause", target)
        paused = True
        deadline = time.monotonic() + outage
        observations: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            observations.append(
                {
                    "live": asdict(probe(live_url)),
                    "ready": asdict(probe(ready_url)),
                }
            )
            time.sleep(1)
        during = {
            "observations": observations,
            "expected_failure_observed": any(
                not bool(
                    observation["live" if target == "api" else "ready"]["ok"]  # type: ignore[index]
                )
                for observation in observations
            ),
        }
    finally:
        if paused:
            run_compose(docker, "unpause", target)

    recovered, attempts = wait_for_recovery(ready_url)
    result = {
        "schema_version": "1.0",
        "scope": "local-synthetic-only",
        "compose_project": PROJECT_NAME,
        "target": target,
        "outage_seconds": outage,
        "before": before,
        "during": during,
        "recovery": {"ready": recovered, "attempts": attempts},
        "deployment_evidence": False,
    }
    if not during.get("expected_failure_observed") or not recovered:
        raise RuntimeError(f"drill acceptance failed: {json.dumps(result, sort_keys=True)}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--outage-seconds", type=int, default=5)
    parser.add_argument("--confirm", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment = os.getenv("AKC_ENV", "development")
    try:
        validate_guardrails(
            target=args.target,
            base_url=args.base_url,
            environment=environment,
            confirmation=args.confirm,
            outage=args.outage_seconds,
        )
        print(json.dumps(execute(args.target, args.base_url, args.outage_seconds), sort_keys=True))
    except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
