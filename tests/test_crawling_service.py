"""crawling_service 단위 테스트 — v2 통합 검증"""
import re
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.crawling_service import CrawlingService, PLACE_NAME_REPLACE_MAP
from app.services.spatic_crawler import split_places


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

    def test_noise_filter(self):
        result = split_places("2차로 확대 구간")
        # '2차로'는 필터링 대상
        assert "2차로" not in " ".join(result)

    def test_empty(self):
        assert split_places("") == []

    def test_single(self):
        result = split_places("광화문")
        assert result == ["광화문"]


# ========================== _normalize_place_name ==========================

class TestNormalizePlaceName:
    """v2 지명 치환 로직 테스트"""

    def test_replace_map(self):
        result = CrawlingService._normalize_place_name("효자파출소 앞")
        assert "청운파출소" in result

    def test_km_removal(self):
        result = CrawlingService._normalize_place_name("광화문 1.5km 지점")
        assert "km" not in result

    def test_bracket_removal(self):
        result = CrawlingService._normalize_place_name("광화문(정부청사)")
        assert "정부청사" not in result

    def test_direction_removal(self):
        result = CrawlingService._normalize_place_name("서울역 남쪽 방면")
        assert "남쪽" not in result
        assert "방면" not in result


# ========================== _merge_and_deduplicate ==========================

class TestMergeAndDeduplicate:
    """SMPA + SPATIC 병합 로직 테스트"""

    def test_basic_merge(self):
        smpa = [{"년": "2026", "월": "02", "일": "20",
                 "start_time": "10:00", "end_time": "18:00",
                 "장소_원본": ["광화문"], "인원": "500", "비고": "SMPA"}]
        spatic = [{"년": "2026", "월": "02", "일": "20",
                   "start_time": "14:00", "end_time": "16:00",
                   "장소_원본": ["시청"], "인원": "", "비고": "SPATIC"}]
        result = CrawlingService._merge_and_deduplicate(smpa, spatic)
        assert len(result) == 2

    def test_dedup_same_place_time(self):
        smpa = [{"년": "2026", "월": "02", "일": "20",
                 "start_time": "10:00", "end_time": "18:00",
                 "장소_원본": ["광화문"], "인원": "500", "비고": "SMPA"}]
        spatic = [{"년": "2026", "월": "02", "일": "20",
                   "start_time": "10:00", "end_time": "18:00",
                   "장소_원본": ["광화문"], "인원": "", "비고": "SPATIC"}]
        result = CrawlingService._merge_and_deduplicate(smpa, spatic)
        # 같은 날짜+시간+장소이므로 중복 제거 — 첫 번째만 남음
        assert len(result) == 1
        assert result[0]["비고"] == "SMPA"

    def test_empty_inputs(self):
        result = CrawlingService._merge_and_deduplicate([], [])
        assert result == []


# ========================== _crawl_spatic_events (mock) ==========================

class TestCrawlSpaticEvents:
    """SPATIC 크롤링 실패 시 폴백 테스트"""

    @pytest.mark.asyncio
    async def test_spatic_failure_returns_empty(self):
        with patch("app.services.crawling_service.scrape_spatic", side_effect=Exception("no selenium")):
            result = await CrawlingService._crawl_spatic_events()
            assert result == []

    @pytest.mark.asyncio
    async def test_spatic_success(self):
        mock_data = [{"년": "2026", "월": "02", "일": "20",
                      "start_time": "10:00", "end_time": "12:00",
                      "장소_원본": ["광화문"], "인원": "", "비고": "SPATIC"}]
        with patch("app.services.crawling_service.scrape_spatic", return_value=mock_data):
            result = await CrawlingService._crawl_spatic_events()
            assert len(result) == 1
