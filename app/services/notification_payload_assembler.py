"""알림 본문 payload 조립기"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.models.event import EventResponse


@dataclass(frozen=True)
class NotificationEventPayload:
    """알림 본문 계약용 이벤트 DTO."""

    location: str
    description: str
    attendees: str
    start_date: Any
    end_date: Any
    image_path: Optional[str] = None


class NotificationPayloadAssembler:
    """도메인 이벤트를 알림 본문 계약 DTO로 번역한다."""

    @staticmethod
    def _display_text(value: Any, fallback: str = "미상") -> str:
        """사용자 표시용 문자열을 공백 제거 후 fallback 과 함께 정규화한다."""
        if value is None:
            return fallback

        value_text = str(value).strip()
        return value_text or fallback

    @staticmethod
    def _display_attendees(value: Any) -> str:
        """신고 인원 표시 문자열을 정규화한다."""
        attendees = NotificationPayloadAssembler._display_text(value)
        if attendees != "미상" and attendees.isdigit() and not attendees.endswith("명"):
            return f"{attendees}명"
        return attendees

    @staticmethod
    def _image_path_or_none(value: Any) -> Optional[str]:
        """이미지 경로를 Optional[str]로 정규화한다."""
        image_path = NotificationPayloadAssembler._display_text(value, fallback="")
        return image_path or None

    @staticmethod
    def event_payload_from_response(event: EventResponse) -> NotificationEventPayload:
        """EventResponse를 알림 본문 계약 DTO로 변환한다."""
        return NotificationEventPayload(
            location=NotificationPayloadAssembler._display_text(event.location_name),
            description=NotificationPayloadAssembler._display_text(event.description),
            attendees=NotificationPayloadAssembler._display_attendees(event.attendees),
            start_date=event.start_date,
            end_date=event.end_date,
            image_path=NotificationPayloadAssembler._image_path_or_none(event.image_path),
        )

    @staticmethod
    def event_payloads_from_responses(events: List[EventResponse]) -> List[NotificationEventPayload]:
        """EventResponse 목록을 알림 본문 계약 DTO 목록으로 변환한다."""
        return [NotificationPayloadAssembler.event_payload_from_response(event) for event in events]

    @staticmethod
    def event_payload_from_row(event_row: Dict[str, Any]) -> NotificationEventPayload:
        """DB row dict를 알림 본문 계약 DTO로 변환한다."""
        return NotificationEventPayload(
            location=NotificationPayloadAssembler._display_text(event_row["location_name"]),
            description=NotificationPayloadAssembler._display_text(event_row.get("description")),
            attendees=NotificationPayloadAssembler._display_attendees(event_row.get("attendees")),
            start_date=event_row["start_date"],
            end_date=event_row.get("end_date"),
            image_path=NotificationPayloadAssembler._image_path_or_none(event_row.get("image_path")),
        )

    @staticmethod
    def event_payloads_from_rows(events: List[Dict[str, Any]]) -> List[NotificationEventPayload]:
        """DB row dict 목록을 알림 본문 계약 DTO 목록으로 변환한다."""
        return [NotificationPayloadAssembler.event_payload_from_row(event) for event in events]
