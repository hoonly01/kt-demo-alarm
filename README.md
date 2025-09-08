# KT Demo Alarm - 집회 알림 시스템

카카오톡을 통한 실시간 집회 알림 서비스입니다. 사용자의 출퇴근 경로에 집회가 있을 때 자동으로 알림을 전송합니다.

## 🎯 주요 기능

### 📱 카카오톡 통합
- **챗봇 폴백 블록**: 사용자 메시지 수신 및 자동 응답
- **스킬 블록**: 경로 등록, 초기 설정, 집회 정보 조회
- **Event API**: 실시간 푸시 알림 전송
- **웹훅**: 채널 추가/차단 상태 실시간 동기화

### 🗺️ 경로 기반 집회 감지
- **실제 보행 경로 계산**: 카카오 Mobility API 연동
- **정밀 거리 계산**: Haversine 알고리즘으로 500m 이내 집회 감지
- **자동 알림**: 경로상 집회 발견 시 즉시 알림 전송
- **일정 기반 체크**: 매일 오전 7시 자동 경로 확인

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

### Backend
- **FastAPI**: Python 웹 프레임워크
- **SQLite**: 경량 데이터베이스
- **APScheduler**: 작업 스케줄링
- **httpx**: 비동기 HTTP 클라이언트

### External APIs
- **카카오톡 Event API**: 실시간 알림 전송
- **카카오 지도 API**: 장소 검색 및 좌표 변환
- **카카오 Mobility API**: 보행 경로 계산
- **SMPA 크롤링**: 집회 데이터 자동 수집

### Development
- **Python 3.9+**: 기본 런타임
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
`.env` 파일 생성:
```env
# 카카오 API 설정
KAKAO_REST_API_KEY=your_kakao_rest_api_key
BOT_ID=your_bot_id

# 서버 설정
PORT=8000
DEBUG=true

# 데이터베이스 설정
DATABASE_PATH=users.db
```

### 3. 서버 실행
```bash
# 개발 서버 시작
uvicorn main:app --reload --port 8000

# ngrok 터널링 (선택사항)
ngrok http 8000
```

## 📋 API 엔드포인트

### 기본 엔드포인트
- `GET /` - 헬스체크
- `POST /kakao/chat` - 카카오톡 챗봇 콜백

### 사용자 관리
- `GET /users` - 등록된 사용자 목록 조회
- `POST /save_user_info` - 사용자 경로 등록
- `POST /initial-setup` - 사용자 초기 설정 (출발지/도착지/버스/언어)

### 집회 관리
- `GET /events` - 집회 목록 조회
- `POST /events` - 새 집회 등록
- `POST /crawl-and-sync-events` - 집회 데이터 크롤링 및 동기화
- `POST /today-protests` - 오늘의 집회 조회
- `POST /upcoming-protests` - 예정된 집회 조회

### 경로 기반 감지
- `GET /check-route-events/{user_id}` - 특정 사용자 경로 집회 확인
- `POST /auto-check-all-routes` - 모든 사용자 경로 일괄 확인
- `POST /manual-schedule-test` - 수동 스케줄 테스트

### 알림 전송
- `POST /send-alarm` - 개별 사용자 알림
- `POST /send-alarm-to-all` - 전체 사용자 알림
- `POST /send-filtered-alarm` - 필터링 알림 (지역별/카테고리별)
- `GET /alarm-status/{task_id}` - 알림 전송 상태 확인

### 웹훅 & 관리
- `POST /webhook/kakao-channel` - 카카오톡 채널 웹훅
- `GET /scheduler-status` - 스케줄러 상태 확인

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
- **알고리즘**: MinhaKim02 크롤링 시스템 기반

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

### 2. 집회 데이터 크롤링 테스트
```bash
# 수동 크롤링 실행
curl -X POST http://127.0.0.1:8000/crawl-and-sync-events
```

### 3. 경로 등록 테스트
```bash
curl -X POST http://127.0.0.1:8000/save_user_info \
  -H "Content-Type: application/json" \
  -d '{
    "userRequest": {
      "user": {"id": "test_user_123", "type": "botUserKey"},
      "utterance": "경로등록"
    },
    "departure": "강남역",
    "arrival": "광화문역"
  }'
```

### 4. 알림 전송 테스트
```bash
# 개별 알림
curl -X POST http://127.0.0.1:8000/send-alarm \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user_123",
    "message": "테스트 알림입니다!"
  }'

# 필터링 알림
curl -X POST http://127.0.0.1:8000/send-filtered-alarm \
  -H "Content-Type: application/json" \
  -d '{
    "message": "광화문 일대 집회 알림",
    "location_filter": "광화문",
    "category_filter": null
  }'
```

## 📁 프로젝트 구조

```
kt-demo-alarm/
├── main.py                    # FastAPI 메인 애플리케이션
├── requirements.txt           # Python 의존성
├── .env                      # 환경변수 (git ignored)
├── users.db                  # SQLite 데이터베이스
├── venv/                     # Python 가상환경
├── archive/                  # 아카이브 폴더
├── temp_pdfs/               # 크롤링된 PDF 임시 저장소
├── CLAUDE.md                # AI 개발 가이드라인
└── README.md                # 이 파일
```

## 🤝 기여 및 협업

### 코드 크레딧
- **메인 시스템**: hoonly01 (FastAPI, 카카오톡 통합, 경로 감지)
- **크롤링 알고리즘**: MinhaKim02 (SMPA PDF 크롤링 시스템)
- **개발 협력**: Claude AI (코드 리뷰 및 최적화)

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

## 📝 라이선스

이 프로젝트는 MIT 라이선스하에 배포됩니다.

## 🔧 문제 해결

### 자주 발생하는 문제들

**1. 서버 시작 오류**
```bash
# 가상환경 활성화 확인
source venv/bin/activate

# 의존성 재설치
pip install -r requirements.txt
```

**2. ngrok 인증 오류**
```bash
# ngrok 토큰 설정
ngrok config add-authtoken YOUR_AUTHTOKEN
```

**3. 데이터베이스 오류**
```bash
# 데이터베이스 재초기화 (주의: 데이터 삭제됨)
rm users.db
# 서버 재시작하면 자동으로 테이블 생성됨
```

## 📞 지원

문제가 발생하거나 개선 제안이 있다면:
- GitHub Issues: https://github.com/hoonly01/kt-demo-alarm/issues
- 이메일: [프로젝트 담당자 이메일]

---

⭐ **Star**를 눌러주시면 프로젝트 개발에 큰 힘이 됩니다!