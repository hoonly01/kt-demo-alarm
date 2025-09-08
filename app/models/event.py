"""집회 관련 Pydantic 모델들"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    """집회 생성 요청 모델"""
    title: str = Field(..., description="집회 제목")
    description: Optional[str] = Field(None, description="집회 설명")
    location_name: str = Field(..., description="집회 장소명")
    location_address: Optional[str] = Field(None, description="집회 주소")
    latitude: float = Field(..., description="위도")
    longitude: float = Field(..., description="경도")
    start_date: datetime = Field(..., description="시작 일시")
    end_date: Optional[datetime] = Field(None, description="종료 일시")
    category: Optional[str] = Field(None, description="집회 카테고리")
    severity_level: int = Field(1, description="심각도 (1: 낮음, 2: 보통, 3: 높음)")


class EventResponse(BaseModel):
    """집회 응답 모델"""
    id: int
    title: str
    description: Optional[str]
    location_name: str
    location_address: Optional[str]
    latitude: float
    longitude: float
    start_date: datetime
    end_date: Optional[datetime]
    category: Optional[str]
    severity_level: int
    status: str
    created_at: datetime
    updated_at: datetime


class RouteEventCheck(BaseModel):
    """경로 집회 확인 결과 모델"""
    user_id: str
    events_found: List[EventResponse]
    route_info: dict
    total_events: int