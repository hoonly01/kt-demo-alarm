import pytest

from app.services.crawling.smpa_coordinates import (
    GeocodeResult,
    choose_representative_coordinate,
    is_jongno_result,
)


def result(query, address, latitude, longitude):
    return GeocodeResult(
        query=query,
        name=query,
        address=address,
        latitude=latitude,
        longitude=longitude,
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
        choose_representative_coordinate("원문 경로", [])
