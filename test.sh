#!/usr/bin/env bash
# Runs the tests. The upstream is faked in-process, so they never touch the
# network and pass whatever FX_UPSTREAM_BASE points at.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  "${PYTHON:-python3}" -m venv .venv
fi
if ! .venv/bin/python -c "import fastapi, uvicorn, httpx, pytest" 2>/dev/null; then
  .venv/bin/pip install --quiet -r requirements-dev.txt
fi

exec .venv/bin/python -m pytest -q "$@"
