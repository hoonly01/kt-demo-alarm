"""집회 데이터 크롤링 서비스

SMPA(서울경찰청) + SPATIC 양쪽 소스에서 집회 정보를 수집하여
events 테이블에 동기화합니다.
"""
import asyncio
import logging
import sqlite3
import os
import re
import json
import time
import urllib.parse
import shutil
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import httpx
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text
from zoneinfo import ZoneInfo

from app.database.connection import DATABASE_PATH
from app.services.spatic_crawler import scrape_spatic, split_places

logger = logging.getLogger(__name__)

# SMPA 크롤링 상수들 (MinhaKim02 구현 기반)
BASE_URL = "https://www.smpa.go.kr"
LIST_URL = f"{BASE_URL}/user/nd54882.do"

# 지명 치환 맵 (v2 지오코딩 정확도 향상)
PLACE_NAME_REPLACE_MAP = {
    "효자파출소": "청운파출소",
    "효자치안센터": "청운파출소",
    "남대문서": "남대문경찰서",
    "파이낸스": "서울파이낸스센터",
    "의사당역": "국회의사당역",
    "사랑채": "청와대 사랑채",
    "전쟁기념관": "용산 전쟁기념관",
}


class CrawlingService:
    """SMPA 집회 데이터 크롤링 비즈니스 로직"""

    @staticmethod
    async def crawl_and_sync_events() -> Dict[str, Any]:
        """
        SMPA 집회 데이터 크롤링 및 동기화
        main_old.py의 crawl_and_sync_events_to_db() 로직 기반
        
        Returns:
            Dict: 크롤링 결과
        """
        try:
            logger.info("=== SMPA 집회 데이터 크롤링 시작 ===")
            
            # 1. 오늘 집회 정보 크롤링 및 파싱
            logger.info("집회 정보 크롤링 및 파싱 시작")
            new_events = await CrawlingService._crawl_and_parse_today_events()
            
            if not new_events:
                return {
                    "success": True,
                    "status": "warning",
                    "message": "크롤링된 이벤트가 없습니다",
                    "total_crawled": 0
                }
            
            # 2. 데이터베이스 동기화
            db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            
            try:
                inserted_count = await CrawlingService._sync_events_to_db(new_events, db)
                
                logger.info(f"=== 크롤링 완료: {inserted_count}개 새 집회 추가 ===")
                
                return {
                    "success": True,
                    "status": "success",
                    "message": f"집회 데이터 크롤링 및 동기화 완료",
                    "total_crawled": len(new_events),
                    "inserted_count": inserted_count
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"크롤링 중 오류 발생: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "total_crawled": 0
            }

    @staticmethod
    async def _crawl_and_parse_today_events() -> List[Dict[str, Any]]:
        """
        오늘 집회 정보를 SMPA + SPATIC 양쪽에서 크롤링하고 파싱하여 DB 형식으로 반환
        """
        # 1. SMPA 크롤링 (기존 PDF 기반)
        smpa_events = await CrawlingService._crawl_smpa_events()
        logger.info(f"SMPA 크롤링 결과: {len(smpa_events)}건")

        # 2. SPATIC 크롤링 (신규, Selenium 기반 — 실패 시 빈 리스트)
        spatic_events = await CrawlingService._crawl_spatic_events()
        logger.info(f"SPATIC 크롤링 결과: {len(spatic_events)}건")

        # 3. 병합 및 중복 제거
        raw_events = CrawlingService._merge_and_deduplicate(smpa_events, spatic_events)
        logger.info(f"병합 후 총: {len(raw_events)}건")

        if not raw_events:
            return []

        # 4. DB 형식으로 변환
        logger.info("DB 형식으로 데이터 변환 시작")
        db_events = await CrawlingService._convert_raw_events_to_db_format(raw_events)
        logger.info(f"DB 형식 변환 완료: {len(db_events)}개 이벤트")

        return db_events

    @staticmethod
    async def _crawl_smpa_events() -> List[Dict[str, Any]]:
        """
        SMPA(서울경찰청) PDF 기반 크롤링 (기존 로직 분리)
        """
        temp_dir = "temp_pdfs"
        try:
            logger.info("SMPA 사이트에서 오늘자 PDF 다운로드 시작")
            pdf_path, title_text = await CrawlingService._download_today_pdf_with_title(out_dir=temp_dir)
            logger.info(f"PDF 다운로드 성공: {pdf_path}")

            ymd = CrawlingService._extract_ymd_from_title(title_text)
            if ymd:
                logger.info(f"제목에서 날짜 추출: {ymd[0]}-{ymd[1]}-{ymd[2]}")
            else:
                logger.warning("제목에서 날짜 추출 실패, 현재 날짜 사용")
                now = datetime.now()
                ymd = (str(now.year), f"{now.month:02d}", f"{now.day:02d}")

            logger.info("PDF 파싱 시작")
            raw_events = CrawlingService._parse_pdf(pdf_path, ymd=ymd)
            logger.info(f"PDF 파싱 완료: {len(raw_events)}개 집회 정보 추출")

            # SMPA 결과에 장소_원본 필드 추가 (병합 호환)
            for row in raw_events:
                place_raw = str(row.get('장소', '')).strip()
                if place_raw.startswith('[') and place_raw.endswith(']'):
                    try:
                        places = json.loads(place_raw)
                    except json.JSONDecodeError:
                        places = split_places(place_raw)
                else:
                    places = split_places(place_raw) if place_raw else []
                row['장소_원본'] = places
                row['비고'] = row.get('비고', '') or 'SMPA'

            try:
                os.remove(pdf_path)
            except OSError:
                pass

            return raw_events

        except Exception as e:
            logger.error(f"SMPA 크롤링 실패: {e}")
            return []
        finally:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except OSError:
                pass

    @staticmethod
    async def _crawl_spatic_events() -> List[Dict[str, Any]]:
        """
        SPATIC(경찰청 집회 시스템) 크롤링 — Selenium 필요, 실패 시 빈 리스트
        """
        try:
            # 동기 함수를 비동기로 실행
            rows = await asyncio.to_thread(scrape_spatic)
            return rows
        except Exception as e:
            logger.warning(f"SPATIC 크롤링 실패 (무시): {e}")
            return []

    @staticmethod
    def _merge_and_deduplicate(
        smpa_list: List[Dict], spatic_list: List[Dict]
    ) -> List[Dict]:
        """
        SMPA와 SPATIC 결과를 병합하고 중복 제거 (v2 로직 포팅)
        """
        combined = smpa_list + spatic_list
        merged = []
        seen = set()

        for row in combined:
            y = row.get("년", "")
            m = row.get("월", "")
            d = row.get("일", "")
            start = row.get("start_time", "")
            places = row.get("장소_원본", [])

            unique_places = []
            for p in places:
                key = f"{y}{m}{d}_{start}_{re.sub(r'\\s+', '', p)}"
                if key not in seen:
                    seen.add(key)
                    unique_places.append(p)

            if unique_places:
                new_row = row.copy()
                new_row["장소_원본"] = unique_places
                merged.append(new_row)

        return merged

    @staticmethod
    async def _sync_events_to_db(events: List[Dict[str, Any]], db: sqlite3.Connection) -> int:
        """
        크롤링된 집회 정보를 DB에 동기화
        main_old.py의 DB 동기화 로직 기반
        
        Args:
            events: 크롤링된 집회 정보 리스트
            db: 데이터베이스 연결
            
        Returns:
            int: 새로 삽입된 이벤트 수
        """
        if not events:
            return 0
            
        cursor = db.cursor()
        inserted_count = 0
        duplicate_count = 0
        error_count = 0
        
        try:
            db.execute("BEGIN TRANSACTION")
            
            for i, event in enumerate(events):
                try:
                    # 중복 체크 (제목과 날짜로 정확한 검사)
                    cursor.execute("""
                        SELECT id FROM events 
                        WHERE (
                            (location_name = ? AND DATE(start_date) = DATE(?))
                            OR (title = ? AND DATE(start_date) = DATE(?))
                        )
                        LIMIT 1
                    """, (
                        event['location_name'], event['start_date'],
                        event['title'], event['start_date']
                    ))
                    
                    existing = cursor.fetchone()
                    
                    if existing:
                        duplicate_count += 1
                        logger.debug(f"중복 이벤트 건너뜀: {event['title']}")
                    else:
                        # 새 이벤트 삽입
                        cursor.execute("""
                            INSERT INTO events 
                            (title, description, location_name, location_address, latitude, longitude, 
                             start_date, end_date, category, severity_level, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            event['title'], event['description'], event['location_name'], 
                            event['location_address'], event['latitude'], event['longitude'],
                            event['start_date'], event['end_date'], event['category'],
                            event['severity_level'], event['status']
                        ))
                        inserted_count += 1
                        logger.debug(f"새 이벤트 삽입: {event['title']}")
                        
                except sqlite3.Error as db_error:
                    error_count += 1
                    logger.error(f"이벤트 {i+1} DB 삽입 실패: {db_error}")
                    continue
            
            db.commit()
            logger.info(f"DB 트랜잭션 커밋 완료: {inserted_count}개 삽입, {duplicate_count}개 중복, {error_count}개 오류")
            
        except Exception as tx_error:
            db.rollback()
            logger.error(f"DB 트랜잭션 실패, 롤백: {tx_error}")
            raise
        
        return inserted_count

    # ========= MinhaKim02 크롤링 알고리즘 구현 =========
    
    @staticmethod
    def _parse_goBoardView(href: str) -> Optional[Tuple[str, str, str]]:
        """goBoardView 자바스크립트 함수 인자 파싱 (원본 by MinhaKim02)"""
        m = re.search(r"goBoardView\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'(\d+)'\)", href)
        if not m:
            return None
        return m.group(1), m.group(2), m.group(3)

    @staticmethod
    def _build_view_urls(board_no: str) -> List[str]:
        """게시판 뷰 URL 생성 (원본 by MinhaKim02)"""
        return [
            f"{BASE_URL}/user/nd54882.do?View&boardNo={board_no}",
            f"{BASE_URL}/user/nd54882.do?dmlType=View&boardNo={board_no}",
        ]

    @staticmethod
    def _extract_ymd_from_title(title: str) -> Optional[Tuple[str, str, str]]:
        """제목에서 YYMMDD를 찾아 (YYYY, MM, DD)로 변환 (원본 by MinhaKim02)"""
        if not title:
            return None
        m = re.search(r'(\d{2})(\d{2})(\d{2})', title)
        if not m:
            return None
        yy, mm, dd = m.group(1), m.group(2), m.group(3)
        yyyy = f"20{yy}"
        return (yyyy, mm, dd)

    @staticmethod
    def _current_title_pattern() -> Tuple[str, str]:
        """오늘 날짜 기반 제목 패턴 생성 (원본 by MinhaKim02)"""
        now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
        current_date = now_kst.strftime("%y%m%d")
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        current_day = weekdays[now_kst.weekday()]
        return current_date, f"오늘의 집회 {current_date} {current_day}"

    @staticmethod
    async def _get_today_post_info(client: httpx.AsyncClient, list_url: str = LIST_URL) -> Tuple[str, str]:
        """
        목록 페이지에서 오늘자 게시글의 뷰 URL과 제목을 반환 (원본 by MinhaKim02)
        """
        current_date, expected_full = CrawlingService._current_title_pattern()
        r = await client.get(list_url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        tbody = soup.select_one("#subContents > div > div.inContent > table > tbody")
        targets = tbody.select("a[href^='javascript:goBoardView']") if tbody \
            else soup.select("a[href^='javascript:goBoardView']")

        target_link = None
        target_title = None
        for a in targets:
            title = a.get_text(strip=True) or (a.find_parent('td').get_text(strip=True) if a.find_parent('td') else "")
            href = a.get("href", "")
            if expected_full in title or f"오늘의 집회 {current_date}" in title:
                target_link = href
                target_title = title
                break

        if not target_link:
            raise RuntimeError("오늘 날짜 게시글을 찾지 못했습니다.")

        parsed = CrawlingService._parse_goBoardView(target_link)
        if not parsed:
            raise RuntimeError("goBoardView 인자를 파싱하지 못했습니다.")
        _, _, board_no = parsed

        for url in CrawlingService._build_view_urls(board_no):
            resp = session.get(url, timeout=20)
            if resp.ok and "html" in (resp.headers.get("Content-Type") or "").lower():
                return url, (target_title or "")
        raise RuntimeError("View 페이지 요청에 실패했습니다.")

    @staticmethod
    def _parse_attach_onclick(a_tag):
        """첨부파일 다운로드 onclick 파싱 (원본 by MinhaKim02)"""
        oc = a_tag.get("onclick", "")
        m = re.search(r"attachfileDownload\('([^']+)'\s*,\s*'(\d+)'\)", oc)
        if not m:
            return None
        return m.group(1), m.group(2)

    @staticmethod
    def _is_pdf(resp: httpx.Response, first: bytes) -> bool:
        """PDF 파일 여부 확인 (원본 by MinhaKim02)"""
        ct = (resp.headers.get("Content-Type") or "").lower()
        return first.startswith(b"%PDF-") or "pdf" in ct

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """파일명 안전하게 변환"""
        return re.sub(r'[<>:"/\|?*]', '_', filename)

    @staticmethod
    def _filename_from_cd(content_disposition: str) -> Optional[str]:
        """Content-Disposition 헤더에서 파일명 추출"""
        if not content_disposition:
            return None
        m = re.search(r'filename\*?=([^;]+)', content_disposition)
        if m:
            value = m.group(1).strip('"\'')
            if value.startswith('UTF-8'):
                # UTF-8''filename 형태 처리
                parts = value.split("''", 1)
                if len(parts) == 2:
                    return urllib.parse.unquote(parts[1])
            return value
        return None

    @staticmethod
    async def _download_from_view(client: httpx.AsyncClient, view_url: str, out_dir: str = "temp") -> str:
        """
        게시글 뷰 페이지에서 PDF 첨부파일 다운로드 (원본 by MinhaKim02)
        """
        os.makedirs(out_dir, exist_ok=True)
        
        r = await client.get(view_url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        candidates = []
        for a in soup.find_all("a"):
            oc = a.get("onclick", "")
            if "attachfileDownload" in oc:
                txt = (a.get_text(strip=True) or "").lower()
                if "pdf" in txt or ".pdf" in txt:
                    candidates.append(a)
        if not candidates:
            candidates = [a for a in soup.find_all("a") if "attachfileDownload" in (a.get("onclick", "") or "")]

        last_error = None
        for a_tag in candidates:
            parsed = CrawlingService._parse_attach_onclick(a_tag)
            if not parsed:
                continue
            path, attach_no = parsed
            download_url = urllib.parse.urljoin(BASE_URL, path)
            try:
                async with client.stream("GET", download_url, params={"attachNo": attach_no}, timeout=30) as resp:
                    resp.raise_for_status()
                    first_chunk = b""
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        if not first_chunk:
                            first_chunk = chunk
                            if not CrawlingService._is_pdf(resp, first_chunk):
                                break
                            cd = resp.headers.get("Content-Disposition", "")
                            filename = CrawlingService._filename_from_cd(cd) or (a_tag.get_text(strip=True) or f"{attach_no}.pdf")
                            root, ext = os.path.splitext(filename)
                            if ext.lower() != ".pdf":
                                filename = root + ".pdf"
                            filename = CrawlingService._sanitize_filename(filename)
                            save_path = os.path.join(out_dir, filename)
                            f = open(save_path, "wb")
                        
                        if chunk:
                            f.write(chunk)
                    
                    if first_chunk:
                        f.close()
                        return save_path
            except Exception as e:
                last_error = e
                continue
        if last_error:
            raise last_error
        raise RuntimeError("PDF 첨부 다운로드에 실패했습니다.")

    @staticmethod
    async def _download_today_pdf_with_title(out_dir: str = "temp") -> Tuple[str, str]:
        """
        오늘자 게시글의 PDF를 다운로드하고 제목과 함께 반환 (원본 by MinhaKim02)
        """
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            'Referer': LIST_URL,
        }
        
        async with httpx.AsyncClient(headers=headers) as client:
            view_url, title_text = await CrawlingService._get_today_post_info(client, LIST_URL)
            pdf_path = await CrawlingService._download_from_view(client, view_url, out_dir=out_dir)
            return pdf_path, title_text

    # PDF 파싱 로직 (원본 by MinhaKim02)
    TIME_RE = re.compile(
        r'(?P<start>\d{1,2}\s*:\s*\d{2})\s*~\s*(?P<end>\d{1,2}\s*:\s*\d{2})',
        re.DOTALL
    )

    @staticmethod
    def _normalize_time_breaks(text: str) -> str:
        """PDF 텍스트의 시간 표기 정규화 (원본 by MinhaKim02)"""
        t = text
        t = re.sub(r'(\d{1,2})\s*\n\s*:\s*(\d{2})', r'\1:\2', t)  # "18\n:00" → "18:00"
        t = re.sub(r'(\d{1,2}\s*:\s*\d{2})\s*\n\s*~\s*\n\s*(\d{1,2}\s*:\s*\d{2})',
                   r'\1~\2', t)  # "12:00\n~\n13:30" → "12:00~13:30"
        return t

    @staticmethod
    def _collapse_korean_gaps(s: str) -> str:
        """한국어 텍스트 간격 정리 (원본 by MinhaKim02)"""
        def fix_token(tok: str) -> str:
            core = tok.replace(" ", "")
            if re.fullmatch(r'[가-힣]+', core) and 2 <= len(core) <= 5:
                return core
            return tok
        return " ".join(fix_token(t) for t in s.split())

    @staticmethod
    def _extract_place_nodes(place_text: str) -> List[str]:
        """장소 텍스트에서 노드들 추출 (원본 by MinhaKim02)"""
        clean = re.sub(r'<[^>]+>', ' ', place_text)  # 보조정보 제거
        clean = re.sub(r'\s+', ' ', clean).strip()
        parts = re.split(r'\s*(?:→|↔|~)\s*', clean)  # 경로 구분자
        nodes = [p.strip() for p in parts if p.strip()]
        return nodes

    @staticmethod
    def _extract_headcount(block: str) -> Optional[Tuple[str, Tuple[int, int]]]:
        """텍스트 블록에서 인원수 추출 (원본 by MinhaKim02)"""
        m = re.search(r'(\d{1,3}(?:,\d{3})*)\s*명', block)
        if m:
            return m.group(1), m.span()
        for m2 in re.finditer(r'(\d{1,3}(?:,\d{3})*|\d{3,})', block):
            num = m2.group(1)
            tail = block[m2.end(): m2.end()+1]
            if tail == '出':  # 출구 번호 오검출 방지
                continue
            try:
                val = int(num.replace(',', ''))
                if val >= 100 or (',' in num):
                    return num, m2.span()
            except ValueError:
                pass
        return None

    @staticmethod
    def _parse_pdf(pdf_path: str, ymd: Optional[Tuple[str, str, str]] = None) -> List[Dict[str, str]]:
        """
        PDF 파일에서 집회 정보 파싱 (원본 by MinhaKim02)
        """
        raw = extract_text(pdf_path) or ""
        text = CrawlingService._normalize_time_breaks(raw)

        rows: List[Dict[str, str]] = []
        matches = list(CrawlingService.TIME_RE.finditer(text))
        
        for i, m in enumerate(matches):
            start_t = re.sub(r'\s+', '', m.group('start'))
            end_t   = re.sub(r'\s+', '', m.group('end'))

            start_idx = m.end()
            end_idx = matches[i+1].start() if i+1 < len(matches) else len(text)
            chunk = text[start_idx:end_idx].strip()

            # 인원 추출
            head = CrawlingService._extract_headcount(chunk)
            if head:
                head_str, (h_s, h_e) = head
                head_clean = head_str.replace(',', '')
                before = chunk[:h_s]
                after  = chunk[h_e:]
            else:
                head_clean = ""
                before = chunk
                after  = ""

            # 장소(경로) 및 보조정보 추출
            place_block = before.strip()
            aux_in_place = " ".join(re.findall(r'<([^>]+)>', place_block))
            nodes = CrawlingService._extract_place_nodes(place_block)

            # 비고 = 인원 이후 잔여 + 장소 보조정보
            remark_raw = " ".join(x for x in [after.strip(), aux_in_place.strip()] if x)
            remark = CrawlingService._collapse_korean_gaps(re.sub(r'\s+', ' ', remark_raw)).strip()

            # 장소 컬럼: 1개면 문자열, 2개 이상이면 JSON 리스트 문자열
            if len(nodes) == 0:
                place_col = ""
            elif len(nodes) == 1:
                place_col = nodes[0]
            else:
                place_col = json.dumps(nodes, ensure_ascii=False)

            row = {
                "년": ymd[0] if ymd else "",
                "월": ymd[1] if ymd else "",
                "일": ymd[2] if ymd else "",
                "start_time": start_t,
                "end_time": end_t,
                "장소": place_col,
                "인원": head_clean,   # 숫자만
                "위도": "[]",         # 지오코딩에서 설정됨
                "경도": "[]",         # 지오코딩에서 설정됨
                "비고": remark,
            }
            rows.append(row)

        return rows

    @staticmethod
    async def _convert_raw_events_to_db_format(raw_events: List[Dict]) -> List[Dict]:
        """
        파싱된 PDF 데이터를 우리 events 테이블 형식으로 변환 (Refactored)
        """
        events = []
        conversion_errors = []
        
        for i, row in enumerate(raw_events):
            try:
                # 1. 데이터 유효성 검증
                if not CrawlingService._validate_row_data(row):
                    logger.warning(f"행 {i+1}: 유효하지 않은 데이터 건너뜀")
                    continue
                
                # 2. 날짜 및 시간 파싱
                try:
                    start_date, end_date = CrawlingService._parse_event_datetime(row)
                except ValueError as e:
                    logger.warning(f"행 {i+1} 날짜 변환 실패: {e}")
                    continue

                # 3. 장소 및 좌표 파싱
                location_name, latitude, longitude = await CrawlingService._resolve_location_info(row, i)
                
                # 4. 설명 및 제목 생성
                title, description = CrawlingService._build_event_content(row, location_name)
                
                # 5. 주소 생성
                location_address = f"서울특별시 종로구"
                if location_name != "알 수 없는 장소":
                    location_address += f" {location_name}"
                
                event = {
                    'title': title,
                    'description': description,
                    'location_name': location_name,
                    'location_address': location_address,
                    'latitude': latitude,
                    'longitude': longitude, 
                    'start_date': start_date,
                    'end_date': end_date,
                    'category': '집회',
                    'severity_level': 2,
                    'status': 'active'
                }
                
                events.append(event)
                
            except Exception as e:
                error_msg = f"행 {i+1} 변환 실패: {e}"
                logger.warning(error_msg)
                conversion_errors.append(error_msg)
                continue
        
        logger.info(f"데이터 변환 완료: {len(events)}개 성공, {len(conversion_errors)}개 실패")
        if conversion_errors:
            logger.warning(f"변환 실패 상세: {conversion_errors[:5]}...")
        
        return events

    @staticmethod
    def _validate_row_data(row: Dict) -> bool:
        """행 데이터 유효성 검증"""
        if not row or all(not str(v).strip() for v in row.values()):
            return False
        return True

    @staticmethod
    def _parse_event_datetime(row: Dict) -> Tuple[str, str]:
        """날짜와 시간 파싱"""
        year = int(row.get('년', 2025))
        month = int(row.get('월', 1))
        day = int(row.get('일', 1))
        
        # 날짜 유효성 검증
        datetime(year, month, day)
        
        start_time = CrawlingService._normalize_time_str(row.get('start_time', '09:00'))
        end_time = CrawlingService._normalize_time_str(row.get('end_time', '18:00'))
        
        return (
            f"{year}-{month:02d}-{day:02d} {start_time}:00",
            f"{year}-{month:02d}-{day:02d} {end_time}:00"
        )

    @staticmethod
    def _normalize_time_str(time_str: str) -> str:
        """시간 문자열 정규화 (HH:MM)"""
        time_str = str(time_str).strip()
        if ':' not in time_str:
            return "09:00"
        parts = time_str.split(':')
        if len(parts) != 2:
            return "09:00"
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                return "09:00"
            return f"{hour:02d}:{minute:02d}"
        except ValueError:
            return "09:00"

    @staticmethod
    def _normalize_place_name(place: str) -> str:
        """장소명 정규화 — 노이즈 제거 및 지명 치환 (v2 로직)"""
        t = place.strip()

        # 노이즈 제거
        t = t.replace("구)", "").replace("(구)", "")
        t = re.sub(r'\d+(\.\d+)?km', '', t)
        t = re.sub(r'[<\[\(].*?[>\]\)]', '', t)
        t = re.sub(r'\(.*$', '', t)

        # 지명 치환
        for old_name, new_name in PLACE_NAME_REPLACE_MAP.items():
            if old_name in t and new_name not in t:
                t = t.replace(old_name, new_name)

        # 방향 분리자 처리
        split_chars = r'[⇄↔→~]'
        if re.search(split_chars, t):
            parts = re.split(split_chars, t)
            if parts:
                t = parts[0].strip()

        # 출구 표기 정리
        t = re.sub(r'(\d+)\s*出', r'\1번출구', t)
        t = t.replace('出', '출구')

        # 방향 지시어 제거
        noise_regex = (
            r'(동측|서측|남측|북측|동쪽|서쪽|남쪽|북쪽|건너편|맞은편|옆|'
            r'방향|방면|부근|일대|진입로|사거리|교차로|삼거리|오거리|'
            r'출구|입구|인근|앞|뒤|안|밖)'
        )
        t = re.sub(noise_regex, ' ', t)
        t = re.sub(r'[^\w\s\d]', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()

        return t

    @staticmethod
    async def _kakao_geocode_multi(place: str) -> Tuple[Optional[float], Optional[float]]:
        """
        다중 쿼리 전략으로 카카오 지오코딩 (v2 로직 적용)
        서울 외 지역 결과는 필터링합니다.
        """
        from app.utils.geo_utils import get_location_info

        clean_name = CrawlingService._normalize_place_name(place)
        if not clean_name or len(clean_name) < 2:
            return None, None

        # 다중 후보 쿼리 생성
        candidates = [f"서울 {clean_name}", clean_name]
        tokens = clean_name.split()
        if len(tokens) > 1:
            candidates.append(f"서울 {tokens[-1]}")
            candidates.append(f"서울 {tokens[0]}")
        if not clean_name.endswith("역") and len(clean_name) <= 5:
            candidates.append(f"서울 {clean_name}역")

        for query in candidates:
            if len(query.replace("서울", "").strip()) < 2:
                continue
            try:
                loc_info = await get_location_info(query)
                if loc_info:
                    addr = loc_info.get("address", "")
                    # 서울 지역만 허용
                    if addr and "서울" not in addr[:5]:
                        logger.debug(f"서울 외 결과 무시: {query} -> {addr}")
                        continue
                    return loc_info["y"], loc_info["x"]
            except Exception:
                continue
            await asyncio.sleep(0.05)

        return None, None

    @staticmethod
    async def _resolve_location_info(row: Dict, row_index: int) -> Tuple[str, float, float]:
        """장소명과 좌표 결정 — v2 다중 지오코딩 전략 적용"""
        # 장소_원본 필드 우선 사용 (병합 후 존재)
        places = row.get('장소_원본', [])
        location_raw = str(row.get('장소', '')).strip()

        # 장소명 결정
        location_name = "알 수 없는 장소"
        if places and isinstance(places, list):
            for p in places:
                if p and str(p).strip():
                    location_name = str(p).strip()
                    break
        elif location_raw:
            if location_raw.startswith('[') and location_raw.endswith(']'):
                try:
                    locations = json.loads(location_raw)
                    if isinstance(locations, list) and locations:
                        for loc in locations:
                            if loc and str(loc).strip():
                                location_name = str(loc).strip()
                                break
                except json.JSONDecodeError:
                    cleaned = location_raw.strip('[]').replace('"', '').replace("'", "")
                    parts = [p.strip() for p in cleaned.split(',') if p.strip()]
                    if parts:
                        location_name = parts[0]
            else:
                location_name = location_raw

        # 좌표 파싱 (PDF 데이터 우선)
        latitude = 37.5709
        longitude = 126.9769
        coords_found = False

        try:
            lat_val = CrawlingService._parse_coordinate_value(row.get('위도'))
            lon_val = CrawlingService._parse_coordinate_value(row.get('경도'))
            if lat_val and lon_val:
                latitude = lat_val
                longitude = lon_val
                coords_found = True
        except Exception as e:
            logger.debug(f"행 {row_index+1} PDF 좌표 파싱 실패: {e}")

        # 카카오 API 다중 쿼리 폴백 (v2 개선)
        if not coords_found and location_name != "알 수 없는 장소":
            lat, lon = await CrawlingService._kakao_geocode_multi(location_name)
            if lat and lon:
                latitude = lat
                longitude = lon
                logger.debug(f"카카오 다중 쿼리 좌표 획득: {location_name}")

        return location_name, latitude, longitude

    @staticmethod
    def _parse_coordinate_value(raw_val: Any) -> Optional[float]:
        """좌표 값 파싱"""
        str_val = str(raw_val).strip()
        if not str_val or str_val in ['', 'nan', 'None']:
            return None
            
        try:
            # JSON 배열인 경우
            if str_val.startswith('[') and str_val.endswith(']'):
                coords = json.loads(str_val)
                if isinstance(coords, list):
                    for c in coords:
                        if c is not None:
                            val = float(c)
                            if 33 <= val <= 39 or 124 <= val <= 132:
                                return val
            # 단일 값인 경우
            else:
                val = float(str_val)
                if 33 <= val <= 39 or 124 <= val <= 132:
                    return val
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        return None

    @staticmethod
    def _build_event_content(row: Dict, location_name: str) -> Tuple[str, str]:
        """제목과 설명 생성"""
        participants = str(row.get('인원', '')).strip()
        remarks = str(row.get('비고', '')).strip()
        
        # 제목
        title = f"{location_name} 집회"
        if participants and participants.isdigit():
            title += f" (참가자 {participants}명)"
            
        # 설명
        desc_parts = []
        if participants:
            desc_parts.append(f"참가인원: {participants}{'명' if participants.isdigit() else ''}")
        if remarks:
            desc_parts.append(f"추가정보: {remarks}")
        desc_parts.append("데이터 출처: SMPA(서울경찰청)")
        
        return title, " | ".join(desc_parts)