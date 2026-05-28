# Rocky Linux 9.3 Native Deploy Guide

## 0. 결론과 현재 상태

이 문서는 Docker/Compose 없이 Rocky Linux 9.3에서 `kt-demo-alarm`을 native 방식으로 실행하기 위한 운영자용 1차 guide다. 실제 서버 변경은 이 문서만으로 바로 수행하지 않고, 아래 gate를 모두 통과한 뒤 별도 cutover 승인으로 진행한다.

| 항목 | 결정 |
|---|---|
| 1차 기본안 | `systemd` + `uv` project virtualenv |
| 현재 판정 | 로컬 full pytest는 통과. 단, 실서버 package/secret/proxy/scheduler gate 전까지 **운영 실행 준비 완료 아님** |
| 코드 변경 | Dockerfile, Compose, GitHub Actions workflow는 이번 패스에서 수정하지 않는다. Ralph 후속에서 알림 템플릿 테스트 blocker 해소를 위해 `app/services/notification_service.py`만 최소 수정했다. |
| Secret 처리 | `.env`, key, credential 원문을 guide, repo, CI 로그에 기록하지 않는다. |
| 테스트 상태 | Ralph 후속 검증에서 `uv run pytest`가 177 passed, 2 skipped로 통과했다. |
| 전달성 | 이 guide는 `.gitignore`에서 `docs/native-linux-deploy-guide.md`만 명시적으로 unignore해 추적 가능하게 둔다. |

## 1. 운영 변수

아래 값은 운영 정책에 맞게 조정한다. 값이 바뀌면 `.env`, systemd unit, proxy 설정, smoke test command의 값도 같이 바뀌어야 한다.

```bash
APP_NAME="kt-demo-alarm"
APP_DIR="/opt/${APP_NAME}"
APP_USER="kt-demo-alarm"
APP_GROUP="kt-demo-alarm"
APP_BIND_HOST="127.0.0.1"
APP_PORT="8000"
PYTHON_BIN="python3.12"
UV_BIN="uv"
PUBLIC_BASE_URL="https://www.jongno.go.kr/rally"
DATABASE_PATH="${APP_DIR}/data/kt_demo_alarm.db"
CACHE_FILE="${APP_DIR}/topis_cache/topis_cache.json"
ATTACHMENT_FOLDER="${APP_DIR}/topis_attachments"
PLAYWRIGHT_BROWSERS_PATH="${APP_DIR}/.cache/ms-playwright"
TZ="Asia/Seoul"
SERVICE_UNIT_PATH="/etc/systemd/system/${APP_NAME}.service"
```

## 2. Docker 책임의 native 치환

| Docker 책임 | 현재 근거 | Native 치환 |
|---|---|---|
| Python runtime | `Dockerfile:2`, `.python-version:1`, `pyproject.toml:5` | Rocky 9.3에서 Python 3.12 실행 가능 여부를 preflight gate로 확인한다. |
| Dependency install | `Dockerfile:23-27`, `uv.lock` | `${UV_BIN} sync --frozen --no-dev`로 lockfile 기반 `.venv`를 만든다. |
| Playwright browser/deps | `Dockerfile:29-32`, `pyproject.toml:23` | `PLAYWRIGHT_BROWSERS_PATH`를 고정하고 Chromium + system deps 설치 가능성을 gate로 확인한다. |
| App command | `Dockerfile:49-50`, `main.py:143-151` | systemd가 `${APP_DIR}/.venv/bin/uvicorn main:app`을 absolute path로 실행한다. |
| Port binding | `docker-compose.yml:5-6` | 기본값은 host-local `127.0.0.1:8000`; 공개 접근은 앞단 proxy가 담당한다. |
| Env and secrets | `docker-compose.yml:7-11`, `app/config/settings.py:80-83` | `.env`는 서버에서 직접 작성/이전하고 원문을 repo/CI에 남기지 않는다. |
| Data volumes | `docker-compose.yml:12-16` | `${APP_DIR}` 하위 `data`, `logs`, `topis_cache`, `topis_attachments`를 service user 소유로 둔다. |
| Restart/healthcheck | `docker-compose.yml:17-23`, `Dockerfile:45-47` | `Restart=on-failure`와 `curl http://${APP_BIND_HOST}:${APP_PORT}/` gate로 대체한다. |
| Existing handover runbook | `docs/jongno-server-handover-runbook.md:653-685` | 기존 Docker 기동 절차는 native 전환 시 참고 문서일 뿐 그대로 실행하지 않는다. |
| CI/CD | `.github/workflows/deploy.yml:31-59`, `.github/workflows/deploy.yml:127-179` | 이번 패스는 제안만 한다. workflow 편집은 별도 승인 후 수행한다. |

## 3. 공식 문서 확인 메모

| 항목 | 확인 내용 | guide 반영 |
|---|---|---|
| uv | `--frozen`은 기존 lockfile을 사용하고, `--no-dev`는 dev dependency 제외 배포 sync에 맞는다. | `${UV_BIN} sync --frozen --no-dev` |
| Playwright Python | Chromium 설치와 OS dependency 설치는 `playwright install --with-deps chromium` 형태로 결합 가능하고, browser path는 `PLAYWRIGHT_BROWSERS_PATH`로 조정 가능하다. | `PLAYWRIGHT_BROWSERS_PATH=... ${UV_BIN} run playwright install --with-deps chromium` |
| systemd | `Type=exec`는 실행 파일이 실제로 `execve()`되기 전까지 start 성공으로 보지 않아 missing binary/user 실패를 더 빨리 드러낸다. `ExecStart`는 shell syntax가 아니며 env substitution 규칙이 제한적이다. | absolute `ExecStart`와 `${APP_BIND_HOST}`, `${APP_PORT}`만 인자로 사용 |
| Rocky/DNF | Rocky Linux 계열 package 변경은 관리자 권한과 repo/proxy/offline mirror 접근이 필요하다. | package repo gate를 cutover 전 필수 조건으로 둔다. |

## 4. Preflight gates

> 아래 command는 운영자가 대상 서버에서 직접 실행할 후보이다. 이 세션에서는 시스템 변경 명령을 실행하지 않는다.

| Gate | Command 후보 | 통과 기준 |
|---|---|---|
| OS | `cat /etc/os-release` | `ID=rocky`, `VERSION_ID=9.3` 또는 승인된 el9 호환 버전 |
| Package repo | `dnf makecache` | 기관 repo/proxy/offline repo 접근 가능 |
| Python | `${PYTHON_BIN} --version` | Python 3.12.x |
| uv | `${UV_BIN} --version` | uv 실행 가능 |
| Source/lockfile | `test -f "${APP_DIR}/pyproject.toml" && test -f "${APP_DIR}/uv.lock"` | source와 lockfile 존재 |
| Secret file | `test -f "${APP_DIR}/.env" && stat -c '%a %U %G %n' "${APP_DIR}/.env"` | 존재, mode `600` 권장, 원문 출력 금지 |
| Data path | `test -d "${APP_DIR}/data" && test -d "${APP_DIR}/topis_cache" && test -d "${APP_DIR}/topis_attachments"` | 앱 쓰기 경로 존재 |
| Single scheduler | 기존 AWS/Docker runtime 상태 확인 | active scheduler가 native 한 개만 남도록 cutover window 확정 |

## 5. Directory and `.env` contract

```text
${APP_DIR}/
  app/
  main.py
  pyproject.toml
  uv.lock
  .venv/
  .env
  data/
  logs/
  topis_cache/
  topis_attachments/
  .cache/ms-playwright/
```

Native `.env`에는 secret 값과 앱 설정을 운영자가 직접 작성한다. 아래 예시는 **값 형태와 key 목록만** 보여주며 secret 값을 포함하지 않는다.

```dotenv
DATABASE_PATH=/opt/kt-demo-alarm/data/kt_demo_alarm.db
CACHE_FILE=/opt/kt-demo-alarm/topis_cache/topis_cache.json
ATTACHMENT_FOLDER=/opt/kt-demo-alarm/topis_attachments
RENDER_EXTERNAL_URL=https://www.jongno.go.kr/rally
TZ=Asia/Seoul
KAKAO_EVENT_API_KEY=<secret>
KAKAO_LOCATION_API_KEY=<secret>
BOT_ID=<secret>
API_KEY=<secret>
SEOUL_BUS_API_KEY=<secret>
TMAP_APP_KEY=<secret>
WORKS_AI_API_KEY=<secret>
ADMIN_USER=<secret>
ADMIN_PASS=<secret>
```

권한 기준:

```bash
test -f "${APP_DIR}/.env"
stat -c '%a %U %G %n' "${APP_DIR}/.env"
```

`stat` 결과는 mode `600`을 권장한다. `.env` 내용을 `cat`, `grep`, log, GitHub summary로 출력하지 않는다.

## 6. Dependency install 후보

```bash
cd "${APP_DIR}"
"${UV_BIN}" sync --frozen --no-dev
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH}" \
  "${UV_BIN}" run playwright install --with-deps chromium
```

`--with-deps`가 package manager 권한을 요구하면 여기서 중단하고 기관 인프라 담당자가 승인한 repo/proxy/offline RPM 경로를 먼저 확정한다.

## 7. systemd unit template

아래 template의 `__...__` placeholder는 설치 전에 운영 변수 값으로 치환한다. `ExecStart`의 첫 번째 인자는 변수가 아니라 rendered absolute path여야 한다.

```ini
[Unit]
Description=KT Demo Alarm FastAPI service
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=__APP_USER__
Group=__APP_GROUP__
WorkingDirectory=__APP_DIR__
EnvironmentFile=__APP_DIR__/.env
Environment=APP_BIND_HOST=__APP_BIND_HOST__
Environment=APP_PORT=__APP_PORT__
Environment=DATABASE_PATH=__DATABASE_PATH__
Environment=CACHE_FILE=__CACHE_FILE__
Environment=ATTACHMENT_FOLDER=__ATTACHMENT_FOLDER__
Environment=PLAYWRIGHT_BROWSERS_PATH=__PLAYWRIGHT_BROWSERS_PATH__
Environment=TZ=__TZ__
ExecStart=__APP_DIR__/.venv/bin/uvicorn main:app --host ${APP_BIND_HOST} --port ${APP_PORT}
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

검증 후보:

```bash
systemd-analyze verify "${SERVICE_UNIT_PATH}"
systemctl status "${APP_NAME}" --no-pager
journalctl -u "${APP_NAME}" -n 100 --no-pager
curl -fsS "http://${APP_BIND_HOST}:${APP_PORT}/"
```

`systemd-analyze verify`가 통과해도 애플리케이션 import/config 오류는 `systemctl start`, `journalctl`, local health gate까지 통과해야 정상으로 본다.

## 8. Front proxy `/rally/` gate

앱은 기본적으로 `127.0.0.1:${APP_PORT}`에만 바인딩한다. 공개 URL `https://www.jongno.go.kr/rally`는 기관 앞단 또는 대상 서버 내부 proxy가 담당한다.

| 항목 | 기준 |
|---|---|
| Prefix strip | `${PUBLIC_BASE_URL}/`이 앱 `/` health로 전달 |
| Forwarded headers | `X-Forwarded-Proto`, `X-Forwarded-Prefix` 정책 확정 |
| Asset URLs | `${PUBLIC_BASE_URL}/static`, `${PUBLIC_BASE_URL}/attachments` 접근 가능 |
| Kakao URLs | webhook/Skill URL 변경은 별도 cutover 승인 뒤 실행 |

Smoke 후보:

```bash
curl -k -fsS "${PUBLIC_BASE_URL}/"
curl -k -I "${PUBLIC_BASE_URL}/static/"
curl -k -I "${PUBLIC_BASE_URL}/attachments/"
```

## 9. Data migration and single-scheduler gate

| 대상 | Native path |
|---|---|
| SQLite DB | `${DATABASE_PATH}` |
| TOPIS cache | `${APP_DIR}/topis_cache/` |
| Attachments | `${APP_DIR}/topis_attachments/` |
| Logs | `${APP_DIR}/logs/` |

운영 원칙:

1. SQLite 정합성을 위해 기존 runtime을 멈춘 뒤 백업한다.
2. native service와 기존 Docker/AWS service를 동시에 오래 켜두지 않는다.
3. 앱 시작 시 scheduler가 자동 시작되므로 cutover window에는 active scheduler가 하나인지 확인한다.
4. DB/cache/attachment 전송은 checksummed archive 또는 승인된 `rsync` 절차로 수행한다.

## 10. Health, cutover, rollback

Local health:

```bash
curl -fsS "http://${APP_BIND_HOST}:${APP_PORT}/"
```

Public health:

```bash
curl -k -fsS "${PUBLIC_BASE_URL}/"
```

| 실패 지점 | 중단/rollback 조치 |
|---|---|
| dependency install 실패 | service 시작 금지, package repo/proxy/offline gate 재확인 |
| systemd verify 실패 | unit render 값과 service user/path 확인 |
| systemd start 실패 | `journalctl -u "${APP_NAME}" -n 100 --no-pager` 확인, cutover 금지 |
| local health 실패 | front proxy/Kakao 전환 금지 |
| public `/rally/` 실패 | Kakao 전환 금지, proxy 담당자 조치 |
| Kakao 2xx 실패 | webhook/Skill URL rollback |
| 중복 scheduler 발견 | 한쪽 runtime 중지 전까지 알림 cutover 금지 |

## 11. CI/CD proposal only

이번 패스에서는 `.github/workflows/deploy.yml`을 편집하지 않는다. 후속 승인 시 제안은 아래 순서다.

1. `deploy-test-bypass` 제거 또는 full test 실패 시 deploy 중단.
2. Docker image artifact 대신 source/release bundle artifact 사용.
3. 원격 `docker load`/`docker compose up` 대신 release directory + `uv sync --frozen --no-dev` + systemd restart 사용.
4. `.env`를 GitHub artifact로 남기지 않고 기관 승인 secret transfer 방식 사용.
5. Productionization gate에서는 immutable release directory + `current` symlink + rollback command를 재검토한다.

## 12. 운영자 handoff checklist

| 완료 | 항목 |
|---|---|
| [ ] | Rocky Linux 9.3 또는 승인된 el9 호환 OS 확인 |
| [ ] | Python 3.12, uv, Playwright Chromium/deps 설치 가능성 확인 |
| [ ] | service user/group과 `${APP_DIR}` 소유권 정책 확정 |
| [ ] | `.env` 직접 작성/이전 및 mode `600` 확인 |
| [ ] | `${DATABASE_PATH}`, `${CACHE_FILE}`, `${ATTACHMENT_FOLDER}` 경로 확인 |
| [ ] | `uv sync --frozen --no-dev` 성공 |
| [ ] | Playwright browser install gate 성공 또는 승인된 대체 절차 확보 |
| [ ] | systemd unit render 및 `systemd-analyze verify` 성공 |
| [ ] | local health 성공 |
| [ ] | public `/rally/` health 성공 |
| [ ] | Kakao URL 전환 승인 및 2xx 검증 |
| [ ] | 기존 AWS/Docker runtime 중지 후에도 public service 정상 |
| [ ] | active scheduler가 하나만 남음 |
| [x] | full test suite blocker 해결: `uv run pytest` 177 passed, 2 skipped |
