"""Give RunPod credentials for the private GHCR images.

Diagnosed by measurement, not inference:

  GHCR visibility        private (both images)
  registry auth in spec  0 occurrences

RunPod cannot pull either image. It tries, GHCR answers 401 because the
package is private, and the platform kills the container -- which is exactly
what was observed three times running:

  desiredStatus:    EXITED
  lastStatusChange: "Exited by Runpod: ..."
  uptimeInSeconds:  null

sshd never had a chance to start, so "never became reachable" was accurate but
described a symptom two layers from the cause. No amount of extra wait time or
container disk would have helped.

This registers a container registry credential with RunPod and attaches it to
the pod spec via containerRegistryAuthId.

Why a stored credential rather than making the packages public: these images
carry the frozen model weights and the rebuilt fastdeploy wheel. Publishing
them to make a scan pass would be the same class of shortcut as lowering the
severity gate -- convenient, and it changes what the artifact is.

The GitHub token is read from the credentials file and never printed. The
created credential's id is printed; the secret is not.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CRED = Path(r"D:\Github_API.txt")
REST = "https://rest.runpod.io/v1"
NAME = "folynta-ghcr-readonly"


def secret(label: str) -> str:
    for line in CRED.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(label):
            return line.split(":", 1)[1].strip()
    raise SystemExit(f"{label} not found in the credentials file")


def call(k: str, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        REST + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {k}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    rp = secret("Runpod_B:")
    gh = secret("Github:")

    status, existing = call(rp, "GET", "/containerregistryauth")
    print(f"list existing: HTTP {status}")
    if isinstance(existing, dict):
        existing = existing.get("data") or existing.get("items") or []
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict) and item.get("name") == NAME:
                print(f"reusing credential {item.get('id')} ({NAME})")
                print(f"CREDENTIAL_ID={item.get('id')}")
                return 0

    status, created = call(
        rp,
        "POST",
        "/containerregistryauth",
        {"name": NAME, "username": "0ssol1620-byte", "password": gh},
    )
    print(f"create: HTTP {status}")
    if status not in (200, 201) or not isinstance(created, dict):
        print(json.dumps(created, indent=2)[:800] if created else "<no body>")
        return 1

    cred_id = created.get("id")
    if not cred_id:
        print(json.dumps(created, indent=2)[:800])
        return 1

    print(f"created credential {cred_id} ({NAME})")
    print(f"CREDENTIAL_ID={cred_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
