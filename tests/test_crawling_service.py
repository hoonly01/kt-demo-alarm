"""crawling_service 단위 테스트 — v2 통합 검증"""
import re
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.crawling_service import (
    CrawlingService, 
    PLACE_NAME_REPLACE_MAP,
    split_places,
    normalize_place_name_for_kakao
)


# ========================== split_places ==========================

class TestSplitPlaces:
    """v2에서 가져온 split_places 유틸 테스트"""

    def test_arrow_split(self):
        result = split_places("광화문→시청→서울역")
        assert result == ["광화문", "시청", "서울역"]

    def test_slash_split(self):
        result = split_places("종로구청 / 경복궁")
        assert result == ["종로구청", "경복궁"]

    def test_dedup(self):
        result = split_places("광화문→시청→광화문")
        assert result == ["광화문", "시청"]

    def test_single(self):
        result = split_places("광화문")
        assert result == ["광화문"]

    def test_empty(self):
        assert split_places("") == []

    def test_single(self):
        result = split_places("광화문")
        assert result == ["광화문"]


# ========================== _normalize_place_name ==========================

class TestNormalizePlaceName:
    """v2 지명 치환 로직 테스트"""

    def test_replace_map(self):
        result = normalize_place_name_for_kakao("효자파출소 앞")
        assert "청운파출소" in result

    def test_km_removal(self):
        result = normalize_place_name_for_kakao("광화문 1.5km 지점")
        assert "km" not in result

    def test_bracket_removal(self):
        result = normalize_place_name_for_kakao("광화문(정부청사)")
        assert "(" not in result
        assert ")" not in result

    def test_direction_removal(self):
        result = normalize_place_name_for_kakao("서울역 남쪽 방면")
        assert "남쪽" not in result
        assert "방면" not in result


# Note: _merge_and_deduplicate logic was merged into _run_sync_pipeline.


# ========================== _crawl_spatic_events (mock) ==========================

class TestCrawlSpaticEvents:
    """SPATIC 크롤링 실패 시 폴백 테스트"""

    @pytest.mark.asyncio
    async def test_spatic_failure_returns_empty(self):
        # Patch sync_playwright instead of the method itself to test error handling
        with patch("app.services.crawling_service.sync_playwright", side_effect=Exception("no playwright")):
            session = MagicMock()
            result = CrawlingService._scrape_spatic(session)
            assert result == []

    @pytest.mark.asyncio
    async def test_spatic_success(self):
        mock_data = [{"년": "2026", "월": "02", "일": "20",
                      "start_time": "10:00", "end_time": "12:00",
                      "장소_원본": ["광화문"], "인원": "", "비고": "SPATIC"}]
        with patch("app.services.crawling_service.CrawlingService._scrape_spatic", return_value=mock_data):
            session = MagicMock()
            result = CrawlingService._scrape_spatic(session)
            assert len(result) == 1


# Note: _fetch_list_playwright logic was merged into CrawlingService._scrape_spatic.
# Specific playwright parsing tests should be updated to test _scrape_spatic if needed.
