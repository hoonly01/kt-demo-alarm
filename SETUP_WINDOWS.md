# KT Demo Alarm - Windows 빠른 시작 가이드

Windows 환경에서 15분 안에 서버를 실행하는 간단한 가이드입니다.

## 📋 필요한 것

- Windows 10/11 (64-bit)
- 관리자 권한
- 인터넷 연결

---

## 🚀 빠른 시작 (3단계)

### 1단계: Docker Desktop 설치 (5분)

1. Docker Desktop 다운로드: https://www.docker.com/products/docker-desktop/
2. 다운로드한 파일 실행 → 설치 완료
3. **컴퓨터 재부팅** (WSL2 활성화를 위해 필요)
4. Docker Desktop 실행 확인

**설치 확인**:
```powershell
# PowerShell 열고 실행
docker --version
```

---

### 2단계: 프로젝트 설정 (5분)

#### A. Git이 없는 경우

1. 프로젝트 ZIP 파일 다운로드 및 압축 해제
2. 압축 해제한 폴더를 `C:\kt-demo-alarm`으로 이동

#### B. Git이 있는 경우

```powershell
# PowerShell 열고 실행
cd C:\
git clone https://github.com/hoonly01/kt-demo-alarm.git
cd kt-demo-alarm
```

---

### 3단계: 서버 실행 (5분)

```powershell
# PowerShell에서 프로젝트 폴더로 이동
cd C:\kt-demo-alarm

# 환경 설정 파일 복사
Copy-Item .env.production.example .env

# 환경 설정 파일 편집 (메모장으로 열림)
notepad .env
```

**`.env` 파일에서 수정할 부분**:
```env
KAKAO_REST_API_KEY=여기에_실제_카카오_API_키_입력
BOT_ID=여기에_실제_봇_ID_입력
```

저장 후 닫기 (Ctrl+S, Alt+F4)

**서버 시작**:
```powershell
# Docker로 서버 시작
docker compose up -d

# 로그 확인 (Ctrl+C로 종료)
docker compose logs -f
```

---

## ✅ 작동 확인

브라우저에서 http://localhost:8000/ 접속

정상 응답:
```json
{
  "message": "KT Demo Alarm API is running",
  "status": "healthy"
}
```

---

## 🔧 주요 명령어

```powershell
# 서버 시작
docker compose up -d

# 서버 중지
docker compose down

# 로그 보기
docker compose logs -f

# 서버 재시작
docker compose restart

# 서버 상태 확인
docker compose ps
```

---

## 🌐 외부 접속 (ngrok)

다른 컴퓨터나 카카오 웹훅에서 접속하려면:

### 1. ngrok 설치

1. ngrok 다운로드: https://ngrok.com/download
2. 압축 해제 후 `ngrok.exe`를 `C:\Windows\System32`로 복사

### 2. 터널 시작

```powershell
# 새 PowerShell 창에서 실행
ngrok http 8000
```

ngrok이 제공하는 URL (예: `https://abc123.ngrok-free.app`)을 카카오 웹훅 URL로 설정

---

## 🆘 문제 해결

### Docker Desktop이 시작 안 됨

```powershell
# PowerShell 관리자 권한으로 실행 후
wsl --install
# 재부팅
Restart-Computer
```

### 포트 8000이 이미 사용중

```powershell
# 사용 중인 프로그램 확인
Get-NetTCPConnection -LocalPort 8000

# 해당 프로그램 종료 후 다시 시도
docker compose up -d
```

### Docker 이미지 다운로드 실패

- 인터넷 연결 확인
- 방화벽/프록시 확인
- 잠시 후 다시 시도

```powershell
# 재시도
docker compose build
docker compose up -d
```

---

## 📞 도움이 필요하면

1. GitHub Issues: https://github.com/hoonly01/kt-demo-alarm/issues
2. 에러 메시지 전체 복사해서 공유
3. `docker compose logs` 출력 공유

---

## 🎉 완료!

이제 Windows 환경에서 KT Demo Alarm 서버가 실행 중입니다!

**다음 단계**:
- 카카오 웹훅 URL 설정
- 사용자 등록 테스트
- 알림 기능 테스트

**Last Updated**: 2025-01-07
