#!/usr/bin/env python3
"""Qualify the W6 runtime and write the attestation receipt. Off-pod half.

`pod_attest_qwen3_6.py` runs on the GPU and reports what it downloaded, hashed
and served. This script is the part that does not trust it.

The pod's claim *"I served revision R"* is worth nothing on its own --- it is the
revision the caller asked for, echoed back. What makes it binding is that every
file digest the pod computed is compared here against the digests Hugging Face
declares for commit R:

- LFS files (the 15 safetensors shards and `tokenizer.json`) carry a real
  `sha256` in the hub listing, compared directly;
- ordinary git files carry a `blobId`, which is
  `sha1("blob <size>\\0" + content)`, recomputed on the pod for exactly this
  comparison.

Every file the runtime holds must match, no file may be present that the commit
does not declare, and no weight, index, config or tokenizer file may be absent. A
partial match is a refusal, not a warning: a checkpoint that is *mostly* the
expected one is a different checkpoint.

Files the serving stack never downloaded --- `README.md`, `LICENSE`,
`.gitattributes` --- are listed as not-downloaded rather than counted as missing.
They are declared by the commit and are not part of what executed, and calling
their absence a mismatch would make the check cry wolf on every real runtime.

The identity chain itself is decided by `model_identity_v8.reconcile`, which
reads the expected revision from `benchmark/v6/candidate-registry.yaml`. Nothing
here writes back to that registry --- if the runtime served something else, the
answer is `MODEL_IDENTITY_MISMATCH`, not an updated expectation.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
RECEIPTS = EXP / "receipts"
POD_PROGRAM = HERE / "pod_attest_qwen3_6.py"
RECEIPT = RECEIPTS / "v8-runtime-attestation.json"
ATTESTATION = RECEIPTS / "v8-model-attestation.json"

HUB = "https://huggingface.co/api/models"

#: The whole `before + after` pair goes to RAW, and the largest development pair
#: is ~158k model tokens. The checkpoint's own `max_position_embeddings` is
#: 262,144 and the candidate registry's condition is a `262144_context_recipe`,
#: so the runtime is served at the checkpoint's full window rather than at a
#: number chosen to make RAW fit.
DEFAULT_MAX_MODEL_LEN = 262144


def _load_identity() -> Any:
    spec = importlib.util.spec_from_file_location("w6_identity_attest",
                                                  HERE / "model_identity_v8.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load model_identity_v8.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["w6_identity_attest"] = module
    spec.loader.exec_module(module)
    return module


IDENTITY = _load_identity()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_json(url: str, timeout: float = 120.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def hub_digests(repository: str, revision: str) -> dict[str, dict[str, Any]]:
    """What Hugging Face declares for this exact commit, per file."""
    info = fetch_json(f"{HUB}/{repository}/revision/{revision}?blobs=true")
    if info.get("sha") != revision:
        raise SystemExit(
            f"the hub resolved {revision} to commit {info.get('sha')}; a revision that "
            "does not resolve to itself is not an immutable pin")
    out: dict[str, dict[str, Any]] = {}
    for sibling in info.get("siblings") or []:
        lfs = sibling.get("lfs") or {}
        out[sibling["rfilename"]] = {
            "sha256": lfs.get("sha256"),
            "git_blob_sha1": None if lfs else sibling.get("blobId"),
            "size": lfs.get("size", sibling.get("size")),
        }
    return out


def is_essential(name: str) -> bool:
    """Files whose absence would mean something other than this checkpoint ran.

    A serving stack downloads what it needs, so `README.md`, `LICENSE` and
    `.gitattributes` are legitimately absent from a snapshot and are recorded as
    not-downloaded rather than treated as missing. Weights, index, config and
    tokenizer are not optional.
    """
    return name.endswith(".safetensors") or name in {
        "config.json", "generation_config.json", "model.safetensors.index.json",
        "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"}


def verify_manifest(observed: dict[str, dict[str, Any]],
                    declared: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare the pod's per-file digests with the hub's, file by file.

    Returns a verdict rather than raising, so a caller can record the mismatch
    instead of losing it in a traceback.
    """
    absent = sorted(set(declared) - set(observed))
    missing = [name for name in absent if is_essential(name)]
    not_downloaded = [name for name in absent if not is_essential(name)]
    unexpected = sorted(set(observed) - set(declared))
    mismatched: list[dict[str, Any]] = []
    unverifiable: list[str] = []
    verified_sha256 = 0
    verified_blob = 0

    for name in sorted(set(observed) & set(declared)):
        want = declared[name]
        got = observed[name]
        if want.get("sha256"):
            if want["sha256"] != got.get("sha256"):
                mismatched.append({"file": name, "field": "sha256",
                                   "declared": want["sha256"], "observed": got.get("sha256")})
            else:
                verified_sha256 += 1
        elif want.get("git_blob_sha1"):
            if want["git_blob_sha1"] != got.get("git_blob_sha1"):
                mismatched.append({"file": name, "field": "git_blob_sha1",
                                   "declared": want["git_blob_sha1"],
                                   "observed": got.get("git_blob_sha1")})
            else:
                verified_blob += 1
        else:
            unverifiable.append(name)

    matches = not (missing or unexpected or mismatched or unverifiable)
    return {
        "matches": matches,
        "files_declared": len(declared),
        "files_observed": len(observed),
        "verified_by_lfs_sha256": verified_sha256,
        "verified_by_git_blob_sha1": verified_blob,
        "missing_from_runtime": missing,
        "declared_but_not_downloaded": not_downloaded,
        "present_but_not_declared": unexpected,
        "digest_mismatches": mismatched,
        "unverifiable": unverifiable,
        "rule": "every file the runtime holds must carry the digest the hub declares for "
                "this commit, and no weight, index, config or tokenizer file may be "
                "absent. A partial match is a different checkpoint, not a nearly-correct "
                "one. Files the serving stack never downloaded (README, LICENSE) are "
                "recorded rather than counted as missing --- they are not what executed.",
    }


def serve_args(*, repository: str, revision: str, max_model_len: int) -> list[str]:
    """What the container's `vllm serve` entrypoint is given, and nothing more.

    The revision is passed twice on purpose: `--revision` pins the weights and
    `--tokenizer-revision` pins the tokenizer, and a runtime that pinned only the
    first would serve a pinned checkpoint through an unpinned tokenizer.
    """
    return [repository,
            "--revision", revision,
            "--tokenizer-revision", revision,
            "--served-model-name", repository,
            "--dtype", "bfloat16",
            "--max-model-len", str(max_model_len),
            "--gpu-memory-utilization", "0.90",
            "--host", "0.0.0.0",
            "--port", "8000"]


def capture_command(*, repository: str, revision: str, image_digest: str) -> str:
    """A single shell command that transfers the capture program and runs it.

    The program is embedded rather than fetched, so the pod runs the reviewed
    file and not whatever a URL happens to serve at that moment. It is gzipped
    before base64 only to keep the command short; the bytes that land on disk are
    the repository's bytes, and the pod recomputes their digest.
    """
    encoded = base64.b64encode(
        gzip.compress(POD_PROGRAM.read_bytes(), mtime=0)).decode("ascii")
    return (
        "set -eu; mkdir -p /workspace/w6-attest; "
        f"printf %s '{encoded}' | base64 -d | gunzip "
        "> /workspace/w6-attest/pod_attest_qwen3_6.py; "
        "python3 /workspace/w6-attest/pod_attest_qwen3_6.py "
        f"--repository '{repository}' --revision '{revision}' "
        f"--image-digest '{image_digest}' "
        "--output /workspace/w6-attest/attestation.json > /dev/null; "
        "cat /workspace/w6-attest/attestation.json"
    )


def build_receipt(*, attestation: dict[str, Any], manifest_verdict: dict[str, Any],
                  chain: dict[str, Any], pod: dict[str, Any],
                  expected: dict[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-runtime-qualification.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "what_this_is": (
            "the live qualification of the W6 runtime. The candidate evidence registry "
            "carried an expected pinned revision and the runtime model registry had not "
            "been qualified against it; this receipt is that qualification."
        ),
        "expected_identity": expected,
        "capture_program": {
            "path": POD_PROGRAM.relative_to(ROOT).as_posix(),
            "local_sha256": file_sha256(POD_PROGRAM),
            "pod_reported_sha256": attestation.get("capture_program_sha256"),
            "transfer": "base64, byte-identical, recomputed on the pod",
        },
        "pod": pod,
        "attestation": attestation,
        "checkpoint_verification": manifest_verdict,
        "identity_chain": chain,
        "fallback": IDENTITY.fallback_is_forbidden_here(IDENTITY.runtime_registry_state()),
        "qualified": bool(manifest_verdict["matches"]
                          and chain.get("state") == "MODEL_IDENTITY_RECONCILED"
                          and attestation.get("ok")),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("serve-args", "capture-command", "capture"),
                    required=True)
    ap.add_argument("--image-digest", help="the immutable registry digest actually deployed")
    ap.add_argument("--max-model-len", type=int, default=DEFAULT_MAX_MODEL_LEN)
    ap.add_argument("--attestation-url",
                    help="capture mode: where the pod serves attestation.json")
    ap.add_argument("--attestation-file", type=Path,
                    help="capture mode: a local copy instead of a URL")
    ap.add_argument("--pod-id")
    ap.add_argument("--pod-gpu")
    ap.add_argument("--pod-cost-per-hour-usd", type=float)
    ap.add_argument("--output", type=Path, default=RECEIPT)
    args = ap.parse_args()

    expected = IDENTITY.expected_identity()
    if expected["state"] != "EXPECTED_REVISION_PINNED":
        print(f"REGISTRY_AMBIGUOUS: {expected['why']}")
        return 2
    repository = expected["repository"]
    revision = expected["expected_revision"]

    if args.mode == "serve-args":
        print(json.dumps(serve_args(repository=repository, revision=revision,
                                    max_model_len=args.max_model_len)))
        return 0

    if args.mode == "capture-command":
        if not args.image_digest:
            print("refusing: --image-digest is the runtime identity, not a detail")
            return 2
        print(capture_command(repository=repository, revision=revision,
                              image_digest=args.image_digest))
        return 0

    if args.attestation_file:
        attestation = json.loads(args.attestation_file.read_text(encoding="utf-8"))
    elif args.attestation_url:
        attestation = fetch_json(args.attestation_url)
    else:
        print("refusing: capture needs --attestation-url or --attestation-file")
        return 2

    if not attestation.get("ok"):
        print(f"MODEL_RUNTIME_NOT_READY: the pod reported "
              f"{attestation.get('failure_reason')}")
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(
            {"schema": "tavonel.w6-v8-runtime-qualification.v1", "qualified": False,
             "generated_at": datetime.now(UTC).isoformat(),
             "state": "MODEL_RUNTIME_NOT_READY", "attestation": attestation},
            indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 3

    declared = hub_digests(repository, revision)
    verdict = verify_manifest(attestation.get("model_file_manifest") or {}, declared)
    chain = IDENTITY.reconcile(attestation, expected=expected)

    pod = {"pod_id": args.pod_id, "gpu": args.pod_gpu,
           "cost_per_hour_usd": args.pod_cost_per_hour_usd,
           "image_digest": args.image_digest or attestation.get("runtime_image_digest")}
    receipt = build_receipt(attestation=attestation, manifest_verdict=verdict,
                            chain=chain, pod=pod, expected=expected)

    RECEIPTS.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    # The freeze takes an attestation object, not this receipt. Writing it out
    # separately keeps the freeze's input exactly the nine attested fields plus
    # their evidence, with no verification verdict folded in.
    ATTESTATION.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    print(f"repository : {repository}")
    print(f"expected   : {revision}")
    print(f"attested   : {attestation.get('checkpoint_revision')}")
    print(f"files      : {verdict['verified_by_lfs_sha256']} by LFS sha256, "
          f"{verdict['verified_by_git_blob_sha1']} by git blob sha1, "
          f"{len(verdict['digest_mismatches'])} mismatched, "
          f"{len(verdict['missing_from_runtime'])} missing")
    print(f"serving    : {attestation.get('serving_runtime')} "
          f"{attestation.get('serving_runtime_version')} "
          f"@ {attestation.get('runtime_image_digest')}")
    print(f"chain      : {chain['state']}")
    print(f"qualified  : {receipt['qualified']}")
    print(f"wrote {args.output.relative_to(ROOT).as_posix()}")
    return 0 if receipt["qualified"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
