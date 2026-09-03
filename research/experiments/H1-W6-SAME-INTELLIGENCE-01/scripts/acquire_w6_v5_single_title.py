#!/usr/bin/env python3
"""W6 v5: single-title historical-revision transport over frozen v3 science."""

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
V5_PROTOCOL = EXP / "PROTOCOL_V5_SINGLE_TITLE_TRANSPORT_2026-08-19.md"
RETRYABLE = {"maxlag", "ratelimited", "readonly"}


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(body.encode("utf-8"))


def load_v3() -> Any:
    spec = importlib.util.spec_from_file_location("tavonel_w6_v3_for_v5", V3_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen v3 module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def resilient_request(v3: Any, params: dict[str, str], *, retries: int = 9) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"format": "json", "formatversion": "2", "maxlag": "5", **params}
    )
    request = urllib.request.Request(  # noqa: S310 -- v3 fixed HTTPS API
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
            if code not in RETRYABLE and not code.startswith("internal_api_error_"):
                raise RuntimeError(last)
            try:
                lag = float(error.get("lag", 0.0) or 0.0)
            except (TypeError, ValueError):
                lag = 0.0
            delay = max(lag, min(120.0, 5.0 * (2**attempt)))
            print(f"MediaWiki API {code}; retry after {delay:.1f}s")
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
            print(f"MediaWiki HTTP {exc.code}; retry after {delay:.1f}s")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 >= retries:
                break
            delay = min(60.0, 3.0 * (2**attempt))
            print(f"MediaWiki transient transport error; retry after {delay:.1f}s")
            time.sleep(delay)
    raise RuntimeError(f"MediaWiki request failed after {retries} attempts: {last}")


def install_single_title_transport(v3: Any) -> None:
    def revision_batch(titles: list[str], cutoff: str) -> dict[str, dict[str, Any] | None]:
        out: dict[str, dict[str, Any] | None] = {}
        for original in titles:
            params = {
                "action": "query",
                "prop": "revisions",
                "titles": original,
                "redirects": "1",
                "rvprop": "ids|timestamp|sha1|content",
                "rvslots": "main",
                "rvlimit": "1",
                "rvstart": cutoff,
                "rvdir": "older",
            }
            data = resilient_request(v3, params)
            redirects = {
                v3.normalize_title(row["from"]): v3.normalize_title(row["to"])
                for row in data["query"].get("redirects", [])
            }
            lookup = redirects.get(v3.normalize_title(original), v3.normalize_title(original))
            pages = {
                v3.normalize_title(page.get("title", "")): page
                for page in data["query"].get("pages", [])
            }
            page = pages.get(lookup)
            revisions = page.get("revisions", []) if page else []
            if not revisions:
                out[original] = None
                continue
            rev = revisions[0]
            content = rev.get("slots", {}).get("main", {}).get("content")
            if content is None:
                out[original] = None
                continue
            out[original] = {
                "resolved_title": lookup,
                "revision_id": rev["revid"],
                "parent_id": rev.get("parentid"),
                "timestamp": rev["timestamp"],
                "mw_sha1": rev.get("sha1"),
                "content": content,
            }
            # Keep request pressure bounded without changing candidate order or
            # scientific stopping rules.
            time.sleep(0.02)
        return out

    v3.revision_batch = revision_batch


def freeze(manifest: Path, output: Path) -> int:
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    if manifest_data.get("protocol_sha256") != file_sha256(V3_PROTOCOL):
        raise SystemExit("v3 protocol hash mismatch")
    if manifest_data.get("acquisition_script_sha256") != file_sha256(V3_SCRIPT):
        raise SystemExit("v3 acquisition-script hash mismatch")
    seal: dict[str, Any] = {
        "schema": "tavonel.w6-v5-single-title-freeze.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "v5_protocol_sha256": file_sha256(V5_PROTOCOL),
        "v5_wrapper_sha256": file_sha256(Path(__file__)),
        "v3_manifest_sha256": file_sha256(manifest),
        "v3_manifest_receipt_sha256": manifest_data.get("receipt_sha256"),
        "v3_protocol_sha256": file_sha256(V3_PROTOCOL),
        "v3_acquisition_script_sha256": file_sha256(V3_SCRIPT),
        "candidate_count": manifest_data.get("candidate_count"),
        "scientific_rules_changed": False,
        "transport_change": "multi-title revision query -> one-title revision query",
        "external_gpu_cost_usd": 0.0,
    }
    seal["receipt_sha256"] = canonical_sha256(seal)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"W6 v5 seal frozen; candidates={seal['candidate_count']}")
    return 0


def verify_seal(seal_path: Path, manifest: Path) -> dict[str, Any]:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    expected = {
        "v5_protocol_sha256": file_sha256(V5_PROTOCOL),
        "v5_wrapper_sha256": file_sha256(Path(__file__)),
        "v3_manifest_sha256": file_sha256(manifest),
        "v3_protocol_sha256": file_sha256(V3_PROTOCOL),
        "v3_acquisition_script_sha256": file_sha256(V3_SCRIPT),
    }
    for key, value in expected.items():
        if seal.get(key) != value:
            raise SystemExit(f"frozen bytes changed: {key}")
    return seal


def acquire(manifest: Path, seal_path: Path, corpus: Path, output: Path, sidecar: Path) -> int:
    seal = verify_seal(seal_path, manifest)
    v3 = load_v3()
    install_single_title_transport(v3)
    started = datetime.now(UTC)
    rc = v3.acquire(manifest, corpus, output)
    completion: dict[str, Any] = {
        "schema": "tavonel.w6-v5-single-title-completion.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started.isoformat(),
        "freeze_file_sha256": file_sha256(seal_path),
        "freeze_receipt_sha256": seal.get("receipt_sha256"),
        "acquisition_receipt_sha256": file_sha256(output) if output.exists() else None,
        "return_code": rc,
        "scientific_rules_changed": False,
        "external_gpu_cost_usd": 0.0,
    }
    completion["receipt_sha256"] = canonical_sha256(completion)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(completion, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"W6 v5 completion sidecar: {sidecar}")
    return rc


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="phase", required=True)
    p_freeze = sub.add_parser("freeze")
    p_freeze.add_argument("--manifest", type=Path, required=True)
    p_freeze.add_argument("--output", type=Path, required=True)
    p_acquire = sub.add_parser("acquire")
    p_acquire.add_argument("--manifest", type=Path, required=True)
    p_acquire.add_argument("--seal", type=Path, required=True)
    p_acquire.add_argument("--corpus", type=Path, required=True)
    p_acquire.add_argument("--output", type=Path, required=True)
    p_acquire.add_argument("--sidecar", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "freeze":
        return freeze(args.manifest, args.output)
    return acquire(args.manifest, args.seal, args.corpus, args.output, args.sidecar)


if __name__ == "__main__":
    raise SystemExit(main())
