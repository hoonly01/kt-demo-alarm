from app.services.notification_service import NotificationService


def test_notification_uses_attendees_not_description():
    message = NotificationService._format_event_message(
        [
            {
                "location": "교보빌딩 남측 -> 청진공원",
                "start_date": "2026-05-15 11:00:00",
                "end_date": "2026-05-15 13:00:00",
                "description": "legacy description must not appear",
                "attendees": "100명",
            }
        ]
    )

    assert "신고 인원 : 100명" in message
    assert "legacy description" not in message


def test_notification_attendees_default_is_unknown():
    message = NotificationService._format_zone_message(
        "광화문광장",
        [
            {
                "location": "송현공원 앞",
                "start_date": "2026-05-15 19:00:00",
                "end_date": "2026-05-15 20:30:00",
                "attendees": "",
            }
        ],
    )

    assert "신고 인원 : 미상" in message
