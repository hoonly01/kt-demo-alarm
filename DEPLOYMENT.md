# KT Demo Alarm - 배포 가이드

AWS EC2에 Docker 기반 FastAPI 애플리케이션을 배포하는 전체 가이드입니다.

## 📋 목차

- [사전 요구사항](#사전-요구사항)
- [EC2 초기 설정](#ec2-초기-설정)
- [GitHub Actions 설정](#github-actions-설정)
- [수동 배포](#수동-배포)
- [Nginx 설정](#nginx-설정)
- [SSL 인증서 설정](#ssl-인증서-설정)
- [모니터링 및 로그](#모니터링-및-로그)
- [트러블슈팅](#트러블슈팅)

---

## 🎯 사전 요구사항

### AWS EC2 인스턴스
- **OS**: Ubuntu 22.04 LTS 또는 24.04 LTS
- **인스턴스 타입**: t3.small 이상 (2 vCPU, 2GB RAM)
- **스토리지**: 20GB 이상

### 보안 그룹 설정
```
인바운드 규칙:
- 22 (SSH): 내 IP
- 80 (HTTP): 0.0.0.0/0
- 443 (HTTPS): 0.0.0.0/0
- 8000 (FastAPI): 내부만 (선택사항)
```

### 필수 정보
- 카카오 API 키: `KAKAO_REST_API_KEY`
- 카카오 봇 ID: `BOT_ID`
- EC2 SSH 키 페어

---

## 🚀 EC2 초기 설정

### 1. EC2 인스턴스 접속

```bash
ssh -i /path/to/your-key.pem ubuntu@your-ec2-ip
```

### 2. 초기 설정 스크립트 실행

```bash
# 프로젝트 클론
git clone https://github.com/hoonly01/kt-demo-alarm.git
cd kt-demo-alarm

# 초기 설정 스크립트 실행
chmod +x scripts/setup-ec2-docker.sh
./scripts/setup-ec2-docker.sh
```

이 스크립트는 다음을 자동으로 설치합니다:
- Docker & Docker Compose
- Git, Vim, Htop 등 필수 도구
- 방화벽 설정 (UFW)
- 프로젝트 디렉토리 생성

### 3. 환경변수 설정

```bash
# .env 파일 생성
cp .env.production.example .env

# 실제 값으로 편집
vim .env
```

필수 환경변수:
```env
KAKAO_REST_API_KEY=your_actual_key
BOT_ID=your_actual_bot_id
DEBUG=false
LOG_LEVEL=INFO
```

### 4. 첫 배포 테스트

```bash
# Docker Compose로 애플리케이션 시작
docker compose up -d

# 로그 확인
docker compose logs -f

# 헬스체크
curl http://localhost:8000/
```

---

## 🤖 GitHub Actions 설정

### 1. GitHub Secrets 추가

GitHub 리포지토리 Settings → Secrets and variables → Actions에서 다음 Secrets를 추가:

```
EC2_HOST=your-ec2-public-ip
EC2_USER=ubuntu
EC2_SSH_KEY=<your-private-ssh-key>
KAKAO_REST_API_KEY=<your-kakao-api-key>
BOT_ID=<your-bot-id>
```

#### SSH 키 설정 방법

```bash
# 로컬에서 SSH 키 내용 복사
cat ~/.ssh/your-key.pem

# GitHub Secrets에 전체 내용 붙여넣기 (-----BEGIN RSA PRIVATE KEY----- 포함)
```

### 2. 자동 배포 워크플로우

`main` 브랜치에 푸시하면 자동으로 배포됩니다:

```bash
git add .
git commit -m "feat: new feature"
git push origin main
```

GitHub Actions에서 배포 진행 상황을 확인할 수 있습니다.

### 3. 수동 트리거

GitHub Actions → Deploy to AWS EC2 → Run workflow 버튼 클릭

---

## 🛠️ 수동 배포

GitHub Actions 없이 EC2에서 직접 배포:

```bash
cd ~/kt-demo-alarm
./scripts/deploy.sh
```

이 스크립트는:
1. Git pull로 최신 코드 가져오기
2. 환경변수 확인
3. 데이터베이스 백업
4. Docker 이미지 빌드
5. 컨테이너 재시작
6. 헬스체크

---

## 🌐 Nginx 설정

### 1. Nginx 설치 및 설정

```bash
cd ~/kt-demo-alarm
chmod +x nginx/setup-nginx.sh
./nginx/setup-nginx.sh
```

### 2. 도메인 설정 (선택사항)

Nginx 설정 파일 수정:

```bash
sudo vim /etc/nginx/sites-available/kt-demo-alarm
```

`server_name _;` 부분을 실제 도메인으로 변경:
```nginx
server_name yourdomain.com www.yourdomain.com;
```

재시작:
```bash
sudo systemctl restart nginx
```

---

## 🔒 SSL 인증서 설정

### Let's Encrypt 인증서 발급

```bash
# Certbot 설치
sudo apt-get install -y certbot python3-certbot-nginx

# 인증서 발급 (도메인 필요)
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# 자동 갱신 확인
sudo certbot renew --dry-run
```

Certbot이 자동으로 Nginx 설정을 업데이트하고 HTTP → HTTPS 리다이렉트를 설정합니다.

---

## 📊 모니터링 및 로그

### Docker 컨테이너 상태 확인

```bash
# 실행 중인 컨테이너 확인
docker compose ps

# 리소스 사용량
docker stats

# 컨테이너 재시작
docker compose restart
```

### 로그 확인

```bash
# 실시간 로그 (전체)
docker compose logs -f

# 최근 100줄
docker compose logs --tail=100

# 특정 시간 이후 로그
docker compose logs --since 10m

# 컨테이너 내부 접속
docker compose exec kt-demo-alarm bash
```

### 시스템 로그

```bash
# Nginx 액세스 로그
sudo tail -f /var/log/nginx/kt-demo-alarm-access.log

# Nginx 에러 로그
sudo tail -f /var/log/nginx/kt-demo-alarm-error.log

# 시스템 로그
journalctl -u docker -f
```

### 디스크 사용량 확인

```bash
# 전체 디스크 사용량
df -h

# Docker 디스크 사용량
docker system df

# 불필요한 이미지/컨테이너 정리
docker system prune -a
```

---

## 🔧 트러블슈팅

### 컨테이너가 시작되지 않는 경우

```bash
# 로그 확인
docker compose logs

# 환경변수 확인
docker compose config

# 컨테이너 강제 재생성
docker compose down
docker compose up -d --force-recreate
```

### 데이터베이스 오류

```bash
# SQLite 파일 권한 확인
ls -la data/kt_demo_alarm.db

# 백업에서 복구
cp data/kt_demo_alarm.db.backup.YYYYMMDD_HHMMSS data/kt_demo_alarm.db
docker compose restart
```

### Nginx 502 Bad Gateway

```bash
# FastAPI 컨테이너 상태 확인
docker compose ps

# 포트 8000 리스닝 확인
netstat -tlnp | grep 8000

# Nginx 에러 로그 확인
sudo tail -f /var/log/nginx/error.log
```

### 메모리 부족

```bash
# 메모리 사용량 확인
free -h

# Docker 메모리 제한 설정 (docker-compose.yml)
services:
  kt-demo-alarm:
    mem_limit: 512m
```

### GitHub Actions 배포 실패

1. **SSH 연결 실패**
   - EC2_HOST, EC2_USER, EC2_SSH_KEY Secrets 확인
   - EC2 보안 그룹에서 GitHub Actions IP 허용 (또는 모든 IP 허용)

2. **환경변수 오류**
   - KAKAO_REST_API_KEY, BOT_ID Secrets 확인
   - EC2에 .env 파일이 있는지 확인

3. **Docker 빌드 실패**
   - EC2에서 `docker compose build` 직접 실행하여 에러 확인
   - 디스크 공간 확인: `df -h`

---

## 📚 유용한 명령어

### 배포 관련

```bash
# 빠른 재배포
cd ~/kt-demo-alarm && git pull && docker compose up -d --build

# 특정 버전으로 롤백
git checkout v1.0.0
docker compose up -d --build

# 컨테이너 중지 (데이터 보존)
docker compose stop

# 컨테이너 완전 제거 (데이터 삭제 X)
docker compose down
```

### 백업 관련

```bash
# 데이터베이스 백업
cp data/kt_demo_alarm.db data/kt_demo_alarm.db.backup.$(date +%Y%m%d_%H%M%S)

# 전체 프로젝트 백업
tar -czf kt-demo-alarm-backup-$(date +%Y%m%d).tar.gz ~/kt-demo-alarm
```

### 성능 모니터링

```bash
# CPU, 메모리 실시간 모니터링
htop

# 네트워크 연결 확인
netstat -tlnp

# 디스크 I/O 확인
iostat -x 1
```

---

## 🚨 보안 체크리스트

배포 전 확인:

- [ ] `DEBUG=false` 설정
- [ ] `.env` 파일 권한: `chmod 600 .env`
- [ ] SSH 키 기반 인증만 허용
- [ ] EC2 보안 그룹 최소 권한 적용
- [ ] 불필요한 포트 닫기
- [ ] HTTPS/SSL 인증서 설정
- [ ] 정기 백업 스크립트 실행
- [ ] 로그 로테이션 설정
- [ ] 시스템 업데이트: `sudo apt update && sudo apt upgrade`

---

## 📞 지원

문제가 발생하면:

1. GitHub Issues: https://github.com/hoonly01/kt-demo-alarm/issues
2. 로그 확인 후 이슈 생성
3. 에러 메시지 및 환경 정보 첨부

---

**Last Updated**: 2025-01-07
