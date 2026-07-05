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

| Job | 역할 | Blocking 여부 |
|---|---|---|
| `blocking-tests` | lockfile freshness + full pytest | **Blocking** |
| `package-native-release` | allowlisted source bundle + checksum 생성 | **Blocking** |
| `deploy-native-preflight` | bundle verify, native static tests, non-mutating preflight | **Blocking** |
| `deploy-native-live` | source bundle 업로드 + remote release deploy | Guarded |
| `public-health` | live job 성공 후 public endpoint 검증 | Guarded |

## 3. Remote release contract

live job는 아래 파일만 target host의 incoming dir로 전송한다.

- `source-bundle.tar.gz`
- `source-bundle.sha256`
- `deploy/native/deploy-release.sh`
- `deploy/native/verify-source-bundle.sh`

그 뒤 remote host에서 `deploy-release.sh`가 release를 수행한다. 내부 단계 순서와 계약은
[`deploy/native/README.md`의 Release flow](../deploy/native/README.md#release-flow)를 참조한다.

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

Legacy Docker 자산과 재활성화 규칙은
[`legacy/docker-deploy/README.md`](../legacy/docker-deploy/README.md)를 참조한다.

<a id="manual-lane"></a>
## 8. Manual redeploy lane (수동 재배포)

GitHub live gate를 쓸 수 없는 서버(예: `scp`만 허용되는 공공기관 환경)에서 **반복 수동
재배포**를 수행하는 절차다. 아래 raw 명령을 순서대로 따라 하면 재배포가 완료된다.
최초 이관(shared-state 이전 포함)의 완료 기록은
[manual-public-server-cutover-guide.md](manual-public-server-cutover-guide.md)를 참조한다.

> **wrapper 경계**: `scripts/manual/public-server-cutover.sh`는 **최초 이관용** tracked
> command surface다. wrapper의 `push` subcommand는 shared-state 아카이브가 없으면
> hard-fail하고 이를 전송 페이로드에 포함하므로, shared state가 이미 서버에 존재하는
> 반복 재배포에는 사용하지 않는다. subcommand 목록은 아카이브된
> [이관 가이드 §3](manual-public-server-cutover-guide.md)을 참조한다.

### 8.1 변수 규약

```bash
APP_NAME="kt-demo-alarm"
APP_ROOT="/opt/kt-demo-alarm"
DEST_HOST="<target-host>"
DEST_USER="<target-user>"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT_DIR="$PWD/release-artifact/manual-${RELEASE_ID}"
INCOMING_DIR="${APP_ROOT}/incoming/${RELEASE_ID}"
```

### 8.2 prepare-artifact — 로컬 검증과 artifact 준비

```bash
mkdir -p "${ARTIFACT_DIR}"

bash -n deploy/native/*.sh scripts/native/*.sh
uv run pytest tests/test_native_runtime_assets.py -q
uv run pytest -q

bash deploy/native/package-source-bundle.sh "${ARTIFACT_DIR}"
bash deploy/native/verify-source-bundle.sh \
  "${ARTIFACT_DIR}/source-bundle.tar.gz" \
  "${ARTIFACT_DIR}/source-bundle.sha256"
```

### 8.3 preflight-dest — 대상 서버 사전 확인

§1 Guard prerequisites의 호스트 조건을 대상 서버에서 증빙으로 확보한다.

```bash
ssh "${DEST_USER}@${DEST_HOST}" "\
systemctl --version && \
uv --version && \
id ${APP_NAME} && \
stat -c '%a %U %G %n' '${APP_ROOT}/shared/.env' && \
docker ps --format '{{.Names}}' || true && \
ss -ltn 'sport = :8000' || true"
```

### 8.4 push — artifact 전송

반복 재배포에서는 shared state가 이미 서버에 있으므로 **`shared-state.tar.gz`를 전송하지
않는다** (최초 이관 시의 shared-state 이전은 아카이브 문서 참조). 아래 4개 파일만 보낸다.

```bash
ssh "${DEST_USER}@${DEST_HOST}" "mkdir -p '${INCOMING_DIR}'"

scp \
  "${ARTIFACT_DIR}/source-bundle.tar.gz" \
  "${ARTIFACT_DIR}/source-bundle.sha256" \
  deploy/native/deploy-release.sh \
  deploy/native/verify-source-bundle.sh \
  "${DEST_USER}@${DEST_HOST}:${INCOMING_DIR}/"
```

### 8.5 deploy — deploy-release 실행

기본값은 승인 없는 cutover를 막는 방향으로 유지한다.

```bash
ssh "${DEST_USER}@${DEST_HOST}" "\
APP_NAME='${APP_NAME}' \
APP_ROOT='${APP_ROOT}' \
RELEASE_ID='${RELEASE_ID}' \
BUNDLE_PATH='${INCOMING_DIR}/source-bundle.tar.gz' \
CHECKSUM_PATH='${INCOMING_DIR}/source-bundle.sha256' \
VERIFY_SOURCE_BUNDLE_BIN='${INCOMING_DIR}/verify-source-bundle.sh' \
bash '${INCOMING_DIR}/deploy-release.sh'"
```

명시적으로 승인된 경우에만 §5의 override(`ALLOW_PORT_TAKEOVER`, `ALLOW_DOCKER_CUTOVER`)를
추가한다.

### 8.6 postcheck — 증빙 수집

§6 Completion evidence의 로컬 항목(active symlink, service, local health, logs)을
원격에서 수집한다.

```bash
ssh "${DEST_USER}@${DEST_HOST}" "\
readlink -f '${APP_ROOT}/current' && \
systemctl status '${APP_NAME}' --no-pager && \
curl -fsS 'http://127.0.0.1:8000/' && \
journalctl -u '${APP_NAME}' -n 100 --no-pager"
```

§6의 public health 항목은 여기서 `&&` 체인에 넣지 않는다. 이 lane의 완료선은
`minimal-cutover`이고, public 도메인·TLS 도달성은 후속 항목이라 재배포 시점에 아직
열려 있지 않을 수 있다([이관 가이드 §7 완료선](manual-public-server-cutover-guide.md)).
public 종단이 준비된 경우에만 별도로 확인한다.

```bash
ssh "${DEST_USER}@${DEST_HOST}" "curl -fsS 'https://<public-domain>/'"
```
