# Native deployment assets

## Contract

`deploy/native/*` is the active deployment asset set for the Docker-free first pass.
The workflow packages a source bundle, verifies the checksum and manifest, and only
then allows a guarded native live job to upload that bundle to the target host.

| Item | Default | Override |
|---|---|---|
| App root | `/opt/kt-demo-alarm` | `APP_ROOT` |
| Releases | `${APP_ROOT}/releases` | `RELEASES_DIR` |
| Active release | `${APP_ROOT}/current` | `CURRENT_LINK` |
| Shared state | `${APP_ROOT}/shared` | `SHARED_DIR` |
| Server-owned env | `${SHARED_DIR}/.env` | `ENV_FILE` |
| Bind address | `127.0.0.1:8000` | `APP_BIND_HOST`, `APP_PORT` |
| Service unit | `/etc/systemd/system/kt-demo-alarm.service` | `SERVICE_UNIT_PATH` |
| Health URL | `http://127.0.0.1:8000/` | `HEALTH_URL` |
| Source bundle | `source-bundle.tar.gz` | `BUNDLE_NAME` |
| Bundle checksum | `source-bundle.sha256` | `CHECKSUM_NAME` |

## Bundle rules

The package/verify scripts enforce the same source-bundle contract:

- allowed: `app/`, `main.py`, `pyproject.toml`, `uv.lock`, `.python-version`,
  `deploy/native/`, `docs/native-linux-deploy-guide.md`,
  `docs/docker-free-fastapi-deploy-runbook.md`, and `nginx/` when present
- denied: `.env*`, `.venv/`, cache directories, SQLite/DB files, attachments,
  `*.key`, `*.pem`, `id_rsa`, `credentials.json`, Docker image archives, and
  path-traversal entries

`bundle-manifest.txt` must be present in the archive and must match the packaged
file list exactly.

## Live activation guard

The live job is not the default behavior of the first pass.

| Guard | Purpose |
|---|---|
| `KT_NATIVE_DEPLOY_ENABLED=1` repository variable | explicit repository-side activation |
| protected `native-live` environment approval | operator-owned cutover gate |

Without both, the workflow should stop after blocking tests, package, advisory
evidence, and deploy preflight.

## Secret ownership

- GitHub Actions must not render or upload the app `.env`.
- The server-owned env file stays at `${SHARED_DIR}/.env`.
- Operators verify path/mode ownership with `stat`; secret contents are never
  printed in workflow logs or summaries.

## Legacy boundary

- Historical Docker deploy files live under `legacy/docker-deploy/`.
- `scripts/setup-ec2.sh` is a legacy Docker bootstrap helper and not part of the
  active native workflow.
- Re-enabling the legacy Docker path requires a new PRD and explicit operator
  approval.

## Local verification

```bash
bash -n deploy/native/*.sh scripts/native/*.sh
uv run pytest tests/test_native_runtime_assets.py -q
python scripts/ci/advisory_contract.py run-blocking-pytest -- -q
python scripts/ci/advisory_contract.py run-advisory-pytest -- -q
```

Do not re-enable the legacy Docker graph from workflow comments without a new PRD
and explicit operator approval.
