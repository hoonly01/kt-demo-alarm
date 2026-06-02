# Test Spec — Docker-free next action

## Metadata

| 항목 | 값 |
|---|---|
| Task slug | `docker-free-next-action` |
| Created at (UTC) | `2026-06-01T18:04:49Z` |
| Related PRD | `.omx/plans/prd-docker-free-next-action-20260601T180449Z.md` |
| Source spec | `.omx/specs/deep-interview-docker-free-next-action.md` |
| Baseline branch | `main@0511546ac392ea5ab43aa9755765fd8dbc8a31d7` |
| Advisory contract | `.omx/plans/advisory-contract-docker-free-next-action-20260601T180449Z.md` |
| Operator gate | `.omx/plans/operator-gate-docker-free-next-action-20260601T180449Z.md` |

## 결론

후속 구현 PR의 검증은 **Phase 1 merge-ready / Phase 2 live activation / Phase 3 advisory retirement**로 분리한다.  
Phase 1에서는 advisory contract `template-only-advisory-v1`만 non-blocking evidence로 허용하고, native preflight path / non-template tests / workflow validation은 blocking 이다.

## Baseline Evidence

| 항목 | 결과 | 근거 |
|---|---|---|
| Full pytest baseline | `2 failed, 175 passed, 2 skipped` | `uv run pytest -q` 실행 결과 (2026-06-01 UTC) |
| Failing selector #1 | `tests/test_notification_attendees.py::test_notification_uses_attendees_not_description` | `tests/test_notification_attendees.py:4-18`, `app/services/notification_service.py:73-80` |
| Failing selector #2 | `tests/test_notification_templates.py::test_kakao_skills_upcoming_protests_uses_numbered_brief_template` | `tests/test_notification_templates.py:101-124`, `app/services/notification_service.py:73-80` |
| Non-template suite | `175 passed, 2 skipped, 2 deselected` | `uv run pytest -q --deselect ... --deselect ...` 실행 결과 (2026-06-01 UTC) |
| Current deploy path | Docker build/deploy | `.github/workflows/deploy.yml:31-240` |
| Current bootstrap assumption | Docker install/enable/start | `scripts/setup-ec2.sh:53-65` |
| Root doc/operator surface | Docker badge + Docker-centric bootstrap exposure | `README.md:4-8`, `scripts/setup-ec2.sh:116-123`, `.gitignore:18-21` |

## Gate topology

| Gate | Blocking 여부 | 설명 |
|---|---|---|
| Advisory template regression lane | Non-blocking | `template-only-advisory-v1`에 정의된 selector만 분리해서 보고 |
| Non-template pytest lane | **Blocking** | advisory contract 외 나머지 전체 regression suite |
| Native asset static tests | **Blocking** | script syntax, workflow parse, unit render, asset inventory |
| Native deploy preflight | **Blocking** | package/preflight/guarded dry-run evidence |
| Native deploy live | **Guarded + Blocking when enabled** | operator gate 충족 시에만 실행 |
| Public health | **Blocking after live enable** | deploy 완료 후 public reachability |
| Live cutover operator checklist | **Blocking before production cutover** | 실제 운영 전환 직전 별도 증빙 |

## Advisory selector source of truth

- selector 원본 목록은 `.omx/plans/advisory-contract-docker-free-next-action-20260601T180449Z.md`만 사용한다.
- workflow/test/doc는 contract ID `template-only-advisory-v1`를 참조한다.

### Explicitly forbidden bypass patterns

- 전체 `uv run pytest` job에 대한 broad `continue-on-error`
- template 파일 전체를 무차별 `--ignore`
- 테스트 기대값을 낮춰 green 처리
- 예외 catch/skip 추가로 알림 포맷 회귀를 숨기기

## Test matrix

### A. Repo-level blocking tests

| ID | 목적 | Command / Method | Expected |
|---|---|---|---|
| A1 | non-template regression 유지 | advisory contract selector만 제외한 `uv run pytest -q` | green |
| A2 | native asset 구조 검증 | `uv run pytest tests/test_native_runtime_assets.py -q` 또는 동등한 새 테스트 | green |
| A3 | shell syntax | `bash -n <native scripts>` | green |
| A4 | workflow parse | Python/YAML loader로 `.github/workflows/deploy.yml` parse | green |
| A5 | Docker legacy isolation | root active workflow/runtime에서 Docker asset path 참조가 남지 않는지 검사 | green |
| A6 | activation guard 검증 | workflow assertion (`KT_NATIVE_DEPLOY_ENABLED`, protected env/approval) | guard 없이는 live job 미실행 |

### B. Advisory tests

| ID | 목적 | Command / Method | Expected |
|---|---|---|---|
| B1 | current known regression 증빙 | advisory contract에 정의된 selector만 실행 | 현재는 red 허용, 결과를 summary에 기록 |
| B2 | regression fix 적용 후 full suite 회복 확인 | `uv run pytest -q` | Phase 3에서 green 목표 |

### C. Native deploy workflow tests

| ID | 목적 | Method | Expected |
|---|---|---|---|
| C1 | active workflow가 native canonical path인지 확인 | `.github/workflows/deploy.yml` DAG assertion | `blocking-tests -> package-native-release -> deploy-native-preflight -> deploy-native-live[guarded] -> public-health` 또는 동등 구조 |
| C2 | active workflow가 Docker build/load/compose를 수행하지 않는지 확인 | uncommented workflow text scan | active path에 Docker build/load/compose 없음 |
| C3 | advisory bypass가 중앙 계약만 참조하는지 확인 | workflow command / summary assertion | broad bypass 없음, raw selector 중복 최소화 |
| C4 | runner-side secret rendering 차단 | workflow text scan | active native path에서 app `.env` 생성/업로드 없음 |
| C5 | live activation guard 확인 | workflow `if` / environment protection assertion | operator gate 없이는 live 미실행 |

### D. Native runtime static/dry-run tests

| ID | 목적 | Method | Expected |
|---|---|---|---|
| D1 | source bundle allowlist/denylist | unit/integration test | `.env*`, DB, attachment, key, image tar 제외 |
| D2 | systemd candidate render | render test | placeholder 미해결 없음, required directives 존재 |
| D3 | preflight conflict detection | temp dirs + simulated checks | Docker/native/port conflict를 fail-fast |
| D4 | rollback script behavior | shell/python test double 또는 dry-run harness | current restore/no-previous-current branch 확인 |

### E. Pre-production / operator blocking checks

| ID | 목적 | Method | Expected |
|---|---|---|---|
| E1 | staging/non-production workflow dispatch | operator-triggered dry-run | checksum/manifest/native local health green |
| E2 | target host local health | `curl -fsS http://127.0.0.1:8000/` 또는 configured host/port | green |
| E3 | public health | `curl -fsS https://<public-domain>/` | green |
| E4 | service evidence | `systemctl status`, `journalctl`, release symlink evidence | cutover proof 확보 |
| E5 | operator gate artifact | `.omx/plans/operator-gate-docker-free-next-action-20260601T180449Z.md`의 표 채움 또는 동등 기록 | required prerequisites all pass |

## Required new tests / assertions

후속 구현 PR은 최소 아래 유형의 신규 검증을 추가해야 한다.

1. `tests/test_native_runtime_assets.py` 또는 동등 파일
   - deploy workflow DAG assertion
   - active path에서 Docker 명령 부재 확인
   - native script syntax / non-mutation assertions
   - Docker legacy asset inventory assertions
   - live activation guard assertions
2. legacy asset inventory test
   - `legacy/docker-deploy/` 존재
   - root README/bootstrap/.gitignore가 native canonical + legacy inventory 설계와 모순되지 않음
   - 활성 workflow에서 해당 경로를 직접 쓰지 않음
3. advisory contract assertion
   - summary/log에서 `template-only-advisory-v1`만 advisory로 보고됨
   - raw selector drift 시 contract 동반 업데이트

## Reference provenance for required tests

| 검증 영역 | 우선 provenance | 구현 메모 |
|---|---|---|
| native workflow / asset test skeleton | `7c95ebc371b941ff62d2d9197dddfb02d6cd451a` | `tests/test_native_runtime_assets.py` 골격과 native deploy 구조 아이디어의 1차 출처로 기록 |
| preflight hardening / guard assertion | `be4e66f9094d5e6b8bcb08966d8e56ae3785968a` | writable-dir / input hardening / conflict detection assertion의 1차 출처로 기록 |
| active Docker baseline / root operator surface | current `main@0511546ac392ea5ab43aa9755765fd8dbc8a31d7` | 무엇을 제거·격리해야 하는지 비교 기준으로 유지 |

## Evidence capture contract

| 증거 | 최소 형식 |
|---|---|
| pytest 결과 | command + pass/fail counts |
| workflow validation | parsed YAML or assertion log |
| shell/static validation | executed commands + exit code |
| deploy dry-run | workflow run id 또는 runner log excerpt 요약 |
| operator checks | command name + timestamp + pass/fail |

## Exit criteria

## Exit criteria by phase

### Phase 1 — merge-ready

1. blocking suite green
2. advisory bypass가 `template-only-advisory-v1`로만 제한됨
3. active deploy workflow가 native canonical path + live activation guard를 사용함
4. Docker legacy asset + root operator-facing legacy inventory가 active path에 영향 없음
5. native preflight/package evidence 확보

### Phase 2 — live activation

1. operator gate artifact required prerequisites all pass
2. guarded live job 실행 evidence 확보
3. local/public health evidence 확보
4. rollback branch evidence 확보

### Phase 3 — advisory retirement

1. notification formatter fix merge
2. `uv run pytest -q` full suite green
3. advisory contract 제거

## Out-of-scope validation

- production host에서의 직접 cutover 수행
- bootstrap 전면 재작성 테스트
- template regression fix 자체 구현 (Phase 1 범위 밖)
