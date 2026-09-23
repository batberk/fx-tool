#!/usr/bin/env bash
# Starts the service on $PORT (default 8080). The app reads the upstream base
# URL from $FX_UPSTREAM_BASE; nothing here hardcodes frankfurter.dev.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  "${PYTHON:-python3}" -m venv .venv
fi
# Only install when something is missing, so later runs work offline.
if ! .venv/bin/python -c "import fastapi, uvicorn, httpx" 2>/dev/null; then
  .venv/bin/pip install --quiet -r requirements.txt
fi

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
