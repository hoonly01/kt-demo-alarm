# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a KT (Korean Telecom) demo alarm application project using Python/FastAPI for backend development with KakaoTalk chatbot integration.

## Project Progress Status

### Phase 1: KakaoTalk Channel Setup ✅ COMPLETED
- 카카오톡 채널 생성 및 설정 완료
- 챗봇 기능 활성화
- 검색 허용 설정

### Phase 2: 사전 설정 작업 ✅ COMPLETED  
- 카카오 비즈니스 계정 등록
- 카카오 개발자 계정 연동
- 기본 챗봇 설정

### Phase 3: Backend API 개발 ✅ COMPLETED
- **FastAPI 서버 구축**: `main.py` 구현 완료
- **Pydantic 모델 정의**: 카카오톡 데이터 구조 검증
- **콜백 엔드포인트**: `/kakao/chat` 구현 완료
- **사용자 식별**: botUserKey 추출 및 로깅

## Repository Structure

- **Language**: Python (FastAPI framework)
- **Main Files**:
  - `main.py`: FastAPI 서버 메인 파일
  - `requirements.txt`: Python 의존성 패키지
  - `venv/`: Python 가상환경
- **IDE Support**: Configured for IntelliJ IDEA, Visual Studio Code

## Development Setup

### Environment
- Python 3.13+ with virtual environment
- FastAPI with uvicorn server
- Dependencies: `fastapi[all]`, `uvicorn[standard]`, `pydantic`

### Run Commands
```bash
# 가상환경 활성화
source venv/bin/activate

# 서버 실행
uvicorn main:app --reload --port 8000
```

### API Endpoints
- `GET /`: Health check endpoint
- `POST /kakao/chat`: KakaoTalk chatbot callback endpoint (폴백 블록)
- `POST /save_user_info`: 사용자 경로 등록 (스킬 블록)
- `POST /send-alarm`: 개별 사용자 알림 전송
- `POST /send-alarm-to-all`: 전체 사용자 알림 전송
- `POST /send-filtered-alarm`: 필터링된 사용자 알림 전송
- `GET /users`: 등록된 사용자 목록 조회 (경로 정보 포함)
- `GET /alarm-status/{task_id}`: 알림 전송 상태 확인
- `POST /users/{user_id}/preferences`: 사용자 설정 업데이트
- `POST /webhook/kakao-channel`: 카카오톡 채널 웹훅

## Current Implementation Details

### Pydantic Models
- `User`: 카카오톡 사용자 정보 (id, type, properties)
- `UserRequest`: 사용자 요청 (user, utterance)
- `KakaoRequest`: 카카오 전체 요청 구조

### Features Implemented
- 사용자 메시지 수신 및 응답
- botUserKey 추출 및 로깅
- 카카오톡 응답 형식 구현

### Phase 4: External Integration ✅ COMPLETED
- **ngrok 설정**: 로컬 서버 외부 접근 가능하도록 설정 완료
- **카카오 관리자센터**: 스킬 등록 및 폴백 블록 연결 완료
- **실제 테스트**: 카카오톡 채널을 통한 실제 메시지 테스트 완료

### Phase 5: Database & Event API Integration ✅ COMPLETED
- **SQLite 데이터베이스**: 사용자 정보 저장 로직 완전 구현
- **사용자 관리 시스템**: botUserKey/appUserId 기반 사용자 관리
- **Event API 알림 전송**: 개별/전체/필터링 알림 시스템 구현
- **웹훅 시스템**: 채널 추가/차단 상태 실시간 동기화
- **실환경 검증**: 실제 카카오톡 알림 전송 성공

### Phase 6: Advanced Features ✅ COMPLETED
- **필터링 알림 시스템**: 지역별/카테고리별/사용자별 필터링
- **알림 상태 추적**: taskId 기반 전송 상태 확인
- **환경변수 관리**: 카카오 API 키, BOT_ID 등 설정 관리
- **배치 처리**: 최대 100명씩 배치로 알림 전송

### Phase 7: 동료 코드 통합 ✅ COMPLETED (Issue #2)
- **SQLite 테이블 확장**: 경로 정보 컬럼 9개 추가 (departure/arrival 각각 name, address, x, y)
- **카카오 지도 API 통합**: 검색어를 좌표로 변환하는 get_location_info() 함수
- **경로 등록 API**: /save_user_info 엔드포인트 (BackgroundTasks 비동기 처리)
- **시스템 연동**: /users API에 구조화된 route_info 객체 포함
- **실환경 검증**: 로컬 테스트 및 API 호출 성공 확인

## Compressed Work History (Memory)

### Completed Tasks Summary
- **Phase 1-3**: 기본 FastAPI 서버, 카카오톡 콜백, SQLite 사용자 관리 시스템
- **Phase 4-6**: ngrok 연동, Event API 알림 시스템, 필터링/배치 처리, 실환경 검증 
- **Phase 7 (Issue #2)**: 동료 Firebase 코드를 SQLite로 통합, 카카오 지도 API 경로 등록 구현
  - 9개 경로 컬럼 추가, /save_user_info API, BackgroundTasks 비동기 처리
  - 전체 시스템 테스트 완료, feature/route-integration 브랜치 작업

### Architecture Decisions Made
- **Database**: SQLite 선택 (PostgreSQL/Firebase 대신) - 현재 요구사항에 충분
- **Pattern**: 현재 monolithic FastAPI, 향후 Router-Service-Repository 리팩토링 예정
- **Async**: BackgroundTasks로 사용자 응답 최적화, httpx로 외부 API 호출

### Key APIs Implemented
- `/kakao/chat` (폴백), `/save_user_info` (스킬), `/send-alarm*` (알림), `/users` (조회)
- 카카오 지도 API 통합, Event API 알림 시스템, 웹훅 처리

### Current Status
- 코드 측면: 모든 기능 완성, 로컬 테스트 검증 완료
- 배포 상태: feature/route-integration 브랜치, main 머지 대기
- 남은 작업: 카카오톡 관리자센터 스킬 블록 설정만 남음

## Phase 8: Next Development (TODO)
- **카카오톡 스킬 블록 설정**: 실제 카카오톡에서 경로 등록 기능 활성화 (URGENT)
- **사용자 메시지 처리 로직**: 명령어 파싱, 자동 응답, 데이터 수집, 개인화 설정
- **MVC 구조 리팩토링**: Router-Service-Repository 패턴으로 코드 분리

## Technical Notes

### Database Schema
- **users 테이블 확장**: 기존 컬럼 + 경로 정보 9개 컬럼 추가
- **안전한 마이그레이션**: ALTER TABLE with exception handling
- **좌표 데이터**: 카카오 지도 API에서 받은 위경도 저장

### External API Integration  
- **카카오 지도 API**: 장소 검색 및 좌표 변환
- **카카오 Event API**: 알림 전송 (기존)
- **httpx 기반**: 비동기 HTTP 클라이언트 사용

### Performance Optimization
- **BackgroundTasks**: 경로 저장을 비동기로 처리
- **사용자 응답 최적화**: 즉시 응답 후 백그라운드 작업
- **배치 처리**: 최대 100명씩 알림 전송

### Testing Status
- ✅ 서버 테스트 완료: 로컬 8000번 포트에서 정상 동작
- ✅ 카카오 지도 API: 실제 좌표 변환 성공 확인  
- ✅ 경로 저장: 데이터베이스 저장 및 조회 검증
- ✅ API 엔드포인트: 모든 기능 로컬 테스트 완료
- 🔄 카카오톡 통합 테스트: 스킬 블록 설정 후 진행 예정

## Commit Message Convention
Put #<issue-number> at the start of the commit message.
feat: add, change, or remove a feature
fix: bug fix
chore: package manager updates; add/remove libraries
docs: add, change, or delete documentation
style: code style changes (formatting, missing semicolons, etc.)
design: UI design changes (e.g., CSS)
refactor: code refactoring (rename variables, move folders, etc.)
test: add or update tests
release: version release