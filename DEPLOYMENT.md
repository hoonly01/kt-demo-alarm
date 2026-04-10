# Deployment Guide

## 전제 조건

- AWS EC2 (Ubuntu 22.04+)
- EC2 보안그룹: 22 (SSH), 80 (HTTP), 443 (HTTPS) 오픈
- 공인 도메인 (A레코드 → EC2 Public IP)
- GitHub Secrets 설정 완료

## 배포 아키텍처

```
인터넷 (HTTPS:443)
  ↓
Nginx (EC2 호스트, Let's Encrypt SSL)
  ↓
localhost:8000 (FastAPI Docker Container)
  ↓
SQLite Volume (호스트 마운트)
```

## GitHub Secrets 목록

| Secret | 설명 |
|--------|------|
| `EC2_HOST` | EC2 Public IP 또는 도메인 |
| `EC2_USERNAME` | EC2 사용자 (보통 `ubuntu`) |
| `EC2_SSH_KEY` | EC2 SSH 프라이빗 키 (pem 전체 내용) |
| `KAKAO_REST_API_KEY` | 카카오 REST API 키 |
| `BOT_ID` | 카카오톡 봇 ID |
| `API_KEY` | 내부 API 보안 키 |
| `GEMINI_API_KEY` | Gemini API 키 |
| `SEOUL_BUS_API_KEY` | 서울 버스 API 키 |
| `ADMIN_USER` | 어드민 대시보드 사용자명 |
| `ADMIN_PASS` | 어드민 대시보드 비밀번호 |
| `TMAP_APP_KEY` | TMAP API 키 |
| `ALARM_SAVE_BLOCK_ID` | 카카오 챗봇 블록 ID |
| `FAVORITE_ZONE_SAVE_BLOCK_ID` | 카카오 챗봇 블록 ID |
| `ROUTE_SETUP_BLOCK_ID` | 카카오 챗봇 블록 ID |
| `ROUTE_DELETE_BLOCK_ID` | 카카오 챗봇 블록 ID |

## EC2 초기 설정 (1회만 실행)

도메인 A레코드가 EC2 IP를 가리키는 상태에서 실행.

```bash
# EC2에 스크립트 복사
scp -i ~/.ssh/kt-demo-alarm-key.pem scripts/setup-ec2.sh ubuntu@<EC2_IP>:~/
scp -i ~/.ssh/kt-demo-alarm-key.pem -r nginx ubuntu@<EC2_IP>:~/

# EC2 접속 후 실행
ssh -i ~/.ssh/kt-demo-alarm-key.pem ubuntu@<EC2_IP>
bash setup-ec2.sh <도메인> <이메일>
```

스크립트가 자동으로 수행하는 작업:
1. Docker 설치
2. Nginx + Certbot 설치
3. Let's Encrypt SSL 인증서 발급
4. `/opt/kt-demo-alarm/` 디렉토리 구성

## 배포

`main` 브랜치에 push하면 GitHub Actions가 자동으로:

1. pytest 전체 실행
2. Docker 이미지 빌드
3. EC2로 이미지 + `nginx.conf` + `docker-compose.yml` 전송
4. Docker 컨테이너 교체 및 Nginx 설정 reload
5. `https://<EC2_HOST>/` 헬스체크

## 수동 재시작

```bash
ssh ubuntu@<EC2_IP>
cd /opt/kt-demo-alarm
docker compose down
docker compose up -d
```

## 로그 확인

```bash
docker compose logs -f           # 실시간
docker compose logs --tail=100   # 최근 100줄
sudo journalctl -u nginx -f      # Nginx 로그
```
