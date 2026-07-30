# Supply-chain pinning

`verified-pins.json` records the immutable references used by production/build
Dockerfiles and GitHub Actions. Container digests were verified against the raw
registry manifest bytes; action SHAs were resolved from exact upstream version
tags and checked as commit objects. Updating a tag requires repeating that
verification and changing the pin record, source reference, and version comment
in one review.

The root Python application and GPU runtime use separate `uv.lock` files.
Images and CI must run `uv sync --locked`; production images exclude development
dependencies. A pinned `uv==0.12.0` bootstrap is the only allowed pre-lock Python
installation.

`docker-compose.dev.yml` intentionally retains readable upstream tags because it
is a loopback-only development stack, not a promotion artifact. The API,
scheduler, web, GPU, CI PostgreSQL, and operational-drill images do not receive
that exception.
