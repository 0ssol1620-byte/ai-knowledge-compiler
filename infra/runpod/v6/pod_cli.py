"""Dry-run-first CLI for paid RunPod Pod qualification resources."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from benchmark.v6.contracts import canonical_sha256
from infra.runpod.v6.pod_client import PodCreateSpec, RunPodPodClient, write_receipt_exclusive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--receipt-out", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    create = sub.add_parser("create")
    create.add_argument("--spec", type=Path, required=True)
    get = sub.add_parser("get")
    get.add_argument("--pod-id", required=True)
    delete = sub.add_parser("delete")
    delete.add_argument("--pod-id", required=True)
    delete.add_argument("--confirm-pod-id", required=True)
    args = parser.parse_args()

    if args.command == "create":
        raw = json.loads(args.spec.read_text(encoding="utf-8-sig"))
        public_key_env = str(raw.pop("public_key_env", "")).strip()
        if public_key_env:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", public_key_env):
                raise SystemExit("public_key_env is invalid")
            raw["public_key"] = os.environ.get(public_key_env, "")
        spec = PodCreateSpec.from_mapping(raw)
        if not args.execute:
            receipt = {
                "executed": False,
                "operation": "create",
                "request_sha256": canonical_sha256(spec.redacted_identity()),
                "redacted_spec": spec.redacted_identity(),
            }
            write_receipt_exclusive(args.receipt_out, receipt)
            return 0
    elif not args.execute:
        write_receipt_exclusive(args.receipt_out, {"executed": False, "operation": args.command})
        return 0

    client = RunPodPodClient.from_environment()
    try:
        if args.command == "inventory":
            payload = {"operation": "inventory", "pods": client.list_pods()}
        elif args.command == "create":
            payload = {"operation": "create", "pod": client.create_pod(spec)}
        elif args.command == "get":
            payload = {"operation": "get", "pod": client.get_pod(args.pod_id)}
        else:
            if args.pod_id != args.confirm_pod_id:
                raise SystemExit("delete confirmation does not match pod_id")
            payload = {"operation": "delete", **client.delete_pod(args.pod_id)}
    finally:
        client.close()
    write_receipt_exclusive(args.receipt_out, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
