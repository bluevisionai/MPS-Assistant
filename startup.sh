#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DATA_DIR="${APP_ROOT}/deploy_data"
RUNTIME_DATA_DIR="${DATA_DIR:-/home/site/data}"
BUNDLE_PATH="${DEPLOY_DATA_DIR}/mps_data_bundle.tgz"

hydrate_deploy_data_if_present() {
  if [[ ! -d "${DEPLOY_DATA_DIR}" ]]; then
    return
  fi

  if [[ ! -f "${BUNDLE_PATH}" ]]; then
    return
  fi

  echo "Found deploy_data bundle, hydrating runtime data in ${RUNTIME_DATA_DIR}"
  rm -rf "${RUNTIME_DATA_DIR}"
  mkdir -p "${RUNTIME_DATA_DIR}"

  tar -xzf "${BUNDLE_PATH}" -C "${RUNTIME_DATA_DIR}"
}

hydrate_deploy_data_if_present

exec "${PYTHON:-python}" -m gunicorn \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout "${GUNICORN_TIMEOUT:-600}" \
  mps_assistant.app:app
