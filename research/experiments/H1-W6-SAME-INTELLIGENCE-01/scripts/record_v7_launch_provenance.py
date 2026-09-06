#!/usr/bin/env python3
"""Pin the exact provenance of the v7 acquisition run.

Exact historical invocation recovery is this programme's weakest reproducibility
result: 1 of 23 experiments has a recoverable original command. That number is
not repairable backwards, so the only thing that can be done about it is to stop
adding to it. Every run from here is recorded completely at launch.

This records the run as launched -- argv, resolved absolute paths, the hashes of
every frozen input, the process identity, and where the completion sidecar is
expected to appear. It deliberately records the *expected* sidecar path rather
than its contents: at the time of writing the run has not finished, and writing
an outcome here would be the inference-as-measurement defect this programme has
recorded five times.

Offline. Reads only.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent

ARGV = [
    "python",
    str(EXP / "scripts" / "acquire_w6_v5_single_title.py"),
    "acquire",
    "--manifest",
    str(EXP / "receipts" / "title-manifest-v3-2026-08-19.json"),
    "--seal",
    str(EXP / "receipts" / "single-title-freeze-v5-2026-08-19.json"),
    "--corpus",
    str(EXP / "corpus-v7"),
    "--output",
    str(EXP / "receipts" / "acquisition-v7-2026-08-19.json"),
    "--sidecar",
    str(EXP / "receipts" / "acquisition-v7-completion-2026-08-19.json"),
]

PID = 33784
STARTED_LOCAL = "2026-08-19T16:27:44"


def sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    manifest = EXP / "receipts" / "title-manifest-v3-2026-08-19.json"
    seal = EXP / "receipts" / "single-title-freeze-v5-2026-08-19.json"
    wrapper = EXP / "scripts" / "acquire_w6_v5_single_title.py"
    sealed = EXP / "scripts" / "acquire_w6_v3.py"
    v3_protocol = EXP / "PROTOCOL_V3_ACQUISITION_2026-08-19.md"
    v5_protocol = EXP / "PROTOCOL_V5_SINGLE_TITLE_TRANSPORT_2026-08-19.md"
    v6_protocol = EXP / "PROTOCOL_V6_RECOVERY_2026-08-19.md"

    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v7-launch-provenance.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "why_this_exists": (
            "Exact historical invocation recovery stands at 1 of 23 experiments. That is "
            "not repairable backwards; the only available response is to record every "
            "subsequent run completely. This is that record for the v7 acquisition."
        ),
        "invocation": {
            "argv": ARGV,
            "argv_shell": " ".join(f'"{a}"' if " " in a else a for a in ARGV),
            "cwd_at_launch": str(Path.cwd()),
            "corpus_path_absolute": str(EXP / "corpus-v7"),
            "corpus_path_is_absolute": (EXP / "corpus-v7").is_absolute(),
            "why_absolute_matters": (
                "A repository-relative --corpus is what raised ValueError at "
                "acquire_w6_v3.py:376 in both the v5 and v6 runs. The absolute path is the "
                "entire repair; the sealed script is byte-identical. See "
                "v6-acquisition-failure-diagnosis-2026-08-19.json."
            ),
        },
        "process_identity": {
            "pid": PID,
            "started_local": STARTED_LOCAL,
            "single_process": True,
            "note": (
                "The v5 wrapper loads the v3 acquisition as a module in-process, so one PID "
                "covers the whole run. A second acquisition process would be a duplicate-run "
                "incident, which this programme has already had once."
            ),
        },
        "frozen_input_hashes": {
            "wrapper_script": sha256_file(wrapper),
            "sealed_acquisition_script": sha256_file(sealed),
            "title_manifest_file": sha256_file(manifest),
            "title_manifest_receipt_sha256": manifest_doc.get("receipt_sha256"),
            "single_title_freeze_seal": sha256_file(seal),
            "protocol_v3_acquisition": sha256_file(v3_protocol),
            "protocol_v5_single_title_transport": sha256_file(v5_protocol),
            "protocol_v6_recovery": sha256_file(v6_protocol),
        },
        "seal_binding": (
            "The wrapper verifies the seal before fetching anything and exits with "
            "'frozen bytes changed: <key>' on any mismatch. The run therefore could not "
            "have started unless the hashes above matched the seal."
        ),
        "manifest_facts": {
            "schema": manifest_doc.get("schema"),
            "titles_in_manifest": len(manifest_doc.get("titles", [])),
            "source_category": manifest_doc.get("source_category"),
        },
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "tz_env": os.environ.get("TZ"),
        },
        "expected_outputs": {
            "corpus_root": str(EXP / "corpus-v7"),
            "acquisition_receipt": str(EXP / "receipts" / "acquisition-v7-2026-08-19.json"),
            "completion_sidecar": str(
                EXP / "receipts" / "acquisition-v7-completion-2026-08-19.json"
            ),
        },
        "run_state_at_record_time": "RUNNING",
        "outcome_deliberately_absent": (
            "The run has not finished. Recording an expected outcome here would be the "
            "inference-promoted-to-measurement defect this programme has now recorded "
            "five times. The completion sidecar is the only thing that may report an "
            "outcome, and the integrity gates run before any endpoint evaluation."
        ),
        "network_access": True,
        "network_access_note": "the acquisition itself fetches; this recording script does not",
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()

    out = EXP / "receipts" / "v7-launch-provenance-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"pid {PID}  corpus {EXP / 'corpus-v7'}")
    print(f"sealed script {receipt['frozen_input_hashes']['sealed_acquisition_script'][:26]}...")
    print(f"titles in manifest: {receipt['manifest_facts']['titles_in_manifest']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
