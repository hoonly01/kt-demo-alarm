# deploy

`kt-demo-alarm`의 배포 자산 모음. 배포 방식은 Docker 이미지가 아니라 **source bundle →
서버측 `uv sync` → systemd 관리 `uvicorn`** 의 native 방식이다.

## 구조

| 위치 | 역할 |
|---|---|
| `deploy/native/` | 번들 계약 자산 — 패키징(`package-source-bundle.sh`), 검증(`verify-source-bundle.sh`), 릴리스 실행(`deploy-release.sh`), systemd 유닛 템플릿, healthcheck. CI(`.github/workflows/deploy.yml`)와 번들 allowlist가 이 경로를 참조한다. 세부 계약은 `native/README.md`. |
| `deploy/manual/` | 운영자용 수동 재배포 도구(`public-server-cutover.sh`). GitHub live gate를 못 쓰는 서버(예: `scp`만 허용되는 공공기관망)에서 재배포를 subcommand로 수행한다. |
| `scripts/native/` | CI 빌드 헬퍼(`setup-runtime.sh`, `preflight.sh`, `render-systemd-unit.sh`, `native-defaults.sh`). `deploy.yml`이 경로를 하드코딩하므로 `scripts/` 아래에 유지한다. `deploy/manual`이 `native-defaults.sh`를 소싱한다. |

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/deploy-runbook.md`](../docs/deploy-runbook.md) | 배포 절차의 단일 서술처 — CI 레인 + **Manual redeploy lane(§8)**(캐시 갱신/스모크 포함). |
| [`docs/native-linux-deploy-guide.md`](../docs/native-linux-deploy-guide.md) | native-first 결정 기록(ADR). |
| [`docs/manual-public-server-cutover-guide.md`](../docs/manual-public-server-cutover-guide.md) | 최초 이관(shared-state 이전 포함) 완료 기록(아카이브). |

## 반복 재배포 (한 줄)

shared state(DB/첨부/캐시)는 대상 서버 `shared/`에 이미 있으므로 전송하지 않는다.

```bash
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)" DEST_HOST="<host>" DEST_USER="<user>" \
  deploy/manual/public-server-cutover.sh redeploy
```

크롤/추출 로직을 바꾼 배포는 캐시 갱신과 스모크를 함께 켠다.

```bash
... REFRESH_CACHE=true SMOKE_ROUTE=162 SMOKE_DATE=2026-07-12 \
  deploy/manual/public-server-cutover.sh redeploy
```

각 단계를 개별 실행하거나 `--dry-run`으로 미리 볼 수 있다
(`prepare-artifact`, `push`, `deploy`, `postcheck`, `refresh-cache`, `smoke`).
절차 상세는 [runbook §8](../docs/deploy-runbook.md#manual-lane) 참조.

## 검증

```bash
uv run pytest tests/test_native_runtime_assets.py tests/test_manual_public_server_cutover_assets.py -q
```

Legacy Docker 자산은 `legacy/docker-deploy/`에 보존되며 active 경로에서 쓰지 않는다.
