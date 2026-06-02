# PRD — Docker-free next action

## Metadata

| 항목 | 값 |
|---|---|
| Task slug | `docker-free-next-action` |
| Created at (UTC) | `2026-06-01T18:04:49Z` |
| Planning mode | `$ralplan` |
| Deliberation mode | `deliberate (auto-enabled: live deploy path change)` |
| Source spec | `.omx/specs/deep-interview-docker-free-next-action.md` |
| Context snapshot | `.omx/context/docker-free-next-action-20260601T174942Z.md` |
| Interview transcript | `.omx/interviews/docker-free-next-action-20260601T175955Z.md` |
| Current base | `main@0511546ac392ea5ab43aa9755765fd8dbc8a31d7` |
| Advisory contract | `.omx/plans/advisory-contract-docker-free-next-action-20260601T180449Z.md` |
| Operator gate | `.omx/plans/operator-gate-docker-free-next-action-20260601T180449Z.md` |

## 결론

다음 액션의 권장 범위는 **`main`을 기준으로 한 신규 구현 브랜치에서, native deploy를 canonical path로 전환하되 live activation은 operator gate로 보호하고, Docker 관련 자산은 `legacy/` 아래로 격리 보관하며, advisory bypass는 중앙 계약(`template-only-advisory-v1`)에 고정하는 first pass PR** 이다.

이 first pass는 **앱의 notification formatter 수정 없이** merge-ready native path와 legacy/operator 경계를 만드는 데 한정한다.  
코드 수정은 이 PRD 승인 이후 별도 실행 lane에서만 시작한다.

## 근거

### 현재 상태 증거

| 사실 | 근거 |
|---|---|
| 현재 기본 배포는 `main` push 시 Docker build/deploy 흐름이다 | `.github/workflows/deploy.yml:3-7`, `.github/workflows/deploy.yml:16-64`, `.github/workflows/deploy.yml:127-240` |
| deploy gate는 현재 전체 pytest가 아니라 bypass notice만 기록한다 | `.github/workflows/deploy.yml:17-29` |
| 현재 deploy job은 runner에서 `.env`를 만들고 Docker artifact/compose를 EC2로 보낸다 | `.github/workflows/deploy.yml:74-145` |
| EC2 bootstrap 스크립트는 Docker 설치/enable/start를 전제로 한다 | `scripts/setup-ec2.sh:53-65` |
| 앱은 `uvicorn main:app` 진입점과 설정 기반 파일 경로를 갖고 있어 native runtime 후보가 성립한다 | `main.py:143-151`, `app/config/settings.py:40-52`, `app/config/settings.py:80-88` |
| 알림 formatter는 아직 description 라인을 출력한다 | `app/services/notification_service.py:68-80` |
| 현재 실패는 정확히 template/message 회귀 2건이다 | `tests/test_notification_attendees.py:4-18`, `tests/test_notification_templates.py:101-124`, `uv run pytest -q` 실행 결과(2026-06-01 UTC) |
| 위 2개 셀렉터만 제외하면 나머지 177개 선택 suite는 green이다 | `uv run pytest -q --deselect tests/test_notification_attendees.py::test_notification_uses_attendees_not_description --deselect tests/test_notification_templates.py::test_kakao_skills_upcoming_protests_uses_numbered_brief_template` 실행 결과(2026-06-01 UTC) |

### 기준 브랜치 참고 근거

| 후보 | 판정 | 근거 |
|---|---|---|
| `origin/chore/native-deploy-without-docker` | **참조용 채택** | native source-bundle/systemd deploy, docs/test skeleton을 제공한다. 단, notification formatter 수정은 제외 대상이다. 커밋 `7c95ebc371b941ff62d2d9197dddfb02d6cd451a` |
| `origin/fix/native-runtime-preflight-136` | **부분 참조용 채택** | native preflight hardening(쓰기 가능 디렉터리, workflow input fix)을 보강한다. 커밋 `be4e66f9094d5e6b8bcb08966d8e56ae3785968a` |
| `origin/chore/native-auto-deploy` | **배제** | Docker asset 삭제와 광범위한 test 비활성화 방향이 현재 boundary와 충돌한다. 커밋 `d610f261727bed9ac6a04a42d2961c177ce73a52` |

## RALPLAN-DR 요약

### Principles

1. **Canonical path first** — 기본 GitHub Action 배포 경로는 native deploy여야 한다.
2. **Legacy preservation without influence** — Docker/bootstrap 자산은 형상관리 차원에서 보존하되 활성 서비스/배포 경로에 영향을 주면 안 된다.
3. **Bypass must stay narrow** — 우회는 현재 확인된 template/message 회귀 2건에 한정한다.
4. **Operator-owned cutover** — live EC2/systemd cutover는 `native-live-activation-gate-v1`를 통과한 후에만 수행한다.
5. **No bootstrap rewrite in first pass** — bootstrap은 분류/문서화까지만 하고 전면개편은 후속 과제로 남긴다.

### Decision Drivers

| 우선순위 | Driver | 이유 |
|---:|---|---|
| 1 | 서비스 영향 최소화 | 현재 main deploy가 Docker 전제이므로 급격한 cutover는 중복 runtime/port 충돌 위험이 있다. |
| 2 | gate 정밀도 | broad bypass는 허용되지 않았고, 실제 실패도 2개 selector로 좁혀져 있다. |
| 3 | rollback 가능성 | Docker 자산은 회귀 정책 가능성을 고려해 삭제 대신 격리 보관해야 한다. |

### Viable Options

| 옵션 | 요약 | 장점 | 단점 | 판정 |
|---|---|---|---|---|
| A | `main` 기반 신규 PR에서 native path + Docker legacy 격리 + selector-level bypass | 요구사항과 가장 정합적, diff 범위를 통제 가능, broad bypass 회피 | 설계/테스트 케이스를 새로 정리해야 함 | **권장** |
| B | `origin/chore/native-deploy-without-docker`를 거의 그대로 흡수 | native 자산/문서/테스트 초안이 이미 존재 | notification formatter 변경이 섞여 있고, operator activation guard를 별도 설계해야 함 | 조건부 대안 |
| C | Docker deploy 유지 + native preflight/manual lane만 추가 | 서비스 영향이 가장 작음 | 사용자가 요구한 canonical native path 전환을 충족하지 못함 | 비권장 |

### 옵션 배제 사유

- **Option B를 그대로 병합하지 않는 이유**: native 구조는 유용하지만 notification formatter 수정이 섞여 있고, live activation guard가 현재 요구 수준으로 명시돼 있지 않다.
- **Option C를 선택하지 않는 이유**: “GitHub Action의 주 배포 흐름은 native deploy”라는 명시 요구를 만족하지 못한다.
- **`origin/chore/native-auto-deploy`를 배제하는 이유**: Docker 자산 삭제/광범위한 비활성화가 현재 인터뷰 결정과 충돌한다.

## 문제 정의

현재 `main`의 활성 배포 경로는 Docker 이미지 빌드·전송·`docker compose up` 중심이며, native runtime은 배포의 canonical path가 아니다 (`.github/workflows/deploy.yml:31-240`). 동시에 앱 진입점과 설정 구조는 native runtime으로도 실행 가능하다 (`main.py:143-151`, `app/config/settings.py:40-52`). 따라서 다음 액션은 **native path를 활성화하면서도 Docker/bootstrap 자산을 안전하게 legacy로 분리하고, template/message 회귀 2건만 advisory로 다루는 최소한의 실행 범위**를 합의하는 것이다.

## 목표

### Primary outcome

- `main` 기준 follow-up PR이 다음을 구현할 수 있도록 범위를 고정한다.
  1. GitHub Actions canonical deploy file/graph = native deploy 기준으로 재구성
  2. 단, `deploy-native-live`는 `native-live-activation-gate-v1` 충족 전까지 guard 상태 유지
  3. Docker deploy 관련 자산 + root operator-facing Docker 표면 = `legacy/` inventory 또는 동등한 inactive 표면으로 정리
  4. advisory bypass는 `template-only-advisory-v1` 계약에만 위임
  5. native preflight, non-template tests, health check, 기타 검증은 blocking

### Non-goals

- Docker 자산 삭제
- `scripts/setup-ec2.sh` 전면 재작성
- live EC2/systemd cutover 직접 수행
- notification template 회귀 수정 자체
- broad pytest policy redesign

## Phase plan

| Phase | 목표 | merge/live 기준 |
|---|---|---|
| Phase 1 — merge-ready native path | native-oriented workflow/legacy inventory/guard/테스트 구조 추가 | merge 가능 |
| Phase 2 — live activation | operator gate 충족 후 guarded native live job 활성화 | live 가능 |
| Phase 3 — advisory retirement | notification formatter 수정 후 advisory contract 제거 | full green 복구 |

## 제안 범위

### 1) 기준 브랜치 / PR 기준선

- **Base branch**: `main@0511546ac392ea5ab43aa9755765fd8dbc8a31d7`
- **Implementation branch policy**: `main`에서 새 작업 브랜치를 생성하고, 아래 reference를 **파일/커밋 단위**로 selective-port 한다.
- **Reference import table**

| Source commit | 가져올 대상 | 검증 provenance | 제외/주의 |
|---|---|---|---|
| `7c95ebc371b941ff62d2d9197dddfb02d6cd451a` | `.github/workflows/deploy.yml`의 native release 구조 아이디어, `deploy/native/*`, `docs/native-linux-deploy-guide.md`, `docs/docker-free-fastapi-deploy-runbook.md`, `tests/test_native_runtime_assets.py` 골격 | workflow DAG / legacy inventory / native asset test의 기본 구조 출처로 기록한다. 후속 PR summary에는 이 commit이 workflow/native-doc/test skeleton source였음을 남긴다. | `app/services/notification_service.py`, `tests/test_notification_attendees.py`, `tests/test_notification_templates.py`의 formatter 기대값 변경은 **first pass 제외** |
| `be4e66f9094d5e6b8bcb08966d8e56ae3785968a` | `scripts/native/preflight.sh`의 writable-dir / input hardening 아이디어, preflight 관련 assertion 패턴 | `D3`(preflight conflict detection), `A3`(shell syntax), `A6/C5`(activation guard) 설계 provenance로 기록한다. | `native-runtime.yml`의 “preflight-only lane” 자체는 그대로 흡수하지 않고, 필요한 assertion만 Phase 1 테스트에 재사용 |
| current `main` | 현행 `.github/workflows/deploy.yml`, `scripts/setup-ec2.sh`, `README.md`, `.gitignore` | Phase 1에서 제거/격리해야 할 active Docker surface와 root operator surface의 baseline source of truth다. | Docker active 표면과 `.md` ignore 규칙을 legacy/native 설계에 맞게 조정해야 함 |
- **금지 기준선**: `origin/chore/native-auto-deploy` 직병합 금지

### 2) 활성 deploy workflow 전환

- `.github/workflows/deploy.yml`의 활성 graph를 Docker build/deploy에서 native deploy graph로 전환한다.
- 권장 active graph:

```text
blocking-tests -> package-native-release -> deploy-native-preflight
                    |                         |
                    |                         +-> deploy-native-live [guarded]
                    |                                     |
                    +-> advisory-template-regression      +-> public-health
```

- **guarded live job contract**
  - `deploy-native-live`는 `KT_NATIVE_DEPLOY_ENABLED=1` 같은 explicit activation flag가 켜져 있고,
  - protected environment approval 또는 동등한 운영 승인 절차를 통과했을 때만 실행한다.
  - guard가 닫혀 있으면 workflow는 preflight/package/advisory evidence까지만 남기고 성공/중립 종료한다.
- **blocking-tests**는 전체 pytest를 broad bypass하지 않고, advisory contract `template-only-advisory-v1`에 정의된 selector만 advisory lane으로 분리한다.
- 나머지 test suite는 blocking 유지가 원칙이다.

### 3) Docker legacy 격리 정책

- first pass에서 아래 자산은 활성 root path에서 제거하고 `legacy/docker-deploy/` 아래로 이동하는 방향을 권장한다.
  - `Dockerfile`
  - `docker-compose.yml`
  - `.dockerignore`
  - Docker-specific 배포/운영 설명서
- 위 이동/격리는 **후속 execution lane에서만 실제 수행**하며, 현재 `$ralplan` 단계에서는 inventory/경계 문구만 고정한다.
- **operator-facing legacy inventory 확대**
  - `scripts/setup-ec2.sh`는 legacy Docker bootstrap로 분류
  - root `README.md`의 Docker badge/설명은 legacy 또는 historical note로 재표현
  - `.gitignore`의 `*.md` 규칙 때문에 native docs가 무시되지 않도록 예외 규칙을 같이 정리
- `legacy/docker-deploy/README.md`를 추가해 다음을 명시한다.
  - inactive legacy asset임
  - 활성 workflow/runtime가 참조하지 않음
  - 재활성화 시 새 PRD와 운영 승인 필요

### 4) Bootstrap 자산 처리

- `scripts/setup-ec2.sh`는 현재 Docker 설치/enable/start를 수행하므로 legacy bootstrap으로 분류한다 (`scripts/setup-ec2.sh:53-65`).
- **first pass에서는 bootstrap 동작 재작성 대신 분류/문서화만 수행**한다.
  - 예: `legacy/bootstrap/README.md` 또는 운영 runbook에 현재 script가 legacy Docker bootstrap임을 명시
  - root에 파일이 남더라도 canonical operator path가 아니라는 사실을 명시해야 한다.
  - 실제 script relocation/rewrite는 follow-up backlog로 분리

### 5) Native runtime 자산 범위

- 신규 native deploy PR은 아래 범위를 포함할 수 있다.
  - `deploy/native/` 또는 동등한 native release asset 디렉토리
  - systemd unit template
  - native preflight/setup/healthcheck scripts
  - source-bundle allowlist/denylist 검증
  - deploy workflow 구조 테스트(`tests/test_native_runtime_assets.py` 또는 동등 테스트)
- 앱 코드 변경은 **first pass에서 원칙적으로 금지**한다.
- 특히 아래 파일은 Phase 1 selective-port 대상에서 제외한다.
  - `app/services/notification_service.py`
  - `tests/test_notification_attendees.py`
  - `tests/test_notification_templates.py`

### 6) Advisory contract

- advisory bypass의 단일 source of truth는 `.omx/plans/advisory-contract-docker-free-next-action-20260601T180449Z.md` 이다.
- workflow/test/doc는 contract ID(`template-only-advisory-v1`)를 참조하고, raw selector 중복을 최소화한다.

### 7) Secret / runtime ownership 정책

- **Phase 1 ADR 결정**: active native workflow는 runner-side app `.env`를 생성·업로드하지 않는다.
- 이유: 현재 Docker deploy는 runner에서 `.env`를 생성·전송한다 (`.github/workflows/deploy.yml:107-145`); native canonical path에서는 server-owned env contract가 더 안전하고 `native-live-activation-gate-v1`와도 정합적이다.
- 따라서 follow-up PR은 아래를 명시적으로 구현·검증해야 한다.
  1. app secret는 target host의 server-owned env path에만 존재
  2. workflow는 env **내용**이 아니라 path/mode/owner evidence만 다룬다
  3. 이 계약을 만족하지 못하면 `deploy-native-live`는 계속 guard 상태로 남고, runner-side env rendering으로 되돌아가지 않는다

### 8) Operator activation artifact

- live activation 전제조건과 증빙 형식은 `.omx/plans/operator-gate-docker-free-next-action-20260601T180449Z.md`를 따른다.
- 최소 요구 증빙:
  - uv/systemd/app user 존재
  - server-owned env path/mode
  - Docker duplicate 여부
  - port takeover 여부
  - staging/native dry-run evidence
  - rollback readiness evidence

## Acceptance Criteria

1. 계획 산출물은 `main` 기반 신규 PR을 canonical execution baseline으로 지정한다.
2. 계획 산출물은 native deploy active graph와 live activation guard를 함께 명시한다.
3. 계획 산출물은 Docker legacy 격리 + root operator-facing legacy inventory를 함께 명시한다.
4. 계획 산출물은 advisory bypass를 contract ID로 중앙화한다.
5. 계획 산출물은 reference selective-port를 파일/커밋 단위로 명시한다.
6. 계획 산출물은 operator gate artifact와 증빙 항목을 명시한다.
7. 계획 산출물은 Docker asset 삭제와 bootstrap rewrite, notification formatter fix를 Phase 1 non-goal로 남긴다.
8. 계획 산출물은 code-change-free handoff임을 유지한다.

## Acceptance Criteria ↔ Verification Crosswalk

| AC | 의미 | 1차 검증 ID / 증거 | 완료 판정 |
|---|---|---|---|
| AC1 | `main` 기반 신규 PR이 canonical execution baseline이다 | PRD metadata, reference import table, C1 | follow-up PR brief와 active workflow 설계가 `main` 기준을 유지 |
| AC2 | native deploy active graph + live activation guard를 명시한다 | A4, A6, C1, C5, operator gate | active graph와 guard가 동시에 검증됨 |
| AC3 | Docker legacy 격리 + root operator-facing legacy inventory를 명시한다 | A5, Required new tests #2 | root active path에서 Docker legacy 영향이 제거됨 |
| AC4 | advisory bypass를 contract ID로 중앙화한다 | B1, C3, advisory contract | raw selector drift 없이 contract ID만 사용 |
| AC5 | selective-port provenance를 파일/커밋 단위로 명시한다 | reference import table, provenance section, E1 evidence note | 구현 PR summary가 source commit↔artifact 관계를 복원 가능 |
| AC6 | operator gate artifact와 증빙 항목을 명시한다 | E1-E5, operator gate | live activation 이전 필수 조건이 모두 추적 가능 |
| AC7 | Docker asset 삭제 / bootstrap rewrite / formatter fix를 non-goal로 유지한다 | PRD non-goals, Out-of-scope validation | execution lane이 범위를 넘지 않음 |
| AC8 | planning-only handoff를 유지한다 | PRD 결론, legacy isolation note, Critic handoff packet | `$ralplan`이 구현으로 넘어가지 않음 |

## Pre-mortem

| 시나리오 | 실패 형태 | 완화책 |
|---|---|---|
| Docker 자산 이동 후 숨은 참조가 남음 | 로컬 문서/스크립트/CI가 옛 root path를 계속 참조 | asset inventory test + grep/LSP 기반 참조 검사 + legacy README 추가 |
| native/runtime cutover와 Docker runtime이 중복 실행 | scheduler 이중 실행, 포트 충돌, 불명확한 rollback | preflight에서 Docker/native active conflict 감지, `native-live-activation-gate-v1`, local/public health blocking |
| template-only bypass가 넓어지거나 이름 drift가 생김 | unrelated regression이 deploy를 통과하거나 workflow가 깨짐 | `template-only-advisory-v1` 중앙 계약, selector 변경 시 contract 동반 수정, broad `continue-on-error` 금지 |

## Expanded Test Planning

### Unit

- notification formatter regression selectors 두 개를 advisory suite로 분리 검증
- source bundle allowlist/denylist 유닛 테스트
- systemd template render assertions
- Docker legacy path inventory assertions

### Integration

- `uv run pytest -q --deselect <2 selectors>` blocking green 유지
- native asset syntax (`bash -n`) / workflow YAML parse / DAG 구조 테스트
- native preflight dry-run test
- deploy workflow가 active Docker build step를 갖지 않는지 검사
- deploy live job guard(`KT_NATIVE_DEPLOY_ENABLED`, protected approval) assertion

### E2E / Ops

- non-production `workflow_dispatch` 또는 staging equivalent에서 native release dry-run
- remote local health (`curl http://127.0.0.1:8000/`) 및 public health blocking
- rollback path validation(이전 release/current 복원)

### Observability

- GitHub job summary에 advisory bypass selector 결과를 별도 표기
- deploy 로그에서 current release id, health timing, rollback branch를 식별 가능하게 유지
- live cutover 시 `systemctl status`, `journalctl`, public health evidence 수집

## ADR

### Decision

`main` 기반 신규 follow-up PR에서 native deploy를 canonical path로 전환하되, live activation은 explicit operator gate 뒤로 미루고, Docker 자산 및 root operator-facing Docker 표면은 `legacy/` inventory로 격리하며, advisory bypass는 `template-only-advisory-v1` 계약으로 중앙화한다.

### Drivers

- 사용자 의사결정: native canonical path + Docker asset 보존 + template-only bypass
- 실제 baseline: 전체 pytest 실패는 2 selector에 한정, 그 외 suite는 green
- 서비스 안전성: 현재 production path는 Docker 전제이고 bootstrap도 Docker 전제

### Alternatives considered

1. `origin/chore/native-deploy-without-docker` 직접 흡수
2. Docker path 유지 + native preflight만 추가
3. `origin/chore/native-auto-deploy` 방향 채택

### Why chosen

권장안은 사용자 제약과 현재 코드/테스트 증거를 모두 만족하면서도, broad bypass와 Docker asset deletion을 피한다.

### Consequences

- 후속 PR은 deploy workflow, legacy asset path, native runtime asset, 테스트 구조, operator docs를 함께 건드리는 중간 규모 변경이 된다.
- Phase 1 merge와 Phase 2 live activation이 분리되므로, merge 직후 production cutover가 자동으로 일어나지 않는다.
- template regression fix는 Phase 3까지 남으므로 advisory lane이 한동안 유지된다.
- bootstrap rewrite는 후속 과제로 남아 기술부채가 유지된다.

### Follow-ups

1. Phase 1 implementation PR 생성
2. native asset / legacy inventory / guard tests 추가
3. operator gate evidence 수집
4. guarded live activation 수행
5. notification formatter fix PR로 advisory contract retire

## 실행 핸드오프 초안

### 권장 lane

- **기본 권장**: `$ultragoal`
- **병렬 실행 필요 시**: `$ultragoal` + `$team`
- **명시적 단일-owner 루프가 필요한 경우만**: `$ralph` fallback

### Goal-Mode Follow-up Suggestions

| Follow-up | 권장도 | 적용 조건 | 이유 |
|---|---|---|---|
| `$ultragoal` | **기본 권장** | 일반 구현/정리/검증을 durable goal ledger로 이어갈 때 | 이 작업은 연구 프로젝트나 성능 최적화 프로젝트가 아니라, 배포 경로 전환과 검증 증거 수집이 핵심인 구현형 작업이다. |
| `$ultragoal` + `$team` | **병렬 구현 권장** | workflow/native asset/legacy inventory/docs를 병렬로 나눠야 할 때 | Ultragoal이 leader-owned ledger를 유지하고, Team이 병렬 작업 증거를 되돌려 줄 수 있다. |
| `$autoresearch-goal` | 비권장 | follow-up이 배포 설계 자체가 아니라 외부 비교 연구/문헌 검증으로 바뀔 때만 | 현재는 이미 repo-local evidence와 candidate branch evidence가 충분해 research-first가 아니다. |
| `$performance-goal` | 비권장 | 목표가 latency/throughput/benchmark 최적화로 바뀔 때만 | 현재 PRD의 성공 조건은 배포 topology와 guard 설계이지 성능 지표가 아니다. |
| `$ralph` | 명시적 fallback만 허용 | 사용자가 단일-owner 지속 검증 루프를 의도적으로 선택할 때 | durable ledger와 병렬 lane이 필요한 작업이라 기본값으로 쓰지 않는다. |

### Suggested staffing

| Lane | Ideal role | Team runtime realization | 권장 headcount | 권장 reasoning | 책임 |
|---|---|---|---:|---|---|
| Workflow lane | `executor` | worker-1 (`executor`) | 1 | medium | `deploy.yml`, native asset graph, advisory/blocking gate 구조, live guard |
| Legacy/operator surface lane | `executor` | worker-2 (`executor`) | 1 | medium | `legacy/docker-deploy/*`, bootstrap/README/.gitignore inventory |
| Native asset lane | `executor` | worker-3 (`executor`) | 1 | medium | `deploy/native/*`, preflight/source-bundle/systemd asset 뼈대 |
| Docs/evidence lane | `writer` | worker-4 (`executor`, writer checklist 적용) | 1 | medium | operator gate/runbook/native guide, summary/evidence 초안 |
| Verification checkpoint | `verifier` / `test-engineer` | leader-owned after `omx team await` | leader-owned | high / medium | A/C/D matrix 통합 검증, B1 advisory evidence 정리, checkpoint-ready evidence 합성 |
| Final boundary review | `architect` | leader-owned final review lane | leader-owned | xhigh | cutover/rollback invariants, operator gate boundary, reviewer handoff |

> `omx team`은 한 번에 하나의 `agent-type`만 받으므로, **실제 tmux 팀 실행 모델은 `4:executor`** 로 고정한다. `writer`/`verifier`는 이상적 역할이며, 이번 handoff에서는 `worker-4 executor + leader-owned verification checkpoint`로 현실화한다.

### Available agent types

`explore`, `planner`, `architect`, `critic`, `executor`, `test-engineer`, `verifier`, `writer`, `researcher`

### Explicit launch hints

| 경로 | 검증된 힌트 | 설명 |
|---|---|---|
| Ultragoal brief 생성 | `omx ultragoal create-goals --brief-file .omx/plans/prd-docker-free-next-action-20260601T180449Z.md` | PRD를 durable goal brief로 등록한다. |
| Ultragoal 실행 시작/재개 | `omx ultragoal complete-goals` | 실제 durable execution start/continue는 이 단계에서 이루어진다. |
| Team 병렬 실행(선택) | `omx team 4:executor "Implement docker-free next action Phase 1 from .omx/plans/prd-docker-free-next-action-20260601T180449Z.md and .omx/plans/test-spec-docker-free-next-action-20260601T180449Z.md"` | 4 executor worker가 workflow / legacy / native asset / docs-evidence를 분담한다. |
| Skill 경로 힌트 | `$team 4:executor "Implement docker-free next action Phase 1 from approved PRD/test-spec"` | tmux runtime에서 동일 의미의 skill 호출 힌트다. |
| 후속 상태 확인 | `omx team status <team-name> --json` | worker evidence와 진행률을 leader가 수집한다. |
| 팀 완료 대기 | `omx team await <team-name> --json` | team terminal evidence를 받은 뒤 leader-owned verification/checkpoint로 넘어간다. |
| Ultragoal checkpoint bridge | `omx ultragoal checkpoint --goal-id <goal-id> --status complete --evidence "<team evidence mentioning .omx/ultragoal and <goal-id>>" --codex-goal-json <fresh-get_goal-json-or-path>` | team evidence를 durable ledger에 반영하는 최종 shell-side checkpoint 형식이다. |

### Concrete team verification path

| 순서 | Owner | 범위 | 검증 ID / 증거 | Team 완료 조건 |
|---|---|---|---|---|
| 1 | worker-1 (`executor`) | active workflow / guard 구현 | A4, A6, C1-C5 | DAG/guard/advisory contract가 active path에서 통과 |
| 2 | worker-2 (`executor`) | Docker legacy 격리 / root operator surface | A5, Required new tests #2 | root active path에서 legacy 영향이 제거되고 inventory가 남음 |
| 3 | worker-3 (`executor`) | native preflight / systemd / bundle asset | A2, A3, D1-D4 | native asset static/dry-run 검증이 green |
| 4 | worker-4 (`executor`) | docs / runbook / evidence draft | B1 summary draft, E1 준비 증거, operator gate 문서 반영 | operator가 live activation 전 체크리스트와 summary 초안을 바로 사용할 수 있음 |
| 5 | leader-owned `verifier`/`test-engineer` checkpoint | cross-lane 통합 검증 | A1-A6, B1, C1-C5, D1-D4, E1 readiness summary | blocking 항목 green + advisory only lane 기록 + evidence capture contract 충족 |
| 6 | leader-owned `architect` boundary review | cutover/rollback boundary 재확인 | operator gate, frozen decisions, unresolved tensions | checkpoint 직전 handoff invariant가 깨지지 않음 |

**Team terminal condition:** `omx team await`는 worker terminal evidence만 보장한다. 실제 Phase 1 completion은 그 이후 leader-owned step 5-6까지 끝나고, 최소 `A1-A6`, `C1-C5`, `D1-D4`가 green이며 `B1`은 advisory evidence로만 남고, operator-only `E2-E5`는 `Phase 2 pending` 또는 별도 실행 증거로 분리됐을 때만 성립한다.

### Ultragoal durable execution bridge

1. leader는 `omx ultragoal create-goals --brief-file ...`로 plan artifact를 durable goal로 등록한다.
2. 실제 execution handoff는 `omx ultragoal complete-goals`에서 시작한다.
3. 현재 story가 병렬 분할 가치가 있을 때만 `omx team 4:executor ...`를 추가로 실행한다.
4. `omx team await <team-name> --json` 후, leader가 Codex에서 fresh `get_goal` snapshot을 확보한다.
5. leader-owned verification/boundary review가 끝나면 `omx ultragoal checkpoint ... --codex-goal-json <fresh-get_goal-json-or-path>`로 checkpoint한다.
6. 병렬 fan-out이 필요 없는 story라면 team 없이 같은 `complete-goals -> fresh get_goal -> checkpoint` 순서를 따른다.

### Critic durable handoff packet

#### Frozen decisions

1. `main` 기반 신규 PR에서 native deploy를 canonical path로 전환한다.
2. live activation은 `native-live-activation-gate-v1` 뒤로 고정한다.
3. Docker asset은 삭제하지 않고 `legacy/` inventory로 격리한다.
4. advisory bypass는 `template-only-advisory-v1`만 허용한다.
5. active native workflow는 runner-side app `.env`를 생성/업로드하지 않는다.
6. `$ralplan`은 planning-only이며 실제 자산 이동/구현은 후속 execution lane에서만 수행한다.

#### Unresolved tensions to preserve

| 긴장 지점 | 현재 결정 | Critic 재검증 포인트 |
|---|---|---|
| canonical native path vs rollout 보수성 | repo-level canonical switch 허용, live guard는 유지 | guard가 충분히 강한지 |
| legacy preservation vs operator simplicity | asset 보존 + root surface 정리 병행 | root/operator 문구가 과하거나 부족하지 않은지 |
| advisory narrowness vs selector drift | central contract 유지 | contract drift 대응이 충분히 testable한지 |

#### Critic review focus

- AC↔verification crosswalk가 실제 follow-up execution에 충분히 구체적인지
- Goal-Mode Follow-up Suggestions가 제품 관점에서 일관적인지
- Team launch hints와 team terminal condition이 실제 durable handoff로 충분한지
- secret/runtime ownership 결정이 모호하지 않은지

### Iteration changelog

- Architect ITERATE를 반영해 Goal-Mode Follow-up Suggestions를 추가했다.
- AC↔verification crosswalk와 Critic durable handoff packet을 추가했다.
- runner-side env rendering 금지 결정을 Phase 1 ADR로 고정했다.
- staffing 표를 `ideal role`과 `team runtime realization`으로 분리해 `4:executor` 운영 모델과 정합시켰다.
- `omx ultragoal complete-goals` 및 checkpoint bridge를 추가해 default durable handoff를 artifact 생성에서 실행 단계까지 닫았다.
- team verification path를 worker-1~4 + leader-owned verifier/architect checkpoint 모델로 재정렬했다.
