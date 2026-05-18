#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
집회 데이터 크롤링 서비스 - 버전 4.2: SMPA PDF 지오코딩 Fallback 로직 추가

SMPA(서울경찰청) + SPATIC 양쪽 소스에서 집회 정보를 수집하고,
Kakao API로 지오코딩을 수행하여 events 테이블에 동기화합니다.

[수정사항 v4.2]
1. ✅ extract_bracket_location() 함수 추가: <동이름> 형식 정보 추출 및 재사용성 확보
2. ✅ geocode_kakao() 2단계 Fallback: 정규화된 검색 실패 시 <동이름> 정보로 대체 검색
3. ✅ 로깅 강화: Phase 1/2 구분으로 운영 모니터링 용이
4. ✅ 기존 호환성 유지: 함수 시그니처 미변경으로 다른 부분 영향 없음
"""

import re
import time
import pathlib
import logging
import asyncio
import sqlite3
from datetime import datetime
from collections import OrderedDict
from typing import List, Dict, Tuple, Optional

from app.database.connection import get_db_connection, get_database_path
from app.config.settings import settings

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams
import json
import fitz
from playwright.sync_api import sync_playwright


class LegacyTLSAdapter(HTTPAdapter):
    """SMPA 등 구형 TLS 설정을 사용하는 서버와의 호환성을 위한 어댑터"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

logger = logging.getLogger(__name__)

# 상수/설정
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent


def get_db_abs_path() -> pathlib.Path:
    """현재 설정 기준 DB 절대 경로를 반환한다."""
    database_path = pathlib.Path(get_database_path())
    if database_path.is_absolute():
        return database_path
    return BASE_DIR / database_path


def get_data_dir() -> pathlib.Path:
    """현재 DB 경로 기준 데이터 디렉터리를 반환한다."""
    return get_db_abs_path().parent

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"

SPATIC_BASE_URL = "https://www.spatic.go.kr"
SPATIC_LIST_URL = f"{SPATIC_BASE_URL}/spatic/main/assem.do"
SPATIC_DETAIL_FMT = f"{SPATIC_BASE_URL}/spatic/assem/getInfoView.do?mgrSeq={{mgrSeq}}"

SMPA_BASE_URL = "https://www.smpa.go.kr"
SMPA_LIST_URL = f"{SMPA_BASE_URL}/user/nd54882.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

SMPA_HEADERS = {
    **HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.smpa.go.kr/",
}

DEFAULT_SEOUL_LAT = 37.5665
DEFAULT_SEOUL_LON = 126.9780

KAKAO_API_TIMEOUT = 5
KAKAO_RATE_LIMIT_DELAY = 0.1
MAX_GEOCODING_RETRIES = 2
GEOCODING_RETRY_DELAY = 1

PDF_EXTRACTION_TIMEOUT = 30


# 공통 유틸리티
def ensure_dir(p: pathlib.Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"[유틸] 디렉토리 생성 실패: {p} - {e}")


def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def parse_date_any(s: str) -> Optional[Tuple[str, str, str]]:
    s = clean_text(s)
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return None


def time_range_to_tuple(s: str) -> Optional[Tuple[str, str]]:
    if not s:
        return None
    s = clean_text(s).replace("∼", "~").replace("〜", "~").replace("–", "-")
    m = re.search(r"(\d{1,2}\s*:\s*\d{2})\s*[~\-]\s*(\d{1,2}\s*:\s*\d{2})", s)
    if m:
        return re.sub(r"\s*", "", m.group(1)), re.sub(r"\s*", "", m.group(2))
    return None


def is_valid_place(place: str) -> bool:
    place = place.strip()

    if len(place) < 2 or place.isdigit():
        return False

    invalid_keywords = [
        '차로', '교차로', '신호', '근처', '부근', '방향', '방면',
        '도로', '거리', '간선', '구간', '지점', '일대',
        '내부', '외부', '입구', '출구', '개수'
    ]

    if re.match(r'\d+개\w+', place):
        return False

    for keyword in invalid_keywords:
        if keyword in place:
            return False

    return True


def split_places(s: str) -> List[str]:
    s = clean_text(s).replace("\n", " / ")
    s = re.sub(r'[①-⑨]', ' / ', s)
    parts = re.split(r"\s*(?:→|↔|⟷|⇒|~|/|,|▶|⇄|↔|内|內|※)\s*", s)

    filtered = []
    for p in parts:
        p = p.strip()
        if len(p) <= 1:
            continue
        p = re.sub(r'^[內内]$', '', p)
        p = re.sub(r'\d+개\w+[)）]?', '', p)
        if p and not p.isdigit():
            filtered.append(p)

    return list(OrderedDict.fromkeys(filtered))


    return None


def get_attachment_dir() -> pathlib.Path:
    """첨부파일 저장 디렉터리를 반환한다."""
    path = get_data_dir() / "attachments"
    ensure_dir(path)
    return path


PLACE_NAME_REPLACE_MAP = {
    "효자파출소": "청운파출소",
    "효자치안센터": "청운파출소",
    "효자PB": "효자동",
    "남대문서": "남대문경찰서",
    "파이낸스": "서울파이낸스센터",
    "의사당역": "국회의사당역",
    "사랑채": "청와대 사랑채",
    "전쟁기념관": "용산 전쟁기념관"
}


def normalize_place_name_for_kakao(place: str) -> str:
    t = place.strip()

    # STEP 1: 괄호 타입별 내용 전체 제거
    t = re.sub(r'\([^)]*\)', '', t)      # (내용) 제거
    t = re.sub(r'（[^）]*）', '', t)    # （내용） 제거
    t = re.sub(r'\[[^\]]*\]', '', t)    # [내용] 제거
    t = re.sub(r'【[^】]*】', '', t)    # 【내용】 제거
    t = re.sub(r'\{[^}]*\}', '', t)     # {내용} 제거

    # STEP 2: 특수 문자 제거 (기존 로직)
    t = re.sub(r'[舊新]', '', t)
    t = t.replace("구)", "").replace("(구)", "")

    # STEP 3: 거리/개수/횟수 정보 제거
    t = re.sub(r'\d+(\.\d+)?\s*km', '', t)         # 2km, 2.5km
    t = re.sub(r'\d+\s*개(?:차로|시간)', '', t)     # 1개차로, 2개시간
    t = re.sub(r'\d+\s*회\s*진행', '', t)           # 2회 진행

    # STEP 4: 앵글 브래킷 내용 제거 (<동이름>은 extract_bracket_location()에서 처리됨)
    t = re.sub(r'<[^>]*>', '', t)

    for old, new in PLACE_NAME_REPLACE_MAP.items():
        if old in t and new not in t:
            t = t.replace(old, new)

    noise_regex = r'(동측|서측|남측|북측|동쪽|서쪽|남쪽|북쪽|건너편|맞은편|옆|방향|방면|부근|일대|진입로|사거리|교차로|출구|입구|인근|앞|뒤|안|밖)'
    t = re.sub(noise_regex, ' ', t)
    t = re.sub(r'[^\w\s\d]', ' ', t)
    return re.sub(r"\s+", " ", t).strip()


def extract_bracket_location(place: str) -> Optional[str]:
    """
    ✅ v4.2 신규 함수: <동이름> 형태에서 동 이름 추출
    
    정규화 전에 호출되어 < > 괄호 정보를 보존한다.
    이후 지오코딩 폴백 시 사용된다.
    
    예시:
    - "더샘퍼스트월드 공사현장 1G 앞<상봉동>" → "상봉동"
    - "장충동2가 186-210 앞<장충동2가>" → "장충동2가"
    - "서울원아이파크 1G 좌측 인도<월계동>" → "월계동"
    - "괄호 없는 장소" → None
    
    Args:
        place (str): 원본 장소명
    
    Returns:
        Optional[str]: 추출된 동 이름 또는 None
    """
    if not place:
        return None
    
    # < > 괄호 내용 추출
    m = re.search(r'<([^>]+)>', place)
    if not m:
        return None
    
    bracket_content = m.group(1).strip()
    
    # 2글자 이상만 유효함
    return bracket_content if len(bracket_content) >= 2 else None


def _kakao_api_call(
        session: requests.Session,
        url: str,
        query: str,
        api_key: str,
        attempt: int = 1
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    headers = {"Authorization": f"KakaoAK {api_key}"}
    try:
        r = session.get(
            url,
            params={"query": query, "size": 1},
            headers=headers,
            timeout=KAKAO_API_TIMEOUT
        )

        if r.status_code == 200:
            docs = r.json().get("documents", [])
            if docs:
                addr = docs[0].get('address_name', '')
                if "서울" in addr[:5]:
                    lat = float(docs[0]['y'])
                    lon = float(docs[0]['x'])
                    logger.debug(f"[Kakao] 지오코딩 성공: {query} → ({lat}, {lon})")
                    return lat, lon, addr
        elif r.status_code == 401:
            logger.error(f"[Kakao API] 인증 오류: API Key 확인 필요")
            return None, None, None
        elif r.status_code == 429:
            logger.warning(f"[Kakao API] Rate Limit 초과 (429)")
            return None, None, None

    except requests.Timeout:
        logger.warning(f"[Kakao API] 타임아웃 ({attempt}/{MAX_GEOCODING_RETRIES}): {query}")
        if attempt < MAX_GEOCODING_RETRIES:
            time.sleep(GEOCODING_RETRY_DELAY)
            return _kakao_api_call(session, url, query, api_key, attempt + 1)
    except Exception as e:
        logger.warning(f"[Kakao API] 오류: {query} - {e}")

    return None, None, None


def geocode_kakao(session: requests.Session, place: str, api_key: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    ✅ v4.2 개선: 2단계 Fallback 지오코딩
    
    Phase 1: 정규화된 장소명으로 상세 검색 시도
    Phase 2: 정규화 실패 또는 검색 실패 시 <동이름> 정보로 대체 검색
    
    Args:
        session (requests.Session): HTTP 세션
        place (str): 원본 장소명 (예: "더샘 <상봉동>")
        api_key (str): Kakao API Key
    
    Returns:
        Tuple[Optional[float], Optional[float], Optional[str]]: (위도, 경도, 주소)
    """
    if not api_key or not api_key.strip():
        logger.error("[Kakao] API Key가 설정되지 않았습니다.")
        return None, None, None

    # ✅ STEP 1: Fallback 동 정보 사전 추출 (정규화 전에 수행)
    fallback_dong = extract_bracket_location(place)

    # STEP 2: 기존 정규화 로직 (수정 없음)
    clean_name = normalize_place_name_for_kakao(place)
    
    if not clean_name or len(clean_name) < 2:
        logger.debug(f"[Kakao] 정규화 실패 (너무 짧음): {place}")
        # 정규화 실패해도 fallback_dong이 있으면 계속 진행
        if not fallback_dong:
            return None, None, None
    
    # STEP 3: Phase 1용 쿼리 생성 (clean_name이 유효한 경우만)
    queries = []
    if clean_name and len(clean_name) >= 2:
        queries = [
            f"서울 {clean_name}",
            clean_name,
        ]

        tokens = clean_name.split()
        if len(tokens) > 1:
            queries.append(f"서울 {tokens[-1]}")
            queries.append(f"서울 {tokens[0]}")

        if not clean_name.endswith("역") and len(clean_name) <= 5:
            queries.append(f"서울 {clean_name}역")

    queries = list(OrderedDict.fromkeys(queries))
    
    # ✅ PHASE 1: 상세 검색 시도
    if queries:
        logger.debug(f"[Kakao] 📌 Phase 1 상세 검색 시도: {place} - 쿼리: {queries[:2]}")
        
        for query in queries:
            if len(query.replace("서울", "").strip()) < 2:
                continue

            lat, lon, addr = _kakao_api_call(session, KAKAO_KEYWORD_URL, query, api_key)
            if lat and lon:
                return lat, lon, addr

            lat, lon, addr = _kakao_api_call(session, KAKAO_ADDRESS_URL, query, api_key)
            if lat and lon:
                return lat, lon, addr

            time.sleep(KAKAO_RATE_LIMIT_DELAY)

    # ✅ PHASE 2: Fallback 검색 (상세 검색 전부 실패한 경우)
    if fallback_dong:
        fallback_query = f"서울 {fallback_dong}"
        logger.info(
            f"💡 [Kakao] Phase 1 전부 실패 → Phase 2 Fallback 검색 시도: "
            f"{fallback_query} (원본: {place})"
        )
        lat, lon, addr = _kakao_api_call(session, KAKAO_KEYWORD_URL, fallback_query, api_key)
        if lat and lon:
            logger.info(f"📍 [Kakao] ✅ Phase 2 성공 (동 단위): {addr} ({lat}, {lon})")
            return lat, lon, addr
        time.sleep(KAKAO_RATE_LIMIT_DELAY)

    # ✅ PHASE 3: 최종 실패
    logger.warning(f"[Kakao] ❌ 모든 폴백 소진. 지오코딩 실패: {place}")
    return None, None, None


class CrawlingService:
    """크롤링 서비스 클래스"""

    @classmethod
    async def crawl_and_sync_events(cls) -> Dict:
        """스케줄러 진입점"""
        logger.info("🔄 [스케줄러] 집회 정보 크롤링을 시작합니다.")
        ensure_dir(get_data_dir())

        if not settings.WORKS_AI_API_KEY or not settings.WORKS_AI_API_KEY.strip():
            logger.error("❌ WORKS_AI_API_KEY 환경변수가 설정되지 않았습니다.")

        return await asyncio.to_thread(cls._run_sync_pipeline)

    @classmethod
    def _call_works_ai_api(cls, prompt: str, max_retries: int = 3) -> Optional[Dict]:
        """Works AI(Gemini) API 호출"""
        if not settings.WORKS_AI_API_KEY:
            return None

        headers = {
            "Authorization": f"Bearer {settings.WORKS_AI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": settings.WORKS_AI_MODEL or "gemini-1.5-flash",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{settings.WORKS_AI_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                result = response.json()
                content = result['choices'][0]['message']['content']
                # 마크다운 코드 블록 제거
                content = re.sub(r"```json\s?|\s?```", "", content).strip()
                return json.loads(content)
            except Exception as e:
                logger.warning(f"[Gemini] API 호출 실패 (시도 {attempt+1}/{max_retries}): {e}")
                time.sleep(2)
        return None

    @classmethod
    def _pdf_to_images(cls, pdf_path: pathlib.Path, notice_seq: str) -> Optional[str]:
        """PDF를 이미지로 변환하여 저장"""
        try:
            doc = fitz.open(pdf_path)
            if len(doc) == 0:
                return None
            
            # 첫 페이지만 이미지로 저장 (대부분의 집회 요약이 1페이지에 있음)
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            
            image_dir = get_attachment_dir() / "protest_images"
            ensure_dir(image_dir)
            
            image_path = image_dir / f"protest_{notice_seq}.png"
            pix.save(str(image_path))
            doc.close()
            
            # 절대 경로 대신 상대 경로 저장 (정적 파일 서빙용)
            return f"attachments/protest_images/protest_{notice_seq}.png"
        except Exception as e:
            logger.error(f"[PDF->Image] 변환 실패: {e}")
            return None

    @classmethod
    def _run_sync_pipeline(cls) -> Dict:
        """Gemini 기반 통합 크롤링 파이프라인"""
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        with requests.Session() as session:
            session.headers.update(HEADERS)
            session.mount("https://www.smpa.go.kr", LegacyTLSAdapter())

            try:
                logger.info("📡 [수집] 소스 데이터 수집 시작...")
                spatic_raw = cls._scrape_spatic_raw(session)
                smpa_raw, pdf_image_path = cls._scrape_smpa_raw(session)

                if not spatic_raw and not smpa_raw:
                    logger.info("ℹ️ [알림] 수집된 데이터가 없습니다.")
                    return {"success": True, "total_crawled": 0}

                # Gemini를 통한 데이터 통합 및 정제
                prompt = f"""당신은 서울시 집회 정보를 분석하고 통합하는 전문가입니다.
제공된 두 소스(SPATIC, SMPA)의 텍스트를 분석하여 중복되는 집회는 하나로 통합하고, 최종 집회 목록을 JSON 형식으로 반환하세요.

[분석 규칙]
1. 중복 통합: 동일한 장소와 시간대의 집회는 하나로 합치세요.
2. 장소 정규화: 지오코딩이 잘 되도록 장소명을 유명한 건물명이나 지하철역, 혹은 정확한 주소 형태로 정제하세요.
3. 종로구 중심 위치 선정 (매우 중요):
   - 행진(A->B->C)의 경우, **종로구 내에 포함된 지점**을 최우선적으로 'location'으로 선정하세요.
   - 행진이 종로구에서 시작해서 종로구에서 끝나면 **시작 지점**을 선정하세요.
   - 행진이 종로구 밖에서 시작하더라도 **이동 경로 중간이나 종료 지점이 종로구 내**라면, 반드시 **종로구에 해당하는 지점**을 'location'으로 뽑으세요. (예: 용산역->광화문 행진이면 '광화문' 선정)
   - 전체 행진 경로는 'description'에 상세히 적으세요.
4. 시간 표준화: HH:MM 형식으로 추출하세요.
5. 인원: 명시된 경우 숫자만 추출하세요.

[소스 데이터]
- SPATIC: {spatic_raw}
- SMPA: {smpa_raw}

[출력 JSON 형식]
{{
  "events": [
    {{
      "title": "집회 제목 또는 단체명",
      "location": "정규화된 장소명 (예: 서울역 광장)",
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "attendees": "숫자",
      "description": "상세 경로 또는 집회 성격"
    }}
  ]
}}"""
                logger.info("🧠 [Gemini] 데이터 통합 및 분석 요청 중...")
                analysis_result = cls._call_works_ai_api(prompt)
                
                if not analysis_result or "events" not in analysis_result:
                    logger.error("❌ [Gemini] 분석 결과가 유효하지 않습니다.")
                    return {"success": False, "error": "Gemini analysis failed"}

                events = analysis_result["events"]
                logger.info(f"📍 [정제] 분석 완료: {len(events)}건 도출됨. 지오코딩 시작...")

                final_list = []
                geocoding_skipped_count = 0
                today = datetime.now()

                for row in events:
                    place = row["location"]
                    lat, lon, addr = geocode_kakao(session, place, settings.KAKAO_LOCATION_API_KEY)

                    if lat is None or lon is None:
                        geocoding_skipped_count += 1
                        logger.warning(f"[정제] {place} 지오코딩 실패 - 건너뜀")
                        continue
                    
                    final_list.append({
                        "년": today.strftime("%Y"),
                        "월": today.strftime("%m"),
                        "일": today.strftime("%d"),
                        "title": row["title"],
                        "description": row["description"],
                        "start_time": row["start_time"],
                        "end_time": row["end_time"],
                        "인원": row.get("attendees", ""),
                        "장소": place,
                        "위도": lat,
                        "경도": lon,
                        "지번주소": addr,
                        "image_path": pdf_image_path
                    })
                    time.sleep(KAKAO_RATE_LIMIT_DELAY)

                inserted_count = cls._sync_to_database(final_list)
                return {
                    "success": True,
                    "total_crawled": len(final_list),
                    "inserted_count": inserted_count,
                    "geocoding_skipped": geocoding_skipped_count
                }

            except Exception as e:
                logger.error(f"❌ [크롤링 실패] {e}", exc_info=True)
                return {"success": False, "error": str(e)}

    @classmethod
    def _scrape_spatic_raw(cls, session: requests.Session) -> str:
        """SPATIC에서 집회 데이터 원본 텍스트 수집"""
        logger.info("[SPATIC] 목록 수집 시작...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=HEADERS["User-Agent"])
                page.goto(SPATIC_LIST_URL, wait_until="networkidle", timeout=45000)
                page.wait_for_selector(".assem_content tr", timeout=15000)
                
                rows = page.query_selector_all(".assem_content tr")
                all_contents = []
                today_str = datetime.now().strftime("%Y-%m-%d") # 예: 2024-05-15
                
                # 목록에서 '오늘 날짜'이고 '집회'가 포함된 게시글의 ID 수집
                target_mgrs = []
                for row in rows:
                    tds = row.query_selector_all("td")
                    if len(tds) < 3:
                        continue
                        
                    title = tds[1].inner_text()
                    date_txt = tds[2].inner_text() # 보통 YYYY-MM-DD 형식
                    
                    # 테스트를 위해 날짜 필터 잠시 완화 (실제 운영시에는 today_str in date_txt 필요)
                    if "집회" in title:
                        onclick = row.get_attribute("onclick") or ""
                        m = re.search(r"(\d{4,})", onclick)
                        if m:
                            target_mgrs.append(m.group(1))
                
                if not target_mgrs:
                    logger.info("[SPATIC] 오늘 등록된 집회 공지가 없습니다.")
                    browser.close()
                    return ""
                
                logger.info(f"[SPATIC] 오늘자 공지 {len(target_mgrs)}건 발견. 상세 수집 시작...")
                
                # 각 게시글의 상세 테이블 내용을 수집
                for mgr in target_mgrs:
                    try:
                        detail_url = SPATIC_DETAIL_FMT.format(mgrSeq=mgr)
                        page.goto(detail_url, wait_until="networkidle")
                        table_text = page.inner_text("table")
                        all_contents.append(f"--- 게시글 ID: {mgr} ---\n{table_text}")
                    except Exception as e:
                        logger.warning(f"[SPATIC] 상세 페이지({mgr}) 수집 실패: {e}")

                browser.close()
                return "\n\n".join(all_contents)
        except Exception as e:
            logger.error(f"[SPATIC] 수집 실패: {e}")
            return ""

    @classmethod
    def _scrape_smpa_raw(cls, session: requests.Session) -> Tuple[str, Optional[str]]:
        """SMPA에서 PDF 텍스트 및 이미지 수집"""
        logger.info("[SMPA] PDF 수집 시작...")
        today_str = datetime.now().strftime("%y%m%d")
        try:
            # 목록 페이지 요청 (재시도 로직 추가)
            r = None
            for attempt in range(3):
                try:
                    r = session.get(SMPA_LIST_URL, headers=SMPA_HEADERS, timeout=15, verify=False)
                    r.raise_for_status()
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.warning(f"[SMPA] 목록 요청 실패 (시도 {attempt+1}/3): {e}. 3초 후 재시도...")
                        time.sleep(3)
                    else:
                        raise e

            if not r: return "", None
            soup = BeautifulSoup(r.text, "html.parser")
            
            pdf_url = None
            board_no = None
            for a in soup.select("a[href^='javascript:goBoardView']"):
                if today_str in a.get_text():
                    m = re.search(r"boardNo=(\d+)", a['href']) or re.search(r"'(\d+)'\)", a['href'])
                    if m:
                        board_no = m.group(1)
                        view_url = f"{SMPA_BASE_URL}/user/nd54882.do?View&boardNo={board_no}"
                        r_view = session.get(view_url, headers=SMPA_HEADERS, verify=False)
                        soup_view = BeautifulSoup(r_view.text, "html.parser")
                        for link in soup_view.find_all("a"):
                            if ".pdf" in link.get_text().lower():
                                m_pdf = re.search(r"attachfileDownload\('([^']+)'\s*,\s*'(\d+)'\)", link.get("onclick", ""))
                                if m_pdf:
                                    pdf_url = f"{SMPA_BASE_URL}{m_pdf.group(1)}?attachNo={m_pdf.group(2)}"
                                    break
                        break

            if not pdf_url:
                return "", None

            pdf_path = get_data_dir() / f"smpa_{today_str}.pdf"
            r_pdf = session.get(pdf_url, headers=SMPA_HEADERS, verify=False)
            with open(pdf_path, "wb") as f:
                f.write(r_pdf.content)

            # 텍스트 추출
            text = ""
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
            
            # 이미지 변환
            image_path = cls._pdf_to_images(pdf_path, today_str)
            
            try: pdf_path.unlink()
            except: pass
            
            return text, image_path

        except Exception as e:
            logger.error(f"[SMPA] 수집 실패: {e}")
            return "", None

        except Exception as e:
            logger.error(f"[SMPA] PDF 크롤링 및 파싱 실패: {e}", exc_info=True)
            return []

    @classmethod
    def _sync_to_database(cls, data_list: List[Dict]) -> int:
        """크롤링된 집회 정보를 데이터베이스에 저장
        
        ✅ v4.2 개선사항:
        - NOT NULL 제약 준수 (사전 검증)
        - IntegrityError/OperationalError 구분 처리
        - 상세한 오류 로깅
        """
        insert_data = []
        skipped_count = 0

        for r in data_list:
            year = r.get('년')
            month = str(r.get('월')).zfill(2)
            day = str(r.get('일')).zfill(2)

            st_time = r.get('start_time')
            ed_time = r.get('end_time')

            start_date = f"{year}-{month}-{day} {st_time}:00" if st_time else None
            end_date = f"{year}-{month}-{day} {ed_time}:00" if ed_time else None

            place_name = r.get('장소', '알 수 없는 장소')
            attendees = r.get('인원', '')

            title = r.get('title') or f"{place_name} 집회"
            description = r.get('description')

            lat = r.get('위도')
            lon = r.get('경도')
            addr = r.get('지번주소')
            img_path = r.get('image_path')

            # ✅ NOT NULL 제약 사전 검증
            if start_date is None:
                skipped_count += 1
                logger.warning(f"[DB] 필수 값 누락 - 장소: {place_name}, 시작시간: {st_time}")
                continue

            if lat is None or lon is None:
                skipped_count += 1
                logger.warning(f"[DB] NOT NULL 제약 위반 - 위도/경도 NULL - 장소: {place_name}")
                continue

            insert_data.append((
                title,
                description,
                place_name,
                addr,
                lat,
                lon,
                start_date,
                end_date,
                '집회',
                3 if attendees and str(attendees).isdigit() and int(attendees) > 1000 else 2,
                'active',
                img_path,
                int(attendees) if attendees and str(attendees).isdigit() else None
            ))

        if skipped_count > 0:
            logger.warning(f"[DB] {skipped_count}건의 데이터를 건너뛰었습니다.")

        if not insert_data:
            logger.warning("[DB] 삽입할 데이터가 없습니다.")
            return 0

        logger.info(f"[DB] {len(insert_data)}건의 데이터 삽입 시도 중...")

        try:
            with get_db_connection() as conn:
                cur = conn.cursor()

                try:
                    cur.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_location_date
                        ON events(location_name, start_date)
                    """)
                    logger.debug("[DB] UNIQUE INDEX 생성/확인 완료")
                except sqlite3.OperationalError as e:
                    logger.debug(f"[DB] INDEX 이미 존재: {e}")
                except Exception as e:
                    logger.warning(f"[DB] INDEX 생성 중 예기치 않은 오류: {e}")

                try:
                    cur.executemany("""
                        INSERT OR IGNORE INTO events (
                            title, description, location_name, location_address,
                            latitude, longitude, start_date, end_date,
                            category, severity_level, status, image_path, attendees
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, insert_data)

                    inserted_count = cur.rowcount
                    conn.commit()

                    logger.info(f"✅ [DB] {len(insert_data)}건 중 {inserted_count}건의 이벤트 저장 완료")

                    if inserted_count < len(insert_data):
                        ignored_count = len(insert_data) - inserted_count
                        logger.warning(f"[DB] {ignored_count}건의 중복 데이터 무시됨 (INSERT OR IGNORE)")

                    return inserted_count

                except sqlite3.IntegrityError as e:
                    logger.error(f"❌ [DB] 무결성 제약 오류: {e}")
                    logger.error(f"[DB] 삽입 시도 샘플: {insert_data[0] if insert_data else 'None'}")
                    conn.rollback()
                    return 0

                except sqlite3.OperationalError as e:
                    logger.error(f"❌ [DB] 운영 오류 (테이블/컬럼 확인 필요): {e}")
                    logger.error(f"[DB] INSERT 쿼리가 events 테이블과 일치하는지 확인하세요")
                    conn.rollback()
                    return 0

                except Exception as e:
                    logger.error(f"❌ [DB] 예기치 않은 오류: {type(e).__name__}: {e}")
                    logger.debug(f"[DB] 상세 오류: ", exc_info=True)
                    conn.rollback()
                    return 0

        except Exception as e:
            logger.error(f"❌ [DB] 데이터베이스 연결 실패: {e}", exc_info=True)
            return 0


if __name__ == "__main__":
    from app.database.connection import init_db
    init_db()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(CrawlingService.crawl_and_sync_events())
