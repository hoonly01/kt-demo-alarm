from datetime import datetime
from collections.abc import Mapping
from typing import override

import httpx
import pytest

from app.config.settings import settings
from app.services.crawling.smpa_coordinates import (
    GeocodeResult,
    build_geocode_query_candidates,
    choose_representative_coordinate,
    is_jongno_result,
    select_coordinate_for_event,
)
from app.services.crawling.smpa_parser import ParsedSmpaEvent

TEST_KAKAO_API_KEY = "test-api-key"
SMPA_TEST_SOURCE_URL = "https://example.test/smpa"
SMPA_TEST_START_AT = datetime(2026, 5, 15, 9, 0)
SMPA_TEST_END_AT = datetime(2026, 5, 15, 10, 0)


class KakaoKeywordTransport(httpx.AsyncBaseTransport):
    """실제 httpx.AsyncClient 경로로 Kakao keyword 응답을 재현하는 인프로세스 전송 계층."""

    def __init__(self, documents_by_query: Mapping[str, list[dict[str, str]]]) -> None:
        self._documents_by_query: Mapping[str, list[dict[str, str]]] = documents_by_query
        self.requested_queries: list[str] = []

    @override
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        self.requested_queries.append(query)
        return httpx.Response(
            200,
            json={"documents": self._documents_by_query.get(query, [])},
            request=request,
        )


def result(query: str, address: str, latitude: float, longitude: float) -> GeocodeResult:
    return GeocodeResult(
        query=query,
        name=query,
        address=address,
        latitude=latitude,
        longitude=longitude,
    )


def smpa_event_for_endpoint(endpoint: str) -> ParsedSmpaEvent:
    return ParsedSmpaEvent(
        title=f"SMPA 집회 - {endpoint}",
        raw_location=endpoint,
        endpoint_candidates=(endpoint,),
        attendees="10명",
        police_station="종로서",
        start_date=SMPA_TEST_START_AT,
        end_date=SMPA_TEST_END_AT,
        source_id="board-1",
        source_url=SMPA_TEST_SOURCE_URL,
    )


def test_selects_start_when_both_endpoints_are_in_jongno():
    start = result("교보빌딩 남측", "서울특별시 종로구 종로1가", 37.5705, 126.9770)
    end = result("청진공원", "서울 종로구 청진동", 37.5710, 126.9800)

    selected = choose_representative_coordinate("교보빌딩 남측 -> 청진공원", [start, end])

    assert selected.selected_name == "교보빌딩 남측"
    assert selected.latitude == start.latitude


def test_selects_only_jongno_endpoint_when_one_endpoint_is_in_jongno():
    start = result("신촌역", "서울특별시 서대문구 신촌동", 37.5550, 126.9360)
    end = result("세종로", "서울특별시 종로구 세종로", 37.5720, 126.9769)

    selected = choose_representative_coordinate("신촌역 -> 세종로", [start, end])

    assert selected.selected_name == "세종로"


def test_selects_start_when_no_endpoint_is_in_jongno():
    start = result("신촌역", "서울특별시 서대문구 신촌동", 37.5550, 126.9360)
    end = result("연세대 정문", "서울특별시 서대문구 연세로", 37.5650, 126.9380)

    selected = choose_representative_coordinate("신촌역 -> 연세대 정문", [start, end])

    assert selected.selected_name == "신촌역"


def test_selects_single_point():
    single = result("송현공원 앞", "서울특별시 종로구 송현동", 37.5765, 126.9807)

    selected = choose_representative_coordinate("송현공원 앞", [single])

    assert selected.selected_name == "송현공원 앞"


def test_bbox_fallback_is_used_only_when_address_is_missing():
    inside_without_address = result("종로 좌표", "", 37.5750, 126.9800)
    outside_with_address = result("서대문 좌표", "서울특별시 서대문구", 37.5750, 126.9800)

    assert is_jongno_result(inside_without_address) is True
    assert is_jongno_result(outside_with_address) is False


def test_empty_geocode_results_are_rejected():
    with pytest.raises(ValueError):
        _ = choose_representative_coordinate("원문 경로", [])


@pytest.mark.parametrize(
    ("candidate", "expected_replaced"),
    [
        ("舊)효자PB", "구)효자치안센터"),
        ("문래역4出", "문래역 4번 출구"),
        ("신교R", "신교교차로"),
        ("효자PB", "효자치안센터"),
    ],
)
def test_build_geocode_query_candidates_applies_generic_abbreviation_replacements(
    candidate: str,
    expected_replaced: str,
) -> None:
    queries = build_geocode_query_candidates(candidate, candidate)

    assert queries == (candidate, expected_replaced)


def test_build_geocode_query_candidates_adds_context_to_replaced_query():
    queries = build_geocode_query_candidates("문래역4出", "문래역4出 -> 당산역10出 <문래동3가 등>")

    assert queries == (
        "문래역4出",
        "문래역 4번 출구",
        "문래동3가 문래역 4번 출구",
        "문래역 4번 출구 문래동3가",
    )


@pytest.mark.asyncio
async def test_select_coordinate_for_event_uses_replaced_query_in_kakao_path() -> None:
    transport = KakaoKeywordTransport(
        {
            "효자치안센터": [
                {
                    "place_name": "효자치안센터",
                    "address_name": "서울 종로구 효자동",
                    "road_address_name": "",
                    "x": "126.9700",
                    "y": "37.5800",
                }
            ]
        }
    )

    previous_key = settings.KAKAO_LOCATION_API_KEY
    settings.KAKAO_LOCATION_API_KEY = TEST_KAKAO_API_KEY
    try:
        async with httpx.AsyncClient(transport=transport) as client:
            selected = await select_coordinate_for_event(
                smpa_event_for_endpoint("효자PB"),
                client,
            )
    finally:
        settings.KAKAO_LOCATION_API_KEY = previous_key

    assert transport.requested_queries == ["효자PB", "효자치안센터"]
    assert selected is not None
    assert selected.selected_name == "효자치안센터"


@pytest.mark.asyncio
async def test_select_coordinate_for_event_keeps_coordinate_failure_visible() -> None:
    transport = KakaoKeywordTransport({})

    previous_key = settings.KAKAO_LOCATION_API_KEY
    settings.KAKAO_LOCATION_API_KEY = TEST_KAKAO_API_KEY
    try:
        async with httpx.AsyncClient(transport=transport) as client:
            selected = await select_coordinate_for_event(
                smpa_event_for_endpoint("신교R"),
                client,
            )
    finally:
        settings.KAKAO_LOCATION_API_KEY = previous_key

    assert transport.requested_queries == ["신교R", "신교교차로"]
    assert selected is None
