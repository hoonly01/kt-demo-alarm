"""Response models for API documentation"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class AlarmTaskProgress(BaseModel):
    """알림 작업 진행 상황"""
    total_recipients: int = Field(..., description="총 대상자 수")
    successful_sends: int = Field(..., description="성공 발송 수")
    failed_sends: int = Field(..., description="실패 발송 수") 
    success_rate: float = Field(..., description="성공률 (백분율)")


class AlarmTaskTimestamps(BaseModel):
    """알림 작업 시간 정보"""
    created_at: str = Field(..., description="작업 생성 시간 (ISO format)")
    updated_at: str = Field(..., description="최종 업데이트 시간 (ISO format)")
    completed_at: Optional[str] = Field(None, description="완료 시간 (ISO format)")


class AlarmStatusResponse(BaseModel):
    """알림 상태 조회 응답"""
    task_id: str = Field(..., description="작업 고유 ID")
    status: str = Field(..., description="작업 상태", examples=["pending", "processing", "completed", "failed", "partial"])
    alarm_type: str = Field(..., description="알림 타입", examples=["individual", "bulk", "filtered"])
    progress: AlarmTaskProgress = Field(..., description="진행 상황")
    timestamps: AlarmTaskTimestamps = Field(..., description="시간 정보")
    error_messages: List[str] = Field([], description="오류 메시지 목록")
    event_id: Optional[int] = Field(None, description="연관된 이벤트 ID")


class AlarmTaskSummary(BaseModel):
    """알림 작업 요약"""
    task_id: str = Field(..., description="작업 고유 ID")
    alarm_type: str = Field(..., description="알림 타입")
    status: str = Field(..., description="작업 상태")
    total_recipients: int = Field(..., description="총 대상자 수")
    successful_sends: Optional[int] = Field(None, description="성공 발송 수")
    failed_sends: Optional[int] = Field(None, description="실패 발송 수")
    success_rate: float = Field(..., description="성공률 (백분율)")
    event_id: Optional[int] = Field(None, description="연관된 이벤트 ID")
    created_at: str = Field(..., description="작업 생성 시간")
    updated_at: str = Field(..., description="최종 업데이트 시간")
    completed_at: Optional[str] = Field(None, description="완료 시간")


class AlarmTaskListResponse(BaseModel):
    """알림 작업 목록 응답"""
    tasks: List[AlarmTaskSummary] = Field(..., description="알림 작업 목록")
    total: int = Field(..., description="총 작업 수")
    limit: int = Field(..., description="조회 제한")


class AlarmSendResponse(BaseModel):
    """알림 전송 응답"""
    message: str = Field(..., description="결과 메시지")
    task_id: str = Field(..., description="생성된 작업 ID")
    user_id: str = Field(..., description="대상 사용자 ID")
    event_name: str = Field(..., description="이벤트 이름")


class BulkAlarmSendResponse(BaseModel):
    """대량 알림 전송 응답"""
    message: str = Field(..., description="결과 메시지")
    task_id: str = Field(..., description="생성된 작업 ID")
    target_users: int = Field(..., description="대상 사용자 수")
    event_name: str = Field(..., description="이벤트 이름")


class FilteredAlarmSendResponse(BaseModel):
    """필터링된 알림 전송 응답"""
    message: str = Field(..., description="결과 메시지") 
    task_id: str = Field(..., description="생성된 작업 ID")
    filter_applied: Dict[str, Any] = Field(..., description="적용된 필터")
    target_users: int = Field(..., description="대상 사용자 수")
    event_name: str = Field(..., description="이벤트 이름")


class CleanupResponse(BaseModel):
    """정리 작업 응답"""
    message: str = Field(..., description="결과 메시지")
    deleted_count: int = Field(..., description="삭제된 작업 수")
    retention_days: int = Field(..., description="보관 기간 (일)")


class ErrorResponse(BaseModel):
    """에러 응답"""
    detail: str = Field(..., description="에러 상세 메시지")


class HealthCheckResponse(BaseModel):
    """헬스체크 응답"""
    message: str = Field(..., description="상태 메시지")
    version: str = Field(..., description="애플리케이션 버전")
    status: str = Field(..., description="헬스 상태", examples=["healthy", "unhealthy"])