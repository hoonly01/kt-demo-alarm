"""알림 관련 Pydantic 모델들"""
from typing import Optional, List
from pydantic import BaseModel


class AlarmRequest(BaseModel):
    """개별 알림 요청 모델"""
    user_id: str
    message: str
    location: Optional[str] = None


class FilteredAlarmRequest(BaseModel):
    """필터링된 알림 요청 모델"""
    message: str
    location_filter: Optional[str] = None
    category_filter: Optional[List[str]] = None
    user_filter: Optional[List[str]] = None  # 특정 사용자들만