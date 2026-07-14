# 프로그램 목록 (Program List)

> **KT Demo Alarm** — 종로구 집회/버스통제 알림 서비스 (FastAPI)
>
> 향후 유지보수를 용이하게 하기 위해 개발된 프로그램의 **디렉토리 구조·설명**, 프로그램을 구성하는
> **파일(PY / HTML / SQL / 설정)의 목록과 위치**, 그리고 **환경설정파일**을 정의한다.
>
> - **아키텍처**: Router — Service — Repository 계층형 (`main.py`가 조립)
> - **런타임**: Python 3.12+ / FastAPI / uvicorn / APScheduler / SQLite(ORM 미사용)
> - **진입점**: 리포지토리 루트 `main.py` (`main:app`)
> - **작성 기준**: 실제 소스코드 및 각 디렉토리 `AGENTS.md` 교차검증

---

## 1. 디렉토리 구조

```
kt-demo-alarm/                         ① 프로젝트 루트 (Eclipse가 아닌 uv 기반 단위 프로젝트)
├── main.py                            ② FastAPI 진입점 : 앱 조립 · 라우터 등록 · lifespan(DB 초기화/스케줄러)
├── pyproject.toml / uv.lock           의존성 매니페스트 / 잠금 파일
├── .env.example                       환경변수 예시 (실제 .env 는 운영 서버가 소유)
├── app/                               ③ 애플리케이션 패키지 (계층별 하위 패키지만 존재, app 직속 모듈 없음)
│   ├── routers/                       ④ HTTP 엔드포인트 : 카카오 스킬/웹훅 · REST · 관리자
│   ├── services/                      ⑤ 비즈니스 로직 : 크롤링 · 알림 발송 · 경로/구역 매칭 · 상태추적
│   │   ├── crawling/                  ─ SMPA 집회 수집 파이프라인 (신규·단위테스트 대상)
│   │   └── bus_logic/                 ─ TOPIS 버스통제 크롤러 내부 (PDF/이미지/AI 추출)
│   ├── models/                        ⑥ Pydantic 요청/응답 · 카카오 페이로드 스키마 (검증부)
│   ├── database/                      ⑦ SQLite 스키마 · 부트스트랩/마이그레이션 · 커넥션 (ORM 없음)
│   ├── config/                        환경설정 (pydantic-settings 단일 Settings)
│   ├── utils/                         공통 헬퍼 : 시간 · 지리/지오코딩 · 스케줄러 · 파일정리
│   └── templates/                     ⑧ 관리자 대시보드 Jinja2 템플릿
├── deploy/native/                     무중단 네이티브 배포 자산 (systemd 유닛 · 소스번들 · 헬스체크)
├── nginx/                             리버스 프록시 설정 (TLS 종단 → 127.0.0.1:8000)
├── scripts/                           EC2/런타임 셋업 스크립트
├── sql/                               수동 테스트용 SQL 픽스처 (events 시드)
└── tests/                             pytest 스위트 (계층별 미러링)
```

## 2. 디렉토리 설명 (계층·모듈 구성)

| 구분 | 디렉토리 | 모듈(파일) | 설명 |
|------|---------|-----------|------|
| **진입점** | `/` | `main.py` | FastAPI 앱 생성, 8개 라우터 등록, `/` 헬스체크, `lifespan`에서 `init_db()`·스케줄러 기동/종료 |
| **④ 라우터** | `app/routers` | `users.py` / `events.py` / `alarms.py` / `kakao.py` / `kakao_skills.py` / `scheduler.py` / `bus_notice.py` / `admin.py` | HTTP 표면. 얇게 유지 — 카카오 스킬/웹훅 파싱, 인증(API키·Basic·CSRF), 서비스 위임, 응답 정형화 |
| **⑤ 서비스** | `app/services` | `user_service` / `event_service` / `notification_service` / `notification_payload_assembler` / `alarm_status_service` / `zone_alarm_service` / `bus_notice_service` / `crawling_service` / `auth_service` | 비즈니스 로직·외부 API 오케스트레이션. 트랜잭션 소유, dict/Pydantic 반환 |
| ─ 수집(SMPA) | `app/services/crawling` | `smpa_pipeline` / `smpa_source` / `smpa_parser` / `smpa_coordinates` / `smpa_geocode_rules` / `smpa_event_sync` | 집회 수집→파싱→지오코딩→해시 기반 upsert 파이프라인 (신규) |
| ─ 수집(버스) | `app/services/bus_logic` | `restricted_bus` / `position_checker` / `hwpx2pdf` / `extract_image` | TOPIS 버스통제 공지 크롤러·PDF/이미지 변환·AI 추출 |
| **⑥ 모델** | `app/models` | `user.py` / `event.py` / `alarm.py` / `kakao.py` / `responses.py` | Pydantic 검증/직렬화 계약 (DB 스키마와 별개) |
| **⑦ DB** | `app/database` | `models.py` / `bootstrap.py` / `connection.py` / `compatibility_probe.py` | SQLite 스키마 원본·부트스트랩·커넥션·호환성 진단 |
| 설정 | `app/config` | `settings.py` | 환경변수 기반 `Settings` 싱글턴 + `setup_logging()` |
| 유틸 | `app/utils` | `time_utils` / `geo_utils` / `scheduler_utils` / `file_cleanup` | 시간(UTC/KST)·지리연산/지오코딩·APScheduler·이미지 정리 |
| **⑧ 템플릿** | `app/templates` | `admin_dashboard.html` | 운영자용 단일 대시보드(HTML+inline CSS/JS) |

> **참고 (레퍼런스와의 차이)**: 본 프로젝트는 Java/JSP(Servlet-Action-DAO-Model)가 아니라 **Python/FastAPI**이다.
> 레퍼런스의 `action` ≈ **라우터**, `dao/model` ≈ **서비스 + database**, `model` ≈ **Pydantic models**,
> JSP 페이지 ≈ **카카오 스킬 JSON 응답 / 관리자 HTML 템플릿**, `QUERY(xml)` ≈ **`database/models.py`의 인라인 SQL**에 대응한다.

---

## 3. 프로그램 목록

> **프로그램ID** = 하나의 기능을 수행하기 위해 관련 파일을 묶은 식별자. **구분** = 파일 형태(PY/HTML/SQL).
> 모델(`app/models`)·DB(`app/database`)·유틸(`app/utils`) 계층은 대부분의 프로그램이 공유하므로 §4에 별도 기재하고,
> 아래에는 각 프로그램의 **핵심 구성 파일**(라우터·서비스·모델·템플릿)을 기재한다.

### 3.1 사용자 관리 (`/users`)

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 1 | user_list | PY | app/routers | users.py `GET /users` | 사용자 목록 + 경로정보 조회 (API키 필요) |
| | | PY | app/services | user_service.py | 사용자 조회/식별(plusfriend→bot 우선순위) |
| 2 | user_initial_setup | PY | app/routers | users.py `POST /users/initial-setup` | 온보딩: 출발/도착·버스·언어 초기 등록 |
| | | PY | app/services | user_service.py | upsert + 출발/도착지 지오코딩(`get_location_info`) |
| | | PY | app/models | user.py `InitialSetupRequest` | 온보딩 요청 스키마 |
| 3 | user_preferences | PY | app/routers | users.py `POST /users/{user_id}/preferences` | 사용자 개인화(위치/카테고리/버스/언어) 갱신 |
| | | PY | app/models | user.py `UserPreferences` | 선호 설정 스키마 |
| 4 | user_alarm_setting | PY | app/routers | users.py `POST /users/alarm-setting` | 알림 on/off 상태 변경 (스킬판과 동기 유지) |
| | | PY | app/services | user_service.py | `update_user_status` |

### 3.2 집회 이벤트 (`/events`)

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 5 | event_create | PY | app/routers | events.py `POST /events` | 집회 이벤트 생성 (API키 필요) |
| | | PY | app/services | event_service.py | 이벤트 저장 |
| | | PY | app/models | event.py `EventCreate` / `EventResponse` | 생성 입력 / 응답 스키마 |
| 6 | event_list | PY | app/routers | events.py `GET /events` | 집회 이벤트 목록 조회 |
| 7 | event_auto_route_check | PY | app/routers | events.py `POST /events/auto-check-all-routes` | 경로 등록 활성 사용자 전체에 근접 집회 검사(fan-out) |
| | | PY | app/services | event_service.py `check_route_events` | 경로-집회 근접 판정 (카카오 모빌리티/직선거리) |
| | | PY | app/utils | geo_utils.py | `haversine_distance` / 경로 근접 연산 |

### 3.3 알림 발송 (`/alarms`)

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 8 | alarm_send | PY | app/routers | alarms.py `POST /alarms/send` | 단일 사용자 카카오 알림 발송 (API키) |
| | | PY | app/services | notification_service.py | 메시지 포맷 + 카카오 Event API 전송 |
| | | PY | app/services | notification_payload_assembler.py | 알림 본문 계약(DTO) 정규화 |
| | | PY | app/services | alarm_status_service.py | `alarm_tasks` 작업 생성/상태 추적 |
| | | PY | app/models | alarm.py `AlarmRequest` | 단건 알림 요청 스키마 |
| 9 | alarm_send_all | PY | app/routers | alarms.py `POST /alarms/send-to-all` | 전체 사용자 대량 발송(≤100 배치) |
| | | PY | app/services | notification_service.py `send_bulk_alarm` | 대량 전송·결과 폴링 |
| 10 | alarm_send_filtered | PY | app/routers | alarms.py `POST /alarms/send-filtered` | 위치/버스/경로 필터 조건 대량 발송 |
| | | PY | app/models | alarm.py `FilteredAlarmRequest` | 필터 발송 요청 스키마 |
| 11 | alarm_status | PY | app/routers | alarms.py `GET /alarms/status`, `GET /alarms/status/{task_id}` | 알림 작업 상태/목록 조회 |
| | | PY | app/models | responses.py | 상태/목록 응답 모델 |
| 12 | alarm_cleanup | PY | app/routers | alarms.py `POST /alarms/cleanup-old-tasks` | N일 경과 알림 작업 정리 |

### 3.4 카카오 챗봇 연동 (`/kakao`)

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 13 | kakao_chat | PY | app/routers | kakao.py `POST /kakao/chat` | 챗봇 폴백 블록: `plusfriend/bot_user_key`로 사용자 upsert·연결 |
| | | PY | app/services | user_service.py `sync_kakao_user` | 카카오 신원 정합(고아/웹훅 행 연결) |
| | | PY | app/models | kakao.py | 카카오 Event API 페이로드 |
| 14 | kakao_channel_webhook | PY | app/routers | kakao.py `POST /kakao/webhook/channel` | 채널 추가/차단 이벤트 처리(open_id 기준) |

### 3.5 카카오 스킬 블록 (root, prefix 없음 — `kakao_skills.py`)

> 카카오 관리자에 등록되는 실제 URL. 스킬 핸들러는 예외를 잡아 **항상 HTTP 200**으로 응답한다(카카오 3초 제약).

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 15 | skill_upcoming_protests | PY | app/routers | kakao_skills.py `POST /upcoming-protests` | 예정 집회 목록 카드 응답 |
| | | PY | app/services | event_service.py | 이벤트 조회 |
| 16 | skill_today_protests | PY | app/routers | kakao_skills.py `POST /today-protests` | 오늘 집회 목록 카드 응답 |
| 17 | skill_check_route | PY | app/routers | kakao_skills.py `POST /check-route` | 내 경로상 집회 확인 |
| | | PY | app/services | event_service.py / user_service.py | 경로-집회 근접 판정 + 사용자 경로 조회 |
| 18 | skill_route_setting | PY | app/routers | kakao_skills.py `POST /route-setting`, `/route-setting/delete` | 출발/도착 경로 등록·삭제 |
| | | PY | app/services | user_service.py | 경로 저장/삭제 + 지오코딩 |
| 19 | skill_save_user_info | PY | app/routers | kakao_skills.py `POST /save_user_info` | 사용자 정보 저장 |
| 20 | skill_favorite_zone | PY | app/routers | kakao_skills.py `POST /favorite-zone`, `/favorite-zone/save` | 관심구역(1/2/3) 선택·저장 |
| | | PY | app/services | user_service.py `update_favorite_zone` | 관심구역 갱신 |
| | | PY | app/utils | geo_utils.py `FAVORITE_ZONES` | 구역 중심/반경 정의 |
| 21 | skill_save_marked_bus | PY | app/routers | kakao_skills.py `POST /save_marked_bus` | 즐겨찾는 버스 저장 |
| 22 | skill_alarm_setting | PY | app/routers | kakao_skills.py `POST /alarm-setting`, `/alarm-setting/save` | 알림 on/off 설정(카카오 등록 URL) |

### 3.6 버스 통제 공지 (`/bus`)

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 23 | bus_webhook | PY | app/routers | bus_notice.py `POST /bus/webhook/{bus_info,route_check,route_image,help}` | 카카오 버스통제 질의 응답(노선번호 파싱) |
| | | PY | app/services | bus_notice_service.py | TOPIS 공지 캐시·경로이미지·응답 템플릿 |
| | | PY | app/services/bus_logic | restricted_bus.py `TOPISCrawler` | 공지 수집·PDF/이미지·AI 추출 |
| 24 | bus_rest | PY | app/routers | bus_notice.py `GET /bus/status`,`/notices`,`/routes/{route}/controls`, `POST /bus/position/controls` | 버스통제 데이터 REST 노출 |
| | | PY | app/services/bus_logic | position_checker.py | 위치기반 인근 정류장 조회 |

### 3.7 스케줄러 상태 (`/scheduler`)

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 25 | scheduler_status | PY | app/routers | scheduler.py `GET /scheduler/status` | APScheduler 잡 상태 조회 |
| | | PY | app/utils | scheduler_utils.py `get_scheduler_status` | 잡 등록/다음 실행시각 |

### 3.8 관리자 백오피스 (`/admin`)

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 26 | admin_dashboard | PY | app/routers | admin.py `GET /admin/dashboard` | 운영 콘솔 렌더(지표·스케줄러·버스캐시·사용자·이벤트) |
| | | HTML | app/templates | admin_dashboard.html | 단일 대시보드 화면(자동 새로고침·패널·액션버튼) |
| 27 | admin_triggers | PY | app/routers | admin.py `POST /admin/trigger-{crawling,bus-notice,route-check,zone-check,test-alarm-for-user}` | 수집/버스공지/경로체크/구역체크/테스트알림 수동 실행(Basic+CSRF 또는 x-api-key) |

### 3.9 백그라운드 수집·발송 (스케줄러 구동, 비-HTTP)

> `main.py` lifespan → `setup_scheduler(...)`가 등록. 발송 시각은 `settings`의 `*_HOUR/_MINUTE`(기본 07:50 수집 / 08:00 경로·구역).

| 순번 | 프로그램ID | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|---|
| 28 | smpa_crawl_pipeline | PY | app/services/crawling | smpa_pipeline.py `crawl_and_sync_smpa_events` | SMPA 집회 수집→파싱→지오코딩→해시 upsert(신규 파이프라인) |
| | | PY | app/services/crawling | smpa_source / smpa_parser / smpa_coordinates / smpa_geocode_rules / smpa_event_sync | HTTP·파싱·좌표선택·약어규칙·DB upsert 단계 |
| | | PY | app/services | crawling_service.py `crawl_and_sync_events` | 레거시 v4.2 : SPATIC(Playwright)+SMPA(PDF) → Works AI 융합 → `INSERT OR IGNORE`(스케줄러 실제 호출부) |
| 29 | topis_bus_crawl | PY | app/services | bus_notice_service.py `refresh` | TOPIS 버스통제 공지 재크롤링 |
| | | PY | app/services/bus_logic | restricted_bus / hwpx2pdf / extract_image | 공지 파이프라인·HWP/PDF/이미지 변환 |
| 30 | scheduled_route_check | PY | app/services | event_service.py `scheduled_route_check` | 사용자 경로별 근접 집회 검사 후 그룹 대량 발송 |
| 31 | scheduled_zone_check | PY | app/services | zone_alarm_service.py `scheduled_zone_check` | 관심구역별 집회 매칭 후 그룹 대량 발송 |
| 32 | image_cleanup | PY | app/utils | file_cleanup.py `cleanup_old_files` | 오래된 집회/버스 경로 이미지 정리(매일 03:00) |

---

## 4. 공통·기반 모듈 (전 프로그램 공유)

### 4.1 데이터 계층 (`app/database`) — 레퍼런스의 QUERY/DAO에 대응

| 순번 | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|
| C1 | PY(SQL) | app/database | models.py | 스키마 원본: `users`/`events`/`alarm_tasks` `CREATE TABLE`·마이그레이션 컬럼·인덱스 (인라인 SQL). 상세 → `docs/erd.md` |
| C2 | PY | app/database | bootstrap.py | 기동 시 스키마 계약 idempotent 적용(테이블/컬럼/인덱스) |
| C3 | PY | app/database | connection.py | `get_database_path`·`get_db`(의존성)·`get_db_connection`(컨텍스트)·`init_db` |
| C4 | PY | app/database | compatibility_probe.py | 읽기전용 스키마/방언 호환성 진단 리포트(CLI) |

### 4.2 모델 계층 (`app/models`)

| 순번 | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|
| C5 | PY | app/models | user.py | `User`/`UserRequest`/`UserPreferences`/`InitialSetupRequest` |
| C6 | PY | app/models | event.py | `EventCreate`/`EventResponse`/`RouteEventCheck` |
| C7 | PY | app/models | alarm.py | `AlarmRequest`/`FilteredAlarmRequest` |
| C8 | PY | app/models | kakao.py | 카카오 Event API v2 페이로드(`KakaoRequest`/`Event`/`EventUser`/`EventAPIRequest`) |
| C9 | PY | app/models | responses.py | 알림 상태/발송/정리/오류 응답 모델, `HealthCheckResponse` |

### 4.3 유틸/설정 계층 (`app/utils`, `app/config`)

| 순번 | 구분 | 디렉토리 | 파일명 | 기능 |
|:---:|---|---|---|---|
| C10 | PY | app/utils | time_utils.py | DB 타임스탬프 정책(UTC/KST) 단일 소스 |
| C11 | PY | app/utils | geo_utils.py | 거리/경로근접 연산 + 카카오/TMAP 지오코딩·라우팅, `FAVORITE_ZONES` |
| C12 | PY | app/utils | scheduler_utils.py | 전역 `AsyncIOScheduler` · 잡 등록/상태 |
| C13 | PY | app/utils | file_cleanup.py | 이미지 파일 정리 |
| C14 | PY | app/config | settings.py | 환경변수 기반 `Settings` 싱글턴 + 로깅 설정 |
| C15 | PY | app/services | auth_service.py | `verify_api_key`(X-API-Key 검증) |

---

## 5. 환경설정파일

프로그램을 유지보수·배포하기 위해 필요한 환경설정파일을 주요 디렉토리별로 기재한다.

### 5.1 `/` (리포지토리 루트) — 의존성·런타임

| 파일명 | 설명 |
|--------|------|
| `pyproject.toml` | 프로젝트/의존성 매니페스트. 핵심 런타임 의존성: `fastapi[all]`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `httpx`, `aiohttp`, `apscheduler`, `beautifulsoup4`, `pdfminer.six`, `pymupdf`, `pandas`, `matplotlib`, `pillow`, `playwright`, `google-generativeai`, `pytz`, `defusedxml`, `python-dotenv`. dev: `pytest`, `pytest-asyncio`. pytest 설정(`testpaths`, `asyncio_mode=auto`) 포함 |
| `uv.lock` | 재현 가능한 의존성 잠금 파일 (`uv sync --frozen`) |
| `.python-version` | 고정 파이썬 버전(3.12+) |
| `.env.example` | 환경변수 예시. 실제 `.env`는 커밋하지 않으며 운영 서버가 소유 |

### 5.2 `app/config` — 애플리케이션 설정 (`.env` → `settings.py`)

`.env`(또는 환경변수)로 주입되어 `Settings`가 읽는 값. 비밀값은 기본 공란이며 환경에서 주입.

| 환경변수(파일) | 설명 |
|--------|------|
| `KAKAO_EVENT_API_KEY`, `KAKAO_LOCATION_API_KEY`, `BOT_ID` | 카카오 Event API 발송 · Local 지오코딩 · 봇 ID |
| `ALARM_SAVE_BLOCK_ID`, `FAVORITE_ZONE_SAVE_BLOCK_ID`, `ROUTE_SETUP_BLOCK_ID`, `ROUTE_DELETE_BLOCK_ID` | 카카오 스킬 블록 연결 ID(미설정 시 message 폴백) |
| `TMAP_APP_KEY` | TMAP 대중교통 경로 API |
| `WORKS_AI_API_KEY` (+ `WORKS_AI_BASE_URL`, `WORKS_AI_MODEL`) | Works AI(BizRouter) — 집회/버스공지 멀티모달 추출·데이터 융합 |
| `SEOUL_BUS_API_KEY` | 서울 버스 공개 API(정류장 조회) |
| `API_KEY` | REST 변경 엔드포인트용 `X-API-Key` |
| `ADMIN_USER`, `ADMIN_PASS` | 관리자 대시보드 Basic Auth |
| `DATABASE_PATH` | SQLite 파일 경로(기본 `kt_demo_alarm.db`) |
| `CACHE_FILE`, `ATTACHMENT_FOLDER` | TOPIS 캐시 · 첨부(이미지) 폴더 |
| `CRAWLING_HOUR/MINUTE`, `ROUTE_CHECK_HOUR/MINUTE`, `ZONE_CHECK_HOUR/MINUTE` | 일일 스케줄(기본 07:50 / 08:00 / 08:00) |
| `SMPA_*` | SMPA 크롤러 URL·타임아웃·재시도·User-Agent |
| `BATCH_SIZE`, `NOTIFICATION_TIMEOUT`, `KAKAO_TASK_RESULT_POLL_*` | 알림 배치 크기·타임아웃·결과 폴링 |
| `ROUTE_THRESHOLD_METERS` | 경로-집회 근접 임계값(기본 500m) |
| `DEBUG`, `LOG_LEVEL`, `PORT`, `ENABLE_MOCK_CALLBACK` | 서버 동작/로깅/목 콜백 |

> `model_config`: `env_file=".env"`, `extra="ignore"` — 정의되지 않은 환경변수는 무시. 앱 어디서도 `os.environ`을 직접 읽지 않고 `settings`만 사용.

### 5.3 `deploy/native` — 배포 (Docker-free 네이티브)

| 파일명 | 설명 |
|--------|------|
| `kt-demo-alarm.service.template` | systemd 유닛 템플릿(`__PLACEHOLDER__`). `Type=exec` uvicorn 서비스, `NoNewPrivileges`/`ProtectSystem=strict` 등 하드닝, `ReadWritePaths=__SHARED_DIR__` |
| `deploy-release.sh` | 배포 오케스트레이터: 번들 검증→해제→`uv sync --frozen --no-dev`→유닛 설치→`current` 심링크 교체→재기동→헬스체크→롤백 |
| `healthcheck.sh` | `HEALTH_URL`(기본 `http://127.0.0.1:8000/`) 폴링 |
| `package-source-bundle.sh` / `verify-source-bundle.sh` | 허용목록 기반 소스 tarball 생성 / 무결성·경로계약 검증 |

### 5.4 `nginx` — 리버스 프록시

| 파일명 | 설명 |
|--------|------|
| `nginx.conf` | 80→443 리다이렉트 + TLS 종단. `location /` → `http://127.0.0.1:8000` 프록시, 보안 헤더(HSTS 등), 10M 바디 제한. `DOMAIN_PLACEHOLDER`는 배포 시 `scripts/setup-ec2.sh`가 치환 |

### 5.5 `scripts` — 호스트/런타임 셋업

| 파일명 | 설명 |
|--------|------|
| `setup-ec2.sh` | EC2 부트스트랩(nginx/certbot 템플릿 치환 포함) |
| `native/setup-runtime.sh`, `native/render-systemd-unit.sh`, `native/preflight.sh`, `native/native-defaults.sh` | 런타임 디렉토리 준비·systemd 유닛 렌더·사전점검·기본값 |

---

## 6. 지침 및 고려사항

- 향후 유지보수가 용이하도록 **계층 방향(라우터→서비스→DB/모델)**을 지키고, 신규 엔드포인트는 라우터에 두고 로직은 서비스로 위임한다.
- **스키마 변경은 `app/database/models.py`에서만** 수행하고, 기존 DB 수렴을 위해 `CREATE TABLE`과 `*_MIGRATION_COLUMNS`를 함께 갱신한다(마이그레이션은 추가 전용). ERD 상세는 `docs/erd.md` 참조.
- 집회 수집 경로가 **2개(신규 `crawling/` 패키지 · 레거시 `crawling_service.py`)** 공존하므로, 스케줄러 진입점이 실제 호출하는 쪽을 확인 후 수정한다(현재 `main.py`는 `CrawlingService.crawl_and_sync_events` 호출).
- 카카오 스킬 핸들러는 예외를 삼키고 **HTTP 200**을 반환해야 한다(3초 제약). REST/관리자 엔드포인트는 반대로 `HTTPException`을 발생시킨다.
- 검증: `uv run pytest` (계층별 타깃 테스트는 각 `AGENTS.md` 참조), 린트 `uv run ruff check app`.
