"""SMPA 집회 대표 좌표 선택과 Kakao 지오코딩 seam."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config.settings import settings
from app.services.crawling.smpa_parser import ParsedSmpaEvent

logger = logging.getLogger(__name__)

KAKAO_LOCAL_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
JONGNO_ADDRESS_MARKERS = ("서울특별시 종로구", "서울 종로구")
JONGNO_BBOX = {
    "min_lat": 37.5650,
    "max_lat": 37.6350,
    "min_lon": 126.9400,
    "max_lon": 127.0250,
}


@dataclass(frozen=True)
class GeocodeResult:
    """지오코딩 결과 중 대표 좌표 선택에 필요한 필드."""

    query: str
    name: str
    address: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class SelectedCoordinate:
    """DB 적재에 사용할 대표 좌표."""

    raw_location: str
    selected_name: str
    selected_address: str
    latitude: float
    longitude: float


def is_jongno_result(result: GeocodeResult) -> bool:
    """주소 우선, 불명확하면 bbox로 종로구 포함 여부를 판정한다."""
    if any(marker in result.address for marker in JONGNO_ADDRESS_MARKERS):
        return True
    if result.address.strip():
        return False
    return (
        JONGNO_BBOX["min_lat"] <= result.latitude <= JONGNO_BBOX["max_lat"]
        and JONGNO_BBOX["min_lon"] <= result.longitude <= JONGNO_BBOX["max_lon"]
    )


def choose_representative_coordinate(
    raw_location: str,
    endpoint_results: list[GeocodeResult],
) -> SelectedCoordinate:
    """A/B endpoint 종로구 포함 조합에 따라 대표 좌표 하나를 고른다."""
    if not endpoint_results:
        raise ValueError("대표 좌표를 선택할 지오코딩 결과가 없습니다.")

    if len(endpoint_results) == 1:
        chosen = endpoint_results[0]
    else:
        start = endpoint_results[0]
        end = endpoint_results[-1]
        start_in_jongno = is_jongno_result(start)
        end_in_jongno = is_jongno_result(end)

        if start_in_jongno and end_in_jongno:
            chosen = start
        elif start_in_jongno:
            chosen = start
        elif end_in_jongno:
            chosen = end
        else:
            chosen = start

    return SelectedCoordinate(
        raw_location=raw_location,
        selected_name=chosen.name or chosen.query,
        selected_address=chosen.address,
        latitude=chosen.latitude,
        longitude=chosen.longitude,
    )


async def geocode_place_with_kakao(
    query: str,
    client: httpx.AsyncClient | None = None,
) -> GeocodeResult | None:
    """Kakao keyword search로 장소명 하나를 좌표로 변환한다."""
    if not settings.KAKAO_LOCATION_API_KEY:
        logger.warning("KAKAO_LOCATION_API_KEY가 없어 지오코딩을 건너뜁니다.")
        return None

    headers = {"Authorization": f"KakaoAK {settings.KAKAO_LOCATION_API_KEY}"}
    params = {"query": query}

    if client is not None:
        response = await client.get(KAKAO_LOCAL_KEYWORD_URL, headers=headers, params=params)
    else:
        async with httpx.AsyncClient(timeout=settings.SMPA_HTTP_TIMEOUT_SECONDS) as new_client:
            response = await new_client.get(KAKAO_LOCAL_KEYWORD_URL, headers=headers, params=params)

    response.raise_for_status()
    documents = response.json().get("documents") or []
    if not documents:
        logger.warning("Kakao 지오코딩 결과 없음: %s", query)
        return None

    first = documents[0]
    return GeocodeResult(
        query=query,
        name=first.get("place_name") or query,
        address=first.get("road_address_name") or first.get("address_name") or "",
        latitude=float(first["y"]),
        longitude=float(first["x"]),
    )


async def select_coordinate_for_event(
    event: ParsedSmpaEvent,
    client: httpx.AsyncClient | None = None,
) -> SelectedCoordinate | None:
    """파싱된 이벤트의 endpoint 후보를 지오코딩하고 대표 좌표를 선택한다."""
    results: list[GeocodeResult] = []
    for candidate in event.endpoint_candidates:
        result = await geocode_place_with_kakao(candidate, client)
        if result is not None:
            results.append(result)
    if not results:
        return None
    return choose_representative_coordinate(event.raw_location, results)
