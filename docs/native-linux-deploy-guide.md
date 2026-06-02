# Native Linux Deploy Guide — first-pass canonical path

## 결론

`kt-demo-alarm`의 active deploy path는 Docker image/Compose가 아니라 아래 흐름이다.

```text
blocking-tests
  -> package-native-release
  -> advisory-template-regression
  -> deploy-native-preflight
  -> deploy-native-live [guarded]
  -> public-health
```

| 항목 | 결정 |
|---|---|
| Canonical deploy path | source bundle → server-side `uv sync --frozen --no-dev` → systemd-managed `uvicorn main:app` |
| Advisory contract | `template-only-advisory-v1` |
| Live activation gate | `native-live-activation-gate-v1` |
| Runtime config ownership | server-owned `${APP_ROOT}/shared/.env` only |
| Legacy Docker | `legacy/docker-deploy/` 아래에 보존하되 active workflow path에서는 사용하지 않음 |

## Workflow jobs

| Job | 역할 | Blocking 여부 |
|---|---|---|
| `blocking-tests` | lockfile freshness + advisory selector를 제외한 pytest | **Blocking** |
| `advisory-template-regression` | `template-only-advisory-v1` selector 2건만 별도 증빙 | Non-blocking evidence |
| `package-native-release` | allowlisted source bundle + checksum 생성 | **Blocking** |
| `deploy-native-preflight` | bundle verify, native static tests, non-mutating preflight | **Blocking** |
| `deploy-native-live` | source bundle 업로드 + remote release deploy | Guarded |
| `public-health` | live job 성공 후 public endpoint 검증 | Guarded |

## Source bundle contract

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

`deploy/native/package-source-bundle.sh`가 `bundle-manifest.txt`를 생성하고,
`deploy/native/verify-source-bundle.sh`가 checksum/allowlist/denylist/manifest 일치를
검증한다.

## Native release layout

| Variable | Default | Purpose |
|---|---|---|
| `APP_ROOT` | `/opt/kt-demo-alarm` | app home |
| `RELEASES_DIR` | `${APP_ROOT}/releases` | immutable release directories |
| `CURRENT_LINK` | `${APP_ROOT}/current` | active release symlink |
| `SHARED_DIR` | `${APP_ROOT}/shared` | mutable shared state |
| `ENV_FILE` | `${SHARED_DIR}/.env` | server-owned app secrets/config |
| `DATA_DIR` | `${SHARED_DIR}/data` | SQLite and related data |
| `LOG_DIR` | `${SHARED_DIR}/logs` | application logs |
| `CACHE_DIR` | `${SHARED_DIR}/topis_cache` | TOPIS cache |
| `ATTACHMENT_DIR` | `${SHARED_DIR}/topis_attachments` | attachment storage |

The deploy script recreates compatibility symlinks inside each release:

| Release path | Target |
|---|---|
| `${RELEASE_DIR}/topis_attachments` | `${SHARED_DIR}/topis_attachments` |
| `${RELEASE_DIR}/topis_cache` | `${SHARED_DIR}/topis_cache` |
| `${RELEASE_DIR}/data` | `${SHARED_DIR}/data` |
| `${RELEASE_DIR}/logs` | `${SHARED_DIR}/logs` |
| `${RELEASE_DIR}/attachments` | `${SHARED_DIR}/data/attachments` |

## Guarded live activation

`deploy-native-live`는 아래 두 조건이 동시에 만족될 때만 실행한다.

1. repository variable `KT_NATIVE_DEPLOY_ENABLED=1`
2. protected `native-live` environment approval

둘 중 하나라도 없으면 workflow는 preflight evidence까지만 남기고 종료한다.

## Server preflight expectations

| Gate | Default behavior |
|---|---|
| Port already listens on `${APP_PORT}` | active native service가 아니면 fail-fast (`ALLOW_PORT_TAKEOVER=true`가 있어야 예외) |
| Existing Docker runtime for same app | fail-fast (`ALLOW_DOCKER_CUTOVER=true`가 있어야 예외) |
| Missing `APP_USER`/`APP_GROUP` | release switch 전에 fail |
| Missing or too-open env file | dependency sync 전에 fail |
| Missing `uv`, `systemd`, `sha256sum`, `tar` | release switch 전에 fail |

## Secret safety

| Rule | Implementation |
|---|---|
| No runner-side app `.env` rendering | active workflow has no `.env` generation/upload step |
| No app `.env` upload | live job uploads only source bundle, checksum, and deploy helper scripts |
| No secret content logs | `stat`/mode/path evidence only |
| Server-owned config | operators provision `${SHARED_DIR}/.env` before cutover |

## Legacy inventory

| Surface | Current status |
|---|---|
| `legacy/docker-deploy/` | historical Docker deploy files (`Dockerfile`, `docker-compose.yml`, `.dockerignore`) |
| `legacy/docker-deploy/README.md` | inactive legacy asset notice + reactivation gate |
| `scripts/setup-ec2.sh` | legacy Docker bootstrap helper; current canonical path 아님 |
| `legacy/bootstrap/README.md` | bootstrap classification and native-path redirect |

## Local verification

```bash
bash -n deploy/native/*.sh scripts/native/*.sh
uv run pytest tests/test_native_runtime_assets.py -q
python scripts/ci/advisory_contract.py run-blocking-pytest -- -q
python scripts/ci/advisory_contract.py run-advisory-pytest -- -q
```

`uv run pytest -q` full suite는 현재 advisory selector 2건 때문에 여전히 red일 수 있다.
