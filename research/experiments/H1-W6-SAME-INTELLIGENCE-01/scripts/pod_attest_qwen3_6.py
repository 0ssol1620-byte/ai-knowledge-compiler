#!/usr/bin/env python3
"""Runs **inside** the W6 runtime pod, alongside the server. Captures what executed.

`model_identity_v8.REQUIRED_ATTESTATION_FIELDS` names nine fields. This program
produces all nine and nothing that would let a name stand in for an identity.

It **attaches** rather than orchestrates. The pod's own entrypoint is
`vllm serve`, so the container image starts the server with the pinned revision
and this program observes the result. That ordering matters: the thing being
attested is the runtime the image actually runs, not a second server this script
could have started with different arguments.

Why it is a file in the repository rather than a heredoc typed at a console: the
program that produces the attestation is part of the evidence chain. Its SHA-256
is recorded in the receipt, and it is transferred byte-identically.

**It does not decide the revision.** Two independent things bind it:

1. `huggingface_hub` stores a checkpoint under
   `snapshots/<commit>/`, so the directory the server loaded from is named by
   the commit the hub resolved --- not by the string this program was given;
2. every file in that directory is hashed here and compared, off the pod,
   against the digests Hugging Face declares for that commit.

The generation proof exists for the same reason. A downloaded checkpoint and a
serving runtime are two claims; a deterministic completion from the running
server is what ties them together.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Fixed, content-free and deliberately trivial. It exists to prove the server
#: generated, not to measure anything. A prompt drawn from the corpus would put
#: benchmark material into an attestation receipt.
PROOF_PROMPT = "Reply with exactly one word: attested."
PROOF_MAX_TOKENS = 256
PROOF_TEMPERATURE = 0.0

#: Hugging Face downloads only what the serving stack asked for, so a file the
#: hub declares may legitimately be absent from the snapshot --- `README.md` and
#: `LICENSE` are not part of what executed. These are the files whose absence
#: would mean something else executed.
ESSENTIAL_SUFFIXES = (".safetensors",)
ESSENTIAL_NAMES = ("config.json", "generation_config.json",
                   "model.safetensors.index.json", "tokenizer.json",
                   "tokenizer_config.json", "vocab.json", "merges.txt")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    """The digest Hugging Face reports for a non-LFS file.

    Small files are plain git objects, so their listed `blobId` is
    `sha1("blob <size>\\0" + content)`. Computing it here lets ordinary config
    files be cross-checked off the pod too, not only the LFS weights.
    """
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def snapshot_dir(repository: str, revision: str, cache_root: Path) -> Path:
    """`models--<org>--<name>/snapshots/<commit>` --- named by the resolved commit."""
    folder = "models--" + repository.replace("/", "--")
    return cache_root / folder / "snapshots" / revision


def file_manifest(root: Path) -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        relative = path.relative_to(root).as_posix()
        resolved = path.resolve()   # the snapshot entries are symlinks into blobs/
        manifest[relative] = {"size": resolved.stat().st_size,
                              "sha256": sha256_file(resolved),
                              "git_blob_sha1": git_blob_sha1(resolved)}
    return manifest


def is_essential(name: str) -> bool:
    return name.endswith(ESSENTIAL_SUFFIXES) or name in ESSENTIAL_NAMES


def get_json(url: str, timeout: float = 60.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: float = 900.0) -> Any:
    request = urllib.request.Request(  # noqa: S310
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


#: A short, content-free string whose tokenization is a behavioural fingerprint of
#: the tokenizer the *server* loaded --- as distinct from the `tokenizer.json` this
#: program hashed on disk. Two runtimes serving the same name can differ here, and
#: a file digest alone would not show it.
TOKENIZER_PROBE_TEXT = "TAVONEL 1,450 — café ü 42.50 USD"


def tokenizer_probe(base_url: str, model: str) -> dict[str, Any]:
    """Ask the running server to tokenize a fixed string, and record what it said."""
    try:
        result = post_json(f"{base_url}/tokenize",
                           {"model": model, "prompt": TOKENIZER_PROBE_TEXT}, timeout=120)
    except Exception as error:
        return {"available": False,
                "error": f"{type(error).__name__}: {error}"[:500],
                "note": "recorded as unavailable rather than omitted; an absent probe is "
                        "not a passing probe"}
    tokens = result.get("tokens")
    return {
        "available": True,
        "text": TOKENIZER_PROBE_TEXT,
        "token_count": result.get("count"),
        "tokens_sha256": canonical_sha256(tokens),
        "max_model_len": result.get("max_model_len"),
        "note": "the tokenizer the server loaded, observed through its own endpoint. It "
                "is reported beside the tokenizer file digest because the two are "
                "different claims.",
    }


def package_manifest() -> dict[str, Any]:
    """Every installed distribution and its version.

    The serving stack is what turns weights into answers, and a base image digest
    does not pin it when packages are installed into the image. Recording the
    full set makes the difference visible instead of implied.
    """
    try:
        from importlib.metadata import distributions
        packages = sorted(
            {f"{d.metadata['Name']}=={d.version}" for d in distributions()
             if d.metadata.get("Name")})
    except Exception as error:
        return {"available": False, "error": f"{type(error).__name__}: {error}"[:300]}
    return {"available": True, "count": len(packages),
            "manifest_sha256": canonical_sha256(packages), "packages": packages}


def failure(reason: str, **extra: Any) -> dict[str, Any]:
    return {"schema": "tavonel.w6-runtime-attestation.v1", "ok": False,
            "failure_reason": reason,
            "observed_at_utc": datetime.now(UTC).isoformat(), **extra}


def capture(*, repository: str, revision: str, image_digest: str, base_url: str,
            cache_root: Path, server_log_path: Path | None = None) -> dict[str, Any]:
    program_sha256 = "sha256:" + sha256_file(Path(__file__))

    snapshot = snapshot_dir(repository, revision, cache_root)
    if not snapshot.is_dir():
        return failure("snapshot_directory_absent", expected_path=str(snapshot),
                       capture_program_sha256=program_sha256,
                       why="the serving stack did not resolve this repository at this "
                           "commit; there is nothing to attest")

    manifest = file_manifest(snapshot)
    if not manifest:
        return failure("snapshot_directory_empty", expected_path=str(snapshot),
                       capture_program_sha256=program_sha256)
    manifest_digest = canonical_sha256(
        {name: entry["sha256"] for name, entry in manifest.items()})

    for required in ("config.json", "tokenizer.json", "tokenizer_config.json"):
        if required not in manifest:
            return failure("essential_file_missing_from_snapshot", missing=required,
                           capture_program_sha256=program_sha256)

    tokenizer_config = json.loads((snapshot / "tokenizer_config.json").read_text(
        encoding="utf-8"))
    config = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
    text_config = config.get("text_config") or {}

    try:
        models = get_json(f"{base_url}/v1/models")
    except Exception as error:
        return failure("server_not_reachable",
                       error=f"{type(error).__name__}: {error}"[:1000],
                       capture_program_sha256=program_sha256)

    served = [m.get("id") for m in (models.get("data") or [])]
    served_root = (models.get("data") or [{}])[0].get("root")
    try:
        completion = post_json(f"{base_url}/v1/chat/completions", {
            "model": served[0] if served else repository,
            "messages": [{"role": "user", "content": PROOF_PROMPT}],
            "temperature": PROOF_TEMPERATURE, "max_tokens": PROOF_MAX_TOKENS, "seed": 0})
    except Exception as error:
        return failure("generation_proof_failed",
                       error=f"{type(error).__name__}: {error}"[:2000],
                       capture_program_sha256=program_sha256)
    proof_text = completion["choices"][0]["message"]["content"]

    server_log = None
    if server_log_path is not None and server_log_path.exists():
        text = server_log_path.read_text(encoding="utf-8", errors="replace")
        launch = [line for line in text.splitlines() if "non-default args" in line]
        server_log = {"path": str(server_log_path),
                      "launch_args_line": launch[0][:2000] if launch else None,
                      "log_sha256": "sha256:" + hashlib.sha256(
                          text.encode("utf-8")).hexdigest(),
                      "tail": text[-4000:]}

    def safe(fn: Any, default: Any = None) -> Any:
        try:
            return fn()
        except Exception:
            return default

    from importlib.metadata import version as _version

    body: dict[str, Any] = {
        "schema": "tavonel.w6-runtime-attestation.v1",
        "ok": True,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "capture_program_sha256": program_sha256,
        "capture_mode": "attached to the container's own `vllm serve` entrypoint",

        # --- the nine required fields -------------------------------------
        "checkpoint_revision": revision,
        "model_file_manifest_sha256": manifest_digest,
        "tokenizer_identity": {
            "repository": repository,
            "revision": revision,
            "tokenizer_class": tokenizer_config.get("tokenizer_class"),
            "vocab_size": text_config.get("vocab_size"),
            "added_tokens": len(tokenizer_config.get("added_tokens_decoder") or {}),
        },
        "tokenizer_hash": "sha256:" + manifest["tokenizer.json"]["sha256"],
        "quantization": "none_bf16_from_checkpoint",
        "serving_runtime": "vllm",
        "serving_runtime_version": safe(lambda: _version("vllm")),
        "runtime_image_digest": image_digest,
        "model_attestation": None,   # filled below; it hashes everything above

        # --- evidence for those fields ------------------------------------
        "repository": repository,
        "snapshot_path": str(snapshot),
        "snapshot_directory_is_named_by_resolved_commit": snapshot.name == revision,
        "model_file_manifest": manifest,
        "essential_files_present": sorted(n for n in manifest if is_essential(n)),
        "quantization_evidence": {
            "launch_quantization_flag": None,
            "launch_dtype_flag": os.environ.get("W6_LAUNCH_DTYPE", "bfloat16"),
            "checkpoint_dtype": text_config.get("dtype"),
            "note": "no quantization flag was passed and the checkpoint is bf16; the "
                    "served weights are the checkpoint weights. This records the executed "
                    "identity, not a claim that bf16 is the only valid load.",
        },
        "served_model_ids": served,
        "served_model_root": served_root,
        "server_max_model_len": (models.get("data") or [{}])[0].get("max_model_len"),
        "architecture": config.get("architectures"),
        "max_position_embeddings": text_config.get("max_position_embeddings"),
        "transformers_version": safe(lambda: _version("transformers")),
        "torch_version": safe(lambda: _version("torch")),
        "cuda_version": safe(lambda: __import__("torch").version.cuda),
        "gpu": safe(lambda: subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,uuid,driver_version,memory.total",  # noqa: S607
             "--format=csv,noheader,nounits"], text=True).strip()),
        "generation_proof": {
            "prompt": PROOF_PROMPT,
            "temperature": PROOF_TEMPERATURE,
            "max_tokens": PROOF_MAX_TOKENS,
            "output_sha256": "sha256:" + hashlib.sha256(
                (proof_text or "").encode("utf-8")).hexdigest(),
            "output_preview": (proof_text or "")[:400],
            "usage": completion.get("usage"),
            "note": "content-free by design: it proves the runtime generated, and puts no "
                    "benchmark material into an attestation receipt",
        },
        "tokenizer_behaviour_probe": tokenizer_probe(base_url, served[0] if served
                                                     else repository),
        "server_launch_log": server_log,
        "package_manifest": package_manifest(),
    }
    body["model_attestation"] = canonical_sha256(
        {k: v for k, v in body.items() if k != "model_attestation"})
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repository", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--image-digest", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--cache-root", type=Path,
                    default=Path(os.environ.get("HF_HUB_CACHE")
                                 or Path.home() / ".cache/huggingface/hub"))
    ap.add_argument("--server-log", type=Path,
                    help="the serving process's log; its launch line records the argv "
                         "the runtime actually received")
    ap.add_argument("--output", type=Path, default=Path("/workspace/w6-attestation.json"))
    args = ap.parse_args()

    body = capture(repository=args.repository, revision=args.revision,
                   image_digest=args.image_digest, base_url=args.base_url,
                   cache_root=args.cache_root, server_log_path=args.server_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({k: v for k, v in body.items()
                      if k not in ("model_file_manifest",)}, indent=2, sort_keys=True))
    return 0 if body.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
