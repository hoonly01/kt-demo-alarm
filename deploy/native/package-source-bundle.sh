#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

OUTPUT_DIR="${1:-${REPO_ROOT}/release-artifact}"
BUNDLE_NAME="${BUNDLE_NAME:-source-bundle.tar.gz}"
CHECKSUM_NAME="${CHECKSUM_NAME:-source-bundle.sha256}"

mkdir -p "${OUTPUT_DIR}"

staging_dir="$(mktemp -d)"
trap 'rm -rf -- "${staging_dir}"' EXIT

source_paths=(
  app
  main.py
  pyproject.toml
  uv.lock
  .python-version
  deploy/native
  docs/native-linux-deploy-guide.md
  docs/docker-free-fastapi-deploy-runbook.md
)

if [[ -d "${REPO_ROOT}/nginx" ]]; then
  source_paths+=(nginx)
fi

for path in "${source_paths[@]}"; do
  if [[ ! -e "${REPO_ROOT}/${path}" ]]; then
    echo "Missing bundle path: ${path}" >&2
    exit 1
  fi
done

tar \
  --exclude='__pycache__' \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='.venv' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='*.pem' \
  -cf - -C "${REPO_ROOT}" "${source_paths[@]}" | tar -xf - -C "${staging_dir}"

denied_paths="$(
  find "${staging_dir}" \
    \( -name '.env' -o -name '.env.*' -o -name '.venv' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \
       -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \
       -o -name 'attachments' -o -name 'topis_attachments' -o -name 'topis_cache' \
       -o -name '*.key' -o -name '*.pem' -o -name 'id_rsa' -o -name 'credentials.json' \
       -o -name '*-image.tar' -o -name '*-image.tar.gz' -o -name '*.image.tar' -o -name '*.image.tar.gz' \) \
    -print
)"
if [[ -n "${denied_paths}" ]]; then
  echo "Denied files present in source bundle staging area:" >&2
  echo "${denied_paths}" >&2
  exit 1
fi

(
  cd "${staging_dir}"
  find . -mindepth 1 \( -type f -o -type l \) \
    | sed 's#^\./##' \
    | sort > bundle-manifest.txt
  tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -czf "${OUTPUT_DIR}/${BUNDLE_NAME}" .
)

sha256sum "${OUTPUT_DIR}/${BUNDLE_NAME}" > "${OUTPUT_DIR}/${CHECKSUM_NAME}"

if ! tar -tzf "${OUTPUT_DIR}/${BUNDLE_NAME}" | sed 's#^\./##' | grep -Fxq bundle-manifest.txt; then
  echo "bundle-manifest.txt is missing from ${BUNDLE_NAME}" >&2
  exit 1
fi

echo "Created ${OUTPUT_DIR}/${BUNDLE_NAME}"
echo "Created ${OUTPUT_DIR}/${CHECKSUM_NAME}"
