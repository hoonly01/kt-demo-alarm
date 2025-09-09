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
    botId: str  # 봇 ID (필수)
    event: EventData  # 이벤트 데이터 (EventData로 수정)
    user: EventUser  # 단일 사용자 (List가 아닌 단일 객체)
    params: Optional[dict] = None