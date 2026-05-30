# Native deployment scripts

## Contract

These scripts implement the active Docker-free deployment path for `kt-demo-alarm`.
They expect GitHub Actions to upload a source bundle plus checksum and then execute
`deploy-release.sh` on the target server.

| Item | Default | Override |
|---|---|---|
| App root | `/opt/kt-demo-alarm` | `APP_ROOT` |
| Releases | `${APP_ROOT}/releases` | `RELEASES_DIR` |
| Active release | `${APP_ROOT}/current` | `CURRENT_LINK` |
| Shared state | `${APP_ROOT}/shared` | `SHARED_DIR` |
| Server-owned env | `${SHARED_DIR}/.env` | `ENV_FILE` |
| Bind address | `127.0.0.1:8000` | `APP_BIND_HOST`, `APP_PORT` |
| Service unit | `/etc/systemd/system/kt-demo-alarm.service` | `SERVICE_UNIT_PATH` |
| `env` executable | `/usr/bin/env` | `ENV_BIN` |
| uv executable | `uv` | `UV_BIN` |

## Required server state

| Requirement | Reason |
|---|---|
| `uv` is installed and on `PATH` or provided through `UV_BIN`. | `deploy-release.sh` runs `uv sync --frozen --no-dev`. |
| `systemd` is available. | The app is started via `systemctl start/restart`. |
| `APP_USER` and `APP_GROUP` exist. | The unit runs without root application privileges. |
| `${ENV_FILE}` exists with no world-readable bits. | Secrets stay server-owned and are never copied from GitHub. |
| Existing Docker runtime is stopped or `ALLOW_DOCKER_CUTOVER=true` is set for an approved transition. | Prevents duplicate scheduler/runtime execution. |

## Source bundle requirements

The bundle must contain `bundle-manifest.txt` and only allowlisted source paths:

- `app/`
- `main.py`
- `pyproject.toml`
- `uv.lock`
- `.python-version`
- `deploy/native/`
- `docs/native-linux-deploy-guide.md`
- `docs/docker-free-fastapi-deploy-runbook.md`
- `nginx/` when present

Denied paths include `.env*`, `.venv/`, cache directories, SQLite/DB files,
attachments, `*.key`, `*.pem`, `id_rsa`, credentials, path traversal entries,
and Docker image archives.

## Rollback behavior

| Branch | Behavior |
|---|---|
| Previous `current` exists | Restore the previous symlink, restart the service, remove the failed release, and exit non-zero. |
| No previous `current` | Stop the native service if started, unlink failed `current`, remove the failed release, and exit non-zero without claiming rollback. |

## Local verification

Run these commands from the repository before relying on the workflow:

```bash
bash -n deploy/native/*.sh
systemd-analyze verify <rendered-candidate-unit>
```

Do not print `.env` contents while debugging. Use `stat` for existence/mode only.
