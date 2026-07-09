#!/usr/bin/env bash
set -euo pipefail

BUNDLE_PATH="${1:-}"
CHECKSUM_PATH="${2:-}"

if [[ -z "${BUNDLE_PATH}" || -z "${CHECKSUM_PATH}" ]]; then
  echo "Usage: deploy/native/verify-source-bundle.sh <bundle-path> <checksum-path>" >&2
  exit 64
fi

[[ -f "${BUNDLE_PATH}" ]] || { echo "Bundle not found: ${BUNDLE_PATH}" >&2; exit 1; }
[[ -f "${CHECKSUM_PATH}" ]] || { echo "Checksum file not found: ${CHECKSUM_PATH}" >&2; exit 1; }

path_is_allowed() {
  local path="$1"
  path="${path#./}"
  path="${path%/}"

  case "${path}" in
    ""|bundle-manifest.txt|app|deploy|deploy/native|docs|nginx) return 0 ;;
    app/*|deploy/native/*|nginx/*) return 0 ;;
    main.py|pyproject.toml|uv.lock|.python-version) return 0 ;;
    docs/native-linux-deploy-guide.md|docs/deploy-runbook.md) return 0 ;;
    *) return 1 ;;
  esac
}

path_is_denied() {
  local path="$1"
  path="${path#./}"

  case "${path}" in
    /*|..|../*|*/../*|*/..) return 0 ;;
    .env|.env.*|*/.env|*/.env.*) return 0 ;;
    .venv|.venv/*|*/.venv|*/.venv/*) return 0 ;;
    .pytest_cache|.pytest_cache/*|*/.pytest_cache|*/.pytest_cache/*) return 0 ;;
    .ruff_cache|.ruff_cache/*|*/.ruff_cache|*/.ruff_cache/*) return 0 ;;
    __pycache__|__pycache__/*|*/__pycache__|*/__pycache__/*) return 0 ;;
    *.pyc|*.pyo) return 0 ;;
    attachments|attachments/*|*/attachments|*/attachments/*) return 0 ;;
    topis_attachments|topis_attachments/*|*/topis_attachments|*/topis_attachments/*) return 0 ;;
    topis_cache|topis_cache/*|*/topis_cache|*/topis_cache/*) return 0 ;;
    *.db|*.sqlite|*.sqlite3|*.key|*.pem|id_rsa|*/id_rsa|credentials.json|*/credentials.json) return 0 ;;
    *-image.tar|*-image.tar.gz|*.image.tar|*.image.tar.gz) return 0 ;;
    *) return 1 ;;
  esac
}

bundle_dir="$(dirname "${BUNDLE_PATH}")"
(
  cd "${bundle_dir}"
  sha256sum -c "$(basename "${CHECKSUM_PATH}")"
)

tar_list="$(mktemp)"
manifest_file="$(mktemp)"
manifest_list="$(mktemp)"
cleanup() {
  rm -f -- "${tar_list}" "${manifest_file}" "${manifest_file}.raw" "${manifest_list}"
}
trap cleanup EXIT

tar -tzf "${BUNDLE_PATH}" | sed 's#^\./##' | sort > "${tar_list}"

if ! grep -Fxq bundle-manifest.txt "${tar_list}"; then
  echo "bundle-manifest.txt is missing from source bundle" >&2
  exit 1
fi

while IFS= read -r path; do
  [[ -n "${path}" ]] || continue
  if path_is_denied "${path}"; then
    echo "Denied path found in source bundle: ${path}" >&2
    exit 1
  fi
  if ! path_is_allowed "${path}"; then
    echo "Path outside source bundle allowlist: ${path}" >&2
    exit 1
  fi
done < "${tar_list}"

if tar -xOzf "${BUNDLE_PATH}" bundle-manifest.txt > "${manifest_file}.raw" 2>/dev/null; then
  :
else
  tar -xOzf "${BUNDLE_PATH}" ./bundle-manifest.txt > "${manifest_file}.raw"
fi

sed 's#^\./##' "${manifest_file}.raw" | sort > "${manifest_file}"
awk 'NF && $0 !~ /\/$/' "${tar_list}" > "${manifest_list}"

if ! diff -u "${manifest_file}" "${manifest_list}" >/dev/null; then
  echo "bundle-manifest.txt does not match packaged file list" >&2
  exit 1
fi

echo "Verified source bundle: ${BUNDLE_PATH}"
