#!/bin/bash
# EC2 초기 설정 스크립트 (Ubuntu 22.04/24.04)
# 사용법: bash scripts/setup-ec2.sh <도메인> <이메일>
# 예시:   bash scripts/setup-ec2.sh example.com admin@example.com
#
# 전제 조건:
# - EC2 보안그룹: 22(SSH), 80(HTTP), 443(HTTPS) 오픈
# - 도메인 A레코드가 이 EC2 IP를 가리키고 있어야 함

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
  echo "사용법: bash setup-ec2.sh <도메인> <이메일>"
  echo "예시:   bash setup-ec2.sh example.com admin@example.com"
  exit 1
fi

echo "=== [1/5] 시스템 업데이트 ==="
sudo apt-get update -y
sudo apt-get upgrade -y
sudo timedatectl set-timezone Asia/Seoul

echo "=== [2/5] 기본 패키지 설치 ==="
sudo apt-get install -y curl git vim jq nginx certbot python3-certbot-nginx

echo "=== [3/5] Docker 설치 ==="
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sudo sh /tmp/get-docker.sh
  rm /tmp/get-docker.sh
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable docker
sudo systemctl start docker

echo "=== [4/5] 애플리케이션 디렉토리 준비 ==="
sudo mkdir -p /opt/kt-demo-alarm/{data,logs,topis_cache,topis_attachments}
sudo chown -R "$USER":"$USER" /opt/kt-demo-alarm

echo "=== [5/5] Nginx 설정 및 HTTPS 인증서 발급 ==="
# Step 1: HTTP 전용 임시 설정으로 nginx 시작 (certbot HTTP 챌린지용)
sudo tee /etc/nginx/sites-available/kt-demo-alarm > /dev/null <<NGINX_CONF
server {
    listen 80;
    server_name $DOMAIN;
}
NGINX_CONF
sudo ln -sf /etc/nginx/sites-available/kt-demo-alarm /etc/nginx/sites-enabled/kt-demo-alarm
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl enable nginx
sudo systemctl start nginx

# Step 2: certbot이 HTTP 챌린지로 인증서 발급 후 nginx 설정을 HTTPS로 자동 수정
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL"

# Step 3: 레포의 nginx.conf(리버스 프록시 포함)로 교체하고 도메인 치환 후 reload
if [[ -f "nginx/nginx.conf" ]]; then
  sudo cp nginx/nginx.conf /etc/nginx/sites-available/kt-demo-alarm
  sudo sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" /etc/nginx/sites-available/kt-demo-alarm
  sudo nginx -t && sudo systemctl reload nginx
fi

echo ""
echo "✅ 설정 완료!"
echo ""
echo "다음 단계:"
echo "  1. /opt/kt-demo-alarm/.env 파일 생성 (.env.example 참고)"
echo "  2. GitHub Secrets 설정 후 main 브랜치 푸시로 자동 배포"
echo "  3. 배포 확인: curl https://$DOMAIN/"
echo ""
echo "⚠️  docker 그룹 반영을 위해 SSH 재접속 필요:"
echo "  exit → ssh ubuntu@$DOMAIN"
