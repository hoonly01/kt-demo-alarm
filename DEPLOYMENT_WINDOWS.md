# KT Demo Alarm - Windows Server 배포 가이드 (Docker)

Windows Server에 Docker 기반으로 FastAPI 애플리케이션을 배포하는 전체 가이드입니다.

## 📋 목차

- [사전 요구사항](#사전-요구사항)
- [Windows Server 초기 설정](#windows-server-초기-설정)
- [Docker Desktop 설치](#docker-desktop-설치)
- [애플리케이션 배포](#애플리케이션-배포)
- [GitHub Actions 설정](#github-actions-설정)
- [수동 배포](#수동-배포)
- [모니터링 및 로그](#모니터링-및-로그)
- [트러블슈팅](#트러블슈팅)
- [Linux와의 차이점](#linux와의-차이점)

---

## 🎯 사전 요구사항

### Windows Server 스펙
- **OS**: Windows Server 2019 또는 2022 (64-bit)
- **메모리**: 최소 4GB RAM (권장: 8GB 이상)
- **스토리지**: 최소 30GB 여유 공간
- **프로세서**: 64-bit 프로세서, SLAT 지원

### 필수 기능
- Hyper-V 활성화 가능
- 가상화 지원 (BIOS/UEFI에서 활성화)
- PowerShell 5.1 이상

### 방화벽 설정
```
인바운드 규칙:
- 3389 (RDP): 원격 데스크톱
- 80 (HTTP): 웹 서비스
- 443 (HTTPS): 웹 서비스 (SSL)
- 8000 (FastAPI): 내부 테스트용 (선택사항)
```

### 필수 정보
- 카카오 API 키: `KAKAO_REST_API_KEY`
- 카카오 봇 ID: `BOT_ID`

---

## 🚀 Windows Server 초기 설정

### 1. PowerShell 관리자 권한으로 실행

시작 메뉴에서 PowerShell을 우클릭 → "관리자 권한으로 실행"

### 2. 초기 설정 스크립트 실행

```powershell
# 프로젝트 디렉토리 생성
New-Item -ItemType Directory -Path "C:\kt-demo-alarm" -Force
cd C:\kt-demo-alarm

# Git 설치 (Chocolatey 사용)
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Git 설치 확인
choco install git -y

# PowerShell 재시작 후 프로젝트 클론
cd C:\
git clone https://github.com/hoonly01/kt-demo-alarm.git
cd kt-demo-alarm
```

또는 자동 설정 스크립트 사용:

```powershell
# setup-windows.ps1 실행
.\scripts\setup-windows.ps1
```

---

## 🐳 Docker Desktop 설치

### 1. Docker Desktop for Windows 다운로드

공식 사이트에서 다운로드: https://www.docker.com/products/docker-desktop/

또는 PowerShell로 설치:

```powershell
# Chocolatey로 Docker Desktop 설치
choco install docker-desktop -y
```

### 2. Docker Desktop 설정

1. Docker Desktop 실행
2. **Settings** → **General** 확인:
   - ✅ Use WSL 2 based engine (권장)
   - 또는 Hyper-V backend 사용
3. **Settings** → **Resources** → **Advanced**:
   - CPUs: 2 이상
   - Memory: 2GB 이상
4. **Apply & Restart**

### 3. Docker 설치 확인

```powershell
# Docker 버전 확인
docker --version
# 출력 예: Docker version 24.0.7, build afdd53b

# Docker Compose 버전 확인
docker compose version
# 출력 예: Docker Compose version v2.23.0

# Docker 실행 테스트
docker run hello-world
```

### 4. WSL2 설정 (Linux 컨테이너 사용 시)

```powershell
# WSL2 설치 (Windows 10 2004 이상 또는 Windows Server 2022)
wsl --install

# WSL2를 기본 버전으로 설정
wsl --set-default-version 2

# Ubuntu 배포판 설치 (선택사항)
wsl --install -d Ubuntu-22.04

# 재부팅
Restart-Computer
```

---

## 📦 애플리케이션 배포

### 1. 환경변수 설정

```powershell
# .env 파일 생성
cd C:\kt-demo-alarm
Copy-Item .env.production.example .env

# 메모장으로 편집
notepad .env
```

필수 환경변수 입력:
```env
KAKAO_REST_API_KEY=your_actual_kakao_api_key_here
BOT_ID=your_actual_bot_id_here
PORT=8000
DEBUG=false
LOG_LEVEL=INFO
DATABASE_PATH=/app/data/kt_demo_alarm.db
```

**중요**: Windows 경로가 아닌 **Linux 경로**를 사용합니다 (컨테이너 내부 경로).

### 2. 데이터 및 로그 디렉토리 생성

```powershell
# 로컬 디렉토리 생성 (볼륨 마운트용)
New-Item -ItemType Directory -Path ".\data" -Force
New-Item -ItemType Directory -Path ".\logs" -Force
```

### 3. Docker Compose로 애플리케이션 시작

```powershell
# 프로덕션 모드로 시작
docker compose -f docker-compose.prod.yml up -d

# 또는 기본 docker-compose.yml 사용
docker compose up -d
```

### 4. 배포 확인

```powershell
# 컨테이너 상태 확인
docker compose ps

# 로그 확인
docker compose logs -f

# 헬스체크
curl http://localhost:8000/
# 또는 브라우저에서 http://localhost:8000 접속
```

정상 응답 예시:
```json
{
  "message": "KT Demo Alarm API is running",
  "status": "healthy"
}
```

---

## 🤖 GitHub Actions 설정

### 1. GitHub Secrets 추가

GitHub 리포지토리 Settings → Secrets and variables → Actions에서 다음 Secrets를 추가:

```
WINDOWS_SERVER_HOST=your-windows-server-ip
WINDOWS_SERVER_USER=Administrator
WINDOWS_SERVER_PASSWORD=your-server-password
KAKAO_REST_API_KEY=your-kakao-api-key
BOT_ID=your-bot-id
```

**참고**: Windows Server는 주로 SSH 대신 **PowerShell Remoting** 또는 **WinRM**을 사용합니다.

### 2. SSH 설정 (선택사항)

Windows Server에서 OpenSSH 서버 활성화:

```powershell
# OpenSSH Server 설치
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# SSH 서비스 시작 및 자동 시작 설정
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'

# 방화벽 규칙 확인
Get-NetFirewallRule -Name *ssh*

# 방화벽 규칙 추가 (필요 시)
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

SSH 키 기반 인증 설정:

```powershell
# .ssh 디렉토리 생성
New-Item -ItemType Directory -Path "$env:USERPROFILE\.ssh" -Force

# authorized_keys 파일 생성
New-Item -ItemType File -Path "$env:USERPROFILE\.ssh\authorized_keys" -Force

# 공개 키 추가 (로컬에서 생성한 public key 내용 붙여넣기)
notepad "$env:USERPROFILE\.ssh\authorized_keys"

# 권한 설정
icacls "$env:USERPROFILE\.ssh\authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
```

### 3. 자동 배포 워크플로우

GitHub Actions는 기존 `.github/workflows/deploy.yml`을 그대로 사용 가능 (SSH 설정 시).

Windows 전용 워크플로우는 `.github/workflows/deploy-windows.yml` 참고.

---

## 🛠️ 수동 배포

### PowerShell 배포 스크립트 사용

```powershell
cd C:\kt-demo-alarm
.\scripts\deploy.ps1
```

이 스크립트는:
1. Git pull로 최신 코드 가져오기
2. 환경변수 확인
3. 데이터베이스 백업
4. Docker 이미지 빌드
5. 컨테이너 재시작
6. 헬스체크

### 수동 명령어

```powershell
# 1. 최신 코드 가져오기
git pull origin main

# 2. Docker 이미지 빌드
docker compose build

# 3. 기존 컨테이너 중지 및 제거
docker compose down

# 4. 새 컨테이너 시작
docker compose up -d

# 5. 헬스체크
Start-Sleep -Seconds 5
Invoke-WebRequest -Uri "http://localhost:8000/" -UseBasicParsing
```

---

## 📊 모니터링 및 로그

### Docker 컨테이너 상태 확인

```powershell
# 실행 중인 컨테이너 확인
docker compose ps

# 리소스 사용량
docker stats

# 컨테이너 재시작
docker compose restart
```

### 로그 확인

```powershell
# 실시간 로그 (전체)
docker compose logs -f

# 최근 100줄
docker compose logs --tail=100

# 특정 시간 이후 로그
docker compose logs --since 10m

# 컨테이너 내부 접속
docker compose exec kt-demo-alarm bash
# Windows 컨테이너인 경우:
docker compose exec kt-demo-alarm powershell
```

### Windows 이벤트 로그

```powershell
# Docker 관련 이벤트 로그 확인
Get-EventLog -LogName Application -Source Docker -Newest 50
```

### 디스크 사용량 확인

```powershell
# 전체 디스크 사용량
Get-PSDrive C

# Docker 디스크 사용량
docker system df

# 불필요한 이미지/컨테이너 정리
docker system prune -a
```

---

## 🔧 트러블슈팅

### Docker Desktop이 시작되지 않는 경우

```powershell
# Hyper-V 상태 확인
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V

# Hyper-V 활성화
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All

# 재부팅
Restart-Computer
```

### WSL2 오류

```powershell
# WSL 업데이트
wsl --update

# WSL 상태 확인
wsl --status

# WSL 재시작
wsl --shutdown
```

### 컨테이너가 시작되지 않는 경우

```powershell
# 로그 확인
docker compose logs

# 환경변수 확인
docker compose config

# 컨테이너 강제 재생성
docker compose down
docker compose up -d --force-recreate
```

### 데이터베이스 오류

```powershell
# SQLite 파일 권한 확인
Get-ChildItem .\data\kt_demo_alarm.db

# 백업에서 복구
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item .\data\kt_demo_alarm.db.backup.* .\data\kt_demo_alarm.db
docker compose restart
```

### 포트 충돌

```powershell
# 포트 8000 사용 중인 프로세스 확인
Get-NetTCPConnection -LocalPort 8000

# 프로세스 종료
Stop-Process -Id <PID> -Force

# 또는 docker-compose.yml에서 다른 포트 사용
# ports:
#   - "9000:8000"
```

### 방화벽 문제

```powershell
# 방화벽 규칙 추가 (HTTP)
New-NetFirewallRule -DisplayName "KT Demo Alarm HTTP" `
                    -Direction Inbound `
                    -LocalPort 80 `
                    -Protocol TCP `
                    -Action Allow

# 방화벽 규칙 추가 (HTTPS)
New-NetFirewallRule -DisplayName "KT Demo Alarm HTTPS" `
                    -Direction Inbound `
                    -LocalPort 443 `
                    -Protocol TCP `
                    -Action Allow

# 방화벽 규칙 추가 (FastAPI)
New-NetFirewallRule -DisplayName "KT Demo Alarm FastAPI" `
                    -Direction Inbound `
                    -LocalPort 8000 `
                    -Protocol TCP `
                    -Action Allow
```

### Docker 네트워크 재설정

```powershell
# 네트워크 목록 확인
docker network ls

# 사용하지 않는 네트워크 제거
docker network prune

# 컨테이너 재시작
docker compose down
docker compose up -d
```

---

## 🔄 Linux와의 차이점

### 명령어 차이

| 작업 | Linux | Windows |
|------|-------|---------|
| **디렉토리 이동** | `cd /home/ubuntu/kt-demo-alarm` | `cd C:\kt-demo-alarm` |
| **파일 복사** | `cp .env.example .env` | `Copy-Item .env.example .env` |
| **디렉토리 생성** | `mkdir data` | `New-Item -ItemType Directory -Path data` |
| **로그 확인** | `tail -f logs/app.log` | `Get-Content logs\app.log -Wait -Tail 10` |
| **프로세스 확인** | `ps aux \| grep python` | `Get-Process python` |
| **네트워크 확인** | `netstat -tlnp` | `Get-NetTCPConnection` |

### 경로 표기법

```powershell
# Windows 호스트 경로 (PowerShell)
C:\kt-demo-alarm\data

# Docker 컨테이너 내부 경로 (항상 Linux 스타일)
/app/data

# docker-compose.yml에서 볼륨 마운트
volumes:
  - ./data:/app/data  # 현재 디렉토리의 data → 컨테이너의 /app/data
```

### Docker 컨테이너 타입

Windows Server에서 Docker를 사용할 때 두 가지 옵션:

1. **Linux Containers (권장)**:
   - WSL2 사용
   - 기존 Dockerfile 그대로 사용 ✅
   - 성능 우수

2. **Windows Containers**:
   - Hyper-V 사용
   - Dockerfile 수정 필요 (FROM python:3.12-slim → FROM mcr.microsoft.com/windows/servercore:ltsc2022)
   - 권장하지 않음 ❌

**현재 프로젝트는 Linux Container 기반이므로 WSL2를 사용하세요!**

### 파일 권한

Linux와 달리 Windows는 파일 권한 개념이 다릅니다:

```powershell
# Linux (chmod)
chmod 600 .env

# Windows (icacls)
icacls .env /inheritance:r /grant:r "$($env:USERNAME):F"
```

Docker 컨테이너 내부는 Linux이므로 권한 문제가 발생할 수 있습니다. 필요 시 Dockerfile에서 처리:

```dockerfile
# Dockerfile
RUN chown -R appuser:appuser /app
USER appuser
```

---

## 📚 유용한 PowerShell 명령어

### 배포 관련

```powershell
# 빠른 재배포
cd C:\kt-demo-alarm
git pull
docker compose up -d --build

# 특정 버전으로 롤백
git checkout v1.0.0
docker compose up -d --build

# 컨테이너 중지 (데이터 보존)
docker compose stop

# 컨테이너 완전 제거 (데이터 삭제 X)
docker compose down
```

### 백업 관련

```powershell
# 데이터베이스 백업
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item .\data\kt_demo_alarm.db .\data\kt_demo_alarm.db.backup.$timestamp

# 전체 프로젝트 백업
$date = Get-Date -Format "yyyyMMdd"
Compress-Archive -Path C:\kt-demo-alarm -DestinationPath C:\Backups\kt-demo-alarm-backup-$date.zip
```

### 성능 모니터링

```powershell
# CPU, 메모리 실시간 모니터링
Get-Process | Sort-Object CPU -Descending | Select-Object -First 10

# Docker 리소스 모니터링
docker stats

# 네트워크 연결 확인
Get-NetTCPConnection | Where-Object {$_.LocalPort -eq 8000}

# 디스크 I/O 확인
Get-Counter '\PhysicalDisk(_Total)\Disk Reads/sec','\PhysicalDisk(_Total)\Disk Writes/sec'
```

---

## 🚨 보안 체크리스트

배포 전 확인:

- [ ] `DEBUG=false` 설정
- [ ] `.env` 파일 권한 설정: `icacls .env /inheritance:r`
- [ ] Windows Defender 방화벽 규칙 설정
- [ ] Windows Update 최신 상태 유지
- [ ] RDP 접근 제한 (특정 IP만 허용)
- [ ] 불필요한 포트 닫기
- [ ] 관리자 계정 비밀번호 강화
- [ ] 정기 백업 작업 스케줄러 등록
- [ ] Docker Desktop 자동 업데이트 활성화

---

## 🔒 자동 시작 설정

Windows 재부팅 시 자동으로 애플리케이션 시작:

### 방법 1: Docker Desktop 자동 시작

1. Docker Desktop Settings → General
2. ✅ Start Docker Desktop when you log in
3. ✅ Automatically check for updates

### 방법 2: 작업 스케줄러

```powershell
# 작업 스케줄러로 부팅 시 자동 실행 스크립트 등록
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' `
    -Argument '-File "C:\kt-demo-alarm\scripts\start-on-boot.ps1"'

$trigger = New-ScheduledTaskTrigger -AtStartup

$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -RunLevel Highest

Register-ScheduledTask -Action $action -Trigger $trigger -Principal $principal `
    -TaskName "KT Demo Alarm Auto Start" -Description "Auto start KT Demo Alarm on boot"
```

`scripts/start-on-boot.ps1` 파일:
```powershell
Start-Sleep -Seconds 30  # Docker Desktop 시작 대기
cd C:\kt-demo-alarm
docker compose up -d
```

---

## 📞 지원

문제가 발생하면:

1. GitHub Issues: https://github.com/hoonly01/kt-demo-alarm/issues
2. 로그 확인 후 이슈 생성
3. 에러 메시지 및 환경 정보 첨부

---

## 🔗 관련 문서

- [Linux 배포 가이드](./DEPLOYMENT.md)
- [프로젝트 README](./README.md)
- [Docker 공식 문서](https://docs.docker.com/)
- [Windows Server 컨테이너](https://docs.microsoft.com/en-us/virtualization/windowscontainers/)

---

**Last Updated**: 2025-01-07
