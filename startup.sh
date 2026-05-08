#!/usr/bin/env bash
set -euo pipefail

exec "${PYTHON:-python}" -m gunicorn \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout "${GUNICORN_TIMEOUT:-600}" \
  mps_assistant.app:app
