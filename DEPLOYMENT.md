# AWS EC2 배포 가이드

KT Demo Alarm API를 AWS EC2에 배포하는 상세 가이드입니다.

## 📋 사전 준비물

- AWS 계정
- GitHub 계정
- 카카오 REST API 키 및 BOT ID
- 로컬에 Git 및 Docker 설치

## 🚀 배포 순서

### 1단계: AWS 리소스 생성 (15분)

#### 1.1 EC2 Key Pair 생성

1. AWS Console 로그인
2. EC2 대시보드 이동
3. 왼쪽 메뉴에서 "Key Pairs" 클릭
4. "Create key pair" 클릭
   - 이름: `kt-demo-alarm-key`
   - 키 타입: RSA
   - 파일 형식: .pem
5. 다운로드 받은 키 파일을 `~/.ssh/` 디렉토리로 이동
6. 권한 설정:
   ```bash
   chmod 400 ~/.ssh/kt-demo-alarm-key.pem
   ```

#### 1.2 Security Group 생성

1. EC2 대시보드 → Security Groups → Create security group
2. 설정:
   - 이름: `kt-demo-alarm-sg`
   - 설명: `Security group for KT Demo Alarm`
   - VPC: 기본 VPC 선택
3. 인바운드 규칙 추가:

| 타입 | 프로토콜 | 포트 | 소스 | 설명 |
|------|----------|------|------|------|
| SSH | TCP | 22 | 내 IP | SSH 접속 |
| HTTP | TCP | 80 | 0.0.0.0/0 | HTTP 트래픽 |
| HTTPS | TCP | 443 | 0.0.0.0/0 | HTTPS 트래픽 |
| Custom TCP | TCP | 8000 | 0.0.0.0/0 | FastAPI 포트 |

#### 1.3 EC2 인스턴스 생성

1. EC2 대시보드 → Instances → Launch Instance
2. 설정:
   - **이름**: `kt-demo-alarm`
   - **AMI**: Ubuntu Server 22.04 LTS (무료 티어 대상)
   - **인스턴스 타입**:
     - 테스트: t2.micro (프리티어 무료)
     - 또는: t3.micro (월 $7.59)
   - **Key pair**: `kt-demo-alarm-key` 선택
   - **Security group**: `kt-demo-alarm-sg` 선택
   - **스토리지**: 10GB gp3
     - **중요**: "Delete on termination" 체크 해제 (데이터 보호)
3. "Launch instance" 클릭
4. Public IP 주소 메모하기

#### 1.4 Elastic IP 할당 (선택사항)

> 인스턴스 재시작 시에도 IP 주소가 고정되길 원한다면 설정

1. EC2 대시보드 → Elastic IPs → Allocate Elastic IP address
2. "Allocate" 클릭
3. 할당된 Elastic IP 선택 → Actions → Associate Elastic IP address
4. 인스턴스: `kt-demo-alarm` 선택
5. "Associate" 클릭

---

### 2단계: EC2 초기 설정 (20분)

#### 2.1 SSH 접속

```bash
ssh -i ~/.ssh/kt-demo-alarm-key.pem ubuntu@<EC2_PUBLIC_IP>
```

> `<EC2_PUBLIC_IP>`는 EC2 콘솔에서 확인한 Public IPv4 주소로 교체

#### 2.2 시스템 업데이트 및 기본 설정

```bash
# 시스템 패키지 업데이트
sudo apt update && sudo apt upgrade -y

# 타임존 설정 (한국 시간)
sudo timedatectl set-timezone Asia/Seoul

# 타임존 확인
timedatectl

# 필수 패키지 설치
sudo apt install -y curl git htop vim jq
```

#### 2.3 Docker 및 Docker Compose 설치

```bash
# Docker 공식 설치 스크립트 다운로드 및 실행
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 현재 사용자(ubuntu)를 docker 그룹에 추가 (sudo 없이 docker 명령 실행)
sudo usermod -aG docker $USER

# Docker 서비스 자동 시작 설정
sudo systemctl enable docker
sudo systemctl start docker

# 설정 적용을 위해 로그아웃 후 재접속
exit
```

재접속:
```bash
ssh -i ~/.ssh/kt-demo-alarm-key.pem ubuntu@<EC2_PUBLIC_IP>
```

설치 확인:
```bash
docker --version
# 예상 출력: Docker version 24.x.x, build...

docker compose version
# 예상 출력: Docker Compose version v2.x.x
```

#### 2.4 애플리케이션 디렉토리 구조 생성

```bash
# /opt 디렉토리에 애플리케이션 디렉토리 생성
sudo mkdir -p /opt/kt-demo-alarm
sudo chown -R ubuntu:ubuntu /opt/kt-demo-alarm
cd /opt/kt-demo-alarm

# 데이터 및 로그 디렉토리 생성
mkdir -p data logs scripts backups

# 디렉토리 구조 확인
tree -L 2
# 또는
ls -la
```

예상 구조:
```
/opt/kt-demo-alarm/
├── data/           # SQLite 데이터베이스 저장
├── logs/           # 애플리케이션 로그
├── scripts/        # 헬스체크, 백업 등 스크립트
├── backups/        # 데이터베이스 백업
├── .env            # 환경변수 (생성 예정)
└── docker-compose.yml  # (GitHub Actions가 배포)
```

#### 2.5 환경변수 파일 생성

```bash
cat > /opt/kt-demo-alarm/.env << 'EOF'
# 카카오 API 설정
KAKAO_REST_API_KEY=your_kakao_rest_api_key_here
BOT_ID=your_bot_id_here

# 서버 설정
PORT=8000
DEBUG=false
LOG_LEVEL=INFO

# 데이터베이스 설정
DATABASE_PATH=/app/data/kt_demo_alarm.db

# 스케줄링 설정 (한국 시간 기준)
CRAWLING_HOUR=8
CRAWLING_MINUTE=30
ROUTE_CHECK_HOUR=7
ROUTE_CHECK_MINUTE=0

# 알림 설정
BATCH_SIZE=100
NOTIFICATION_TIMEOUT=10.0

# 경로 감지 설정
ROUTE_THRESHOLD_METERS=500
EOF
```

**중요: 실제 API 키로 수정**

```bash
# vim 편집기로 열기
vim /opt/kt-demo-alarm/.env

# 또는 nano 편집기
nano /opt/kt-demo-alarm/.env
```

수정 내용:
- `KAKAO_REST_API_KEY`: 실제 카카오 REST API 키 입력
- `BOT_ID`: 실제 카카오톡 봇 ID 입력

저장 후 권한 설정:
```bash
chmod 600 /opt/kt-demo-alarm/.env

# 환경변수 확인 (API 키는 보이지 않도록 주의)
cat /opt/kt-demo-alarm/.env
```

---

### 3단계: GitHub Actions 설정 (10분)

#### 3.1 GitHub Repository Secrets 추가

1. GitHub에서 프로젝트 리포지토리 이동
2. `Settings` 탭 클릭
3. 왼쪽 메뉴에서 `Secrets and variables` → `Actions` 클릭
4. `New repository secret` 버튼 클릭

추가할 Secrets (총 5개):

**1. EC2_HOST**
```
Name: EC2_HOST
Value: <EC2 Public IP 또는 Elastic IP>
예: 54.123.45.67
```

**2. EC2_USERNAME**
```
Name: EC2_USERNAME
Value: ubuntu
```

**3. EC2_SSH_KEY**
```
Name: EC2_SSH_KEY
Value: <Private Key 전체 내용>
```

Private Key 가져오기:
```bash
# 로컬 터미널에서 실행
cat ~/.ssh/kt-demo-alarm-key.pem
```

출력된 전체 내용 (-----BEGIN RSA PRIVATE KEY----- 부터 -----END RSA PRIVATE KEY----- 까지) 복사하여 Value에 붙여넣기

**4. KAKAO_REST_API_KEY**
```
Name: KAKAO_REST_API_KEY
Value: <실제 카카오 REST API 키>
```

**5. BOT_ID**
```
Name: BOT_ID
Value: <실제 카카오톡 봇 ID>
```

모든 Secrets 추가 완료 확인:
- EC2_HOST ✓
- EC2_USERNAME ✓
- EC2_SSH_KEY ✓
- KAKAO_REST_API_KEY ✓
- BOT_ID ✓

#### 3.2 GitHub Actions 워크플로우 확인

다음 파일이 이미 생성되어 있는지 확인:
```
.github/workflows/deploy.yml
```

워크플로우 내용:
- **Test**: pytest 실행
- **Build**: Docker 이미지 빌드
- **Deploy**: EC2로 배포
- **Verify**: 헬스체크

---

### 4단계: 첫 배포 실행 (10분)

#### 4.1 로컬에서 변경사항 확인

```bash
cd /Users/hwangjonghoon/projects/kt-demo-alarm/dev/demo-alarm

# 변경된 파일 확인
git status

# 예상 출력:
# modified:   docker-compose.yml
# new file:   .github/workflows/deploy.yml
# new file:   DEPLOYMENT.md
```

#### 4.2 Git Commit 및 Push

```bash
# 변경사항 스테이징
git add .github/workflows/deploy.yml
git add docker-compose.yml
git add DEPLOYMENT.md

# 커밋
git commit -m "feat: Add AWS EC2 deployment with GitHub Actions

- Add GitHub Actions workflow for automated deployment
- Update docker-compose.yml for production (DEBUG=false)
- Add comprehensive deployment guide"

# GitHub에 푸시
git push origin main
```

#### 4.3 GitHub Actions 배포 진행 상황 확인

1. GitHub 리포지토리 → `Actions` 탭 클릭
2. 최신 워크플로우 실행 클릭 (방금 푸시한 커밋)
3. 각 Job 확인:
   - ✅ **test**: 테스트 실행
   - ✅ **build-and-push**: Docker 이미지 빌드
   - ✅ **deploy**: EC2로 배포 및 컨테이너 시작
   - ✅ **verify**: 헬스체크

배포 시간: 약 5-10분

#### 4.4 배포 완료 확인

로컬 터미널에서 헬스체크:

```bash
# EC2 Public IP로 헬스체크
curl http://<EC2_PUBLIC_IP>:8000/

# 예상 응답:
{
  "message": "KT Demo Alarm API is running!",
  "version": "1.0.0",
  "status": "healthy"
}
```

API 엔드포인트 테스트:
```bash
# 사용자 목록 조회
curl http://<EC2_PUBLIC_IP>:8000/users

# 집회 목록 조회
curl http://<EC2_PUBLIC_IP>:8000/events

# 스케줄러 상태 확인
curl http://<EC2_PUBLIC_IP>:8000/scheduler/status
```

#### 4.5 EC2에서 로그 확인

```bash
# EC2에 SSH 접속
ssh -i ~/.ssh/kt-demo-alarm-key.pem ubuntu@<EC2_PUBLIC_IP>

# 애플리케이션 디렉토리로 이동
cd /opt/kt-demo-alarm

# 실시간 로그 확인
docker compose logs -f

# Ctrl+C로 종료

# 최근 100줄 로그 확인
docker compose logs --tail=100

# 컨테이너 상태 확인
docker compose ps
```

예상 출력:
```
NAME                   IMAGE               STATUS         PORTS
kt-demo-alarm-1        kt-demo-alarm:latest   Up 5 minutes   0.0.0.0:8000->8000/tcp
```

---

### 5단계: 모니터링 및 유지보수 설정 (15분)

#### 5.1 헬스체크 스크립트 생성

```bash
# EC2에 SSH 접속 상태에서
cat > /opt/kt-demo-alarm/scripts/healthcheck.sh << 'EOF'
#!/bin/bash
response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/)
if [ $response -eq 200 ]; then
  echo "[$(date)] ✅ Application is healthy (HTTP $response)"
  exit 0
else
  echo "[$(date)] ❌ Application is unhealthy (HTTP $response) - Restarting..."
  cd /opt/kt-demo-alarm && docker compose restart
  exit 1
fi
EOF

chmod +x /opt/kt-demo-alarm/scripts/healthcheck.sh

# 테스트 실행
/opt/kt-demo-alarm/scripts/healthcheck.sh
```

#### 5.2 자동 헬스체크 설정 (Cron)

```bash
# Crontab 편집
crontab -e

# 첫 실행 시 편집기 선택 (vim 추천: 1 선택)
```

다음 라인 추가:
```
# 5분마다 헬스체크 실행
*/5 * * * * /opt/kt-demo-alarm/scripts/healthcheck.sh >> /opt/kt-demo-alarm/logs/healthcheck.log 2>&1
```

저장 후 종료 (vim: `:wq` 입력 후 Enter)

Cron 작업 확인:
```bash
crontab -l
```

#### 5.3 백업 스크립트 생성

```bash
cat > /opt/kt-demo-alarm/scripts/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/kt-demo-alarm/backups"
mkdir -p $BACKUP_DIR
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 데이터베이스 백업
cp /opt/kt-demo-alarm/data/kt_demo_alarm.db $BACKUP_DIR/db_backup_$TIMESTAMP.db

# 7일 이상 된 백업 파일 삭제
find $BACKUP_DIR -name "db_backup_*.db" -mtime +7 -delete

echo "[$(date)] Backup completed: db_backup_$TIMESTAMP.db"

# 백업 파일 목록
ls -lh $BACKUP_DIR/
EOF

chmod +x /opt/kt-demo-alarm/scripts/backup.sh

# 테스트 실행
/opt/kt-demo-alarm/scripts/backup.sh
```

Crontab에 백업 작업 추가:
```bash
crontab -e
```

추가:
```
# 매일 새벽 2시 데이터베이스 백업
0 2 * * * /opt/kt-demo-alarm/scripts/backup.sh >> /opt/kt-demo-alarm/logs/backup.log 2>&1
```

#### 5.4 시스템 상태 확인 스크립트

```bash
cat > /opt/kt-demo-alarm/scripts/status.sh << 'EOF'
#!/bin/bash
echo "========================================="
echo "KT Demo Alarm - System Status"
echo "========================================="
echo ""
echo "📊 System Resources:"
echo "CPU Usage: $(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1"%"}')"
echo "Memory: $(free -h | awk '/^Mem:/ {print $3 " / " $2}')"
echo "Disk: $(df -h / | awk 'NR==2 {print $3 " / " $2 " (" $5 ")"}')"
echo ""
echo "🐳 Docker Status:"
docker compose ps
echo ""
echo "📝 Recent Logs (last 10 lines):"
docker compose logs --tail=10
echo ""
echo "🔍 Health Check:"
curl -s http://localhost:8000/ | jq '.' 2>/dev/null || curl -s http://localhost:8000/
echo ""
echo "========================================="
EOF

chmod +x /opt/kt-demo-alarm/scripts/status.sh

# 실행
/opt/kt-demo-alarm/scripts/status.sh
```

---

## 📱 카카오톡 웹훅 URL 업데이트

배포 완료 후 Kakao Developers Console에서 웹훅 URL을 업데이트해야 합니다.

### Kakao Developers Console 설정

1. https://developers.kakao.com/ 로그인
2. 내 애플리케이션 → KT Demo Alarm 선택
3. 카카오톡 채널 → 봇 설정

**챗봇 API 서버 URL 업데이트:**
```
기존: http://localhost:8000/kakao/chat
변경: http://<EC2_PUBLIC_IP>:8000/kakao/chat
```

**채널 추가/차단 웹훅 URL 업데이트:**
```
기존: http://localhost:8000/kakao/webhook/channel
변경: http://<EC2_PUBLIC_IP>:8000/kakao/webhook/channel
```

> 도메인 연결 시: `http://your-domain.com/kakao/...`

---

## 🔄 이후 코드 업데이트 방법

코드 수정 후 자동 배포:

```bash
# 로컬에서 코드 수정
vim app/services/some_service.py

# Git에 커밋 및 푸시
git add .
git commit -m "feat: Add new feature"
git push origin main

# GitHub Actions가 자동으로:
# 1. 테스트 실행
# 2. Docker 이미지 빌드
# 3. EC2로 배포
# 4. 헬스체크
```

배포 시간: 약 5-10분

---

## 📝 자주 사용하는 명령어

### EC2 관리

```bash
# EC2 SSH 접속
ssh -i ~/.ssh/kt-demo-alarm-key.pem ubuntu@<EC2_IP>

# 애플리케이션 디렉토리로 이동
cd /opt/kt-demo-alarm

# 시스템 상태 확인
/opt/kt-demo-alarm/scripts/status.sh
```

### Docker 관리

```bash
# 컨테이너 시작
docker compose up -d

# 컨테이너 중지
docker compose down

# 컨테이너 재시작
docker compose restart

# 로그 확인 (실시간)
docker compose logs -f

# 로그 확인 (최근 100줄)
docker compose logs --tail=100

# 컨테이너 상태 확인
docker compose ps

# 컨테이너 내부 진입
docker compose exec kt-demo-alarm bash
```

### 애플리케이션 관리

```bash
# 헬스체크
curl http://localhost:8000/

# 수동 크롤링
curl -X POST http://localhost:8000/scheduler/crawl-events

# 수동 경로 체크
curl -X POST http://localhost:8000/scheduler/check-routes

# 스케줄러 상태 확인
curl http://localhost:8000/scheduler/status
```

### 백업 및 복구

```bash
# 수동 백업
/opt/kt-demo-alarm/scripts/backup.sh

# 백업 파일 목록 확인
ls -lh /opt/kt-demo-alarm/backups/

# 백업에서 복구
cp /opt/kt-demo-alarm/backups/db_backup_YYYYMMDD_HHMMSS.db \
   /opt/kt-demo-alarm/data/kt_demo_alarm.db
docker compose restart
```

---

## 🛠️ 트러블슈팅

### 배포 실패 시

**GitHub Actions 로그 확인:**
1. GitHub → Actions → 실패한 워크플로우 클릭
2. 실패한 Job 클릭 → 로그 확인

**EC2에서 수동 확인:**
```bash
ssh -i ~/.ssh/kt-demo-alarm-key.pem ubuntu@<EC2_IP>
cd /opt/kt-demo-alarm

# 로그 확인
docker compose logs --tail=100

# 컨테이너 상태 확인
docker compose ps

# 수동 재시작
docker compose down
docker compose up -d
```

### 컨테이너가 시작되지 않을 때

```bash
# 환경변수 확인
cat /opt/kt-demo-alarm/.env

# 포트 충돌 확인
sudo netstat -tulpn | grep 8000

# Docker 로그 상세 확인
docker compose logs -f

# 수동 실행으로 에러 확인
docker compose up

# 이미지 재빌드
docker compose down
docker compose up --build
```

### 데이터베이스 문제

```bash
# 데이터베이스 파일 권한 확인
ls -la /opt/kt-demo-alarm/data/

# 데이터베이스 백업에서 복구
cd /opt/kt-demo-alarm
ls -lh backups/
cp backups/db_backup_YYYYMMDD_HHMMSS.db data/kt_demo_alarm.db
docker compose restart
```

### 헬스체크 실패

```bash
# 로컬에서 헬스체크
curl -v http://localhost:8000/

# 외부에서 헬스체크
curl -v http://<EC2_PUBLIC_IP>:8000/

# 방화벽 확인
sudo ufw status

# Security Group 확인 (AWS Console)
```

---

## 💰 예상 비용

### 월별 예상 비용 (us-east-1 기준)

| 항목 | 사양 | 비용 (월) |
|------|------|-----------|
| EC2 t3.micro | 730시간 | $7.59 |
| EBS 10GB | gp3 | $0.80 |
| 데이터 전송 | ~1GB | $0.09 |
| **총계** | | **$8.48** |
| | | |
| **프리티어 (t2.micro)** | 750시간/월 무료 | **$0.80** |

### 비용 절감 팁

1. **프리티어 활용**: 첫 12개월 동안 t2.micro 무료 사용
2. **Elastic IP**: 인스턴스에 연결된 상태면 무료, 미사용 시 과금
3. **예약 인스턴스**: 장기 운영 시 1년 예약으로 약 40% 할인
4. **스팟 인스턴스**: 개발/테스트 환경에서 최대 90% 할인
5. **AWS Budgets**: 예산 한도 설정 및 알림

---

## ✅ 배포 성공 체크리스트

### 배포 전
- [ ] AWS EC2 인스턴스 생성 완료
- [ ] Security Group 설정 (22, 80, 443, 8000 포트 오픈)
- [ ] SSH 접속 성공
- [ ] Docker 설치 완료
- [ ] `/opt/kt-demo-alarm/.env` 파일 생성 및 API 키 입력
- [ ] GitHub Secrets 5개 추가
- [ ] `.github/workflows/deploy.yml` 파일 생성

### 배포 후
- [ ] GitHub Actions 워크플로우 전체 성공 (초록색 체크)
- [ ] `curl http://<EC2_IP>:8000/` 응답 정상
- [ ] API 엔드포인트 테스트 성공 (`/users`, `/events`, `/scheduler/status`)
- [ ] Docker 컨테이너 정상 실행 중 (`docker compose ps`)
- [ ] 로그에 ERROR 없음
- [ ] 카카오톡 웹훅 URL 업데이트 완료
- [ ] 헬스체크 스크립트 정상 작동
- [ ] 백업 스크립트 정상 작동
- [ ] Cron 작업 설정 완료

---

## 📚 추가 참고 자료

- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [Docker 공식 문서](https://docs.docker.com/)
- [GitHub Actions 공식 문서](https://docs.github.com/en/actions)
- [AWS EC2 사용 설명서](https://docs.aws.amazon.com/ec2/)
- [카카오 i 오픈빌더 가이드](https://chatbot.kakao.com/docs/)

---

## 🆘 지원

문제가 발생하거나 질문이 있다면:

1. GitHub Issues: https://github.com/hoonly01/kt-demo-alarm/issues
2. 배포 로그 확인: GitHub Actions 탭
3. EC2 로그 확인: `docker compose logs -f`

---

**작성일**: 2026-01-08
**버전**: 1.0.0
**담당**: Claude Code
