"""인증 및 보안 관련 서비스"""
from fastapi import Header, HTTPException, status
from app.config.settings import settings

async def verify_api_key(x_api_key: str = Header(..., description="API Access Key")):
    """
    API 키 검증 의존성 함수
    
    Args:
        x_api_key (str): HTTP 헤더의 X-API-Key 값
        
    Raises:
        HTTPException: 
            - 500: 서버에 API Key가 설정되지 않은 경우
            - 401: API Key가 유효하지 않은 경우
    """
    if not settings.API_KEY:
        # 보안을 위해 서버 측 설정이 누락된 경우 모든 요청 차단
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server Authorization not configured"
        )
    
    if x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    
    return x_api_key
