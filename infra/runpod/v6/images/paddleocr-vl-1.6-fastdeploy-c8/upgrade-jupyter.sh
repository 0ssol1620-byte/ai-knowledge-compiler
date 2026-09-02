#!/bin/sh
# Upgrade the Jupyter packages the base image ships, where they actually live.
#
# The Trivy scan located the vulnerable copy exactly:
#   usr/local/lib/python3.12/dist-packages/jupyter_server-2.17.0.dist-info
#
# The previous inline attempt ran `python3 -m pip install ... 2>/dev/null ||
# true`, finished in 1.7 seconds, printed success, and left 2.17.0 in place.
# Two defects: `python3` need not be the interpreter that owns dist-packages,
# and swallowing stderr behind `|| true` made that impossible to notice. A
# check that cannot fail is not a check.
#
# This script is deliberately strict. It fails the build if the upgrade does
# not take, and is a no-op only when the package is genuinely absent -- so a
# future base image that drops Jupyter does not break, but one that ships a
# vulnerable copy cannot pass silently.
#
# --no-deps is required: this must not move any pinned runtime package. The
# pin re-assertion later in the Dockerfile independently verifies that.
set -eu

FLOOR_MAJOR=2
FLOOR_MINOR=20
FLOOR_PATCH=0

if ! command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12 not present; nothing to upgrade"
    exit 0
fi

if ! python3.12 -m pip show jupyter-server >/dev/null 2>&1; then
    echo "jupyter-server absent from python3.12; nothing to upgrade"
    exit 0
fi

before="$(python3.12 -m pip show jupyter-server | awk '/^Version:/ {print $2}')"
echo "jupyter-server before: ${before}"

python3.12 -m pip install --no-cache-dir --quiet --no-deps --upgrade \
    'jupyter-server>=2.20.0' 'jupyterlab>=4.5.7' 'notebook>=7.5.6'

after="$(python3.12 -m pip show jupyter-server | awk '/^Version:/ {print $2}')"
echo "jupyter-server after:  ${after}"

python3.12 - "$after" "$FLOOR_MAJOR" "$FLOOR_MINOR" "$FLOOR_PATCH" <<'PY'
import sys

raw, *floor = sys.argv[1:]
want = tuple(int(x) for x in floor)
got = tuple(int(p) for p in raw.split(".")[:3] if p.isdigit())
if got < want:
    sys.exit(
        f"jupyter-server {raw} is below the required "
        f"{'.'.join(str(n) for n in want)} (GHSA-fcw5-x6j4-ccmp)"
    )
print(f"jupyter-server {raw} clears GHSA-fcw5-x6j4-ccmp")
PY
