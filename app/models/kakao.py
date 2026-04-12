"""카카오톡 API 관련 Pydantic 모델들"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from .user import User, UserRequest


class KakaoRequest(BaseModel):
    """카카오톡 요청 모델"""
    userRequest: UserRequest


# Event API 모델 정의
class Event(BaseModel):
    """Event API 이벤트 모델"""
    name: str
    data: Optional[Dict[str, Any]] = None  # 카카오 Event API 명세에 따른 범용 JSON 객체


class EventUser(BaseModel):
    """Event API 사용자 모델"""
    type: str  # "botUserKey", "plusfriendUserKey", "appUserId"
    id: str
    properties: Optional[dict] = None


class EventAPIRequest(BaseModel):
    """Event API 요청 모델 (v2)

    botId는 URL 경로에 포함되므로 body에서 제거.
    user는 최대 100명까지 배열로 전송 가능.
    """
    event: Event
    user: List[EventUser]
    params: Optional[dict] = None