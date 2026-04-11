#!/bin/bash
# EC2 초기 설정 스크립트 (Amazon Linux 2023 / Ubuntu 22.04+)
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

# 간단한 FQDN 검증 (영문/숫자/하이픈 라벨 + 점)
if ! [[ "$DOMAIN" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]; then
  echo "❌ 유효하지 않은 도메인 형식: $DOMAIN"
  exit 1
fi

# OS 감지
if [ -f /etc/os-release ]; then
  . /etc/os-release
  OS_ID="${ID:-unknown}"
else
  OS_ID="unknown"
fi

echo "=== [1/5] 시스템 업데이트 (OS: $OS_ID) ==="
if [[ "$OS_ID" == "amzn" ]]; then
  sudo dnf update -y
  sudo timedatectl set-timezone Asia/Seoul
else
  sudo apt-get update -y
  sudo apt-get upgrade -y
  sudo timedatectl set-timezone Asia/Seoul
fi

echo "=== [2/5] 기본 패키지 + Nginx + Certbot 설치 ==="
if [[ "$OS_ID" == "amzn" ]]; then
  # curl-minimal이 이미 설치되어 있어 curl 풀버전과 충돌하므로 제외
  sudo dnf install -y git vim jq nginx certbot python3-certbot-nginx
else
  sudo apt-get install -y curl git vim jq nginx certbot python3-certbot-nginx
fi

echo "=== [3/5] Docker 설치 ==="
if ! command -v docker &> /dev/null; then
  if [[ "$OS_ID" == "amzn" ]]; then
    sudo dnf install -y docker
  else
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sudo sh /tmp/get-docker.sh
    rm /tmp/get-docker.sh
  fi
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable docker
sudo systemctl start docker

echo "=== [4/5] 애플리케이션 디렉토리 준비 ==="
sudo mkdir -p /opt/kt-demo-alarm/{data,logs,topis_cache,topis_attachments}
sudo chown -R "$USER":"$USER" /opt/kt-demo-alarm

echo "=== [5/5] Nginx 설정 및 HTTPS 인증서 발급 ==="
# Step 1: HTTP 전용 임시 설정으로 nginx 시작 (certbot HTTP 챌린지용)
# Amazon Linux 2023은 conf.d만 사용; Ubuntu는 sites-available → sites-enabled 구조
if [[ "$OS_ID" == "amzn" ]]; then
  NGINX_SITE_CONF="/etc/nginx/conf.d/kt-demo-alarm.conf"
else
  NGINX_SITE_CONF="/etc/nginx/sites-available/kt-demo-alarm"
fi

sudo tee "${NGINX_SITE_CONF}" > /dev/null <<NGINX_CONF
server {
    listen 80;
    server_name $DOMAIN;
}
NGINX_CONF

if [[ "$OS_ID" != "amzn" ]]; then
  sudo ln -sf /etc/nginx/sites-available/kt-demo-alarm /etc/nginx/sites-enabled/kt-demo-alarm
  sudo rm -f /etc/nginx/sites-enabled/default
fi

sudo systemctl enable nginx
sudo systemctl start nginx

# Step 2: certbot이 HTTP 챌린지로 인증서 발급 후 nginx 설정을 HTTPS로 자동 수정
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL"

# Step 3: 레포의 nginx.conf(리버스 프록시 포함)로 교체하고 도메인 치환 후 reload
if [[ ! -f "$HOME/nginx/nginx.conf" ]]; then
  echo "❌ nginx/nginx.conf 파일을 찾을 수 없습니다."
  echo "   스크립트 실행 전에 nginx/ 디렉토리를 EC2로 전송했는지 확인하세요:"
  echo "   scp -r nginx ${USER}@<EC2_IP>:~/"
  exit 1
fi
# sed replacement 안전 처리 (\, &, | 이스케이프)
ESCAPED_DOMAIN="${DOMAIN//\\/\\\\}"
ESCAPED_DOMAIN="${ESCAPED_DOMAIN//&/\\&}"
ESCAPED_DOMAIN="${ESCAPED_DOMAIN//|/\\|}"
sudo cp "$HOME/nginx/nginx.conf" "${NGINX_SITE_CONF}"
sudo sed -i "s|DOMAIN_PLACEHOLDER|${ESCAPED_DOMAIN}|g" "${NGINX_SITE_CONF}"
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "✅ 설정 완료!"
echo ""
echo "다음 단계:"
echo "  1. /opt/kt-demo-alarm/.env 파일 생성 (.env.example 참고)"
echo "  2. GitHub Secrets의 EC2_USERNAME을 ${USER}로 확인"
echo "  3. GitHub main 브랜치 push로 자동 배포"
echo "  4. 배포 확인: curl https://$DOMAIN/"
echo ""
echo "⚠️  docker 그룹 반영을 위해 SSH 재접속 필요:"
echo "  exit → ssh ${USER}@<EC2_HOST_또는_IP>"
