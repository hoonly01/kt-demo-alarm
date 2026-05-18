"""사용자 관련 Pydantic 모델들"""
from pydantic import BaseModel, Field


class User(BaseModel):
    """카카오톡 사용자 모델"""
    id: str  # botUserKey. 카카오 문서에서는 plusfriendUserKey 또는 botUserKey 라고 함
    type: str
    properties: dict[str, object] = Field(default_factory=dict)


class UserRequest(BaseModel):
    """카카오톡 사용자 요청 모델"""
    user: User
    utterance: str = ""  # 사용자가 입력한 실제 메시지 (Event 콜백 시 빈 값)


class UserPreferences(BaseModel):
    """사용자 설정 모델"""
    location: str | None = None
    categories: list[str] | None = None
    preferences: dict[str, object] | None = None
    marked_bus: str | None = None
    language: str | None = None


class InitialSetupRequest(BaseModel):
    """초기 설정 요청 모델"""
    bot_user_key: str  # 사용자 식별 키 (필수)
    departure: str | None = None
    arrival: str | None = None
    marked_bus: str | None = None
    language: str | None = None
    userRequest: UserRequest | None = None  # 카카오톡 요청 시에만 사용
