#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import pathlib
import logging
import asyncio
from datetime import datetime
from collections import OrderedDict
from typing import List, Dict, Tuple, Optional

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text
from playwright.sync_api import sync_playwright
from pydantic_settings import BaseSettings, SettingsConfigDict

# 4번 리뷰 반영: 중앙 스키마 임포트 (경로는 프로젝트 구조에 맞게 설정되어야 함)
from app.database.models import EVENTS_TABLE_SCHEMA

# 로거 설정
logger = logging.getLogger(__name__)

# ------------------------------- 환경 변수 설정 (Pydantic) --------------------------------
class Settings(BaseSettings):
    KAKAO_REST_API_KEY: Optional[str] = None

    # .env 파일에서 로드하며, 정의되지 않은 추가 환경변수는 무시(ignore)합니다.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# ------------------------------- 상수/설정 ------------------------------------
# 프로젝트 루트 기준 data 폴더 설정
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "kt_demo_alarm.db"

# Kakao API Key 설정 (Pydantic Settings에서 가져옴)
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"

# URLs
SPATIC_BASE_URL = "https://www.spatic.go.kr"
SPATIC_LIST_URL = f"{SPATIC_BASE_URL}/spatic/main/assem.do"
SPATIC_DETAIL_FMT = f"{SPATIC_BASE_URL}/spatic/assem/getInfoView.do?mgrSeq={{mgrSeq}}"

SMPA_BASE_URL = "https://www.smpa.go.kr"
SMPA_LIST_URL = f"{SMPA_BASE_URL}/user/nd54882.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


# --------------------------- 공통 유틸리티 ---------------------------
def ensure_dir(p: pathlib.Path):
    p.mkdir(parents=True, exist_ok=True)


def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def parse_date_any(s: str) -> Optional[Tuple[str, str, str]]:
    s = clean_text(s)
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m: return m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return None


def time_range_to_tuple(s: str) -> Optional[Tuple[str, str]]:
    if not s: return None
    s = clean_text(s).replace("∼", "~").replace("〜", "~").replace("–", "-")
    m = re.search(r"(\d{1,2}\s*:\s*\d{2})\s*[~\-]\s*(\d{1,2}\s*:\s*\d{2})", s)
    if m: return re.sub(r"\s*", "", m.group(1)), re.sub(r"\s*", "", m.group(2))
    return None


def split_places(s: str) -> List[str]:
    """장소 텍스트를 개별 장소로 분리"""
    s = clean_text(s).replace("\n", " / ")
    s = re.sub(r'[①-⑨]', ' / ', s)
    parts = re.split(r"\s*(?:→|↔|⟷|⇒|~|/|,|▶|⇄|↔|内|內)\s*", s)

    filtered = []
    for p in parts:
        p = p.strip()
        if len(p) <= 1: continue
        p = re.sub(r'^[內内]$', '', p)
        if p: filtered.append(p)
    return list(OrderedDict.fromkeys(filtered))


# --------------------------- 지오코딩 (Kakao) ---------------------------
PLACE_NAME_REPLACE_MAP = {
    "효자파출소": "청운파출소", "효자치안센터": "청운파출소", "남대문서": "남대문경찰서",
    "파이낸스": "서울파이낸스센터", "의사당역": "국회의사당역", "사랑채": "청와대 사랑채",
    "전쟁기념관": "용산 전쟁기념관"
}

def normalize_place_name_for_kakao(place: str) -> str:
    t = place.strip()
    t = t.replace("구)", "").replace("(구)", "")
    t = re.sub(r'\d+(\.\d+)?km', '', t)
    t = re.sub(r'[<\[\(].*?[>\]\)]', '', t)
    t = re.sub(r'\(.*$', '', t)

    for old, new in PLACE_NAME_REPLACE_MAP.items():
        if old in t and new not in t: t = t.replace(old, new)

    noise_regex = r'(동측|서측|남측|북측|동쪽|서쪽|남쪽|북쪽|건너편|맞은편|옆|방향|방면|부근|일대|진입로|사거리|교차로|출구|입구|인근|앞|뒤|안|밖)'
    t = re.sub(noise_regex, ' ', t)
    t = re.sub(r'[^\w\s\d]', ' ', t)
    return re.sub(r"\s+", " ", t).strip()

def _kakao_api_call(session, url, query, api_key):
    headers = {"Authorization": f"KakaoAK {api_key}"}
    try:
        r = session.get(url, params={"query": query, "size": 1}, headers=headers, timeout=5)
        if r.status_code == 200:
            docs = r.json().get("documents", [])
            if docs:
                addr = docs[0].get('address_name', '')
                if "서울" in addr[:5]:  # 서울 지역 필터링
                    return float(docs[0]['y']), float(docs[0]['x']), addr
    except Exception as e:
        logger.warning(f"[Kakao API] Geocoding failed for {query}: {e}")
    return None, None, None


def geocode_kakao(session, place, api_key):
    clean_name = normalize_place_name_for_kakao(place)
    if not clean_name or len(clean_name) < 2: return None, None, None

    for query in [f"서울 {clean_name}", clean_name]:
        lat, lon, addr = _kakao_api_call(session, KAKAO_KEYWORD_URL, query, api_key)
        if lat: return lat, lon, addr
        lat, lon, addr = _kakao_api_call(session, KAKAO_ADDRESS_URL, query, api_key)
        if lat: return lat, lon, addr
    return None, None, None


# --------------------------- 서비스 클래스 ---------------------------
class CrawlingService:
    """
    main.py의 스케줄러에서 호출되는 크롤링 서비스 클래스
    """

    @classmethod
    async def crawl_and_sync_events(cls):
        """스케줄러 진입점: 라우터와의 호환성을 위해 비동기로 작동하며, 내부의 블로킹 I/O는 별도 스레드에서 실행"""
        logger.info("🔄 [스케줄러] 집회 정보 크롤링을 시작합니다.")
        ensure_dir(DATA_DIR)
        return await asyncio.to_thread(cls._run_sync_pipeline)

    @classmethod
    def _run_sync_pipeline(cls):
        """실제 크롤링이 진행되는 동기 파이프라인 메서드"""
        with requests.Session() as session:
            session.headers.update(HEADERS)

            try:
                # 1. 사이트별 데이터 수집
                spatic_data = cls._scrape_spatic(session)
                smpa_data = cls._scrape_smpa(session)
                data = spatic_data + smpa_data

                if not data:
                    logger.info("ℹ️ [알림] 오늘 수집된 집회 데이터가 없습니다.")
                    return

                logger.info(f"📍 [정제] 총 {len(data)}건의 데이터 지오코딩 진행 중...")

                # 2. 데이터 정제 및 좌표 변환
                final_list = []
                for row in data:
                    for p in row["장소_원본"]:
                        lat, lon, addr = geocode_kakao(session, p, settings.KAKAO_REST_API_KEY)
                        new_row = {k: v for k, v in row.items() if k != "장소_원본"}
                        new_row.update({"장소": p, "위도": lat, "경도": lon, "지번주소": addr})
                        final_list.append(new_row)
                        # API Rate Limit 방지용 딜레이
                        time.sleep(0.1)

                # 3. 데이터베이스 저장
                cls._sync_to_database(final_list)
                logger.info("✅ [완료] 크롤링 및 DB 저장이 성공적으로 완료되었습니다.")

                # 기존 시스템과의 호환성을 위해 결과 딕셔너리 반환
                return {
                    "success": True,
                    "status": "success",
                    "message": "집회 데이터 크롤링 및 동기화 완료",
                    "total_crawled": len(final_list),
                    "inserted_count": len(final_list)
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
        logger.info("[SPATIC] Playwright 목록 수집 시작...")
        posts = []
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
                page.goto(SPATIC_LIST_URL, wait_until="networkidle")
                page.wait_for_selector(".assem_content tr", timeout=15000)
                rows = page.query_selector_all(".assem_content tr")
                for row in rows:
                    mgr = row.get_attribute("key")
                    if not mgr:
                        onclick = row.get_attribute("onclick") or ""
                        m = re.search(r"(\d{4,})", onclick)
                        if m: mgr = m.group(1)

                    tds = row.query_selector_all("td")
                    if len(tds) < 3: continue
                    title = tds[1].inner_text().strip()
                    date_txt = tds[2].inner_text().strip()

                    if mgr and "집회" in title:
                        parsed = parse_date_any(date_txt)
                        if parsed:
                            posts.append(
                                {"number": mgr, "title": title, "date": f"{parsed[0]}-{parsed[1]}-{parsed[2]}"})
            except Exception as e:
                logger.error(f"[SPATIC] Playwright 수집 에러: {e}")
            finally:
                browser.close()

        unique_posts = list({p["number"]: p for p in posts}.values())
        if not unique_posts: return []

        unique_posts.sort(key=lambda x: int(x['number']), reverse=True)
        target = unique_posts[0]

        try:
            r = session.get(SPATIC_DETAIL_FMT.format(mgrSeq=target['number']), timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            tb = soup.find("table")
            if not tb: return []

            rows = []
            Y, M, D = target['date'].split('-')
            for tr in tb.find_all("tr")[1:]:
                tds = tr.find_all("td")
                if len(tds) < 3: continue
                t_range = time_range_to_tuple(tds[1].get_text())
                if not t_range: continue

                rows.append({
                    "년": Y, "월": M, "일": D,
                    "start_time": t_range[0], "end_time": t_range[1],
                    "장소_원본": split_places(tds[2].get_text()),
                    "인원": "",
                    "비고": "SPATIC",
                    "title": None,
                    "description": None
                })
            return rows
        except Exception as e:
            logger.error(f"[SPATIC] 상세 정보 파싱 에러: {e}")
            return []

    @classmethod
    def _scrape_smpa(cls, session: requests.Session) -> List[Dict]:
        logger.info("[SMPA] PDF 수집 시작...")
        today_str = datetime.now().strftime("%y%m%d")
        try:
            r = session.get(SMPA_LIST_URL, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            target_view = None
            for a in soup.select("a[href^='javascript:goBoardView']"):
                if today_str in a.get_text():
                    m = re.search(r"boardNo=(\d+)", a['href']) or re.search(r"'(\d+)'\)", a['href'])
                    if m:
                        target_view = f"{SMPA_BASE_URL}/user/nd54882.do?View&boardNo={m.group(1 if 'boardNo' in a['href'] else 1)}"
                        break
            if not target_view: return []

            r = session.get(target_view)
            soup = BeautifulSoup(r.text, "html.parser")
            pdf_url = None
            for a in soup.find_all("a"):
                if ".pdf" in a.get_text().lower():
                    m = re.search(r"attachfileDownload\('([^']+)'\s*,\s*'(\d+)'\)", a.get("onclick", ""))
                    if m: pdf_url = f"{SMPA_BASE_URL}{m.group(1)}?attachNo={m.group(2)}"

            if not pdf_url: return []
            pdf_path = DATA_DIR / f"smpa_{today_str}.pdf"
            with session.get(pdf_url) as r:
                with open(pdf_path, "wb") as f: f.write(r.content)

            text = extract_text(pdf_path)
            
            # 3번 리뷰 반영: PDF 내용 추출 후 즉시 파일 삭제
            pdf_path.unlink(missing_ok=True) 

            pattern = re.compile(r'(?P<start>\d{1,2}:\d{2})\s*~\s*(?P<end>\d{1,2}:\d{2})')
            matches = list(pattern.finditer(text))
            now = datetime.now()
            rows = []
            for i, m in enumerate(matches):
                chunk = text[m.end():(matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
                head_m = re.search(r'(\d+(?:,\d{3})*)\s*명', chunk)
                rows.append({
                    "년": now.strftime("%Y"), "월": now.strftime("%m"), "일": now.strftime("%d"),
                    "start_time": m.group('start'), "end_time": m.group('end'),
                    "장소_원본": split_places(chunk[:head_m.start()] if head_m else chunk),
                    "인원": head_m.group(1).replace(',', '') if head_m else "",
                    "비고": "SMPA",
                    "title": None,
                    "description": None
                })
            return rows
        except Exception as e:
            logger.error(f"[SMPA] PDF 크롤링 및 파싱 에러: {e}")
            return []

    @classmethod
    def _sync_to_database(cls, data_list: List[Dict]):
        import sqlite3
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()

            # 4번 리뷰 대응: 중앙 스키마를 사용하여 만약 테이블이 없다면 일관된 구조로 생성
            cur.execute(EVENTS_TABLE_SCHEMA)

            insert_data = []
            for r in data_list:
                lat = r.get('위도')
                lon = r.get('경도')

                # 스키마의 NOT NULL 제약조건 방어: 좌표값이 없으면 저장 건너뜀
                if lat is None or lon is None:
                    continue

                year = r.get('년')
                month = str(r.get('월')).zfill(2)
                day = str(r.get('일')).zfill(2)

                # 스키마의 NOT NULL 제약조건 방어: 시간 정보가 없으면 "00:00"을 기본으로 설정
                st_time = r.get('start_time') or "00:00"
                ed_time = r.get('end_time')

                start_date = f"{year}-{month}-{day} {st_time}:00"
                end_date = f"{year}-{month}-{day} {ed_time}:00" if ed_time else None

                place_name = r.get('장소', '알 수 없는 장소')
                attendees = r.get('인원', '')

                # 5번 리뷰 반영: title과 description 생성
                title = r.get('title')
                if not title:
                    title = f"{place_name} 집회"
                    if attendees and attendees.isdigit():
                        title += f" (참가자 {attendees}명)"

                description = r.get('description')
                if not description:
                    description = f"출처: {r.get('비고', '알 수 없음')}"
                    if attendees:
                        description += f" / 예상 인원: {attendees}명"

                insert_data.append((
                    title,
                    description,
                    place_name,
                    r.get('지번주소'),
                    lat,
                    lon,
                    start_date,
                    end_date,
                    '집회',
                    3 if attendees and attendees.isdigit() and int(attendees) > 1000 else 2,
                    'active'
                ))

            if insert_data:
                cur.executemany("""
                    INSERT INTO events (
                        title, description, location_name, location_address,
                        latitude, longitude, start_date, end_date,
                        category, severity_level, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_data)

            conn.commit()
            logger.info(f"데이터베이스에 {len(insert_data)}건의 이벤트 데이터가 성공적으로 저장되었습니다.")

        except Exception as e:
            logger.error(f"SQLite3 저장 중 에러: {e}", exc_info=True)
        finally:
            if 'conn' in locals():
                conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(CrawlingService.crawl_and_sync_events())