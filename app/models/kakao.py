"""카카오톡 API 관련 Pydantic 모델들"""
from typing import Optional, List
from pydantic import BaseModel
from .user import User, UserRequest


class KakaoRequest(BaseModel):
    """카카오톡 요청 모델"""
    userRequest: UserRequest


# Event API 모델 정의
class EventData(BaseModel):
    """Event API 데이터 모델"""
    text: Optional[str] = None


class Event(BaseModel):
    """Event API 이벤트 모델"""
    name: str
    data: Optional[EventData] = None


class EventUser(BaseModel):
    """Event API 사용자 모델"""
    type: str  # "botUserKey", "plusfriendUserKey", "appUserId"
    id: str
    properties: Optional[dict] = None


class EventAPIRequest(BaseModel):
    """Event API 요청 모델"""
    event: Event
    user: List[EventUser]
    params: Optional[dict] = None