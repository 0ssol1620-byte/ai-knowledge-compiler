#!/usr/bin/env python3
"""Transport-only W6 v4 wrapper around the hash-frozen v3 acquisition logic."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "research" / "experiments" / "H1-W6-SAME-INTELLIGENCE-01"
V3_SCRIPT = EXP / "scripts" / "acquire_w6_v3.py"
V3_PROTOCOL = EXP / "PROTOCOL_V3_ACQUISITION_2026-08-19.md"
V4_PROTOCOL = EXP / "PROTOCOL_V4_TRANSPORT_AMENDMENT_2026-08-19.md"
RETRYABLE_API_CODES = {"maxlag", "ratelimited", "readonly"}


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(body.encode("utf-8"))


def load_v3() -> Any:
    spec = importlib.util.spec_from_file_location("tavonel_w6_v3_frozen", V3_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen v3 acquisition module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def freeze(manifest: Path, output: Path) -> int:
    v3 = load_v3()
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    if manifest_data.get("protocol_sha256") != file_sha256(V3_PROTOCOL):
        raise SystemExit("frozen v3 manifest no longer matches v3 protocol bytes")
    if manifest_data.get("acquisition_script_sha256") != file_sha256(V3_SCRIPT):
        raise SystemExit("frozen v3 manifest no longer matches v3 acquisition bytes")
    seal: dict[str, Any] = {
        "schema": "tavonel.w6-v4-transport-freeze.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "v4_protocol_sha256": file_sha256(V4_PROTOCOL),
        "v4_wrapper_sha256": file_sha256(Path(__file__)),
        "v3_manifest_sha256": file_sha256(manifest),
        "v3_manifest_receipt_sha256": manifest_data.get("receipt_sha256"),
        "v3_protocol_sha256": file_sha256(V3_PROTOCOL),
        "v3_acquisition_script_sha256": file_sha256(V3_SCRIPT),
        "candidate_count": manifest_data.get("candidate_count"),
        "source_category": manifest_data.get("source_category"),
        "scientific_rules_changed": False,
        "transport_change_only": True,
        "external_gpu_cost_usd": 0.0,
    }
    # Touch these constants so a refactor cannot accidentally freeze a wrapper
    # against a v3 module with a different public API origin.
    seal["api_origin"] = v3.API
    seal["receipt_sha256"] = canonical_sha256(seal)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(seal, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("W6 v4 transport seal frozen")
    print(f"candidate count: {seal['candidate_count']}")
    return 0


def _api_error_retryable(code: str) -> bool:
    return code in RETRYABLE_API_CODES or code.startswith("internal_api_error_")


def install_resilient_transport(v3: Any) -> None:
    def request_json(params: dict[str, str], *, retries: int = 9) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        )
        request = urllib.request.Request(  # noqa: S310 -- fixed HTTPS v3.API origin
            f"{v3.API}?{query}",
            headers={"User-Agent": v3.USER_AGENT, "Accept": "application/json"},
        )
        last: Exception | str | None = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
                    data = json.loads(response.read().decode("utf-8"))
                    error = data.get("error")
                    if not error:
                        return data
                    code = str(error.get("code", "unknown"))
                    info = str(error.get("info", ""))
                    last = f"MediaWiki API error {code}: {info}"
                    if not _api_error_retryable(code):
                        raise RuntimeError(last)
                    lag = error.get("lag")
                    try:
                        lag_delay = float(lag) if lag is not None else 0.0
                    except (TypeError, ValueError):
                        lag_delay = 0.0
                    delay = max(lag_delay, min(120.0, 5.0 * (2**attempt)))
                    print(f"MediaWiki API {code}; retrying after {delay:.1f}s")
                    time.sleep(delay)
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in {429, 503} or attempt + 1 >= retries:
                    raise
                retry_after = exc.headers.get("Retry-After")
                try:
                    server_delay = float(retry_after) if retry_after else 0.0
                except ValueError:
                    server_delay = 0.0
                delay = max(server_delay, min(120.0, 8.0 * (2**attempt)))
                print(f"MediaWiki HTTP {exc.code}; retrying after {delay:.1f}s")
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                if attempt + 1 >= retries:
                    break
                delay = min(60.0, 3.0 * (2**attempt))
                print(f"MediaWiki transient transport error; retrying after {delay:.1f}s")
                time.sleep(delay)
        raise RuntimeError(f"MediaWiki request failed after {retries} attempts: {last}")

    v3.request_json = request_json


def verify_seal(seal_path: Path, manifest: Path) -> dict[str, Any]:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    checks = {
        "v4_protocol_sha256": file_sha256(V4_PROTOCOL),
        "v4_wrapper_sha256": file_sha256(Path(__file__)),
        "v3_manifest_sha256": file_sha256(manifest),
        "v3_protocol_sha256": file_sha256(V3_PROTOCOL),
        "v3_acquisition_script_sha256": file_sha256(V3_SCRIPT),
    }
    for key, observed in checks.items():
        if seal.get(key) != observed:
            raise SystemExit(f"W6 v4 frozen bytes changed before acquisition: {key}")
    return seal


def acquire(manifest: Path, seal_path: Path, corpus: Path, output: Path, sidecar: Path) -> int:
    seal = verify_seal(seal_path, manifest)
    v3 = load_v3()
    install_resilient_transport(v3)
    started = datetime.now(UTC)
    rc = v3.acquire(manifest, corpus, output)
    completion: dict[str, Any] = {
        "schema": "tavonel.w6-v4-transport-completion.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started.isoformat(),
        "transport_freeze_sha256": file_sha256(seal_path),
        "transport_freeze_receipt_sha256": seal.get("receipt_sha256"),
        "v3_acquisition_receipt_sha256": file_sha256(output) if output.exists() else None,
        "v3_acquisition_return_code": rc,
        "scientific_rules_changed": False,
        "transport_change_only": True,
        "external_gpu_cost_usd": 0.0,
    }
    completion["receipt_sha256"] = canonical_sha256(completion)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(completion, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"v4 sidecar: {sidecar}")
    return rc


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="phase", required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--manifest", type=Path, required=True)
    freeze_parser.add_argument("--output", type=Path, required=True)
    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--manifest", type=Path, required=True)
    acquire_parser.add_argument("--seal", type=Path, required=True)
    acquire_parser.add_argument("--corpus", type=Path, required=True)
    acquire_parser.add_argument("--output", type=Path, required=True)
    acquire_parser.add_argument("--sidecar", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "freeze":
        return freeze(args.manifest, args.output)
    return acquire(args.manifest, args.seal, args.corpus, args.output, args.sidecar)


if __name__ == "__main__":
    raise SystemExit(main())
