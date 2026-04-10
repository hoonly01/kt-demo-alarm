#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
집회 데이터 크롤링 서비스

SMPA(서울경찰청) + SPATIC 양쪽 소스에서 집회 정보를 수집하고,
Kakao API로 지오코딩을 수행하여 events 테이블에 동기화합니다.
"""

import re
import time
import pathlib
import logging
import asyncio
from datetime import datetime
from collections import OrderedDict
from typing import List, Dict, Tuple, Optional

from app.database.connection import get_db_connection, DATABASE_PATH
from app.config.settings import settings

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text
from playwright.sync_api import sync_playwright

# 로거 설정
logger = logging.getLogger(__name__)

# ------------------------------- 상수/설정 ------------------------------------
# 프로젝트 루트 기준 data 폴더 설정 (개선: 절대 경로로 통일)
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
if not pathlib.Path(DATABASE_PATH).is_absolute():
    DB_ABS_PATH = BASE_DIR / DATABASE_PATH
else:
    DB_ABS_PATH = pathlib.Path(DATABASE_PATH)
DATA_DIR = DB_ABS_PATH.parent

# Kakao API URLs
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"

# SPATIC URLs
SPATIC_BASE_URL = "https://www.spatic.go.kr"
SPATIC_LIST_URL = f"{SPATIC_BASE_URL}/spatic/main/assem.do"
SPATIC_DETAIL_FMT = f"{SPATIC_BASE_URL}/spatic/assem/getInfoView.do?mgrSeq={{mgrSeq}}"

# SMPA URLs
SMPA_BASE_URL = "https://www.smpa.go.kr"
SMPA_LIST_URL = f"{SMPA_BASE_URL}/user/nd54882.do"

# HTTP Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# 서울 중심 좌표 (지오코딩 실패 시 폴백용)
DEFAULT_SEOUL_LAT = 37.5665
DEFAULT_SEOUL_LON = 126.9780

# Kakao API 설정
KAKAO_API_TIMEOUT = 5
KAKAO_RATE_LIMIT_DELAY = 0.1  # API Rate Limit 방지용
MAX_GEOCODING_RETRIES = 2
GEOCODING_RETRY_DELAY = 1  # 재시도 간 대기 시간

# PDF 처리
PDF_EXTRACTION_TIMEOUT = 30


# --------------------------- 공통 유틸리티 ---------------------------
def ensure_dir(p: pathlib.Path) -> None:
    """디렉토리 생성 (없으면 생성, 있으면 무시)"""
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"[유틸] 디렉토리 생성 실패: {p} - {e}")


def clean_text(t: str) -> str:
    """텍스트 공백 정규화"""
    return re.sub(r"\s+", " ", t or "").strip()


def parse_date_any(s: str) -> Optional[Tuple[str, str, str]]:
    """다양한 날짜 형식에서 (YYYY, MM, DD) 추출"""
    s = clean_text(s)
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return None


def time_range_to_tuple(s: str) -> Optional[Tuple[str, str]]:
    """시간 범위 문자열을 (시작, 종료) 튜플로 변환"""
    if not s:
        return None
    s = clean_text(s).replace("∼", "~").replace("〜", "~").replace("–", "-")
    m = re.search(r"(\d{1,2}\s*:\s*\d{2})\s*[~\-]\s*(\d{1,2}\s*:\s*\d{2})", s)
    if m:
        return re.sub(r"\s*", "", m.group(1)), re.sub(r"\s*", "", m.group(2))
    return None


def split_places(s: str) -> List[str]:
    """장소 텍스트를 개별 장소로 분리"""
    s = clean_text(s).replace("\n", " / ")
    s = re.sub(r'[①-⑨]', ' / ', s)
    parts = re.split(r"\s*(?:→|↔|⟷|⇒|~|/|,|▶|⇄|↔|内|內|※)\s*", s)

    filtered = []
    for p in parts:
        p = p.strip()
        if len(p) <= 1:
            continue
        p = re.sub(r'^[內内]$', '', p)
        if p:
            filtered.append(p)
    return list(OrderedDict.fromkeys(filtered))


# --------------------------- 지오코딩 (Kakao) ---------------------------
PLACE_NAME_REPLACE_MAP = {
    "효자파출소": "청운파출소",
    "효자치안센터": "청운파출소",
    "남대문서": "남대문경찰서",
    "파이낸스": "서울파이낸스센터",
    "의사당역": "국회의사당역",
    "사랑채": "청와대 사랑채",
    "전쟁기념관": "용산 전쟁기념관"
}


def normalize_place_name_for_kakao(place: str) -> str:
    """Kakao API 쿼리용 장소명 정규화"""
    t = place.strip()
    # 구분자 제거
    t = t.replace("구)", "").replace("(구)", "")
    # 거리 정보 제거
    t = re.sub(r'\d+(\.\d+)?km', '', t)
    # 괄호 내용 제거
    t = re.sub(r'[<\[\(].*?[>\]\)]', '', t)
    t = re.sub(r'\(.*$', '', t)

    # 지명 치환
    for old, new in PLACE_NAME_REPLACE_MAP.items():
        if old in t and new not in t:
            t = t.replace(old, new)

    # 방향 지시어 제거
    noise_regex = r'(동측|서측|남측|북측|동쪽|서쪽|남쪽|북쪽|건너편|맞은편|옆|방향|방면|부근|일대|진입로|사거리|교차로|출구|입구|인근|앞|뒤|안|밖)'
    t = re.sub(noise_regex, ' ', t)
    t = re.sub(r'[^\w\s\d]', ' ', t)
    return re.sub(r"\s+", " ", t).strip()


def _kakao_api_call(
    session: requests.Session,
    url: str,
    query: str,
    api_key: str,
    attempt: int = 1
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Kakao API 호출 (단일 URL)
    
    Args:
        session: requests.Session 인스턴스
        url: API 엔드포인트 (keyword 또는 address)
        query: 검색 쿼리
        api_key: Kakao REST API Key
        attempt: 현재 재시도 횟수
    
    Returns:
        (위도, 경도, 주소) 또는 (None, None, None)
    """
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
                # 서울 지역 필터링
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
    Kakao API를 사용한 다중 쿼리 지오코딩
    
    Args:
        session: requests.Session 인스턴스
        place: 장소명
        api_key: Kakao REST API Key
    
    Returns:
        (위도, 경도, 주소) 또는 (None, None, None)
    """
    # API Key 검증
    if not api_key or not api_key.strip():
        logger.error("[Kakao] API Key가 설정되지 않았습니다. .env 파일에 KAKAO_REST_API_KEY를 설정하세요.")
        return None, None, None
    
    clean_name = normalize_place_name_for_kakao(place)
    if not clean_name or len(clean_name) < 2:
        logger.debug(f"[Kakao] 정규화 실패 (너무 짧음): {place}")
        return None, None, None

    # 다중 쿼리 시도 순서
    queries = [
        f"서울 {clean_name}",
        clean_name,
    ]
    
    # 토큰으로 분리된 경우 추가 쿼리 생성
    tokens = clean_name.split()
    if len(tokens) > 1:
        queries.append(f"서울 {tokens[-1]}")
        queries.append(f"서울 {tokens[0]}")
    
    # 역 키워드 추가
    if not clean_name.endswith("역") and len(clean_name) <= 5:
        queries.append(f"서울 {clean_name}역")

    # 중복 제거
    queries = list(OrderedDict.fromkeys(queries))

    logger.debug(f"[Kakao] 지오코딩 시도: {place} - 쿼리: {queries[:2]}")

    for query in queries:
        if len(query.replace("서울", "").strip()) < 2:
            continue
        
        # Keyword API 먼저 시도
        lat, lon, addr = _kakao_api_call(session, KAKAO_KEYWORD_URL, query, api_key)
        if lat and lon:
            return lat, lon, addr
        
        # Address API 시도
        lat, lon, addr = _kakao_api_call(session, KAKAO_ADDRESS_URL, query, api_key)
        if lat and lon:
            return lat, lon, addr
        
        # Rate Limit 방지
        time.sleep(KAKAO_RATE_LIMIT_DELAY)

    logger.warning(f"[Kakao] 지오코딩 실패: {place}")
    return None, None, None


# --------------------------- 서비스 클래스 ---------------------------
class CrawlingService:
    """
    main.py의 스케줄러에서 호출되는 크롤링 서비스 클래스
    
    SMPA(서울경찰청) + SPATIC(경찰청 집회 시스템) 양쪽에서
    집회 정보를 크롤링하여 데이터베이스에 동기화합니다.
    """

    @classmethod
    async def crawl_and_sync_events(cls) -> Dict:
        """
        스케줄러 진입점
        
        라우터와의 호환성을 위해 비동기로 작동하며,
        내부의 블로킹 I/O는 별도 스레드에서 실행됩니다.
        """
        logger.info("🔄 [스케줄러] 집회 정보 크롤링을 시작합니다.")
        
        # 데이터 디렉토리 생성
        ensure_dir(DATA_DIR)
        
        # 환경변수 검증
        if not settings.KAKAO_REST_API_KEY or not settings.KAKAO_REST_API_KEY.strip():
            error_msg = "❌ KAKAO_REST_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요."
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "total_crawled": 0
            }
        
        # 동기 파이프라인 실행
        return await asyncio.to_thread(cls._run_sync_pipeline)

    @classmethod
    def _run_sync_pipeline(cls) -> Dict:
        """실제 크롤링이 진행되는 동기 파이프라인 메서드"""
        with requests.Session() as session:
            session.headers.update(HEADERS)

            try:
                # 1. 사이트별 데이터 수집
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

                # 2. 데이터 정제 및 좌표 변환
                final_list = []
                geocoding_failed_count = 0
                
                for row in data:
                    places = row.get("장소_원본", [])
                    for place in places:
                        lat, lon, addr = geocode_kakao(session, place, settings.KAKAO_REST_API_KEY)
                        
                        new_row = {k: v for k, v in row.items() if k != "장소_원본"}
                        new_row.update({
                            "장소": place,
                            "위도": lat,
                            "경도": lon,
                            "지번주소": addr
                        })
                        
                        # 지오코딩 실패 시 기본 좌표 사용
                        if lat is None or lon is None:
                            geocoding_failed_count += 1
                            logger.warning(
                                f"[정제] {place} 지오코딩 실패 - 기본 좌표(서울시청) 사용"
                            )
                            new_row["위도"] = DEFAULT_SEOUL_LAT
                            new_row["경도"] = DEFAULT_SEOUL_LON
                        
                        final_list.append(new_row)
                        # API Rate Limit 방지용 딜레이
                        time.sleep(KAKAO_RATE_LIMIT_DELAY)

                if geocoding_failed_count > 0:
                    logger.warning(
                        f"⚠️  [정제] {geocoding_failed_count}건의 장소 지오코딩 실패 - 기본 좌표로 대체됨"
                    )

                # 3. 데이터베이스 저장
                inserted_count = cls._sync_to_database(final_list)
                
                logger.info(f"✅ [완료] 크롤링 및 DB 저장이 완료되었습니다. (저장된 데이터: {inserted_count}건)")

                return {
                    "success": True,
                    "status": "success",
                    "message": "집회 데이터 크롤링 및 동기화 완료",
                    "total_crawled": len(final_list),
                    "inserted_count": inserted_count,
                    "geocoding_failed": geocoding_failed_count
                }

            except Exception as e:
                logger.error(f"❌ [크롤링 실패] 크롤링 파이프라인 실행 중 오류 발생: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": str(e),
                    "total_crawled": 0
                }

    @classmethod
    def _scrape_spatic(cls, session: requests.Session) -> List[Dict]:
        """
        SPATIC(경찰청 집회 안내 시스템)에서 집회 데이터 수집
        
        Playwright를 사용하여 JavaScript 렌더링 페이지에서 데이터를 추출합니다.
        """
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

        # 중복 제거
        unique_posts = list({p["number"]: p for p in posts}.values())
        if not unique_posts:
            logger.info("[SPATIC] 집회 관련 게시글을 찾을 수 없습니다.")
            return []

        # 가장 최신 게시물 선택
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
            
            for tr in tb.find_all("tr")[1:]:
                tds = tr.find_all("td")
                if len(tds) < 3:
                    continue
                
                t_range = time_range_to_tuple(tds[1].get_text())
                if not t_range:
                    continue

                rows.append({
                    "년": Y,
                    "월": M,
                    "일": D,
                    "start_time": t_range[0],
                    "end_time": t_range[1],
                    "장소_원본": split_places(tds[2].get_text()),
                    "인원": "",
                    "비고": "SPATIC",
                    "title": None,
                    "description": None
                })
            
            logger.info(f"[SPATIC] {len(rows)}건의 집회 정보 파싱 완료")
            return rows
            
        except Exception as e:
            logger.error(f"[SPATIC] 상세 정보 파싱 실패: {e}")
            return []

    @classmethod
    def _scrape_smpa(cls, session: requests.Session) -> List[Dict]:
        """
        SMPA(서울경찰청)에서 집회 데이터 수집
        
        오늘 날짜의 PDF 문서를 다운로드하여 집회 정보를 추출합니다.
        """
        logger.info("[SMPA] PDF 수집 시작...")
        today_str = datetime.now().strftime("%y%m%d")
        
        try:
            # 1. 목록 페이지에서 오늘자 게시글 찾기
            r = session.get(SMPA_LIST_URL, timeout=10)
            r.raise_for_status()
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

            # 2. 뷰 페이지 접속
            r = session.get(target_view, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            
            # 3. PDF 다운로드 링크 찾기
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

            # 4. PDF 다운로드 (개선: 컨텍스트 매니저 올바르게 사용)
            logger.info(f"[SMPA] PDF 다운로드 시작: {pdf_url}")
            pdf_path = DATA_DIR / f"smpa_{today_str}.pdf"
            
            r = session.get(pdf_url, timeout=10)
            r.raise_for_status()
            
            with open(pdf_path, "wb") as f:
                f.write(r.content)
            
            logger.info(f"[SMPA] PDF 다운로드 완료: {pdf_path}")

            # 5. PDF 텍스트 추출
            try:
                text = extract_text(pdf_path)
            except Exception as e:
                logger.error(f"[SMPA] PDF 텍스트 추출 실패: {e}")
                return []
            finally:
                # PDF 파일 삭제 (정보 추출 후 즉시 삭제)
                try:
                    pdf_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"[SMPA] PDF 파일 삭제 실패: {e}")

            # 6. 텍스트에서 집회 정보 파싱
            pattern = re.compile(r'(?P<start>\d{1,2}:\d{2})\s*~\s*(?P<end>\d{1,2}:\d{2})')
            matches = list(pattern.finditer(text))
            
            if not matches:
                logger.warning("[SMPA] PDF에서 시간 정보를 찾을 수 없습니다.")
                return []
            
            now = datetime.now()
            rows = []
            
            for i, m in enumerate(matches):
                chunk = text[m.end():(matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
                head_m = re.search(r'(\d+(?:,\d{3})*)\s*명', chunk)
                
                rows.append({
                    "년": now.strftime("%Y"),
                    "월": now.strftime("%m"),
                    "일": now.strftime("%d"),
                    "start_time": m.group('start'),
                    "end_time": m.group('end'),
                    "장소_원본": split_places(chunk[:head_m.start()] if head_m else chunk),
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
        """
        크롤링된 집회 정보를 데이터베이스에 저장
        
        Args:
            data_list: 크롤링된 데이터 리스트
        
        Returns:
            실제 삽입된 행의 개수
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

            # 필수 값 검증
            if start_date is None:
                skipped_count += 1
                logger.warning(f"[DB] 필수 값 누락으로 삽입 스킵 - 장소: {place_name}, 시작시간: {st_time}")
                continue

            # NOT NULL 제약이 있는 lat, lon도 이미 폴백 처리됨
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

        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                
                # 중복 방지 인덱스 생성 시도
                try:
                    cur.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_location_date
                        ON events(location_name, start_date)
                    """)
                except Exception:
                    # 이미 존재하거나 기존 데이터 충돌 시 무시
                    pass
                
                # 데이터 삽입
                cur.executemany("""
                    INSERT OR IGNORE INTO events (
                        title, description, location_name, location_address,
                        latitude, longitude, start_date, end_date,
                        category, severity_level, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_data)
                
                # 실제 삽입된 행의 개수 확인
                inserted_count = cur.rowcount
                conn.commit()
                
                logger.info(f"✅ [DB] 데이터베이스에 {len(insert_data)}건 중 {inserted_count}건의 이벤트 데이터가 저장되었습니다.")
                return inserted_count
                
        except Exception as e:
            logger.error(f"❌ [DB] SQLite3 저장 중 오류: {e}", exc_info=True)
            return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(CrawlingService.crawl_and_sync_events())