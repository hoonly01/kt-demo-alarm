from app.services.notification_payload_assembler import NotificationEventPayload, NotificationPayloadAssembler
from app.services.notification_service import NotificationService


def test_notification_uses_description_and_attendees_in_distinct_lines():
    message = NotificationService.format_event_message(
        [
            NotificationEventPayload(
                location="교보빌딩 남측 -> 청진공원",
                start_date="2026-05-15 11:00:00",
                end_date="2026-05-15 13:00:00",
                description="도심 행진",
                attendees="100명",
            )
        ]
    )

    assert "상세 내용 : 도심 행진" in message
    assert "신고 인원 : 100명" in message


def test_notification_description_and_attendees_default_to_unknown():
    event = NotificationPayloadAssembler.event_payload_from_row(
        {
            "location_name": "송현공원 앞",
            "start_date": "2026-05-15 19:00:00",
            "end_date": "2026-05-15 20:30:00",
            "description": "",
            "attendees": "",
        }
    )
    message = NotificationService.format_zone_message(
        "광화문광장",
        [event],
    )

    assert "상세 내용 : 미상" in message
    assert "신고 인원 : 미상" in message


def test_notification_image_url_normalizes_leading_slash(settings_overrides):
    settings_overrides(RENDER_EXTERNAL_URL="http://localhost:8000")

    url = NotificationService.first_event_image_url(
        [
            NotificationEventPayload(
                location="광화문광장",
                start_date="2026-05-15 19:00:00",
                end_date="2026-05-15 20:30:00",
                description="도심 행진",
                attendees="50명",
                image_path="/attachments/protest_images/demo.png",
            )
        ]
    )

    assert url == "http://localhost:8000/attachments/protest_images/demo.png"
