"""Issue #173: 버스 통제 조회 회귀 테스트.

- Layer 1: _clean_json_response 가 LLM 출력의 'Extra data'/잘림을 방어하는지
- Layer A: _get_bus_notices 가 통제안내(0201) + 버스안내(0202)를 병합하는지
- Layer 5: 추출 실패(extraction_incomplete) 공지를 "정상 운행"으로 오인하지 않는지
"""
import os
import sys
import json
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.bus_logic.restricted_bus import TOPISCrawler
from app.services.bus_notice_service import BusNoticeService


def _clean(text):
    # self 미사용 순수 함수라 인스턴스 없이 호출
    return TOPISCrawler._clean_json_response(None, text)


# ── Layer 1: JSON 파싱 견고화 ─────────────────────────────

def test_clean_json_plain():
    assert json.loads(_clean('{"a": 1}')) == {"a": 1}


def test_clean_json_markdown_fence():
    raw = '```json\n{"a": 1, "b": [2, 3]}\n```'
    assert json.loads(_clean(raw)) == {"a": 1, "b": [2, 3]}


def test_clean_json_extra_data_trailing():
    # 유효 JSON 뒤에 잡문/사고흔적 (관측된 'Extra data: line ..' 유형)
    raw = '{"route_pages": {"162": 1}}\n\n설명: 위 노선은 ...'
    assert json.loads(_clean(raw)) == {"route_pages": {"162": 1}}


def test_clean_json_truncated_recovers():
    # 출력이 중간에 잘림 (관측된 'Expecting delimiter' 유형) → 닫아서 파싱 가능
    raw = '{"route_pages": {"162": 1, "503": 2'
    data = json.loads(_clean(raw))
    assert data["route_pages"] == {"162": 1, "503": 2}


def test_clean_json_braces_inside_string():
    # 문자열 내부 중괄호가 depth 계산을 깨지 않아야 함
    raw = '{"note": "구간 {A} 통제", "n": 1} trailing'
    assert json.loads(_clean(raw)) == {"note": "구간 {A} 통제", "n": 1}


# ── Layer A: 카테고리 병합 수집 ───────────────────────────

def test_get_bus_notices_merges_control_and_bus_categories(tmp_path):
    c = TOPISCrawler(cache_file=str(tmp_path / "cache.json"), download_folder=str(tmp_path / "dl"))
    seen = []

    def fake_post(data, max_retries=3):
        seen.append(data["bdwrDivCd"])
        if data["bdwrDivCd"] == "0201":   # 통제안내: 버스 우회 공지가 여기 있음
            return [{"bdwrSeq": "6021"}, {"bdwrSeq": "6018"}]
        return [{"bdwrSeq": "6018"}, {"bdwrSeq": "6017"}]  # 버스안내(6018 중복)

    c._post_notice_list = fake_post
    res = c._get_bus_notices()
    seqs = [r["bdwrSeq"] for r in res["rows"]]

    assert set(seen) == {"0201", "0202"}      # 두 카테고리 모두 조회
    assert seqs == ["6021", "6018", "6017"]   # 중복 제거 + seq 내림차순


# ── Layer 5: 추출 실패 시 안전 강등 ───────────────────────

@pytest.mark.asyncio
async def test_route_check_degrades_when_extraction_incomplete(tmp_path, monkeypatch):
    crawler = TOPISCrawler(cache_file=str(tmp_path / "c.json"), download_folder=str(tmp_path / "dl"))
    notice = {
        "seq": "9999",
        "title": "테스트 통제 공지",
        "create_date": "2026-07-15 00:00:00",
        "general_periods": ["2026-07-15 00:00 ~ 2026-07-20 23:59"],
        "route_pages": {},
        "route_images": {},
        "extraction_incomplete": True,
    }
    monkeypatch.setattr(BusNoticeService, "crawler", crawler)
    monkeypatch.setattr(BusNoticeService, "cached_notices", {"9999": notice})

    resp = await BusNoticeService.get_route_check_response("162", {"date": "2026-07-16"})
    text = resp["template"]["outputs"][0]["simpleText"]["text"]
    assert "확인하지 못했습니다" in text
    assert "정상 운행" not in text


@pytest.mark.asyncio
async def test_route_check_says_normal_when_no_notice(tmp_path, monkeypatch):
    crawler = TOPISCrawler(cache_file=str(tmp_path / "c.json"), download_folder=str(tmp_path / "dl"))
    monkeypatch.setattr(BusNoticeService, "crawler", crawler)
    monkeypatch.setattr(BusNoticeService, "cached_notices", {})

    resp = await BusNoticeService.get_route_check_response("162", {"date": "2026-07-16"})
    text = resp["template"]["outputs"][0]["simpleText"]["text"]
    assert "정상 운행" in text


@pytest.mark.asyncio
async def test_background_callback_degrades_when_extraction_incomplete(tmp_path, monkeypatch):
    # 비동기 콜백 경로(process_route_check_background)도 동기 경로와 동일하게
    # 추출 실패 공지를 "정상 운행"으로 단정하지 않아야 한다.
    crawler = TOPISCrawler(cache_file=str(tmp_path / "c.json"), download_folder=str(tmp_path / "dl"))
    notice = {
        "seq": "9999",
        "title": "테스트 통제 공지",
        "create_date": "2026-07-15 00:00:00",
        "general_periods": ["2026-07-15 00:00 ~ 2026-07-20 23:59"],
        "route_pages": {},
        "route_images": {},
        "extraction_incomplete": True,
    }
    monkeypatch.setattr(BusNoticeService, "crawler", crawler)
    monkeypatch.setattr(BusNoticeService, "cached_notices", {"9999": notice})

    sent = {}

    async def fake_send(cls_url, message):
        sent["text"] = message["template"]["outputs"][0]["simpleText"]["text"]

    monkeypatch.setattr(BusNoticeService, "_send_callback_request", classmethod(
        lambda cls, url, message: fake_send(url, message)
    ))

    await BusNoticeService.process_route_check_background("162", {"date": "2026-07-16"}, "http://callback.test")
    assert "확인하지 못했습니다" in sent["text"]
    assert "정상 운행" not in sent["text"]
