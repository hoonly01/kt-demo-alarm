"""애플리케이션 설정"""
import logging
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """애플리케이션 설정 클래스"""

    # --- Kakao API ---
    KAKAO_REST_API_KEY: str = ""
    BOT_ID: str = ""

    # --- Block IDs for Kakao Chatbot ---
    ALARM_SAVE_BLOCK_ID: Optional[str] = None
    FAVORITE_ZONE_SAVE_BLOCK_ID: Optional[str] = None
    ROUTE_SETUP_BLOCK_ID: Optional[str] = None
    ROUTE_DELETE_BLOCK_ID: Optional[str] = None

    # --- TMAP API ---
    TMAP_APP_KEY: str = ""

    # --- AI ---
    GEMINI_API_KEY: str = ""
    WORKS_AI_API_KEY: Optional[str] = None
    WORKS_AI_BASE_URL: str = "https://api.bizrouter.ai/v1"
    WORKS_AI_MODEL: str = "google/gemini-3.1-pro-preview"

    # --- Bus API ---
    SEOUL_BUS_API_KEY: str = ""
    RENDER_EXTERNAL_URL: str = "http://localhost:8000"

    # --- Security ---
    API_KEY: str = ""
    ADMIN_USER: Optional[str] = None
    ADMIN_PASS: Optional[str] = None

    # --- Server ---
    APP_NAME: str = "KT Demo Alarm API"
    APP_VERSION: str = "1.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # --- Database ---
    DATABASE_PATH: str = "kt_demo_alarm.db"

    # --- File Paths ---
    CACHE_FILE: str = "topis_cache/topis_cache.json"
    ATTACHMENT_FOLDER: str = "topis_attachments"

    # --- Scheduling ---
    CRAWLING_HOUR: int = 7
    CRAWLING_MINUTE: int = 0
    ROUTE_CHECK_HOUR: int = 8
    ROUTE_CHECK_MINUTE: int = 0
    ZONE_CHECK_HOUR: int = 8
    ZONE_CHECK_MINUTE: int = 0

    # --- Notification ---
    BATCH_SIZE: int = 100
    NOTIFICATION_TIMEOUT: float = 10.0

    # --- Geo/Route ---
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
