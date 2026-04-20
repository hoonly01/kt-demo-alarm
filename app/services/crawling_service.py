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

from app.database.connection import get_db_connection, DATABASE_PATH
from app.config.settings import settings

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams
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
if not pathlib.Path(DATABASE_PATH).is_absolute():
    DB_ABS_PATH = BASE_DIR / DATABASE_PATH
else:
    DB_ABS_PATH = pathlib.Path(DATABASE_PATH)
DATA_DIR = DB_ABS_PATH.parent

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


def extract_pdf_text_with_fallback(pdf_path: pathlib.Path) -> Optional[str]:
    try:
        logger.info(f"[PDF] pdfminer 텍스트 추출 시도...")
        laparams = LAParams(line_margin=0.2, word_margin=0.1)
        text = extract_text(str(pdf_path), laparams=laparams)

        if text and len(text.strip()) >= 10:
            logger.info(f"[PDF] pdfminer 추출 성공 (길이: {len(text)} 글자)")
            return text
        else:
            logger.warning(f"[PDF] pdfminer 추출 결과 불충분 (길이: {len(text) if text else 0})")
    except Exception as e:
        logger.warning(f"[PDF] pdfminer 추출 실패: {e}")

    if PDFPLUMBER_AVAILABLE:
        try:
            logger.info(f"[PDF] pdfplumber 텍스트 추출 시도 (폴백)...")
            text = ""
            with pdfplumber.open(pdf_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        logger.debug(f"[PDF] 페이지 {page_idx + 1}: {len(page_text)} 글자 추출")
                        text += page_text + "\n"

            if text and len(text.strip()) >= 10:
                logger.info(f"[PDF] pdfplumber 추출 성공 (길이: {len(text)} 글자)")
                return text
            else:
                logger.warning(f"[PDF] pdfplumber 추출 결과 불충분 (길이: {len(text)})")
        except Exception as e:
            logger.warning(f"[PDF] pdfplumber 추출 실패: {e}")
    else:
        logger.warning("[PDF] pdfplumber가 설치되지 않았습니다. pip install pdfplumber를 실행하세요.")

    return None


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
        ensure_dir(DATA_DIR)

        if PDFPLUMBER_AVAILABLE:
            logger.info("ℹ️ [PDF] pdfplumber가 사용 가능합니다 (폴백 지원)")
        else:
            logger.warning("⚠️ [PDF] pdfplumber가 설치되지 않았습니다.")

        if not settings.KAKAO_LOCATION_API_KEY or not settings.KAKAO_LOCATION_API_KEY.strip():
            error_msg = "❌ KAKAO_LOCATION_API_KEY 환경변수가 설정되지 않았습니다."
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "total_crawled": 0
            }

        return await asyncio.to_thread(cls._run_sync_pipeline)

    @classmethod
    def _run_sync_pipeline(cls) -> Dict:
        """실제 크롤링이 진행되는 동기 파이프라인"""
        with requests.Session() as session:
            session.headers.update(HEADERS)
            session.mount("https://www.smpa.go.kr", LegacyTLSAdapter())

            try:
                logger.info("📡 [수집] SPATIC 및 SMPA에서 데이터 수집 중...")
                spatic_data = cls._scrape_spatic(session)
                smpa_data = cls._scrape_smpa(session)
                data = spatic_data + smpa_data

                if not data:
                    logger.info("ℹ️ [알림] 오늘 수집된 집회 데이터가 없습니다.")
                    return {
                        "success": True,
                        "status": "info",
                        "message": "수집된 데이터가 없습니다",
                        "total_crawled": 0,
                        "inserted_count": 0
                    }

                logger.info(f"📍 [정제] 총 {len(data)}건의 데이터 지오코딩 진행 중...")

                final_list = []
                geocoding_skipped_count = 0

                for row in data:
                    places = row.get("장소_원본", [])
                    for place in places:
                        # ✅ v4.2: geocode_kakao()에서 자동으로 Fallback 로직 처리됨
                        lat, lon, addr = geocode_kakao(session, place, settings.KAKAO_LOCATION_API_KEY)

                        # ✅ NOT NULL 제약 준수: 지오코딩 실패 시 행 건너뜀
                        if lat is None or lon is None:
                            geocoding_skipped_count += 1
                            logger.warning(
                                f"[정제] {place} 지오코딩 완전 실패 - 해당 장소 건너뜀 (DB NOT NULL 제약)"
                            )
                            continue
                        
                        # 지오코딩 성공한 경우만 여기 도달
                        new_row = {k: v for k, v in row.items() if k != "장소_원본"}
                        new_row.update({
                            "장소": place,
                            "위도": lat,
                            "경도": lon,
                            "지번주소": addr
                        })

                        final_list.append(new_row)
                        time.sleep(KAKAO_RATE_LIMIT_DELAY)

                if geocoding_skipped_count > 0:
                    logger.warning(
                        f"⚠️  [정제] {geocoding_skipped_count}건의 장소 지오코딩 실패로 건너뜀"
                    )

                logger.info(f"📍 [정제] 지오코딩 완료! {len(final_list)}건이 DB 저장 대기 중...")
                inserted_count = cls._sync_to_database(final_list)

                logger.info(f"✅ [완료] 크롤링 및 DB 저장이 완료되었습니다. (저장된 데이터: {inserted_count}건)")

                return {
                    "success": True,
                    "status": "success",
                    "message": "집회 데이터 크롤링 및 동기화 완료",
                    "total_crawled": len(final_list),
                    "inserted_count": inserted_count,
                    "geocoding_skipped": geocoding_skipped_count
                }

            except Exception as e:
                logger.error(f"❌ [크롤링 실패] {e}", exc_info=True)
                return {
                    "success": False,
                    "error": str(e),
                    "total_crawled": 0
                }

    @classmethod
    def _scrape_spatic(cls, session: requests.Session) -> List[Dict]:
        """SPATIC에서 집회 데이터 수집"""
        logger.info("[SPATIC] Playwright 목록 수집 시작...")
        posts = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu'
                    ]
                )
                page = browser.new_page(user_agent=HEADERS["User-Agent"])

                try:
                    page.goto(SPATIC_LIST_URL, wait_until="networkidle", timeout=45000)
                    page.wait_for_selector(".assem_content tr", timeout=15000)
                    rows = page.query_selector_all(".assem_content tr")

                    logger.info(f"[SPATIC] {len(rows)}개 행 발견")

                    for row in rows:
                        try:
                            mgr = row.get_attribute("key")
                            if not mgr:
                                onclick = row.get_attribute("onclick") or ""
                                m = re.search(r"(\d{4,})", onclick)
                                if m:
                                    mgr = m.group(1)

                            tds = row.query_selector_all("td")
                            if len(tds) < 3:
                                continue

                            title = tds[1].inner_text().strip()
                            date_txt = tds[2].inner_text().strip()

                            if mgr and "집회" in title:
                                parsed = parse_date_any(date_txt)
                                if parsed:
                                    posts.append({
                                        "number": mgr,
                                        "title": title,
                                        "date": f"{parsed[0]}-{parsed[1]}-{parsed[2]}"
                                    })
                        except Exception as row_err:
                            logger.debug(f"[SPATIC] 행 파싱 실패: {row_err}")
                            continue

                except Exception as e:
                    logger.error(f"[SPATIC] Playwright 페이지 로드 오류: {e}")
                    return []
                finally:
                    browser.close()

        except Exception as e:
            logger.error(f"[SPATIC] Playwright 크롤링 실패: {e}")
            return []

        unique_posts = list({p["number"]: p for p in posts}.values())
        if not unique_posts:
            logger.info("[SPATIC] 집회 관련 게시글을 찾을 수 없습니다.")
            return []

        unique_posts.sort(key=lambda x: int(x['number']), reverse=True)
        target = unique_posts[0]

        logger.info(f"[SPATIC] 상세 정보 파싱 시작: mgrSeq={target['number']}")

        try:
            detail_url = SPATIC_DETAIL_FMT.format(mgrSeq=target['number'])
            r = session.get(detail_url, timeout=10)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "html.parser")
            tb = soup.find("table")
            if not tb:
                logger.warning("[SPATIC] 상세 페이지에서 테이블을 찾을 수 없습니다.")
                return []

            rows = []
            Y, M, D = target['date'].split('-')

            try:
                headers = [th.get_text().strip() for th in tb.find_all("th")]
                if headers:
                    logger.debug(f"[SPATIC] 테이블 헤더: {headers}")
            except Exception:
                pass

            for tr in tb.find_all("tr")[1:]:
                tds = tr.find_all("td")
                if len(tds) < 3:
                    logger.debug(f"[SPATIC] 행 건너뜀 (컬럼 부족: {len(tds)} < 3)")
                    continue

                time_cell = tds[1].get_text() if len(tds) > 1 else ""
                place_cell = tds[2].get_text() if len(tds) > 2 else ""

                logger.debug(f"[SPATIC] 행 분석 - 시간: {time_cell[:50]}, 장소: {place_cell[:100]}")

                t_range = time_range_to_tuple(time_cell)
                if not t_range:
                    logger.debug(f"[SPATIC] 시간 파싱 실패: {time_cell}")
                    continue

                places = split_places(place_cell)
                valid_places = [p for p in places if is_valid_place(p)]

                logger.debug(f"[SPATIC] 원본 장소: {places} → 필터링: {valid_places}")

                if not valid_places:
                    logger.debug(f"[SPATIC] 유효한 장소 없음: {place_cell[:100]}")
                    continue

                rows.append({
                    "년": Y,
                    "월": M,
                    "일": D,
                    "start_time": t_range[0],
                    "end_time": t_range[1],
                    "장소_원본": valid_places,
                    "인원": "",
                    "비고": "SPATIC",
                    "title": None,
                    "description": None
                })

            logger.info(f"[SPATIC] {len(rows)}건의 집회 정보 파싱 완료")
            return rows

        except Exception as e:
            logger.error(f"[SPATIC] 상세 정보 파싱 실패: {e}", exc_info=True)
            return []

    @classmethod
    def _scrape_smpa(cls, session: requests.Session) -> List[Dict]:
        """SMPA(서울경찰청)에서 집회 데이터 수집"""
        logger.info("[SMPA] PDF 수집 시작...")
        today_str = datetime.now().strftime("%y%m%d")

        try:
            last_exc: Exception = Exception("SMPA 요청 실패")
            for attempt in range(3):
                try:
                    r = session.get(SMPA_LIST_URL, headers=SMPA_HEADERS, timeout=10)
                    r.raise_for_status()
                    break
                except Exception as e:
                    last_exc = e
                    if attempt < 2:
                        logger.warning(f"[SMPA] 목록 요청 실패 (시도 {attempt + 1}/3): {e}. 2초 후 재시도...")
                        time.sleep(2)
            else:
                raise last_exc
            soup = BeautifulSoup(r.text, "html.parser")

            target_view = None
            for a in soup.select("a[href^='javascript:goBoardView']"):
                if today_str in a.get_text():
                    m = re.search(r"boardNo=(\d+)", a['href']) or re.search(r"'(\d+)'\)", a['href'])
                    if m:
                        target_view = f"{SMPA_BASE_URL}/user/nd54882.do?View&boardNo={m.group(1 if 'boardNo' in a['href'] else 1)}"
                        break

            if not target_view:
                logger.warning("[SMPA] 오늘 날짜의 게시글을 찾을 수 없습니다.")
                return []

            r = session.get(target_view, headers=SMPA_HEADERS, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            pdf_url = None
            for a in soup.find_all("a"):
                if ".pdf" in a.get_text().lower():
                    m = re.search(r"attachfileDownload\('([^']+)'\s*,\s*'(\d+)'\)", a.get("onclick", ""))
                    if m:
                        pdf_url = f"{SMPA_BASE_URL}{m.group(1)}?attachNo={m.group(2)}"
                        break

            if not pdf_url:
                logger.warning("[SMPA] PDF 다운로드 링크를 찾을 수 없습니다.")
                return []

            logger.info(f"[SMPA] PDF 다운로드 시작: {pdf_url}")
            pdf_path = DATA_DIR / f"smpa_{today_str}.pdf"

            r = session.get(pdf_url, headers=SMPA_HEADERS, timeout=10)
            r.raise_for_status()

            with open(pdf_path, "wb") as f:
                f.write(r.content)

            logger.info(f"[SMPA] PDF 다운로드 완료: {pdf_path} (크기: {pdf_path.stat().st_size} bytes)")

            try:
                text = extract_pdf_text_with_fallback(pdf_path)

                if not text:
                    logger.error("[SMPA] PDF에서 텍스트를 추출하지 못했습니다.")
                    return []

            except Exception as e:
                logger.error(f"[SMPA] PDF 텍스트 추출 실패: {e}")
                return []
            finally:
                try:
                    pdf_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"[SMPA] PDF 파일 삭제 실패: {e}")

            pattern = re.compile(r'(?P<start>\d{1,2}:\d{2})\s*~\s*(?P<end>\d{1,2}:\d{2})')
            matches = list(pattern.finditer(text))

            logger.info(f"[SMPA] 정규식 매칭 결과: {len(matches)}개 시간대 발견")

            if not matches:
                logger.warning("[SMPA] PDF에서 시간 정보를 찾을 수 없습니다.")
                logger.debug(f"[SMPA] 검색 패턴: {pattern.pattern}")
                logger.debug(f"[SMPA] 텍스트 샘플 (처음 1000글자): {text[:1000]}")
                return []

            now = datetime.now()
            rows = []

            for i, m in enumerate(matches):
                chunk = text[m.end():(matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()

                logger.debug(f"[SMPA] Chunk {i} (길이: {len(chunk)}): {chunk[:100]}...")

                head_m = re.search(r'(\d+(?:,\d{3})*)\s*명', chunk)
                place_text = chunk[:head_m.start()] if head_m else chunk
                places = split_places(place_text)

                valid_places = [p for p in places if is_valid_place(p)]

                logger.debug(f"[SMPA] 청크 {i} - 원본: {places} → 필터링: {valid_places}")

                if not valid_places:
                    logger.debug(f"[SMPA] {i}번째 청크에서 유효한 장소 추출 실패")
                    continue

                rows.append({
                    "년": now.strftime("%Y"),
                    "월": now.strftime("%m"),
                    "일": now.strftime("%d"),
                    "start_time": m.group('start'),
                    "end_time": m.group('end'),
                    "장소_원본": valid_places,
                    "인원": head_m.group(1).replace(',', '') if head_m else "",
                    "비고": "SMPA",
                    "title": None,
                    "description": None
                })

            logger.info(f"[SMPA] {len(rows)}건의 집회 정보 파싱 완료")
            return rows

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
                3 if attendees and attendees.isdigit() and int(attendees) > 1000 else 2,
                'active'
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
                            category, severity_level, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    logging.basicConfig(level=logging.INFO)
    asyncio.run(CrawlingService.crawl_and_sync_events())
