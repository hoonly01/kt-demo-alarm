"""애플리케이션 설정"""
import os
import logging
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()


class Settings:
    """애플리케이션 설정 클래스"""
    
    # 카카오 API 설정
    KAKAO_REST_API_KEY: str = os.getenv("KAKAO_REST_API_KEY", "")
    BOT_ID: str = os.getenv("BOT_ID", "")
    
    # 데이터베이스 설정
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "kt_demo_alarm.db")
    
    # 애플리케이션 설정
    APP_NAME: str = "KT Demo Alarm API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # 로깅 설정
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # 스케줄링 설정
    CRAWLING_HOUR: int = int(os.getenv("CRAWLING_HOUR", "8"))
    CRAWLING_MINUTE: int = int(os.getenv("CRAWLING_MINUTE", "30"))
    ROUTE_CHECK_HOUR: int = int(os.getenv("ROUTE_CHECK_HOUR", "7"))
    ROUTE_CHECK_MINUTE: int = int(os.getenv("ROUTE_CHECK_MINUTE", "0"))
    
    # 알림 설정
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "100"))
    NOTIFICATION_TIMEOUT: float = float(os.getenv("NOTIFICATION_TIMEOUT", "10.0"))
    
    # 경로 감지 설정
    ROUTE_THRESHOLD_METERS: int = int(os.getenv("ROUTE_THRESHOLD_METERS", "500"))


def setup_logging():
    """로깅 설정"""
    logging.basicConfig(
        level=getattr(logging, Settings.LOG_LEVEL.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


# 전역 설정 인스턴스
settings = Settings()