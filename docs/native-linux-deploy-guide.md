# Native Linux Deploy Guide — native-first 결정 기록 (ADR)

> 이 문서는 `kt-demo-alarm`이 Docker 기반 배포 대신 native Linux 배포를 canonical path로
> 채택한 **결정 기록(ADR)** 이다. 계약과 절차의 현행 서술처는 [문서 맵](#doc-map)을 따른다.

## 배경 (Context)

- 운영 대상에 GitHub guarded live gate를 재구성할 수 없고 `scp` 중심 수동 전송만 허용되는
  공공기관 서버가 포함된다 ([이관 기록](manual-public-server-cutover-guide.md) 참조).
- 배포 경로가 보장해야 하는 조건: 시크릿이 CI를 경유하지 않을 것(server-owned config),
  기존 Docker runtime·port와의 충돌을 사전에 차단할 것(preflight fail-fast), 이미지 반입
  없이 소스 번들만으로 재현 가능할 것.

<a id="decision"></a>
## 결정 (Decision)

`kt-demo-alarm`의 active deploy path는 Docker image/Compose가 아니라 아래 흐름이다.

```text
blocking-tests
  -> package-native-release
  -> deploy-native-preflight
  -> deploy-native-live [guarded]
  -> public-health
```

| 항목 | 결정 |
|---|---|
| Canonical deploy path | source bundle → server-side `uv sync --frozen --no-dev` → systemd-managed `uvicorn main:app` |
| Pytest policy | full `uv run pytest -q` blocking green |
| Live activation gate | `native-live-activation-gate-v1` |
| Runtime config ownership | server-owned `${APP_ROOT}/shared/.env` only |
| Legacy Docker | `legacy/docker-deploy/` 아래에 보존하되 active workflow path에서는 사용하지 않음 |

## 대안 (Alternatives considered)

| 대안 | 기각 사유 |
|---|---|
| Docker image/Compose 경로 유지 | 이미지 반입이 불가능한 대상 서버에서 재현 불가, 기존 runtime과의 중복 실행 위험. 자산은 legacy로 보존하고 재활성화 게이트를 둠 |
| CI runner 측 `.env` 렌더링/업로드 | 시크릿이 워크플로를 경유하게 됨 — server-owned `${APP_ROOT}/shared/.env` 단일 소유로 대체 |
| live 배포 상시 활성화 | 운영자 승인 없는 cutover 위험 — repository variable + protected environment 이중 가드로 대체 |

## 결과 (Consequences)

- 배포 계약(번들 allowlist/denylist, release layout, activation guard, release flow)은
  [`deploy/native/README.md`](../deploy/native/README.md)가 단일 서술처이며, 실질 소스는
  packaging/verify 스크립트다.
- CI 레인과 수동 재배포 절차는 [runbook](docker-free-fastapi-deploy-runbook.md)이 단일
  서술처다.
- live 배포는 이중 가드(repository variable + protected environment) 뒤에 있으며, 가드
  조건과 동작의 서술처는 [`deploy/native/README.md`](../deploy/native/README.md)다.
- 최초 서버 이관은 완료되었고(#165), 그 기록은
  [이관 가이드](manual-public-server-cutover-guide.md)에 아카이브로 보존된다.

<a id="doc-map"></a>
## 문서 맵

| 주제 | 서술처 |
|---|---|
| 배포 계약 — 번들 allowlist/denylist, release layout, activation guard, release flow | [`deploy/native/README.md`](../deploy/native/README.md) |
| 배포 절차 — CI 레인, 수동 재배포(manual lane), preflight, postcheck 증빙 | [`docker-free-fastapi-deploy-runbook.md`](docker-free-fastapi-deploy-runbook.md) |
| 최초 이관 기록 (완료, 아카이브) | [`manual-public-server-cutover-guide.md`](manual-public-server-cutover-guide.md) |
| Legacy 규칙 — Docker 자산 `legacy/docker-deploy/`, bootstrap helper `scripts/setup-ec2.sh` | [`legacy/docker-deploy/README.md`](../legacy/docker-deploy/README.md) |
