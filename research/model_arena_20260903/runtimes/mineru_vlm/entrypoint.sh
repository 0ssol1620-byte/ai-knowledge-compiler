#!/usr/bin/env bash
# MinerU VLM - arena runtime entrypoint (ARENA_CONTRACT.md section 11.3 item 5).
#
# One entrypoint for both modes. The baked image sets
# ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]; in bootstrap mode the B2
# start command extracts the bundle, symlinks /opt/arena/runtime ->
# /opt/arena/runtimes/mineru_vlm, and runtimes/mineru_vlm/bootstrap.sh execs
# this file. Nothing below knows or cares which of the two happened.
#
# ARENA_CONTRACT D19 - process ownership. This runtime starts NO model server:
# MinerU runs in-process through mineru.cli.common.do_parse inside the adapter,
# with no vLLM/paddlex service and no loopback port. D19 keeps `exec` for
# in-process inference - there is no server process to poll, to trap, or to
# orphan - so the entrypoint hands straight over to the worker server and the
# worker's exit code is this container's exit code by construction.
#
# MASTERPLAN SECTION 14: concurrency 1 per worker, replicas only. Nothing here
# raises it and adapter.load() refuses any other value.

set -euo pipefail

export ARENA_MODEL_KEY="mineru_vlm"
export ARENA_RUNTIME_DIR="${ARENA_RUNTIME_DIR:-/opt/arena/runtime}"
export PYTHONPATH="${PYTHONPATH:-/opt/arena}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
export ARENA_WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/opt/arena/weights/mineru_vlm}"
export MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-local}"
export MINERU_TOOLS_CONFIG_JSON="${MINERU_TOOLS_CONFIG_JSON:-/opt/arena/mineru.json}"
export MINERU_API_MAX_CONCURRENT_REQUESTS="${MINERU_API_MAX_CONCURRENT_REQUESTS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

for required in runtime.json adapter.py canonical.py; do
  if [ ! -f "${ARENA_RUNTIME_DIR}/${required}" ]; then
    echo "entrypoint: ${ARENA_RUNTIME_DIR}/${required} is missing; refusing to start" >&2
    exit 1
  fi
done

exec "${PYTHON_BIN}" -m arena.worker.server
