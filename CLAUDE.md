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
- `POST /kakao/chat`: KakaoTalk chatbot callback endpoint

## Current Implementation Details

### Pydantic Models
- `User`: 카카오톡 사용자 정보 (id, type, properties)
- `UserRequest`: 사용자 요청 (user, utterance)
- `KakaoRequest`: 카카오 전체 요청 구조

### Features Implemented
- 사용자 메시지 수신 및 응답
- botUserKey 추출 및 로깅
- 카카오톡 응답 형식 구현

## Next Steps (Pending)

### Phase 4: External Integration
- **ngrok 설정**: 로컬 서버 외부 접근 가능하도록 설정
- **카카오 관리자센터**: 스킬 등록 및 폴백 블록 연결
- **실제 테스트**: 카카오톡 채널을 통한 실제 메시지 테스트

### Phase 5: Database Integration
- 사용자 정보 저장 로직 구현
- botUserKey 기반 사용자 관리
- 알림 설정 저장 기능

### Phase 6: Core Features
- 지역별 알림 설정 (예: "광화문 알림 설정")
- 실시간 알림 발송 시스템
- 사용자 명령어 처리

## Technical Notes

- 서버 테스트 완료: 로컬 8000번 포트에서 정상 동작
- 콜백 엔드포인트 검증: curl 테스트로 정상 응답 확인
- 로깅 시스템: 사용자 메시지 수신 로그 정상 작동

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