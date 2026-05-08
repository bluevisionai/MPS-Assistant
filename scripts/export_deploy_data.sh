#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DATA_DIR="${1:-${ROOT_DIR}/data}"
DEPLOY_DATA_DIR="${ROOT_DIR}/deploy_data"
BUNDLE_NAME="mps_data_bundle.tgz"
BUNDLE_PATH="${DEPLOY_DATA_DIR}/${BUNDLE_NAME}"
STAGE_DIR="${DEPLOY_DATA_DIR}/.stage"

DB_FILE="${SOURCE_DATA_DIR}/mps_assistant.db"
RAW_DIR="${SOURCE_DATA_DIR}/raw"
UPLOADS_DIR="${SOURCE_DATA_DIR}/uploads"

if [[ ! -f "${DB_FILE}" ]]; then
  echo "Expected database not found: ${DB_FILE}" >&2
  exit 1
fi

mkdir -p "${DEPLOY_DATA_DIR}"
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"

cp "${DB_FILE}" "${STAGE_DIR}/mps_assistant.db"

if [[ -d "${RAW_DIR}" ]]; then
  cp -R "${RAW_DIR}" "${STAGE_DIR}/raw"
else
  mkdir -p "${STAGE_DIR}/raw"
fi

if [[ -d "${UPLOADS_DIR}" ]]; then
  cp -R "${UPLOADS_DIR}" "${STAGE_DIR}/uploads"
else
  mkdir -p "${STAGE_DIR}/uploads"
fi

# Remove local SQLite transient files if present.
find "${STAGE_DIR}" -type f \( -name '*.db-wal' -o -name '*.db-shm' -o -name '*.sqlite-wal' -o -name '*.sqlite-shm' \) -delete

tar -czf "${BUNDLE_PATH}" -C "${STAGE_DIR}" .
rm -rf "${STAGE_DIR}"

generated_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
raw_count="$(find "${RAW_DIR}" -type f 2>/dev/null | wc -l | tr -d ' ')"
upload_count="$(find "${UPLOADS_DIR}" -type f 2>/dev/null | wc -l | tr -d ' ')"
bundle_size="$(stat -f %z "${BUNDLE_PATH}")"

cat > "${DEPLOY_DATA_DIR}/manifest.json" <<EOF
{
  "generated_at_utc": "${generated_at}",
  "source_data_dir": "data",
  "bundle": "${BUNDLE_NAME}",
  "bundle_size_bytes": ${bundle_size},
  "raw_file_count": ${raw_count},
  "upload_file_count": ${upload_count}
}
EOF

echo "Deploy data exported to ${DEPLOY_DATA_DIR}"
echo "Bundle: ${BUNDLE_PATH}"
echo "Raw files: ${raw_count}"
echo "Upload files: ${upload_count}"
