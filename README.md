# KT Demo Alarm - 집회 알림 시스템

![Branch](https://img.shields.io/badge/branch-main-blue)
![Status](https://img.shields.io/badge/status-development-yellow)
![Python](https://img.shields.io/badge/python-3.13+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-teal)

카카오톡을 통한 실시간 집회 알림 서비스입니다. Router-Service-Repository 패턴을 적용한 모듈화된 아키텍처로 구축되었습니다.

## 📌 현재 상태

- ✅ **로컬 개발 환경 구축 완료**
- ✅ **Router-Service-Repository 패턴 적용**
- ✅ **SMPA 크롤링 시스템 구현** (MinhaKim02 알고리즘)
- ✅ **경로 기반 집회 감지 기능 완료**
- ⏳ **알림 상태 추적 시스템** (PR #22 대기 중)
- ⏳ **Docker 컨테이너화** (PR #22 대기 중)
- ⏳ **테스트 인프라** (PR #22 대기 중)
- ❌ **CI/CD 파이프라인** (Issue #23 계획)
- ❌ **프로덕션 배포** (Issue #23 계획)

**중요 링크:**
- 📝 [Issue #23: 통합 개선 과제](https://github.com/hoonly01/kt-demo-alarm/issues/23)
- 🔀 [PR #22: 현대화 및 성능 최적화](https://github.com/hoonly01/kt-demo-alarm/pull/22)
- 🤖 [CLAUDE.md: AI 개발 가이드](./CLAUDE.md)

## 🏗️ 아키텍처

### Router-Service-Repository 패턴
- **Router**: API 엔드포인트 및 요청/응답 처리
- **Service**: 비즈니스 로직 구현
- **Repository**: 데이터 접근 계층 (Database)
- **Model**: Pydantic 데이터 검증 모델
- **Utils**: 공통 유틸리티 함수

```
app/
├── routers/         # API 라우터들
├── services/        # 비즈니스 로직
├── models/          # Pydantic 모델들
├── utils/           # 유틸리티 함수들
├── database/        # DB 연결 및 초기화
└── config/          # 설정 파일들
```

## 🎯 주요 기능

### 📱 카카오톡 통합
- **챗봇 폴백 블록**: 사용자 메시지 수신 및 자동 응답
- **스킬 블록**: 경로 등록, 초기 설정, 집회 정보 조회
- **Event API**: 실시간 푸시 알림 전송 (병렬 처리 최적화)
- **웹훅**: 채널 추가/차단 상태 실시간 동기화

### 🗺️ 경로 기반 집회 감지
- **실제 보행 경로 계산**: 카카오 Mobility API 연동
- **정밀 거리 계산**: Haversine 알고리즘으로 500m 이내 집회 감지
- **자동 알림**: 경로상 집회 발견 시 즉시 알림 전송
- **병렬 처리**: `asyncio.gather()`로 성능 최적화

### 📊 집회 데이터 관리
- **자동 크롤링**: SMPA(서울경찰청) PDF 데이터 수집
- **실시간 동기화**: 매일 오전 8시 30분 자동 업데이트
- **중복 제거**: 스마트 데이터 중복 방지
- **완전한 CRUD**: 집회 정보 생성/조회/수정/삭제

### 🚌 버스 통제 알림 (New!)
- **실시간 데이터 수집**: TOPIS 버스 운행 변경 공지사항 자동 크롤링
- **AI 기반 분석**: Gemini API를 활용한 비정형 데이터(텍스트, 첨부파일) 구조화
- **시각화**: 우회 경로 및 통제 정보를 시각적인 이미지로 생성하여 제공
- **카카오톡 챗봇**: "100번 확인해줘", "100번 이미지" 등의 명령어로 즉시 조회 가능


### 👥 사용자 관리
- **자동 등록**: 카카오톡 메시지 시 자동 사용자 생성
- **경로 설정**: 카카오 지도 API로 출발지/도착지 좌표 변환
- **개인화 설정**: 관심 버스 노선, 선호 언어 설정
- **상태 동기화**: 웹훅을 통한 실시간 활성/비활성 관리

## 🛠️ 기술 스택

### Backend Architecture
- **FastAPI**: Python 웹 프레임워크
- **Router-Service-Repository**: 깔끔한 아키텍처 패턴
- **Pydantic**: 데이터 검증 및 직렬화
- **SQLite**: 경량 데이터베이스
- **APScheduler**: 작업 스케줄링
- **requests**: HTTP 클라이언트 (httpx 마이그레이션 예정 - PR #22)

### Performance Optimization
- **asyncio.gather()**: 병렬 비동기 처리
- **Connection Pooling**: 데이터베이스 연결 최적화
- **Batch Processing**: 대량 알림 전송 최적화
- **Background Tasks**: 사용자 응답 시간 단축

### External APIs
- **카카오톡 Event API**: 실시간 알림 전송
- **카카오 지도 API**: 장소 검색 및 좌표 변환
- **카카오 Mobility API**: 보행 경로 계산
- **카카오 Mobility API**: 보행 경로 계산
- **SMPA 크롤링**: 집회 데이터 자동 수집
- **TOPIS 크롤링**: 버스 통제 정보 수집
- **Google Gemini API**: 공지사항 문서 분석 및 정보 추출


### Development
- **Python 3.13+**: 최신 런타임
- **ngrok**: 로컬 개발 터널링
- **dotenv**: 환경변수 관리

## 🚀 빠른 시작

### 1. 환경 설정
```bash
# 저장소 클론
git clone https://github.com/hoonly01/kt-demo-alarm.git
cd kt-demo-alarm

# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. 환경변수 설정
`.env` 파일 생성 (git ignored):
```bash
# .env.example 파일을 복사하여 시작
cp .env.example .env

# 또는 직접 생성
cat > .env << EOF
# 카카오 API 설정
KAKAO_REST_API_KEY=your_kakao_rest_api_key
BOT_ID=your_bot_id

# 서버 설정
PORT=8000
DEBUG=true

# 데이터베이스 설정 (SQLite 파일은 자동 생성됨)
DATABASE_PATH=users.db

# Gemini API 설정 (버스 통제 알림용)
GOOGLE_API_KEY=your_gemini_api_key_here
EOF
```


### 3. 서버 실행
```bash
# 개발 서버 시작
uvicorn main:app --reload --port 8000

# ngrok 터널링 (선택사항)
ngrok http 8000
```

## 📋 API 엔드포인트 (Router-Service 구조)

### 기본 엔드포인트
- `GET /` - 헬스체크 및 서버 정보

### 🤖 카카오톡 라우터 (`/kakao`)
- `POST /kakao/chat` - 카카오톡 챗봇 폴백 블록
- `POST /kakao/webhook/channel` - 카카오톡 채널 웹훅

### 👥 사용자 라우터 (`/users`)
- `GET /users` - 등록된 사용자 목록 조회 (경로 정보 포함)
- `POST /users/save_user_info` - 사용자 경로 등록 (스킬 블록)
- `POST /users/initial-setup` - 사용자 초기 설정 (테스트용)
- `POST /users/{user_id}/preferences` - 사용자 설정 업데이트

### 📊 집회 라우터 (`/events`)
- `GET /events` - 집회 목록 조회 (카테고리/상태 필터)
- `POST /events` - 새 집회 등록
- `GET /events/today` - 오늘 진행되는 집회 조회
- `GET /events/upcoming` - 다가오는 집회 조회 (기본 5개)
- `GET /events/{user_id}/check-route` - 사용자 경로 기반 집회 확인

### 🔔 알림 라우터 (`/alarms`)
- `POST /alarms/send` - 개별 사용자 알림 전송
- `POST /alarms/send-to-all` - 전체 활성 사용자 알림 전송
- `POST /alarms/send-filtered` - 필터링된 사용자 알림 전송
- `GET /alarms/status/{task_id}` - 알림 전송 상태 확인 (placeholder, 실제 추적 시스템은 PR #22에서 추가 예정)

### ⏰ 스케줄러 라우터 (`/scheduler`)
- `POST /scheduler/crawl-events` - 집회 데이터 크롤링 및 동기화
- `POST /scheduler/check-routes` - 모든 사용자 경로 일괄 확인
- `POST /scheduler/manual-test` - 수동 스케줄 테스트
- `POST /scheduler/manual-test` - 수동 스케줄 테스트
- `GET /scheduler/status` - 스케줄러 상태 확인

### 🚌 버스 라우터 (`/bus`)
- `POST /bus/webhook/bus_info` - 버스 정보 조회 (카카오 챗봇)
- `POST /bus/webhook/route_check` - 노선 통제 확인 (콜백 지원)
- `GET /bus/notices` - 공지사항 목록 조회
- `GET /bus/routes/{route}/controls` - 노선별 통제 정보 상세 조회


## 💾 데이터베이스 스키마

### users 테이블
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_user_key TEXT UNIQUE NOT NULL,
    first_message_at DATETIME,
    last_message_at DATETIME,
    message_count INTEGER DEFAULT 1,
    location TEXT,
    active BOOLEAN DEFAULT TRUE,
    -- 경로 정보
    departure_name TEXT, 
    departure_address TEXT, 
    departure_x REAL, 
    departure_y REAL, 
    arrival_name TEXT, 
    arrival_address TEXT, 
    arrival_x REAL, 
    arrival_y REAL, 
    route_updated_at DATETIME,
    -- 개인화 설정
    marked_bus TEXT,  -- 관심 버스 노선
    language TEXT     -- 선호 언어
);
```

### events 테이블
```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    location_name TEXT NOT NULL,
    location_address TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    start_date DATETIME NOT NULL,
    end_date DATETIME,
    category TEXT,
    severity_level INTEGER DEFAULT 1,  -- 1: 낮음, 2: 보통, 3: 높음
    status TEXT DEFAULT 'active',     -- active, ended, cancelled
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### alarm_tasks 테이블 (PR #22에서 추가 예정)
```sql
CREATE TABLE alarm_tasks (
    task_id TEXT PRIMARY KEY,
    alarm_type TEXT NOT NULL,  -- individual, bulk, filtered
    status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed, partial
    total_recipients INTEGER DEFAULT 0,
    successful_sends INTEGER DEFAULT 0,
    failed_sends INTEGER DEFAULT 0,
    event_id INTEGER,  -- FK to events table
    request_data TEXT,  -- JSON string
    error_messages TEXT,  -- JSON array
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    FOREIGN KEY (event_id) REFERENCES events (id)
);
```
> ⚠️ **알림 상태 추적 시스템**은 PR #22 머지 후 사용 가능합니다.

## 🔄 자동화 스케줄

### 집회 데이터 크롤링
- **시간**: 매일 오전 8시 30분
- **작업**: SMPA PDF 다운로드 → 파싱 → DB 동기화

### 경로 기반 집회 감지
- **시간**: 매일 오전 7시
- **작업**: 전체 사용자 경로 확인 → 집회 감지 → 자동 알림

## 🧪 테스트 방법

### 1. 기본 API 테스트
```bash
# 서버 상태 확인
curl http://127.0.0.1:8000/

# 사용자 목록 조회
curl http://127.0.0.1:8000/users

# 집회 데이터 확인
curl http://127.0.0.1:8000/events
```

### 2. 집회 데이터 크롤링 테스트 (스케줄러 라우터)
```bash
# 수동 크롤링 실행
curl -X POST http://127.0.0.1:8000/scheduler/crawl-events

# 모든 사용자 경로 확인
curl -X POST http://127.0.0.1:8000/scheduler/check-routes

# 스케줄러 상태 확인
curl http://127.0.0.1:8000/scheduler/status
```

### 3. 경로 등록 테스트 (사용자 라우터)
```bash
# 카카오톡 스킬 블록 시뮬레이션
curl -X POST http://127.0.0.1:8000/users/save_user_info \
  -H "Content-Type: application/json" \
  -d '{
    "userRequest": {
      "user": {"id": "test_user_123", "type": "botUserKey"},
      "utterance": "경로등록"
    },
    "action": {
      "params": {
        "departure": "강남역",
        "arrival": "광화문역"
      }
    }
  }'

# 직접 초기 설정 (테스트용)
curl -X POST http://127.0.0.1:8000/users/initial-setup \
  -H "Content-Type: application/json" \
  -d '{
    "bot_user_key": "test_user_456",
    "departure": "수원역",
    "arrival": "광화문역"
  }'
```

### 4. 알림 전송 테스트 (알림 라우터)
```bash
# 개별 알림
curl -X POST http://127.0.0.1:8000/alarms/send \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user_123",
    "event_name": "route_rally_alert",
    "data": {
      "message": "테스트 알림입니다!",
      "events_count": 1
    }
  }'

# 전체 사용자 알림
curl -X POST http://127.0.0.1:8000/alarms/send-to-all \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "general_alert",
    "data": {
      "message": "전체 사용자 테스트 알림"
    }
  }'

# 필터링된 알림
curl -X POST http://127.0.0.1:8000/alarms/send-filtered \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "filtered_alert",
    "data": {
      "message": "필터링된 테스트 알림"
    },
    "filter_location": "광화문",
    "filter_has_route": true
  }'
```

### 5. 집회 관리 테스트 (집회 라우터)
```bash
# 오늘 집회 조회
curl http://127.0.0.1:8000/events/today

# 다가오는 집회 조회
curl http://127.0.0.1:8000/events/upcoming

# 특정 사용자 경로 기반 집회 확인
curl http://127.0.0.1:8000/events/test_user_123/check-route
```

## 📁 프로젝트 구조

```
kt-demo-alarm/
├── main.py                      # FastAPI 메인 진입점
├── requirements.txt             # Python 의존성
├── .gitignore                   # Git 무시 파일 설정
├── README.md                    # 프로젝트 문서
├── CLAUDE.md                    # Claude Code용 가이드
├── .env.example                 # 환경변수 템플릿
│
├── app/                         # 모듈화된 애플리케이션
│   ├── config/                  # 애플리케이션 설정
│   │   ├── __init__.py
│   │   └── settings.py          # 환경변수 및 설정 관리
│   ├── database/                # 데이터베이스 관련
│   │   ├── __init__.py
│   │   ├── connection.py        # DB 연결 및 초기화
│   │   └── models.py            # DB 스키마 정의
│   ├── models/                  # Pydantic 모델들
│   │   ├── __init__.py
│   │   ├── alarm.py             # 알림 모델
│   │   ├── event.py             # 집회 모델
│   │   ├── kakao.py             # 카카오 API 모델
│   │   ├── user.py              # 사용자 모델
│   │   └── responses.py         # API 응답 모델 (PR #22)
│   ├── routers/                 # API 라우터들
│   │   ├── __init__.py
│   │   ├── alarms.py            # 알림 전송 라우터
│   │   ├── events.py            # 집회 관리 라우터
│   │   ├── kakao.py             # 카카오톡 라우터
│   │   ├── scheduler.py         # 스케줄러 라우터
│   │   ├── users.py             # 사용자 관리 라우터
│   │   └── bus_notice.py        # [NEW] 버스 통제 알림 라우터
│   ├── services/                # 비즈니스 로직
│   │   ├── __init__.py
│   │   ├── crawling_service.py  # 집회 데이터 크롤링 서비스
│   │   ├── event_service.py     # 집회 관리 서비스
│   │   ├── notification_service.py  # 알림 전송 서비스
│   │   ├── user_service.py      # 사용자 관리 서비스
│   │   ├── alarm_status_service.py  # 알림 상태 추적 (PR #22)
│   │   ├── bus_notice_service.py # [NEW] 버스 통제 알림 서비스
│   │   └── bus_logic/           # [NEW] 버스 통제 핵심 로직
│   │       ├── restricted_bus.py    # TOPIS 크롤러 및 Gemini 연동
│   │       ├── position_checker.py  # 위치 기반 조회 로직
│   │       ├── hwpx2pdf.py          # HWP 변환 유틸리티
│   │       └── extract_image.py     # 이미지 추출 유틸리티
│   └── utils/                   # 유틸리티 함수들
│       ├── __init__.py
│       ├── geo_utils.py         # 지리 계산 유틸리티
│       └── scheduler_utils.py   # 스케줄러 유틸리티
│
├── tests/                       # 테스트 (PR #22)
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_database.py
│   ├── test_api_basic.py
│   ├── test_alarm_status_service.py
│   └── test_bus_notice.py       # [NEW] 버스 통제 알림 테스트
│
├── Dockerfile                   # Docker 설정 (PR #22)

├── docker-compose.yml           # Docker Compose (PR #22)
└── pytest.ini                   # pytest 설정 (PR #22)
```

> 📝 **PR #22** 표시 항목은 현재 main 브랜치에는 없고, PR 머지 후 추가됩니다.

### 커밋 컨벤션
```
feat: 새로운 기능 추가
fix: 버그 수정
chore: 패키지 관리, 라이브러리 추가/제거
docs: 문서 추가/변경/삭제
style: 코드 스타일 변경 (포매팅, 세미콜론 등)
refactor: 코드 리팩토링
test: 테스트 추가 또는 업데이트
```

## 🏗️ 아키텍처 개선사항

### 이전 버전 (main_old.py)에서 새 구조로의 개선점

#### 🔄 **구조적 개선**
- **모듈화**: 단일 파일 (2000+ 라인) → Router-Service-Repository 패턴
- **관심사 분리**: API, 비즈니스 로직, 데이터 접근 완전 분리
- **의존성 주입**: 데이터베이스 연결 관리 개선
- **코드 재사용성**: 공통 유틸리티 함수 분리

#### ⚡ **성능 개선**
- **병렬 처리**: `asyncio.gather()`로 사용자 경로 확인 성능 향상
- **배치 처리**: 대량 알림 전송 최적화
- **백그라운드 작업**: 사용자 응답 시간 단축
- **연결 풀링**: 데이터베이스 연결 효율화

#### 🛡️ **안정성 향상**
- **에러 처리 강화**: 모든 서비스에 try-catch 블록 추가
- **데이터 검증**: Pydantic 모델 확장 및 개선
- **타입 힌팅**: 전체 코드베이스에 타입 안정성 확보
- **로깅 개선**: 구조화된 로깅 시스템

#### 📈 **확장성 개선**
- **서비스 레이어**: 새로운 기능 추가 용이
- **라우터 분리**: API 엔드포인트 관리 체계화  
- **설정 관리**: 환경변수 중앙화
- **테스트 용이성**: 각 레이어별 독립적 테스트 가능

### 마이그레이션 완료 현황
- ✅ **스케줄링 시스템**: 병렬 처리로 성능 향상
- ✅ **지리 계산**: 유틸리티 모듈로 분리
- ✅ **사용자 관리**: 서비스 레이어 추상화
- ✅ **알림 시스템**: 배치 처리 최적화
- ✅ **크롤링 시스템**: MinhaKim02 알고리즘 보존
- ✅ **API 엔드포인트**: 라우터별 체계적 구성

## 🚢 배포

### 현재 상태 (main 브랜치)
**로컬 개발 환경만 지원**
```bash
# 서버 수동 실행
uvicorn main:app --reload --port 8000

# ngrok 터널링 (테스트용)
ngrok http 8000
```

**현재 배포 프로세스 없음:**
- ❌ CI/CD 파이프라인 없음
- ❌ Docker 컨테이너화 없음
- ❌ 프로덕션 배포 가이드 없음

### 향후 개선 예정 (PR #22, Issue #23)

**PR #22에서 추가 예정:**
- ✅ Docker 컨테이너화 (Dockerfile, docker-compose.yml)
- ✅ 프로덕션 준비 설정
- ✅ 헬스체크 설정

**Issue #23에서 계획:**
- 🔄 CI/CD 파이프라인 (GitHub Actions)
- 🔄 자동 테스트 및 배포
- 🔄 환경별 배포 전략 (dev/staging/prod)

**배포 플랫폼 옵션:**
1. **클라우드**: AWS ECS/Fargate, GCP Cloud Run, Azure Container Instances
2. **PaaS**: Railway, Fly.io, Render
3. **서버리스**: AWS Lambda + API Gateway
4. **VPS**: DigitalOcean, Vultr 등에 Docker 배포

## 🔧 문제 해결

### 자주 발생하는 문제들

**1. 서버 시작 오류**
```bash
# 가상환경 활성화 확인
source venv/bin/activate

# 의존성 재설치
pip install -r requirements.txt

# .env 파일 확인 (git ignored이므로 직접 생성 필요)
cp .env.example .env  # 또는 수동으로 .env 파일 생성
```

**2. 환경변수 설정 오류**
```bash
# .env 파일이 없는 경우 (git ignored 파일)
# README의 환경변수 설정 섹션을 참고하여 .env 파일을 직접 생성
echo "KAKAO_REST_API_KEY=your_key_here" > .env
echo "BOT_ID=your_bot_id_here" >> .env
```

**3. ngrok 인증 오류**
```bash
# ngrok 토큰 설정
ngrok config add-authtoken YOUR_AUTHTOKEN
```

**4. 모듈 import 오류**
```bash
# Python 경로 확인
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 또는 개발 모드로 설치
pip install -e .
```

## 📞 지원

문제가 발생하거나 개선 제안이 있다면:
- GitHub Issues: https://github.com/hoonly01/kt-demo-alarm/issues
- 이메일: [프로젝트 담당자 이메일]

---

⭐ **Star**를 눌러주시면 프로젝트 개발에 큰 힘이 됩니다!