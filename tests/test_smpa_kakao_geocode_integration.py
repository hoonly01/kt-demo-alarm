import os

import pytest

from app.services.crawling.smpa_coordinates import geocode_place_with_kakao


@pytest.mark.asyncio
async def test_kakao_geocode_real_integration():
    if os.environ.get("RUN_KAKAO_GEOCODE") != "1":
        pytest.skip("RUN_KAKAO_GEOCODE=1 이 설정되지 않아 Kakao geocode 통합 검증을 건너뜁니다.")
    if not os.environ.get("KAKAO_LOCATION_API_KEY"):
        pytest.skip("KAKAO_LOCATION_API_KEY 환경변수가 없어 Kakao geocode 통합 검증을 건너뜁니다.")

    result = await geocode_place_with_kakao("교보빌딩")

    assert result is not None
    assert result.latitude
    assert result.longitude
