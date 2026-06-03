# Docker-free FastAPI Deploy Runbook

## 0. 목적

이 runbook은 `kt-demo-alarm`의 native live activation을 **operator-owned cutover**로 수행할 때
확인해야 할 최소 절차를 정리한다. GitHub Actions는 package/preflight evidence를 기본으로 남기고,
실제 live deploy는 `native-live-activation-gate-v1`가 열렸을 때만 수행한다.

## 1. Guard prerequisites

| Check | Evidence example | Pass condition |
|---|---|---|
| `KT_NATIVE_DEPLOY_ENABLED=1` | repository variable screenshot or settings note | explicit repo-side activation |
| protected `native-live` environment | environment config / approval log | required reviewers enabled |
| `uv` availability | `uv --version` | host에서 `uv` 실행 가능 |
| `systemd` availability | `systemctl --version` | host에서 systemd 관리 가능 |
| service account | `id kt-demo-alarm` | app user/group 존재 |
| server-owned env | `stat -c '%a %U %G %n' /opt/kt-demo-alarm/shared/.env` | world access 없음 |
| Docker duplicate risk | `docker ps --format '{{.Names}}'` | 동일 앱 Docker runtime 없음, 또는 cutover 승인 있음 |
| port takeover risk | `ss -ltn sport = :8000` | target service만 쓰거나 cutover 승인 있음 |
| rollback readiness | previous `current` release 존재 여부 + runbook 확인 | 실패 시 복구 경로 명확 |

`.env` 내용은 출력하지 않는다. 경로와 mode만 증빙한다.

## 2. Workflow contract

| Phase | Expected behavior |
|---|---|
| Phase 1 — merge-ready | `blocking-tests`, `package-native-release`, `deploy-native-preflight`만 기본 수행 |
| Phase 2 — activation | `deploy-native-live`는 guard가 열렸을 때만 실행 |
| Phase 3 — post-activation | `public-health`는 live success 뒤에만 blocking 수행 |

## 3. Remote release contract

live job는 아래 파일만 target host의 incoming dir로 전송한다.

- `source-bundle.tar.gz`
- `source-bundle.sha256`
- `deploy/native/deploy-release.sh`
- `deploy/native/verify-source-bundle.sh`

그 뒤 remote host에서 `deploy-release.sh`가 아래 순서로 동작한다.

1. checksum/manifest/allowlist 검증
2. port/Docker/user/group/env preflight
3. release dir 생성
4. source bundle unpack
5. shared compatibility symlink 생성
6. `uv sync --frozen --no-dev`
7. systemd candidate render + `systemd-analyze verify`
8. current symlink switch
9. service start/restart
10. local health check
11. old release prune

## 4. Failure handling

| Failure point | Action |
|---|---|
| bundle verify 실패 | release switch 전 중단 |
| env file missing/mode 실패 | server-side fix 후 재실행 |
| `uv sync --frozen --no-dev` 실패 | lockfile/runtime mismatch 조사 후 재실행 |
| systemd verify/install 실패 | `/etc` install 전 중단 |
| service start/restart 실패 | previous `current` restore 시도, 없으면 current unlink + stop |
| local health 실패 | previous `current` restore 시도, 없으면 current unlink + stop |

## 5. Manual dry-run example

```bash
APP_NAME="kt-demo-alarm" \
APP_ROOT="/opt/kt-demo-alarm" \
RELEASE_ID="<release-id>" \
BUNDLE_PATH="/opt/kt-demo-alarm/incoming/<release-id>/source-bundle.tar.gz" \
CHECKSUM_PATH="/opt/kt-demo-alarm/incoming/<release-id>/source-bundle.sha256" \
VERIFY_SOURCE_BUNDLE_BIN="/opt/kt-demo-alarm/incoming/<release-id>/verify-source-bundle.sh" \
bash /opt/kt-demo-alarm/incoming/<release-id>/deploy-release.sh
```

승인된 cutover에서만 아래 override를 사용한다.

| Override | 의미 |
|---|---|
| `ALLOW_PORT_TAKEOVER=true` | 기존 listener takeover를 operator가 승인 |
| `ALLOW_DOCKER_CUTOVER=true` | 기존 Docker runtime 존재를 operator가 승인 |

## 6. Completion evidence

| Check | Command example |
|---|---|
| Active symlink | `readlink -f /opt/kt-demo-alarm/current` |
| Service | `systemctl status kt-demo-alarm --no-pager` |
| Local health | `curl -fsS http://127.0.0.1:8000/` |
| Public health | `curl -fsS https://<public-domain>/` |
| Recent logs | `journalctl -u kt-demo-alarm -n 100 --no-pager` |

## 7. Legacy Docker note

Docker assets are preserved for history and rollback planning under `legacy/docker-deploy/`,
but the active workflow must not build, load, or start Docker images. `scripts/setup-ec2.sh`
is also a legacy bootstrap helper only. Re-enabling a Docker runtime path requires a new
PRD and explicit operator approval.
