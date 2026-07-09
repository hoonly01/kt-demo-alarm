# 공공기관 서버 수동 이관 가이드

> **📦 완료된 최초 이관 기록** — 이 문서의 이관 절차는 2026-06~07 서버 이관(#146, #165)으로
> 완료되었다. **반복 수동 재배포는
> [runbook의 Manual redeploy lane](deploy-runbook.md#manual-lane)을 사용한다.**
> 본 문서는 최초 이관의 기록과 예외 경로 설계 근거로 보존한다.

## 0. 목적

이 문서는 **GitHub guarded live gate를 서버 B용으로 재구성할 수 없고**, 대상 환경이 공공기관 정책 때문에
**`scp` 중심 수동 전송만 허용하는 상황**에서 `kt-demo-alarm`을 이관하는 operator-owned 절차를 정의한다.

이 가이드는 canonical native deploy contract를 대체하지 않는다.
**동일한 source bundle + `deploy-release.sh` 계약을 GitHub live job 대신 operator-local lane으로 재현**하는 문서다.

## 1. 결론

| 항목 | 결정 |
|---|---|
| 코드 이전 방식 | `deploy/native/package-source-bundle.sh`가 만든 source bundle을 사용한다. |
| 운영 상태 이전 방식 | `data/`, `topis_cache/`, `topis_attachments/`, 선택적으로 `logs/`만 별도 tar/scp로 옮긴다. |
| 비밀값 | `.env`는 bundle/shared-state tar/scp에 넣지 않고 `${APP_ROOT}/shared/.env`에 별도 provision 한다. |
| 서비스 전환 방식 | 대상 서버에서 기존 `deploy/native/deploy-release.sh`를 1회 실행한다. |
| 완료선 | 1차 완료선은 `minimal-cutover`이며 public/TLS/Playwright/outbound readiness는 follow-up으로 분리한다. |
| GitHub live gate | 그대로 유지한다. 이 가이드는 `native-live` gate의 operator-equivalent 예외 경로다. |

## 2. canonical contract와 범위

| 구분 | 내용 | 근거 |
|---|---|---|
| Active deploy path | source bundle → server-side `uv sync --frozen --no-dev` → systemd-managed `uvicorn main:app` | [native-linux-deploy-guide.md의 결정 기록](native-linux-deploy-guide.md#decision) |
| Bundle safety | `.env`, `.venv`, DB, attachments, cache는 source bundle에 포함하지 않는다 | [deploy/native/README.md의 Bundle rules](../deploy/native/README.md#bundle-rules) |
| Remote activation | verify → unpack → shared symlink → `uv sync` → systemd install → current switch → local health | `deploy/native/deploy-release.sh:342-360` |
| Non-goal | GitHub workflow, bundle allowlist/denylist, deploy-release activation flow는 바꾸지 않는다 | `.omx/plans/prd-server-migration-20260604T021812Z.md` |

## 3. operator-local wrapper contract

이 manual lane의 tracked command surface는 `deploy/manual/public-server-cutover.sh` 를 기준으로 정의한다.
wrapper는 **default one-shot `all` 동작 없이**, phase-based / rerunnable subcommand만 제공해야 한다.

| Phase | 목적 | 기대 side effect |
|---|---|---|
| `prepare-artifact` | local syntax/test/package/verify를 묶어 artifact를 준비 | 로컬 `release-artifact/manual-${RELEASE_ID}` 생성 |
| `detect-source-layout` | source host가 `native-shared` 인지 `legacy-flat` 인지 판별 | 출력만 수행 |
| `export-shared-state` | 허용된 shared state만 tar로 export | `shared-state.tar.gz` 생성 |
| `preflight-dest` | 대상 서버 prerequisite와 blocker를 확인 | 출력만 수행 |
| `push` | 준비된 artifact와 helper만 `scp` 전송 | `${APP_ROOT}/incoming/${RELEASE_ID}` 로 업로드 |
| `restore-shared` | 대상 서버 `${APP_ROOT}/shared` 로 tar 복원 | shared state 복원 |
| `deploy` | 기존 `deploy-release.sh`를 remote에서 1회 실행 | release switch 가능 |
| `postcheck` | `current`, `systemctl`, local curl, journal evidence 수집 | 증빙 출력 |
| `followup-checklist` | public/TLS/Playwright/outbound 후속 체크 표시 | 출력만 수행 |

## 4. 변수 규약

| 변수 | 예시/기본값 | 설명 |
|---|---|---|
| `APP_NAME` | `kt-demo-alarm` | systemd unit / app 식별자 |
| `APP_ROOT` | `/opt/kt-demo-alarm` | canonical app root |
| `SRC_HOST`, `SRC_USER` | source host/operator | 기존 운영 서버 |
| `DEST_HOST`, `DEST_USER` | destination host/operator | 공공기관 대상 서버 |
| `RELEASE_ID` | `$(date -u +%Y%m%dT%H%M%SZ)` | immutable release identifier |
| `ARTIFACT_DIR` | `$PWD/release-artifact/manual-${RELEASE_ID}` | local artifact staging dir |
| `INCOMING_DIR` | `${APP_ROOT}/incoming/${RELEASE_ID}` | remote upload staging dir |

```bash
APP_NAME="kt-demo-alarm"
APP_ROOT="/opt/kt-demo-alarm"
SRC_HOST="<server-a-host>"
SRC_USER="<server-a-user>"
DEST_HOST="<server-b-host>"
DEST_USER="<server-b-user>"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT_DIR="$PWD/release-artifact/manual-${RELEASE_ID}"
INCOMING_DIR="${APP_ROOT}/incoming/${RELEASE_ID}"
```

## 5. source layout과 shared-state 범위

> **[완료된 이관 기록 — 재사용 대상 아님]**

### 5.1 source layout 판별

| source layout | 판별 기준 | destination restore target |
|---|---|---|
| `native-shared` | `${APP_ROOT}/shared/` 존재 | 그대로 `${APP_ROOT}/shared/` 아래에 복원 |
| `legacy-flat` | `${APP_ROOT}/data`, `logs`, `topis_cache`, `topis_attachments` 사용 | `${APP_ROOT}/shared/` 아래 canonical layout으로 재배치 |

### 5.2 전송 허용 범위

| 분류 | 항목 | 비고 |
|---|---|---|
| 코드 artifact | `source-bundle.tar.gz`, `source-bundle.sha256`, `deploy-release.sh`, `verify-source-bundle.sh` | package/verify 후 전송 |
| shared state | `data/`, `topis_cache/`, `topis_attachments/`, 선택적 `logs/` | 별도 tar/scp |
| 비밀값 | `${APP_ROOT}/shared/.env` | **전송 금지**, destination에서 별도 provision |
| edge/TLS | Nginx / reverse proxy / TLS | 기관 표준에 따라 별도 반영 |

### 5.3 `.env` non-transfer rule

- `.env`는 source bundle에 넣지 않는다.
- `.env`는 shared-state tar에 넣지 않는다.
- `.env`는 `scp` payload에 넣지 않는다.
- 증빙은 `${APP_ROOT}/shared/.env` 의 **path / mode / owner** 로만 남긴다.

## 6. phase-by-phase 절차

> 반복 사용 절차의 canonical 명령은 [runbook Manual redeploy lane](deploy-runbook.md#manual-lane)이 보유한다. 아래 본문은 최초 이관 당시의 기록이다.

### 6.1 `prepare-artifact`

> [현행 절차: runbook Manual redeploy lane 참조](deploy-runbook.md#manual-lane)

로컬 검증과 artifact 준비를 먼저 수행한다.

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

### 6.2 `detect-source-layout`

> **[완료된 이관 기록 — 재사용 대상 아님]**

```bash
ssh "${SRC_USER}@${SRC_HOST}" "\
if [ -d '${APP_ROOT}/shared' ]; then
  echo native-shared;
else
  echo legacy-flat;
fi"
```

### 6.3 `export-shared-state`

> **[완료된 이관 기록 — 재사용 대상 아님]**

#### A. `native-shared`

```bash
ssh "${SRC_USER}@${SRC_HOST}" "\
tar -C '${APP_ROOT}/shared' -czf - \
  data topis_cache topis_attachments logs" \
  > "${ARTIFACT_DIR}/shared-state.tar.gz"
```

#### B. `legacy-flat`

```bash
ssh "${SRC_USER}@${SRC_HOST}" "\
tar -C '${APP_ROOT}' -czf - \
  data topis_cache topis_attachments logs" \
  > "${ARTIFACT_DIR}/shared-state.tar.gz"
```

> `logs/` 는 optional 이다. 없으면 제외해도 된다.  
> `.env` 는 어떤 layout에서도 tar 대상이 아니다.

### 6.4 `preflight-dest`

> [현행 절차: runbook Manual redeploy lane 참조](deploy-runbook.md#manual-lane)

최근 preflight baseline 에서는 `uv`, service account, `${APP_ROOT}/shared/.env`, Docker 중복, port 8000 takeover 위험이 blocker 였다.
같은 계열 환경이면 아래 출력을 먼저 확보한다.

```bash
ssh "${DEST_USER}@${DEST_HOST}" "\
systemctl --version && \
uv --version && \
id ${APP_NAME} && \
stat -c '%a %U %G %n' '${APP_ROOT}/shared/.env' && \
docker ps --format '{{.Names}}' || true && \
ss -ltn 'sport = :8000' || true"
```

| Check | pass 조건 | blocker 예시 |
|---|---|---|
| `uv` | `uv --version` 성공 | 설치 없음 |
| service account | `id ${APP_NAME}` 성공 | user/group 없음 |
| server-owned `.env` | `${APP_ROOT}/shared/.env` 존재 + world access 없음 | 경로/권한 미구성 |
| Docker duplicate risk | 동일 앱 컨테이너 없음 또는 명시적 승인 | 기존 컨테이너 잔존 |
| port takeover risk | `127.0.0.1:8000` 비충돌 또는 명시적 승인 | 다른 프로세스 LISTEN |

### 6.5 `push`

> [현행 절차: runbook Manual redeploy lane 참조](deploy-runbook.md#manual-lane) — 반복 재배포의 push 페이로드는 `shared-state.tar.gz`를 포함하지 않는다.

remote upload는 `scp` 로만 수행한다.

```bash
scp \
  "${ARTIFACT_DIR}/source-bundle.tar.gz" \
  "${ARTIFACT_DIR}/source-bundle.sha256" \
  "${ARTIFACT_DIR}/shared-state.tar.gz" \
  deploy/native/deploy-release.sh \
  deploy/native/verify-source-bundle.sh \
  "${DEST_USER}@${DEST_HOST}:${INCOMING_DIR}/"
```

### 6.6 `restore-shared`

> **[완료된 이관 기록 — 재사용 대상 아님]**

```bash
ssh "${DEST_USER}@${DEST_HOST}" "\
mkdir -p \
  '${APP_ROOT}/shared/data' \
  '${APP_ROOT}/shared/logs' \
  '${APP_ROOT}/shared/topis_cache' \
  '${APP_ROOT}/shared/topis_attachments' && \
tar -C '${APP_ROOT}/shared' -xzf '${INCOMING_DIR}/shared-state.tar.gz'"
```

### 6.7 `deploy`

> [현행 절차: runbook Manual redeploy lane 참조](deploy-runbook.md#manual-lane)

기본값은 승인 없는 cutover 를 막는 방향으로 유지한다.

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

명시적으로 승인된 경우에만 override 를 추가한다.

```bash
ssh "${DEST_USER}@${DEST_HOST}" "\
APP_NAME='${APP_NAME}' \
APP_ROOT='${APP_ROOT}' \
RELEASE_ID='${RELEASE_ID}' \
BUNDLE_PATH='${INCOMING_DIR}/source-bundle.tar.gz' \
CHECKSUM_PATH='${INCOMING_DIR}/source-bundle.sha256' \
VERIFY_SOURCE_BUNDLE_BIN='${INCOMING_DIR}/verify-source-bundle.sh' \
ALLOW_DOCKER_CUTOVER='true' \
ALLOW_PORT_TAKEOVER='true' \
bash '${INCOMING_DIR}/deploy-release.sh'"
```

### 6.8 `postcheck`

> [현행 절차: runbook Manual redeploy lane 참조](deploy-runbook.md#manual-lane)

```bash
ssh "${DEST_USER}@${DEST_HOST}" "\
readlink -f '${APP_ROOT}/current' && \
systemctl status '${APP_NAME}' --no-pager && \
curl -fsS 'http://127.0.0.1:8000/' && \
journalctl -u '${APP_NAME}' -n 100 --no-pager"
```

## 7. `minimal-cutover` 완료선

1차 완료는 아래 **3개 증빙** 으로 닫는다.

| 증빙 | 설명 |
|---|---|
| `current` symlink | 새 release 가 활성화됐는지 확인 |
| `systemctl status ${APP_NAME}` | systemd 기동 상태 확인 |
| `curl http://127.0.0.1:8000/` | local health 성공 확인 |

> 이 단계에서는 public 도메인, TLS, Playwright browser, outbound API readiness 를 포함하지 않는다.

## 8. follow-up checklist

`minimal-cutover` 이후 별도 확인해야 하는 항목들이다.

| 항목 | 확인 내용 |
|---|---|
| Public/TLS | 기관 reverse proxy / TLS 종단 구성이 실제로 서버 B를 향하는지 |
| Playwright/Chromium | SPATIC 수집용 browser/runtime 이 기관 승인 경로로 준비됐는지 |
| Runtime outbound | Kakao, TOPIS, TMAP, BizRouter, SPATIC/SMPA 등 목적지 allowlist 가 열려 있는지 |
| Public smoke | 필요 시 `https://<public-domain>/` health 확인 |

### Playwright / Chromium 주의사항

`app/services/crawling_service.py` 의 SPATIC 수집 경로는 Chromium 기반 Playwright를 사용한다.
source bundle 계약은 browser binary 를 포함하지 않으므로, cutover 성공과 browser 준비 완료는 같은 의미가 아니다.

## 9. rollback

`deploy-release.sh` 는 switch 이후 실패 시 자동 rollback 을 시도한다.
수동 rollback 이 필요하면 이전 release 를 `current` 로 다시 가리킨 뒤 systemd 를 재기동한다.

```bash
APP_ROOT="/opt/kt-demo-alarm"
APP_NAME="kt-demo-alarm"
PREVIOUS_RELEASE="<absolute-path-to-previous-release>"

ssh "${DEST_USER}@${DEST_HOST}" "\
ln -sfn '${PREVIOUS_RELEASE}' '${APP_ROOT}/current.rollback' && \
mv -Tf '${APP_ROOT}/current.rollback' '${APP_ROOT}/current' && \
systemctl restart '${APP_NAME}'"
```

## 10. 참고 문서

| 문서 | 역할 |
|---|---|
| `docs/native-linux-deploy-guide.md` | native-first 결정 기록 (ADR) |
| `docs/deploy-runbook.md` | 배포 절차 — CI 레인, manual redeploy lane, 증빙 |
| `deploy/native/README.md` | 배포 계약 — bundle allowlist/denylist, release flow, live gate, env ownership |
| `.omx/logs/g076-user-host-preflight-20260602T1046Z.md` | 기존 host preflight blocker baseline |
