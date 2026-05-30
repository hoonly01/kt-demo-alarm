# Docker-free FastAPI Deploy Runbook

## 0. 목적

이 runbook은 `kt-demo-alarm`을 Docker/Compose 없이 native Linux release로 배포할 때 운영자가 확인할 절차를 정리한다. 명령 예시는 secret 값을 포함하지 않으며, source bundle에는 `.env*`, `*.key`, `*.pem`, `id_rsa`, `credentials.json`이 들어가면 안 된다.

## 1. 준비 체크리스트

| 완료 | 항목 | 기준 |
|---|---|---|
| [ ] | 서비스 계정 | `APP_USER`/`APP_GROUP`이 존재 |
| [ ] | uv | `uv --version` 또는 `UV_BIN`으로 실행 가능 |
| [ ] | systemd | `systemctl`/`systemd-analyze` 실행 가능 |
| [ ] | app root | `${APP_ROOT}` 생성 및 deploy user 접근 가능 |
| [ ] | env file | `${SHARED_DIR}/.env` 존재, world-readable 아님 |
| [ ] | single scheduler | 기존 Docker/AWS runtime과 native runtime이 동시에 장시간 실행되지 않도록 cutover window 확정 |

`.env` 내용은 `cat`, `grep`, CI summary, issue, chat에 출력하지 않는다.

## 2. 서버 디렉터리

```text
${APP_ROOT}/
  incoming/
  releases/
  current -> releases/<release-id>
  shared/
    .env
    data/
      attachments/
    logs/
    topis_cache/
    topis_attachments/
    ms-playwright/
```

Shared state는 release pruning 대상이 아니다.

## 3. Cutover 전 확인

| Gate | Command 후보 | 통과 기준 |
|---|---|---|
| Env file mode | `stat -c '%a %U %G %n' "${SHARED_DIR}/.env"` | path/mode만 확인, world access 없음 |
| Port | `ss -ltn sport = :8000` | 미사용 또는 target native service만 사용 |
| Docker duplicate | `docker ps --format '{{.Names}}'` | 같은 앱 Docker runtime 없음, 또는 승인된 `ALLOW_DOCKER_CUTOVER=true` |
| Native service | `systemctl status kt-demo-alarm --no-pager` | 첫 배포면 inactive 가능, 재배포면 target service만 active |
| Public proxy | 운영 proxy 담당자 확인 | `/rally` public path 변경 없음 |

## 4. GitHub Actions 배포 흐름

| Step | 성공 조건 |
|---|---|
| `test` | `uv lock --check`, `uv run pytest` 통과 |
| `package-source` | allowlisted source bundle과 SHA-256 checksum 생성 |
| `deploy-native` | remote checksum/manifest 검증, `uv sync --frozen --no-dev`, systemd verify/install, local health 통과 |

Deploy가 실패하면 workflow는 non-zero로 종료되어야 하며, 실패한 release를 active로 남기지 않는다.

## 5. 수동 dry-run 후보

운영 서버에서 bundle과 checksum을 받은 뒤 아래 형태로 실행한다. 값은 운영 환경에 맞게 조정한다.

```bash
APP_NAME="kt-demo-alarm" \
APP_ROOT="/opt/kt-demo-alarm" \
RELEASE_ID="<release-id>" \
BUNDLE_PATH="/opt/kt-demo-alarm/incoming/<release-id>/source-bundle.tar.gz" \
CHECKSUM_PATH="/opt/kt-demo-alarm/incoming/<release-id>/source-bundle.sha256" \
bash /opt/kt-demo-alarm/incoming/<release-id>/deploy-release.sh
```

Planned cutover에서만 아래 override를 사용한다.

| Override | 의미 |
|---|---|
| `ALLOW_PORT_TAKEOVER=true` | 기존 non-target port listener를 운영자가 확인했고 전환을 승인 |
| `ALLOW_DOCKER_CUTOVER=true` | 기존 Docker runtime 존재를 운영자가 확인했고 전환을 승인 |

## 6. 실패 대응

| 실패 지점 | 조치 |
|---|---|
| checksum/manifest 실패 | artifact 오염 또는 packaging 오류로 간주; release switch 전 중단 |
| `.env` missing/mode 실패 | 서버에서 env file을 준비/권한 수정한 뒤 재실행; 내용 출력 금지 |
| `uv sync --frozen --no-dev` 실패 | lockfile/서버 Python/uv 상태 확인; service restart 금지 |
| `systemd-analyze verify` 실패 | rendered candidate unit 확인; `/etc` 설치 전 중단 |
| systemd start/restart 실패 | previous `current`가 있으면 restore 후 restart, 없으면 service stop/current unlink |
| local health 실패 | previous `current`가 있으면 restore 후 restart, 없으면 service stop/current unlink |

## 7. 정상 완료 확인

| Check | Command 후보 |
|---|---|
| Active symlink | `readlink -f "${APP_ROOT}/current"` |
| Service | `systemctl status kt-demo-alarm --no-pager` |
| Local health | `curl -fsS http://127.0.0.1:8000/` |
| Recent logs | `journalctl -u kt-demo-alarm -n 100 --no-pager` |

Log review 중에도 secret values를 복사하거나 공유하지 않는다.

## 8. Docker legacy policy

`Dockerfile`과 `docker-compose.yml`은 삭제하지 않는다. 기존 Docker 배포 경로는 workflow의 inactive legacy comment block에만 남아 있으며, 재활성화하려면 새 PRD와 운영 승인 후 별도 변경으로 진행한다.
