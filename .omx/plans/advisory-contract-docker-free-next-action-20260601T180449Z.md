# Advisory Contract — docker-free next action

## Metadata

| 항목 | 값 |
|---|---|
| Contract ID | `template-only-advisory-v1` |
| Created at (UTC) | `2026-06-01T18:04:49Z` |
| Scope | docker-free native deploy first pass |
| Related PRD | `.omx/plans/prd-docker-free-next-action-20260601T180449Z.md` |
| Related Test Spec | `.omx/plans/test-spec-docker-free-next-action-20260601T180449Z.md` |

## 목적

`template-only bypass`의 허용 범위를 **정확히 2개 selector**로 중앙화한다.  
이 문서 외의 workflow/test/doc에는 raw selector 목록을 중복 정의하지 않는 것을 원칙으로 한다.

## Allowed advisory selectors

| Selector | 근거 |
|---|---|
| `tests/test_notification_attendees.py::test_notification_uses_attendees_not_description` | `tests/test_notification_attendees.py:4-18`, `app/services/notification_service.py:68-80` |
| `tests/test_notification_templates.py::test_kakao_skills_upcoming_protests_uses_numbered_brief_template` | `tests/test_notification_templates.py:101-124`, `app/services/notification_service.py:68-80` |

## Contract rules

1. 위 두 selector만 advisory lane으로 분리 가능하다.
2. broad `continue-on-error`, glob ignore, 디렉터리 단위 skip은 금지한다.
3. selector 이름이 바뀌면 이 contract를 같은 PR에서 함께 갱신해야 한다.
4. selector 개수가 2개를 초과하면 first pass merge 기준을 만족하지 못한다.
5. advisory lane은 증빙(summary/log) 용도이며, live deploy safety gate를 대체하지 않는다.

## Exit condition

아래 조건이 충족되면 이 contract는 retire 대상이다.

- 알림 template 회귀 수정 PR이 merge됨
- `uv run pytest -q` 전체 suite가 green
- deploy workflow가 더 이상 advisory selector를 참조하지 않음

