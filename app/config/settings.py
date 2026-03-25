"""애플리케이션 설정"""
import logging
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """애플리케이션 설정 클래스"""
    
    # --- Kakao API Configuration ---
    KAKAO_REST_API_KEY: str = ""
    BOT_ID: str = ""
    KAKAO_BOT_API_URL: str = "https://bot-api.kakao.com/v1/bots/message/send"
    # 알람 On/Off ListCard에서 사용할 저장 스킬 블록 ID (카카오 챗봇 관리자센터에서 확인)
    ALARM_SAVE_BLOCK_ID: Optional[str] = None

    # --- TMAP API Configuration ---
    TMAP_APP_KEY: str = ""

    # Gemini API 설정 (버스 통제 알림용)
    GEMINI_API_KEY: str = ""

    # --- Bus API Configuration ---
    SEOUL_BUS_API_KEY: str = ""
    RENDER_EXTERNAL_URL: str = "http://localhost:8000"
    
    # --- Security Configuration ---
    API_KEY: str = ""
    
    # 어드민 대시보드 로그인 정보
    ADMIN_USER: Optional[str] = None
    ADMIN_PASS: Optional[str] = None
    
    # --- Server Configuration ---
    APP_NAME: str = "KT Demo Alarm API"
    APP_VERSION: str = "1.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # --- Database Configuration ---
    DATABASE_PATH: str = "kt_demo_alarm.db"
    
    # --- Scheduling Configuration ---
    CRAWLING_HOUR: int = 8
    CRAWLING_MINUTE: int = 30
    ROUTE_CHECK_HOUR: int = 7
    ROUTE_CHECK_MINUTE: int = 0
    
    # --- Notification Configuration ---
    BATCH_SIZE: int = 100
    NOTIFICATION_TIMEOUT: float = 10.0
    
    # --- Geo/Route Configuration ---
    ROUTE_THRESHOLD_METERS: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# 전역 설정 인스턴스
settings = Settings()


def setup_logging():
    """로깅 설정"""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )