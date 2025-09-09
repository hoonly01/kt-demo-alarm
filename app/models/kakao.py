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
    """Event API 요청 모델"""
    botId: str  # 봇 ID (필수)
    event: Event  # 이벤트 (Event 모델 사용)
    user: EventUser  # 단일 사용자 (List가 아닌 단일 객체)
    params: Optional[dict] = None