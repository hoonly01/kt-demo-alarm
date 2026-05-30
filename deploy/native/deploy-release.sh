#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-kt-demo-alarm}"
APP_ROOT="${APP_ROOT:-/opt/kt-demo-alarm}"
RELEASE_ID="${RELEASE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RELEASES_DIR="${RELEASES_DIR:-${APP_ROOT}/releases}"
CURRENT_LINK="${CURRENT_LINK:-${APP_ROOT}/current}"
SHARED_DIR="${SHARED_DIR:-${APP_ROOT}/shared}"
DATA_DIR="${DATA_DIR:-${SHARED_DIR}/data}"
LOG_DIR="${LOG_DIR:-${SHARED_DIR}/logs}"
CACHE_DIR="${CACHE_DIR:-${SHARED_DIR}/topis_cache}"
ATTACHMENT_DIR="${ATTACHMENT_DIR:-${SHARED_DIR}/topis_attachments}"
ENV_FILE="${ENV_FILE:-${SHARED_DIR}/.env}"
APP_USER="${APP_USER:-${APP_NAME}}"
APP_GROUP="${APP_GROUP:-${APP_USER}}"
APP_BIND_HOST="${APP_BIND_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
DATABASE_PATH="${DATABASE_PATH:-${DATA_DIR}/kt_demo_alarm.db}"
CACHE_FILE="${CACHE_FILE:-${CACHE_DIR}/topis_cache.json}"
ATTACHMENT_FOLDER="${ATTACHMENT_FOLDER:-${ATTACHMENT_DIR}}"
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-${SHARED_DIR}/ms-playwright}"
TZ="${TZ:-Asia/Seoul}"
SERVICE_UNIT_PATH="${SERVICE_UNIT_PATH:-/etc/systemd/system/${APP_NAME}.service}"
RELEASE_KEEP="${RELEASE_KEEP:-5}"
HEALTH_URL="${HEALTH_URL:-http://${APP_BIND_HOST}:${APP_PORT}/}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"
HEALTH_INTERVAL_SECONDS="${HEALTH_INTERVAL_SECONDS:-3}"
ALLOW_PORT_TAKEOVER="${ALLOW_PORT_TAKEOVER:-false}"
ALLOW_DOCKER_CUTOVER="${ALLOW_DOCKER_CUTOVER:-false}"
CHOWN_SHARED_DIRS="${CHOWN_SHARED_DIRS:-true}"
UV_BIN="${UV_BIN:-uv}"
ENV_BIN="${ENV_BIN:-/usr/bin/env}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
SYSTEMD_ANALYZE_BIN="${SYSTEMD_ANALYZE_BIN:-systemd-analyze}"
SUDO_BIN="${SUDO_BIN:-sudo}"
BUNDLE_PATH="${BUNDLE_PATH:-}"
CHECKSUM_PATH="${CHECKSUM_PATH:-}"

RELEASE_DIR="${RELEASES_DIR}/${RELEASE_ID}"
UNIT_CANDIDATE="${RELEASE_DIR}/${APP_NAME}.service.candidate"
PREVIOUS_CURRENT=""
DEPLOY_PHASE="pre-switch"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  printf '[%s] ERROR: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
  exit 1
}

is_truthy() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    "${SUDO_BIN}" "$@"
  fi
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[&|\]/\\&/g'
}

safe_release_path() {
  local path="$1"
  [[ "${path}" == "${RELEASES_DIR}/"* ]] || fail "Refusing to modify non-release path: ${path}"
  [[ "${path}" != "${RELEASES_DIR}" ]] || fail "Refusing to modify releases root"
}

safe_remove_release_dir() {
  local path="$1"
  safe_release_path "${path}"
  if [[ -d "${path}" ]]; then
    rm -r -- "${path}"
  fi
}

cleanup_pre_switch_failure() {
  local status=$?
  if [[ "${status}" -ne 0 && "${DEPLOY_PHASE}" == "pre-switch" && -d "${RELEASE_DIR}" ]]; then
    log "Cleaning failed pre-switch release directory: ${RELEASE_DIR}"
    safe_remove_release_dir "${RELEASE_DIR}" || true
  fi
  exit "${status}"
}

trap cleanup_pre_switch_failure EXIT

validate_inputs() {
  [[ -n "${BUNDLE_PATH}" ]] || fail "BUNDLE_PATH is required"
  [[ -n "${CHECKSUM_PATH}" ]] || fail "CHECKSUM_PATH is required"
  [[ -f "${BUNDLE_PATH}" ]] || fail "Bundle not found: ${BUNDLE_PATH}"
  [[ -f "${CHECKSUM_PATH}" ]] || fail "Checksum file not found: ${CHECKSUM_PATH}"
  [[ "${RELEASE_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || fail "RELEASE_ID contains unsafe characters"
  [[ "${APP_PORT}" =~ ^[0-9]+$ ]] || fail "APP_PORT must be numeric"
  [[ "${RELEASE_KEEP}" =~ ^[0-9]+$ ]] || fail "RELEASE_KEEP must be numeric"
}

preflight_commands() {
  require_command tar
  require_command sha256sum
  require_command find
  require_command stat
  require_command sed
  require_command "${UV_BIN}"
  require_command "${ENV_BIN}"
  require_command "${SYSTEMCTL_BIN}"
  require_command "${SYSTEMD_ANALYZE_BIN}"
  if [[ "$(id -u)" -ne 0 ]]; then
    require_command "${SUDO_BIN}"
  fi
}

native_service_active() {
  "${SYSTEMCTL_BIN}" is-active --quiet "${APP_NAME}" >/dev/null 2>&1
}

preflight_runtime() {
  if command -v ss >/dev/null 2>&1 && ss -ltn "sport = :${APP_PORT}" | grep -q LISTEN; then
    if native_service_active; then
      log "Port ${APP_PORT} is already used by active ${APP_NAME}; restart is allowed."
    elif is_truthy "${ALLOW_PORT_TAKEOVER}"; then
      log "ALLOW_PORT_TAKEOVER=true; continuing despite port ${APP_PORT} listener."
    else
      fail "Port ${APP_PORT} is occupied by a non-target process. Set ALLOW_PORT_TAKEOVER=true only for an approved cutover."
    fi
  fi

  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -Eq "(^|[-_])${APP_NAME}($|[-_])"; then
    if is_truthy "${ALLOW_DOCKER_CUTOVER}"; then
      log "ALLOW_DOCKER_CUTOVER=true; continuing with an existing Docker runtime visible."
    else
      fail "Existing Docker runtime for ${APP_NAME} is visible. Set ALLOW_DOCKER_CUTOVER=true only during an approved transition."
    fi
  fi

  if ! id "${APP_USER}" >/dev/null 2>&1; then
    fail "Service user does not exist: ${APP_USER}"
  fi

  if ! getent group "${APP_GROUP}" >/dev/null 2>&1; then
    fail "Service group does not exist: ${APP_GROUP}"
  fi
}

prepare_release_dirs() {
  mkdir -p "${RELEASES_DIR}" "${SHARED_DIR}" "${DATA_DIR}" "${LOG_DIR}" "${CACHE_DIR}" "${ATTACHMENT_DIR}" "${DATA_DIR}/attachments"
  [[ ! -e "${RELEASE_DIR}" ]] || fail "Release directory already exists: ${RELEASE_DIR}"
  mkdir -p "${RELEASE_DIR}"

  if is_truthy "${CHOWN_SHARED_DIRS}"; then
    run_privileged chown -R "${APP_USER}:${APP_GROUP}" "${SHARED_DIR}"
  fi
}

verify_checksum() {
  local bundle_dir
  bundle_dir="$(dirname "${BUNDLE_PATH}")"
  (
    cd "${bundle_dir}"
    sha256sum -c "$(basename "${CHECKSUM_PATH}")"
  )
}

path_is_allowed() {
  local path="$1"
  path="${path#./}"
  path="${path%/}"

  case "${path}" in
    ""|bundle-manifest.txt|app|deploy|deploy/native|docs|nginx) return 0 ;;
    app/*|deploy/native/*|nginx/*) return 0 ;;
    main.py|pyproject.toml|uv.lock|.python-version) return 0 ;;
    docs/native-linux-deploy-guide.md|docs/docker-free-fastapi-deploy-runbook.md) return 0 ;;
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

verify_bundle_manifest() {
  local tar_list manifest_file manifest_list
  tar_list="$(mktemp)"
  manifest_file="$(mktemp)"
  manifest_list="$(mktemp)"

  tar -tzf "${BUNDLE_PATH}" | sed 's#^\./##' | sort > "${tar_list}"

  if ! grep -Fxq bundle-manifest.txt "${tar_list}"; then
    fail "bundle-manifest.txt is missing from source bundle"
  fi

  while IFS= read -r path; do
    [[ -n "${path}" ]] || continue
    if path_is_denied "${path}"; then
      fail "Denied path found in bundle: ${path}"
    fi
    if ! path_is_allowed "${path}"; then
      fail "Path outside source bundle allowlist: ${path}"
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
    rm -f -- "${tar_list}" "${manifest_file}" "${manifest_file}.raw" "${manifest_list}"
    fail "bundle-manifest.txt does not match packaged file list"
  fi

  rm -f -- "${tar_list}" "${manifest_file}" "${manifest_file}.raw" "${manifest_list}"
}

unpack_release() {
  tar -xzf "${BUNDLE_PATH}" -C "${RELEASE_DIR}"
  while IFS= read -r path; do
    rel="${path#${RELEASE_DIR}/}"
    if path_is_denied "${rel}"; then
      fail "Denied path found after unpack: ${rel}"
    fi
  done < <(find "${RELEASE_DIR}" -mindepth 1 -print)
}

create_compat_symlinks() {
  local shared_real target_real
  shared_real="$(realpath -m "${SHARED_DIR}")"

  declare -A links=(
    ["topis_attachments"]="${ATTACHMENT_DIR}"
    ["topis_cache"]="${CACHE_DIR}"
    ["data"]="${DATA_DIR}"
    ["logs"]="${LOG_DIR}"
    ["attachments"]="${DATA_DIR}/attachments"
  )

  for link_name in "${!links[@]}"; do
    local target="${links[${link_name}]}"
    local link_path="${RELEASE_DIR}/${link_name}"
    target_real="$(realpath -m "${target}")"
    [[ "${target_real}" == "${shared_real}" || "${target_real}" == "${shared_real}/"* ]] \
      || fail "Symlink target escapes shared directory: ${link_name} -> ${target}"
    [[ ! -e "${link_path}" && ! -L "${link_path}" ]] || fail "Release path already exists: ${link_path}"
    ln -s "${target}" "${link_path}"
  done
}

check_env_file() {
  [[ -f "${ENV_FILE}" ]] || fail "Server-owned env file is missing: ${ENV_FILE}"

  local mode
  mode="$(stat -c '%a' "${ENV_FILE}")"
  if (( 8#${mode} & 0027 )); then
    fail "Env file mode ${mode} is too open for ${ENV_FILE}; expected no group write/execute and no world access."
  fi

  log "Env file exists with acceptable mode ${mode}: ${ENV_FILE}"
}

sync_dependencies() {
  (
    cd "${RELEASE_DIR}"
    "${UV_BIN}" sync --frozen --no-dev
  )
}

render_systemd_unit() {
  local template="${RELEASE_DIR}/deploy/native/kt-demo-alarm.service.template"
  [[ -f "${template}" ]] || fail "systemd template missing: ${template}"

  sed \
    -e "s|__APP_USER__|$(escape_sed_replacement "${APP_USER}")|g" \
    -e "s|__APP_GROUP__|$(escape_sed_replacement "${APP_GROUP}")|g" \
    -e "s|__CURRENT_LINK__|$(escape_sed_replacement "${CURRENT_LINK}")|g" \
    -e "s|__ENV_FILE__|$(escape_sed_replacement "${ENV_FILE}")|g" \
    -e "s|__APP_BIND_HOST__|$(escape_sed_replacement "${APP_BIND_HOST}")|g" \
    -e "s|__APP_PORT__|$(escape_sed_replacement "${APP_PORT}")|g" \
    -e "s|__DATABASE_PATH__|$(escape_sed_replacement "${DATABASE_PATH}")|g" \
    -e "s|__CACHE_FILE__|$(escape_sed_replacement "${CACHE_FILE}")|g" \
    -e "s|__ATTACHMENT_FOLDER__|$(escape_sed_replacement "${ATTACHMENT_FOLDER}")|g" \
    -e "s|__LOG_DIR__|$(escape_sed_replacement "${LOG_DIR}")|g" \
    -e "s|__PLAYWRIGHT_BROWSERS_PATH__|$(escape_sed_replacement "${PLAYWRIGHT_BROWSERS_PATH}")|g" \
    -e "s|__TZ__|$(escape_sed_replacement "${TZ}")|g" \
    -e "s|__ENV_BIN__|$(escape_sed_replacement "${ENV_BIN}")|g" \
    -e "s|__UV_BIN__|$(escape_sed_replacement "${UV_BIN}")|g" \
    -e "s|__SHARED_DIR__|$(escape_sed_replacement "${SHARED_DIR}")|g" \
    "${template}" > "${UNIT_CANDIDATE}"

  "${SYSTEMD_ANALYZE_BIN}" verify "${UNIT_CANDIDATE}"
}

install_systemd_unit() {
  local unit_dir
  unit_dir="$(dirname "${SERVICE_UNIT_PATH}")"
  if [[ -w "${unit_dir}" ]]; then
    install -m 0644 "${UNIT_CANDIDATE}" "${SERVICE_UNIT_PATH}"
  else
    run_privileged install -m 0644 "${UNIT_CANDIDATE}" "${SERVICE_UNIT_PATH}"
  fi
  run_privileged "${SYSTEMCTL_BIN}" daemon-reload
}

capture_previous_current() {
  if [[ -L "${CURRENT_LINK}" ]]; then
    PREVIOUS_CURRENT="$(readlink -f "${CURRENT_LINK}")"
    log "Previous current release: ${PREVIOUS_CURRENT}"
  else
    PREVIOUS_CURRENT=""
    log "No previous current symlink exists; first native deploy rollback is limited."
  fi
}

switch_current() {
  local next_link="${CURRENT_LINK}.next"
  ln -sfn "${RELEASE_DIR}" "${next_link}"
  mv -Tf "${next_link}" "${CURRENT_LINK}"
  DEPLOY_PHASE="post-switch"
}

restart_service() {
  if native_service_active; then
    run_privileged "${SYSTEMCTL_BIN}" restart "${APP_NAME}"
  else
    run_privileged "${SYSTEMCTL_BIN}" start "${APP_NAME}"
  fi
}

rollback_after_switch() {
  local reason="$1"
  log "Post-switch failure: ${reason}"

  if [[ -n "${PREVIOUS_CURRENT}" && -d "${PREVIOUS_CURRENT}" ]]; then
    log "Restoring previous current symlink: ${PREVIOUS_CURRENT}"
    ln -sfn "${PREVIOUS_CURRENT}" "${CURRENT_LINK}.rollback"
    mv -Tf "${CURRENT_LINK}.rollback" "${CURRENT_LINK}"
    run_privileged "${SYSTEMCTL_BIN}" restart "${APP_NAME}" || true
    log "Rollback attempted; inspect service logs without printing secrets."
  else
    log "No previous current release exists; stopping native service and unlinking failed current."
    run_privileged "${SYSTEMCTL_BIN}" stop "${APP_NAME}" || true
    if [[ -L "${CURRENT_LINK}" ]]; then
      rm -- "${CURRENT_LINK}"
    fi
  fi

  safe_remove_release_dir "${RELEASE_DIR}" || true
  exit 1
}

run_healthcheck() {
  local healthcheck_script="${RELEASE_DIR}/deploy/native/healthcheck.sh"
  [[ -x "${healthcheck_script}" ]] || chmod +x "${healthcheck_script}"

  APP_BIND_HOST="${APP_BIND_HOST}" \
  APP_PORT="${APP_PORT}" \
  HEALTH_URL="${HEALTH_URL}" \
  HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS}" \
  HEALTH_INTERVAL_SECONDS="${HEALTH_INTERVAL_SECONDS}" \
    "${healthcheck_script}"
}

prune_old_releases() {
  (( RELEASE_KEEP > 0 )) || return 0

  local current_real
  current_real="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
  mapfile -t releases < <(find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)

  local kept=0
  for release in "${releases[@]}"; do
    if [[ "${release}" == "${current_real}" ]]; then
      kept=$((kept + 1))
      continue
    fi

    if (( kept < RELEASE_KEEP )); then
      kept=$((kept + 1))
      continue
    fi

    log "Pruning old release: ${release}"
    safe_remove_release_dir "${release}"
  done
}

main() {
  validate_inputs
  preflight_commands
  preflight_runtime
  prepare_release_dirs
  verify_checksum
  verify_bundle_manifest
  unpack_release
  create_compat_symlinks
  check_env_file
  sync_dependencies
  render_systemd_unit
  install_systemd_unit
  capture_previous_current
  switch_current
  restart_service || rollback_after_switch "systemd start/restart failed"
  run_healthcheck || rollback_after_switch "local health check failed"
  prune_old_releases
  DEPLOY_PHASE="complete"
  log "Native deployment completed for release ${RELEASE_ID}"
}

main "$@"
