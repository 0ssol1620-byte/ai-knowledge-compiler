#!/usr/bin/env python3
"""Run hard-200 with v10's pipeline and a startup budget re-derived from measurement.

v10 lost four hosts in a row and the obvious reading -- "the 11.79 GB vLLM image
pull is slower than the 600 s cutoff" -- turned out to be wrong.  Four probes
(`probe_stage1_host_startup_discriminator_v1.py`) settled it:

  probe-3b32d03f6a2c  python:3.12-slim   0.05 GB  machine sms1rfl9ulmx   READY   37.7 s
  probe-ceafa5645cd5  pytorch cu124      3.93 GB  machine 0vkszbho34pn   READY   39.3 s
  probe-bc67c22be6d1  pytorch cu124      3.93 GB  machine 9drulpjpn6uf   dead   900   s
  probe-e390351eeeb5  vllm-openai       11.79 GB  machine jkwji5720pz9   dead  1810   s

The same 3.93 GB image bound ports in 39 s on one host and never moved on
another, so the variable is the host, not the image, the image size, our
dockerEntrypoint (27 bytes of env in every probe) or our env payload.  A dead
host reports desiredStatus RUNNING with uptime 0 and stays there: 1810 s of it
changed nothing.  Both healthy hosts were ready inside 40 s.

So a longer cutoff buys nothing and a wider draw buys everything.  v11 keeps
every v10 contract -- one R2 upload outside the host loop, deny-list child env,
the v4 observability driver, the watchdog started before the paid create, the
v4 qualifier bytes and READY untouched -- and changes exactly two numbers:

  STARTUP_TIMEOUT_SECONDS  600 -> 360   fast-fail; 9x the slowest healthy start,
                                        and 2.4x the 150 s a cold 11.79 GB pull
                                        implies at the throughput 3.93 GB/39 s shows
  MAX_STARTUP_ATTEMPTS       4 ->   7   more draws for the same wall-clock budget

Worst-case startup spend is 7 x 360 s = 42 min, within a rounding error of
v10's 4 x 600 s = 40 min, for 7 host draws instead of 4.

It also swaps the RunPod transport for an in-process httpx one.  `RunPodCurlTransport`
spawns curl for every call, and this host's commit charge is thin enough that
`CreateProcess` intermittently fails: WinError 8 leaked probe Pod
`b3rk1h2v9ciis2`, and WinError 1455 killed a v11 run inside `verify_deleted`
after 2 host draws.  A campaign that dies at a random RunPod call is a campaign
that can abandon a billing Pod, so the calls stop needing a child process.
`RunPodHttpxTransport` keeps the same allowlist, validation, status codes and
error strings — including "transport failure", which `create_once_or_reconcile`
keys on to reconcile an ambiguous create instead of retrying it.

Beyond that this wrapper re-implements nothing.  It rebinds constants on the v10
module and calls v10.main(), so the audited create, reconciliation, cleanup and
receipt paths are the same code that ran in run-72ff5d21f453.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runpod_httpx_transport import RunPodHttpxTransport

V10_PATH = Path(__file__).with_name("run_stage1_v29_r2_v10_runtime_ready.py")
_spec = importlib.util.spec_from_file_location("stage1_v10_for_v11", V10_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v10 module cannot be loaded")
v10 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v10
_spec.loader.exec_module(v10)

# Re-derived from the four probe receipts named in the module docstring, not
# tuned to make a run pass.  Both healthy hosts were ready in under 40 s; both
# dead hosts were unchanged at 900 s and 1810 s.
STARTUP_TIMEOUT_SECONDS = 360
MAX_STARTUP_ATTEMPTS = 7

# Evidence pointers, so a reader can check the numbers without this docstring.
STARTUP_BUDGET_EVIDENCE = (
    ".chatgpt2codex/formal-runtime-v29/startup-probe/probe-3b32d03f6a2c/probe-receipt.json",
    ".chatgpt2codex/formal-runtime-v29/startup-probe/probe-ceafa5645cd5/probe-receipt.json",
    ".chatgpt2codex/formal-runtime-v29/startup-probe/probe-bc67c22be6d1/probe-receipt.json",
    ".chatgpt2codex/formal-runtime-v29/startup-probe/probe-e390351eeeb5/probe-receipt.json",
)


CREATE_5XX_ATTEMPTS = 3
# Seconds between create retries. Separate from the attempt count because the two
# answer different questions: how many times to ask, and how long the thing being
# waited on takes to change. A transient 500 clears in seconds; GPU capacity does
# not, so a caller waiting for capacity raises the delay, not just the count.
CREATE_5XX_DELAY_SECONDS = 5

# The 1.11 GB bundle upload is the third thing this host's exhausted commit
# charge has broken, after CreateProcess (WinError 8, which leaked a Pod) and
# WinError 1455 (which killed a run inside verify_deleted). This time botocore
# raised MemoryError while buffering for the upload checksum, with 2.6 GB of
# commit left against a 47.9 GB limit.
#
# v7 asks for 64 MB parts at concurrency 8, so roughly half a gigabyte can be in
# flight at once. Nothing needs that: the upload is one file, once, before any
# GPU is rented, and its duration is irrelevant to the campaign budget. Smaller
# parts trade upload speed -- which costs nothing here -- for headroom, which is
# what actually runs out.
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_CONCURRENCY = 2

# Bound at import, before main() patches the attribute -- reading it at call time
# would resolve to the wrapper itself and recurse forever.
_ORIGINAL_CREATE = v10.base.create_once_or_reconcile
_ORIGINAL_TRANSFER_CONFIG = v10.base.TransferConfig


def frugal_transfer_config(**kwargs: object) -> object:
    """v7's TransferConfig with the two memory-relevant knobs turned down.

    Patched at the class rather than at the call site so `r2_upload_bundle`
    itself stays exactly the audited v7 function: same file, same ExtraArgs,
    same sha256 metadata, same head_object verification, same presign.
    """
    overridden = dict(kwargs)
    overridden["multipart_chunksize"] = UPLOAD_CHUNK_BYTES
    overridden["max_concurrency"] = UPLOAD_CONCURRENCY
    if kwargs.get("multipart_threshold"):
        overridden["multipart_threshold"] = min(
            int(kwargs["multipart_threshold"]), UPLOAD_CHUNK_BYTES  # type: ignore[arg-type]
        )
    print(
        f"[v11] R2 upload: {UPLOAD_CHUNK_BYTES // (1024 * 1024)} MB parts x "
        f"{UPLOAD_CONCURRENCY} (v7 asked for "
        f"{int(kwargs.get('multipart_chunksize', 0)) // (1024 * 1024)} MB x "
        f"{kwargs.get('max_concurrency')}); this host has run out of commit "
        "charge three times tonight",
        flush=True,
    )
    return _ORIGINAL_TRANSFER_CONFIG(**overridden)


def create_tolerating_server_errors(
    transport: object, *, payload: dict[str, object], name: str
) -> tuple[dict[str, object], bool]:
    """Survive RunPod's intermittent 500s on POST /v1/pods.

    Two campaign launches died on a single 500 that a retry seconds later did
    not reproduce -- the same payload and image created a Pod on the next try.
    v10's host loop calls create_once_or_reconcile with no handler, so one
    transient server error throws away every remaining host draw.

    This is not a blind retry.  It follows the rule the v9 critique set for an
    ambiguous POST: reconcile by unique name first, and only try again once the
    inventory has proved that no Pod was created.  If one WAS created, it is
    adopted and reported as reconciled, never duplicated.
    """
    last: RuntimeError | None = None
    for attempt in range(CREATE_5XX_ATTEMPTS):
        try:
            return _ORIGINAL_CREATE(transport, payload=payload, name=name)
        except RuntimeError as exc:
            if "failed with status 5" not in str(exc):
                raise
            last = exc
            existing = transport.reconcile_unique_pod(name)  # type: ignore[attr-defined]
            if existing is not None:
                print(f"[v11] create 5xx but Pod exists; adopting {name}", flush=True)
                return existing, True
            print(
                f"[v11] create 5xx attempt {attempt + 1}/{CREATE_5XX_ATTEMPTS}, "
                f"inventory confirms no Pod was created",
                flush=True,
            )
            time.sleep(CREATE_5XX_DELAY_SECONDS)
    assert last is not None
    raise last


def main() -> int:
    v10.STARTUP_TIMEOUT_SECONDS = STARTUP_TIMEOUT_SECONDS
    v10.MAX_STARTUP_ATTEMPTS = MAX_STARTUP_ATTEMPTS
    # Both bindings matter: v10 builds its own candidates, and the v7 base builds
    # one in read_runpod_key. A curl transport left anywhere reintroduces the
    # child-process dependency this wrapper exists to remove.
    v10.RunPodCurlTransport = RunPodHttpxTransport
    v10.base.RunPodCurlTransport = RunPodHttpxTransport
    # v10's host loop resolves this through `base`, so patching the attribute is
    # enough; the original stays reachable inside the wrapper.
    v10.base.create_once_or_reconcile = create_tolerating_server_errors
    v10.base.TransferConfig = frugal_transfer_config
    print("[v11] transport=httpx (no child process per RunPod call)", flush=True)
    print(
        f"[v11] startup_timeout={STARTUP_TIMEOUT_SECONDS}s "
        f"max_attempts={MAX_STARTUP_ATTEMPTS} "
        f"worst_case_startup_minutes={STARTUP_TIMEOUT_SECONDS * MAX_STARTUP_ATTEMPTS / 60:.0f}",
        flush=True,
    )
    return int(v10.main())


if __name__ == "__main__":
    raise SystemExit(main())
