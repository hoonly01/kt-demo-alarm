# KT Demo Alarm - 집회 알림 시스템

카카오톡을 통한 실시간 집회 알림 서비스입니다. Router-Service-Repository 패턴을 적용한 모듈화된 아키텍처로 구축되었습니다.

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
- **httpx**: 비동기 HTTP 클라이언트

### Performance Optimization
- **asyncio.gather()**: 병렬 비동기 처리
- **Connection Pooling**: 데이터베이스 연결 최적화
- **Batch Processing**: 대량 알림 전송 최적화
- **Background Tasks**: 사용자 응답 시간 단축

### External APIs
- **카카오톡 Event API**: 실시간 알림 전송
- **카카오 지도 API**: 장소 검색 및 좌표 변환
- **카카오 Mobility API**: 보행 경로 계산
- **SMPA 크롤링**: 집회 데이터 자동 수집

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
- `GET /alarms/status/{task_id}` - 알림 전송 상태 확인

### ⏰ 스케줄러 라우터 (`/scheduler`)
- `POST /scheduler/crawl-events` - 집회 데이터 크롤링 및 동기화
- `POST /scheduler/check-routes` - 모든 사용자 경로 일괄 확인
- `POST /scheduler/manual-test` - 수동 스케줄 테스트
- `GET /scheduler/status` - 스케줄러 상태 확인

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
├── app/                         # 모듈화된 애플리케이션
│   ├── config/                  # 애플리케이션 설정
│   │   ├── __init__.py
│   │   └── settings.py          # 환경변수 및 설정 관리
│   ├── database/                # 데이터베이스 관련
│   │   ├── __init__.py
│   │   ├── connection.py        # DB 연결 및 초기화
│   │   └── models.py            # SQLAlchemy 모델 정의
│   ├── models/                  # Pydantic 모델들
│   │   ├── __init__.py
│   │   ├── alarm.py             # 알림 모델
│   │   ├── event.py             # 집회 모델
│   │   ├── kakao.py             # 카카오 API 모델
│   │   └── user.py              # 사용자 모델
│   ├── routers/                 # API 라우터들
│   │   ├── __init__.py
│   │   ├── alarms.py            # 알림 전송 라우터
│   │   ├── events.py            # 집회 관리 라우터
│   │   ├── kakao.py             # 카카오톡 라우터
│   │   ├── scheduler.py         # 스케줄러 라우터
│   │   └── users.py             # 사용자 관리 라우터
│   ├── services/                # 비즈니스 로직
│   │   ├── __init__.py
│   │   ├── crawling_service.py  # 집회 데이터 크롤링 서비스
│   │   ├── event_service.py     # 집회 관리 서비스
│   │   ├── notification_service.py  # 알림 전송 서비스
│   │   └── user_service.py      # 사용자 관리 서비스
│   └── utils/                   # 유틸리티 함수들
│       ├── __init__.py
│       ├── geo_utils.py         # 지리 계산 유틸리티
│       └── scheduler_utils.py   # 스케줄러 유틸리티
```

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