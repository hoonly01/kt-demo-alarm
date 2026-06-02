# Operator Gate — docker-free native activation

## Metadata

| 항목 | 값 |
|---|---|
| Gate ID | `native-live-activation-gate-v1` |
| Created at (UTC) | `2026-06-01T18:04:49Z` |
| Related PRD | `.omx/plans/prd-docker-free-next-action-20260601T180449Z.md` |
| Related Test Spec | `.omx/plans/test-spec-docker-free-next-action-20260601T180449Z.md` |

## 결론

native deploy는 **repo merge와 live activation을 분리**해야 한다.  
권장 보호장치는 다음 두 가지를 동시에 요구하는 것이다.

1. repository variable 또는 동등한 explicit flag: `KT_NATIVE_DEPLOY_ENABLED=1`
2. protected environment approval 또는 동등한 운영 승인 단계

이 두 조건 중 하나라도 없으면 `deploy-native-live`는 실행되지 않고, workflow는 preflight/package evidence까지만 남겨야 한다.

## Required prerequisites

| Check | Owner | Evidence example | Pass condition |
|---|---|---|---|
| uv availability | operator | `uv --version` | host에서 `uv` 실행 가능 |
| systemd availability | operator | `systemctl --version` | systemd 관리 가능 |
| app user/group | operator | `id <app-user>` | service 계정 존재 |
| server-owned env | operator | `stat -c '%a %U %G %n' <env-path>` | env path 존재, world access 없음 |
| native app root writable | operator | `stat` / `test -w` 결과 | deploy 계정이 target dir 접근 가능 |
| Docker duplicate risk | operator | `docker ps --format '{{.Names}}'` 또는 승인 메모 | 동일 앱 Docker runtime 없음 또는 명시 승인 있음 |
| port takeover risk | operator | `ss -ltn sport = :8000` 또는 configured port | target listener만 존재하거나 승인 있음 |
| staging/native dry-run | operator | workflow run id / 로그 요약 | package/preflight/local health green |
| rollback readiness | operator | 이전 release/current 존재 여부 + runbook 확인 | 실패 시 복구 절차 명확 |

## Workflow guard contract

| Phase | Workflow expectation |
|---|---|
| Phase 1 — merge-ready | `blocking-tests`, `package-native-release`, `deploy-native-preflight`만 blocking 수행 |
| Phase 2 — activation | `deploy-native-live`는 `KT_NATIVE_DEPLOY_ENABLED=1` **and** protected approval 충족 시에만 실행 |
| Phase 3 — post-activation | `public-health`는 live job 성공 이후에만 blocking 수행 |

## Notes

- 이 gate는 live cutover 안전장치이며, template advisory contract와 별개다.
- `.env` 내용은 출력하지 않는다. path/mode만 증빙한다.
- Docker fallback 재활성화는 이 gate를 통과했다고 자동 허용되지 않는다.

