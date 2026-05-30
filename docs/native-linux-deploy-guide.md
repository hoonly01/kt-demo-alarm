# Native Linux Deploy Guide — Docker-free active path

## 0. 결론

`kt-demo-alarm`의 active deploy path는 Docker image/Compose가 아니라 **source bundle → server-side `uv sync --frozen --no-dev` → systemd-managed `uvicorn main:app`** 방식이다.

| 항목 | 결정 |
|---|---|
| Runtime | host Linux + systemd |
| Process | `uvicorn main:app` |
| Dependency gate | `uv sync --frozen --no-dev` |
| Active release | `${APP_ROOT}/current` symlink |
| Mutable state | `${APP_ROOT}/shared` |
| Secret source | server-owned `${SHARED_DIR}/.env` only |
| Public prefix | 기존 `/rally` 정책 유지; 이번 변경은 public URL/prefix를 바꾸지 않음 |
| Legacy Docker | `Dockerfile`/`docker-compose.yml` 보존, workflow에서는 inactive comment block only |

## 1. Release layout

| Variable | Default | Purpose |
|---|---|---|
| `APP_ROOT` | `/opt/kt-demo-alarm` | app home |
| `RELEASES_DIR` | `${APP_ROOT}/releases` | immutable release directories |
| `CURRENT_LINK` | `${APP_ROOT}/current` | systemd `WorkingDirectory` target |
| `SHARED_DIR` | `${APP_ROOT}/shared` | release-independent mutable state |
| `ENV_FILE` | `${SHARED_DIR}/.env` | server-owned app config/secrets |
| `DATA_DIR` | `${SHARED_DIR}/data` | SQLite and data attachments |
| `LOG_DIR` | `${SHARED_DIR}/logs` | application logs |
| `CACHE_DIR` | `${SHARED_DIR}/topis_cache` | TOPIS cache |
| `ATTACHMENT_DIR` | `${SHARED_DIR}/topis_attachments` | static attachments |

The deploy script creates these compatibility symlinks inside each release:

| Release path | Target |
|---|---|
| `${RELEASE_DIR}/topis_attachments` | `${SHARED_DIR}/topis_attachments` |
| `${RELEASE_DIR}/topis_cache` | `${SHARED_DIR}/topis_cache` |
| `${RELEASE_DIR}/data` | `${SHARED_DIR}/data` |
| `${RELEASE_DIR}/logs` | `${SHARED_DIR}/logs` |
| `${RELEASE_DIR}/attachments` | `${SHARED_DIR}/data/attachments` |

All targets must resolve under `${SHARED_DIR}`. This preserves existing relative app paths without changing FastAPI business logic.

## 2. GitHub Actions graph

The workflow graph is fixed:

```text
test -> package-source -> deploy-native
```

| Job | Responsibility | Gate |
|---|---|---|
| `test` | checkout, Python from `.python-version`, uv setup, `uv lock --check`, `uv run pytest` | failure blocks packaging |
| `package-source` | allowlisted source bundle, `bundle-manifest.txt`, SHA-256 checksum | `needs: test` |
| `deploy-native` | remote checksum/manifest validation, release deploy, systemd restart, local health | `needs: package-source` |

The active path must not build, load, or run Docker images. The old Docker path is retained only as an inactive workflow comment block for audit and handover context.

## 3. Source bundle contract

### Must include

- `app/`
- `main.py`
- `pyproject.toml`
- `uv.lock`
- `.python-version`
- `deploy/native/`
- `docs/native-linux-deploy-guide.md`
- `docs/docker-free-fastapi-deploy-runbook.md`
- `nginx/` when present

### Must exclude

- `.env`, `.env.*`
- `.venv/`
- `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`
- `*.db`, `*.sqlite`, `*.sqlite3`
- `attachments/`, `topis_attachments/`, `topis_cache/`
- `*.key`, `*.pem`, `id_rsa`, `credentials.json`
- Docker image tar/gzip artifacts

The remote script verifies the checksum and manifest before switching `${CURRENT_LINK}`.

## 4. Server preflight

| Gate | Default behavior |
|---|---|
| `127.0.0.1:${APP_PORT}` occupied by non-target process | fail fast unless `ALLOW_PORT_TAKEOVER=true` is explicitly set for approved cutover |
| Existing Docker runtime for same app | fail fast unless `ALLOW_DOCKER_CUTOVER=true` is explicitly set for approved transition |
| Existing native service active | allowed when the service name matches `${APP_NAME}` |
| `${ENV_FILE}` missing or too open | fail before dependency sync or restart; print path/mode only |
| `APP_USER`/`APP_GROUP` missing | fail before release switch |
| `uv`, `systemd`, `sha256sum`, `tar` missing | fail before release switch |

Do not print `.env` contents. Use only existence and mode checks.

## 5. Remote deploy order

1. Validate inputs and command availability.
2. Run port/Docker/native/env preflight.
3. Prepare `${RELEASE_DIR}` and shared directories.
4. Verify bundle checksum.
5. Verify `bundle-manifest.txt` allowlist/denylist.
6. Unpack source bundle.
7. Re-check unpacked tree for denied paths.
8. Create and validate compatibility symlinks.
9. Check `${ENV_FILE}` exists and mode is acceptable.
10. Run `uv sync --frozen --no-dev`.
11. Render systemd candidate unit outside `/etc`.
12. Run `systemd-analyze verify <candidate>`.
13. Install unit and run `systemctl daemon-reload`.
14. Switch `${CURRENT_LINK}` to the new release.
15. Start or restart `${APP_NAME}`.
16. Run local health against `http://127.0.0.1:8000/` by default.
17. Prune old releases only after successful local health.

## 6. systemd unit behavior

The template is `deploy/native/kt-demo-alarm.service.template`.

| Unit field | Contract |
|---|---|
| `WorkingDirectory` | rendered `${CURRENT_LINK}` |
| `EnvironmentFile` | rendered `${ENV_FILE}` |
| `ExecStart` | rendered `${ENV_BIN:-/usr/bin/env} ${UV_BIN:-uv} run --no-sync --no-dev uvicorn main:app --host ${APP_BIND_HOST} --port ${APP_PORT}` |
| `ReadWritePaths` | rendered `${SHARED_DIR}` |
| `UMask` | `0077` |
| `Restart` | `on-failure` |

`systemd-analyze verify` checks the rendered candidate before it is installed.

## 7. Rollback

| Branch | Behavior |
|---|---|
| Previous `current` exists | Restore previous symlink, restart service, remove failed release, exit non-zero. |
| First native deploy, no previous `current` | Stop native service if started, unlink failed `current`, remove failed release, exit non-zero. Do not claim rollback. |
| Successful deploy | Keep previous release for rollback and prune only old release directories after local health. Never prune `${SHARED_DIR}`. |

Docker/public fallback is an operator runbook action, not an automatic workflow branch.

## 8. Secret safety

| Rule | Implementation |
|---|---|
| No app `.env` creation on GitHub runner | Workflow no longer renders app secrets into `.env`. |
| No app `.env` upload | Deploy job uploads only source bundle, checksum, and deploy script. |
| No secret summary/log output | Script prints path and mode only for `${ENV_FILE}`. |
| Server-owned config | Operators prepare `${SHARED_DIR}/.env` on the server before cutover. |

SSH key material is written only to a temporary runner file for the SSH connection and removed by a trap.

## 9. Local verification

Run from repository root:

```bash
uv run pytest
python - <<'PY'
from pathlib import Path
import yaml
yaml.safe_load(Path('.github/workflows/deploy.yml').read_text())
print('workflow yaml ok')
PY
bash -n deploy/native/*.sh
git check-ignore -v docs/native-linux-deploy-guide.md docs/docker-free-fastapi-deploy-runbook.md
```

`git check-ignore` must return no ignored result for the two required docs.

## 10. Public `/rally` note

This deploy path validates local app health only. Existing public `/rally` routing stays unchanged and remains a separate proxy/cutover gate. Do not change Kakao webhook or public URL settings as part of this deployment refactor.
