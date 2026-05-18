"""SMPA 집회 대표 좌표 선택과 Kakao 지오코딩 seam."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

import httpx

from app.config.settings import settings
from app.services.crawling.smpa_geocode_rules import (
    SMPA_GEOCODE_ABBREVIATION_RULES,
    GeocodeAbbreviationRule,
)
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
LOCATION_CONTEXT_RE = re.compile(r"<(?P<context>[^>]+)>")
CONTEXT_TRAILING_MARKERS_RE = re.compile(r"\s*(?:등|일대)$")


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


def _clean_query_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _dedupe_queries(queries: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        cleaned = _clean_query_text(query)
        if cleaned and cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)
    return tuple(deduped)


def _extract_location_context(raw_location: str) -> str:
    match = LOCATION_CONTEXT_RE.search(raw_location)
    if match is None:
        return ""
    context = _clean_query_text(match.group("context"))
    return CONTEXT_TRAILING_MARKERS_RE.sub("", context).strip()


@lru_cache(maxsize=16)
def _compile_geocode_abbreviation_rules(
    raw_rules: tuple[GeocodeAbbreviationRule, ...],
) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(pattern_text), replacement) for pattern_text, replacement in raw_rules)


def _active_geocode_abbreviation_rules() -> tuple[tuple[re.Pattern[str], str], ...]:
    return _compile_geocode_abbreviation_rules(SMPA_GEOCODE_ABBREVIATION_RULES)


def _replace_geocode_abbreviations(query: str) -> str:
    replaced = query
    for pattern, replacement in _active_geocode_abbreviation_rules():
        replaced = pattern.sub(replacement, replaced)
    return _clean_query_text(replaced)


def build_geocode_query_candidates(candidate: str, raw_location: str) -> tuple[str, ...]:
    """SMPA 장소 표기를 Kakao keyword search용 후보 검색어로 확장한다."""
    cleaned = _clean_query_text(candidate)
    replaced = _replace_geocode_abbreviations(cleaned)
    context = _extract_location_context(raw_location)

    queries = [cleaned, replaced]
    base_for_context = replaced or cleaned
    if context and base_for_context:
        queries.extend([f"{context} {base_for_context}", f"{base_for_context} {context}"])

    return _dedupe_queries(queries)


def _first_kakao_document(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    payload_mapping = cast(dict[str, object], payload)
    raw_documents = payload_mapping.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        return None
    documents = cast(list[object], raw_documents)
    first = documents[0]
    if not isinstance(first, dict):
        return None
    return cast(dict[str, object], first)


def _optional_text(value: object, fallback: str = "") -> str:
    if isinstance(value, str) and value:
        return value
    return fallback


async def geocode_place_with_kakao(
    query: str,
    client: httpx.AsyncClient | None = None,
    *,
    warn_on_empty_result: bool = True,
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

    _ = response.raise_for_status()
    payload = cast(object, response.json())
    first = _first_kakao_document(payload)
    if first is None:
        if warn_on_empty_result:
            logger.warning("Kakao 지오코딩 결과 없음: %s", query)
        return None

    latitude = first.get("y")
    longitude = first.get("x")
    if not isinstance(latitude, str) or not isinstance(longitude, str):
        logger.warning("Kakao 지오코딩 좌표 형식 오류: %s", query)
        return None

    return GeocodeResult(
        query=query,
        name=_optional_text(first.get("place_name"), query),
        address=_optional_text(
            first.get("road_address_name"),
            _optional_text(first.get("address_name")),
        ),
        latitude=float(latitude),
        longitude=float(longitude),
    )


async def _geocode_first_matching_query(
    queries: tuple[str, ...],
    client: httpx.AsyncClient | None,
) -> GeocodeResult | None:
    if not settings.KAKAO_LOCATION_API_KEY:
        logger.warning("KAKAO_LOCATION_API_KEY가 없어 지오코딩을 건너뜁니다.")
        return None

    for query in queries:
        result = await geocode_place_with_kakao(
            query,
            client,
            warn_on_empty_result=False,
        )
        if result is not None:
            return result
    logger.warning("Kakao 지오코딩 결과 없음: %s", " | ".join(queries))
    return None


async def select_coordinate_for_event(
    event: ParsedSmpaEvent,
    client: httpx.AsyncClient | None = None,
) -> SelectedCoordinate | None:
    """파싱된 이벤트의 endpoint 후보를 지오코딩하고 대표 좌표를 선택한다."""
    results: list[GeocodeResult] = []
    for candidate in event.endpoint_candidates:
        queries = build_geocode_query_candidates(candidate, event.raw_location)
        result = await _geocode_first_matching_query(queries, client)
        if result is not None:
            results.append(result)
    if not results:
        return None
    return choose_representative_coordinate(event.raw_location, results)
