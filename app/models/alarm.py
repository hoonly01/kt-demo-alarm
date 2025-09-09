"""알림 관련 Pydantic 모델들"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class AlarmRequest(BaseModel):
    """개별 알림 요청 모델"""
    user_id: str
    event_name: str  # 카카오 Event API용 이벤트 이름
    data: Dict[str, Any]  # 카카오 Event API용 데이터
    message: Optional[str] = None  # 호환성을 위해 선택적 필드로 유지
    location: Optional[str] = None


class FilteredAlarmRequest(BaseModel):
    """필터링된 알림 요청 모델"""
    message: str
    location_filter: Optional[str] = None
    category_filter: Optional[List[str]] = None
    user_filter: Optional[List[str]] = None  # 특정 사용자들만