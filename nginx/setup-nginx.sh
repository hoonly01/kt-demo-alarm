#!/bin/bash

###############################################################################
# Nginx 설치 및 설정 스크립트
#
# 용도: EC2에 Nginx를 설치하고 리버스 프록시 설정
#
# 실행 방법:
#   chmod +x nginx/setup-nginx.sh
#   ./nginx/setup-nginx.sh
###############################################################################

set -e

echo "========================================"
echo "  Nginx 설치 및 설정"
echo "========================================"

# 1. Nginx 설치
echo "[1/4] Nginx 설치..."
sudo apt-get update
sudo apt-get install -y nginx

# 2. 설정 파일 복사
echo "[2/4] Nginx 설정 파일 복사..."
sudo cp nginx/nginx.conf /etc/nginx/sites-available/kt-demo-alarm

# 3. 심볼릭 링크 생성
echo "[3/4] 사이트 활성화..."
sudo ln -sf /etc/nginx/sites-available/kt-demo-alarm /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 4. 설정 테스트 및 재시작
echo "[4/4] Nginx 재시작..."
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx

echo ""
echo "✅ Nginx 설정 완료!"
echo ""
echo "다음 단계:"
echo "1. FastAPI 애플리케이션 시작: cd ~/kt-demo-alarm && docker compose up -d"
echo "2. Nginx 상태 확인: sudo systemctl status nginx"
echo "3. 브라우저에서 접속: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)/"
echo ""
echo "SSL 인증서 설정 (선택):"
echo "  sudo apt-get install -y certbot python3-certbot-nginx"
echo "  sudo certbot --nginx -d your-domain.com"
echo ""
