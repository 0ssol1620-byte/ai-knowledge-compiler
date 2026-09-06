#!/usr/bin/env python3
from __future__ import annotations

import os
import time
import urllib.request

URL = "https://api.github.com/repos/octocat/Hello-World"


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("credential absent")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tavonel-post-terminal-diagnostic/1.0",
    }
    remaining: list[int] = []
    request_ids: list[bool] = []
    for _ in range(10):
        request = urllib.request.Request(URL, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            remaining.append(int(response.headers["x-ratelimit-remaining"]))
            request_ids.append(bool(response.headers.get("x-github-request-id")))
            response.read()
        time.sleep(0.4)
    deltas = [remaining[index - 1] - remaining[index] for index in range(1, len(remaining))]
    print("DELTAS=" + ",".join(map(str, deltas)))
    print("ALL_UNIT_DELTAS=" + str(all(delta == 1 for delta in deltas)))
    print("ALL_REQUEST_IDS=" + str(all(request_ids)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
