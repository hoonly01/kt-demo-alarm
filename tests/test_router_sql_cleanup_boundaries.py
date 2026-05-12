"""라우터 SQL cleanup 후 endpoint 계약 통합 테스트."""
import sqlite3


API_HEADERS = {"x-api-key": "test-api-key"}


def test_users_list_endpoint_preserves_route_info_contract(test_client, clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    conn.execute(
        """
        INSERT INTO users (
            bot_user_key, first_message_at, last_message_at, message_count,
            location, active, departure_name, departure_address,
            departure_x, departure_y, arrival_name, arrival_address,
            arrival_x, arrival_y, route_updated_at, marked_bus, language
        )
        VALUES (?, ?, ?, 3, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "bot-with-route",
            "2026-05-12T08:00:00",
            "2026-05-12T09:00:00",
            "종로",
            "출발지",
            "서울 출발 주소",
            127.01,
            37.51,
            "도착지",
            "서울 도착 주소",
            126.98,
            37.56,
            "2026-05-12T09:05:00",
            "7016",
            "ko",
        ),
    )
    conn.execute(
        """
        INSERT INTO users (
            bot_user_key, first_message_at, last_message_at, message_count,
            location, active, marked_bus, language
        )
        VALUES (?, ?, ?, 1, ?, 0, ?, ?)
        """,
        (
            "bot-no-route",
            "2026-05-12T07:00:00",
            "2026-05-12T10:00:00",
            "광화문",
            "162",
            "en",
        ),
    )
    conn.commit()
    conn.close()

    response = test_client.get("/users", headers=API_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["users"][0]["bot_user_key"] == "bot-no-route"
    assert body["users"][0]["route_info"] is None
    assert body["users"][1]["bot_user_key"] == "bot-with-route"
    assert body["users"][1]["route_info"] == {
        "departure": {
            "name": "출발지",
            "address": "서울 출발 주소",
            "x": 127.01,
            "y": 37.51,
        },
        "arrival": {
            "name": "도착지",
            "address": "서울 도착 주소",
            "x": 126.98,
            "y": 37.56,
        },
        "updated_at": "2026-05-12T09:05:00",
    }


def test_kakao_chat_uses_identity_boundary_for_plusfriend_user(test_client, clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    conn.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at,
            last_message_at, message_count, active
        )
        VALUES (?, ?, ?, ?, 1, 1)
        """,
        ("old-bot", "pf-chat", "2026-05-12T08:00:00", "2026-05-12T08:00:00"),
    )
    conn.commit()
    conn.close()

    response = test_client.post(
        "/kakao/chat",
        json={
            "userRequest": {
                "utterance": "안녕",
                "user": {
                    "id": "new-bot",
                    "type": "botUserKey",
                    "properties": {"plusfriendUserKey": "pf-chat"},
                },
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "2.0"
    assert body["template"]["quickReplies"][0]["messageText"] == "이동 경로를 등록하고 싶어요"

    conn = sqlite3.connect(clean_test_db)
    row = conn.execute(
        """
        SELECT bot_user_key, plusfriend_user_key, message_count, active
        FROM users
        WHERE plusfriend_user_key = ?
        """,
        ("pf-chat",),
    ).fetchone()
    conn.close()

    assert row == ("new-bot", "pf-chat", 2, 1)


def test_kakao_channel_webhook_uses_identity_boundary_for_open_id(test_client, clean_test_db):
    response = test_client.post(
        "/kakao/webhook/channel",
        json={"event": "added", "id": "open-webhook"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "processed_event": "added",
        "open_id": "open-webhook",
    }

    conn = sqlite3.connect(clean_test_db)
    active_row = conn.execute(
        "SELECT open_id, active FROM users WHERE open_id = ?",
        ("open-webhook",),
    ).fetchone()
    conn.close()
    assert active_row == ("open-webhook", 1)

    response = test_client.post(
        "/kakao/webhook/channel",
        json={"event": "blocked", "id": "open-webhook"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "processed_event": "blocked",
        "open_id": "open-webhook",
    }

    conn = sqlite3.connect(clean_test_db)
    inactive_row = conn.execute(
        "SELECT open_id, active FROM users WHERE open_id = ?",
        ("open-webhook",),
    ).fetchone()
    conn.close()
    assert inactive_row == ("open-webhook", 0)
