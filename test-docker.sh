#!/bin/bash
# Docker 테스트 스크립트

set -e

echo "========================================="
echo "  🐳 Docker 테스트 시작"
echo "========================================="
echo ""

# 1. 준비
echo "[1/6] 환경 확인..."
if [ ! -f .env ]; then
    echo "❌ .env 파일이 없습니다!"
    echo "   다음 명령어로 생성하세요:"
    echo "   cp .env.production.example .env"
    exit 1
fi
echo "✅ .env 파일 존재"

# 2. 디렉토리 생성
echo ""
echo "[2/6] 데이터 디렉토리 생성..."
mkdir -p data logs
echo "✅ data, logs 디렉토리 생성 완료"

# 3. 기존 컨테이너 정리
echo ""
echo "[3/6] 기존 컨테이너 정리..."
docker compose down 2>/dev/null || true
echo "✅ 정리 완료"

# 4. 빌드
echo ""
echo "[4/6] Docker 이미지 빌드..."
docker compose build

# 5. 시작
echo ""
echo "[5/6] 컨테이너 시작..."
docker compose up -d

# 6. 대기 및 헬스체크
echo ""
echo "[6/6] 서버 시작 대기..."
sleep 10

echo ""
echo "헬스체크 중..."
MAX_RETRIES=10
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f http://localhost:8000/ > /dev/null 2>&1; then
        echo "✅ 헬스체크 성공!"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "⏳ 대기 중... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ 헬스체크 실패!"
    echo ""
    echo "로그 확인:"
    docker compose logs
    exit 1
fi

# 상태 출력
echo ""
echo "========================================="
echo "  ✅ Docker 테스트 완료!"
echo "========================================="
echo ""
echo "컨테이너 상태:"
docker compose ps
echo ""
echo "유용한 명령어:"
echo "  로그 보기:     docker compose logs -f"
echo "  상태 확인:     docker compose ps"
echo "  재시작:        docker compose restart"
echo "  중지:          docker compose down"
echo ""
echo "API 테스트:"
echo "  curl http://localhost:8000/"
echo "  curl http://localhost:8000/users"
echo "  curl http://localhost:8000/events/upcoming"
echo ""
