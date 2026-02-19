"""애플리케이션 설정"""
import os
import logging
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()


class Settings:
    """애플리케이션 설정 클래스"""
    
    # --- Kakao API Configuration ---
    KAKAO_REST_API_KEY: str = os.getenv("KAKAO_REST_API_KEY", "")
    BOT_ID: str = os.getenv("BOT_ID", "")
    KAKAO_BOT_API_URL: str = os.getenv("KAKAO_BOT_API_URL", "https://bot-api.kakao.com/v1/bots/message/send")

    # Gemini API 설정 (버스 통제 알림용)
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # --- Security Configuration ---
    API_KEY: str = os.getenv("API_KEY", "")
    
    # --- Server Configuration ---
    APP_NAME: str = "KT Demo Alarm API"
    APP_VERSION: str = "1.0.0"
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # --- Database Configuration ---
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "kt_demo_alarm.db")
    
    # --- Scheduling Configuration ---
    CRAWLING_HOUR: int = int(os.getenv("CRAWLING_HOUR", "8"))
    CRAWLING_MINUTE: int = int(os.getenv("CRAWLING_MINUTE", "30"))
    ROUTE_CHECK_HOUR: int = int(os.getenv("ROUTE_CHECK_HOUR", "7"))
    ROUTE_CHECK_MINUTE: int = int(os.getenv("ROUTE_CHECK_MINUTE", "0"))
    
    # --- Notification Configuration ---
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "100"))
    NOTIFICATION_TIMEOUT: float = float(os.getenv("NOTIFICATION_TIMEOUT", "10.0"))
    
    # --- Geo/Route Configuration ---
    ROUTE_THRESHOLD_METERS: int = int(os.getenv("ROUTE_THRESHOLD_METERS", "500"))


# 전역 설정 인스턴스
settings = Settings()


def setup_logging():
    """로깅 설정"""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )