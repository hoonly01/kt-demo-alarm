"""사용자 관련 Pydantic 모델들"""
from typing import Optional, List
from pydantic import BaseModel


class User(BaseModel):
    """카카오톡 사용자 모델"""
    id: str  # botUserKey. 카카오 문서에서는 plusfriendUserKey 또는 botUserKey 라고 함
    type: str
    properties: dict = {}


class UserRequest(BaseModel):
    """카카오톡 사용자 요청 모델"""
    user: User
    utterance: str  # 사용자가 입력한 실제 메시지


class UserPreferences(BaseModel):
    """사용자 설정 모델"""
    location: Optional[str] = None
    categories: Optional[List[str]] = None
    preferences: Optional[dict] = None


class InitialSetupRequest(BaseModel):
    """초기 설정 요청 모델"""
    bot_user_key: str  # 사용자 식별 키 (필수)
    departure: Optional[str] = None
    arrival: Optional[str] = None
    marked_bus: Optional[str] = None
    language: Optional[str] = None
    userRequest: Optional[UserRequest] = None  # 카카오톡 요청 시에만 사용