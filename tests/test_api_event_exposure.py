import pytest

from app.config.settings import settings


@pytest.mark.usefixtures("clean_test_db")
def test_events_api_exposes_product_fields_and_hides_source_envelope(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    payload = {
        "title": "SMPA 집회",
        "description": "future summary",
        "attendees": "100명",
        "police_station": "종로",
        "location_name": "교보빌딩 남측 -> 청진공원",
        "location_address": "서울특별시 종로구 종로1가",
        "latitude": 37.5705,
        "longitude": 126.977,
        "start_date": "2026-05-15T11:00:00",
        "end_date": "2026-05-15T13:00:00",
        "category": "protest",
        "severity_level": 2,
    }

    response = test_client.post("/events", json=payload, headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["attendees"] == "100명"
    assert body["police_station"] == "종로"
    assert "source_record_hash" not in body
    assert "source_payload_hash" not in body
