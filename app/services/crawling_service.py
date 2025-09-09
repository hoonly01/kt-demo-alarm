"""집회 데이터 크롤링 서비스"""
import logging
import sqlite3
import os
import re
import json
import urllib.parse
import shutil
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text
from zoneinfo import ZoneInfo

from app.database.connection import DATABASE_PATH

logger = logging.getLogger(__name__)

# SMPA 크롤링 상수들 (MinhaKim02 구현 기반)
BASE_URL = "https://www.smpa.go.kr"
LIST_URL = f"{BASE_URL}/user/nd54882.do"


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
        오늘 집회 정보를 크롤링하고 파싱하여 DB 형식으로 반환
        MinhaKim02의 완전한 크롤링 알고리즘 구현
        
        Returns:
            List[Dict]: DB 형식으로 변환된 집회 정보
        """
        temp_dir = "temp_pdfs"
        
        try:
            # 1. SMPA 사이트에서 오늘자 PDF 다운로드
            logger.info("SMPA 사이트에서 오늘자 PDF 다운로드 시작")
            pdf_path, title_text = await CrawlingService._download_today_pdf_with_title(out_dir=temp_dir)
            logger.info(f"PDF 다운로드 성공: {pdf_path}")
            
            # 2. 제목에서 날짜 추출
            ymd = CrawlingService._extract_ymd_from_title(title_text)
            if ymd:
                logger.info(f"제목에서 날짜 추출: {ymd[0]}-{ymd[1]}-{ymd[2]}")
            else:
                logger.warning("제목에서 날짜 추출 실패, 현재 날짜 사용")
                now = datetime.now()
                ymd = (str(now.year), f"{now.month:02d}", f"{now.day:02d}")
            
            # 3. PDF 파싱
            logger.info("PDF 파싱 시작")
            raw_events = CrawlingService._parse_pdf(pdf_path, ymd=ymd)
            logger.info(f"PDF 파싱 완료: {len(raw_events)}개 집회 정보 추출")
            
            # 4. DB 형식으로 변환  
            logger.info("DB 형식으로 데이터 변환 시작")
            db_events = CrawlingService._convert_raw_events_to_db_format(raw_events)
            logger.info(f"DB 형식 변환 완료: {len(db_events)}개 이벤트")
            
            # 5. 임시 파일 정리
            try:
                os.remove(pdf_path)
                logger.debug(f"임시 PDF 파일 삭제: {pdf_path}")
            except:
                pass
            
            return db_events
            
        except Exception as e:
            logger.error(f"집회 정보 크롤링 및 파싱 실패: {e}")
            return []
        finally:
            # 임시 디렉토리 정리
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except:
                pass

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
    async def _get_today_post_info(session: requests.Session, list_url: str = LIST_URL) -> Tuple[str, str]:
        """
        목록 페이지에서 오늘자 게시글의 뷰 URL과 제목을 반환 (원본 by MinhaKim02)
        """
        current_date, expected_full = CrawlingService._current_title_pattern()
        r = session.get(list_url, timeout=20)
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
    def _is_pdf(resp: requests.Response, first: bytes) -> bool:
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
    async def _download_from_view(session: requests.Session, view_url: str, out_dir: str = "temp") -> str:
        """
        게시글 뷰 페이지에서 PDF 첨부파일 다운로드 (원본 by MinhaKim02)
        """
        os.makedirs(out_dir, exist_ok=True)
        
        r = session.get(view_url, timeout=20)
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
                with session.get(download_url, params={"attachNo": attach_no}, stream=True, timeout=30) as resp:
                    resp.raise_for_status()
                    it = resp.iter_content(chunk_size=8192)
                    first_chunk = next(it, b"")
                    if not CrawlingService._is_pdf(resp, first_chunk):
                        continue
                    cd = resp.headers.get("Content-Disposition", "")
                    filename = CrawlingService._filename_from_cd(cd) or (a_tag.get_text(strip=True) or f"{attach_no}.pdf")
                    root, ext = os.path.splitext(filename)
                    if ext.lower() != ".pdf":
                        filename = root + ".pdf"
                    filename = CrawlingService._sanitize_filename(filename)
                    save_path = os.path.join(out_dir, filename)
                    with open(save_path, "wb") as f:
                        if first_chunk:
                            f.write(first_chunk)
                        for chunk in it:
                            if chunk:
                                f.write(chunk)
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
        sess = requests.Session()
        sess.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            'Referer': LIST_URL,
        })
        view_url, title_text = await CrawlingService._get_today_post_info(sess, LIST_URL)
        pdf_path = await CrawlingService._download_from_view(sess, view_url, out_dir=out_dir)
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
    def _convert_raw_events_to_db_format(raw_events: List[Dict]) -> List[Dict]:
        """
        파싱된 PDF 데이터를 우리 events 테이블 형식으로 변환
        Integration: MinhaKim02의 파싱 결과를 우리 DB 스키마로 변환
        
        PDF Parse Schema (by MinhaKim02):
        - 년,월,일,start_time,end_time,장소,인원,위도,경도,비고
        
        Our events table:
        - title, description, location_name, latitude, longitude, start_date, end_date, category
        """
        events = []
        conversion_errors = []
        
        for i, row in enumerate(raw_events):
            try:
                # 데이터 유효성 검증
                if not row or all(not str(v).strip() for v in row.values()):
                    logger.warning(f"행 {i+1}: 빈 데이터 건너뜀")
                    continue
                
                # 날짜/시간 변환 (더 강력한 검증)
                try:
                    year = int(row.get('년', 2025))
                    month = int(row.get('월', 1))
                    day = int(row.get('일', 1))
                    
                    # 날짜 유효성 검증
                    if not (2020 <= year <= 2030):
                        raise ValueError(f"연도가 범위를 벗어남: {year}")
                    if not (1 <= month <= 12):
                        raise ValueError(f"월이 범위를 벗어남: {month}")
                    if not (1 <= day <= 31):
                        raise ValueError(f"일이 범위를 벗어남: {day}")
                    
                    # 실제 날짜 검증
                    datetime(year, month, day)
                    
                except (ValueError, TypeError) as e:
                    raise ValueError(f"날짜 변환 오류: {e}")
                
                # 시간 변환 (HH:MM 형식 검증)
                start_time_raw = row.get('start_time', '09:00').strip()
                end_time_raw = row.get('end_time', '18:00').strip()
                
                # 시간 형식 정규화
                def normalize_time(time_str):
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
                
                start_time = normalize_time(start_time_raw)
                end_time = normalize_time(end_time_raw)
                
                start_date = f"{year}-{month:02d}-{day:02d} {start_time}:00"
                end_date = f"{year}-{month:02d}-{day:02d} {end_time}:00"
                
                # 장소 파싱 개선 (JSON 배열 또는 단일 문자열)
                location_raw = str(row.get('장소', '')).strip()
                location_name = "알 수 없는 장소"  # 기본값
                
                if location_raw:
                    if location_raw.startswith('[') and location_raw.endswith(']'):
                        # JSON 배열인 경우
                        try:
                            locations = json.loads(location_raw)
                            if isinstance(locations, list) and locations:
                                # 비어있지 않은 첫 번째 장소 찾기
                                for loc in locations:
                                    if loc and str(loc).strip():
                                        location_name = str(loc).strip()
                                        break
                        except json.JSONDecodeError:
                            # JSON 파싱 실패 시 대체 방법
                            cleaned = location_raw.strip('[]').replace('"', '').replace("'", "")
                            parts = [p.strip() for p in cleaned.split(',') if p.strip()]
                            if parts:
                                location_name = parts[0]
                    else:
                        # 단일 문자열인 경우
                        location_name = location_raw
                
                # 좌표 획득 - 카카오 지도 API 사용하여 장소명을 좌표로 변환
                latitude = 37.5709  # 광화문 기본 좌표 (fallback)
                longitude = 126.9769
                
                # 먼저 PDF의 좌표 데이터 파싱 시도
                coordinates_found = False
                try:
                    lat_raw = str(row.get('위도', '')).strip()
                    lon_raw = str(row.get('경도', '')).strip()
                    
                    def parse_coordinate(coord_str, default_val):
                        if not coord_str or coord_str in ['', 'nan', 'None']:
                            return None
                        
                        if coord_str.startswith('[') and coord_str.endswith(']'):
                            # JSON 배열
                            try:
                                coords = json.loads(coord_str)
                                if isinstance(coords, list) and coords:
                                    for coord in coords:
                                        if coord is not None:
                                            val = float(coord)
                                            # 한국 좌표 범위 검증
                                            if 33 <= val <= 39 or 124 <= val <= 132:
                                                return val
                            except (json.JSONDecodeError, ValueError, TypeError):
                                pass
                        else:
                            # 단일 값
                            try:
                                val = float(coord_str)
                                if 33 <= val <= 39 or 124 <= val <= 132:
                                    return val
                            except (ValueError, TypeError):
                                pass
                        return None
                    
                    parsed_lat = parse_coordinate(lat_raw, None)
                    parsed_lon = parse_coordinate(lon_raw, None)
                    
                    if parsed_lat and parsed_lon:
                        latitude = parsed_lat
                        longitude = parsed_lon
                        coordinates_found = True
                        logger.debug(f"PDF에서 좌표 파싱 성공: {location_name} -> ({latitude}, {longitude})")
                    
                except Exception as coord_e:
                    logger.debug(f"행 {i+1}: PDF 좌표 파싱 실패: {coord_e}")
                
                # PDF에서 좌표를 찾지 못한 경우 카카오 지도 API 사용
                if not coordinates_found and location_name != "알 수 없는 장소":
                    try:
                        from app.utils.geo_utils import get_location_info
                        location_info = await get_location_info(location_name)
                        if location_info:
                            latitude = location_info["y"]  # 위도
                            longitude = location_info["x"]  # 경도
                            logger.info(f"카카오 지도 API로 좌표 획득: {location_name} -> ({latitude}, {longitude})")
                        else:
                            logger.warning(f"카카오 지도 API에서 장소를 찾을 수 없음: {location_name}")
                    except Exception as api_e:
                        logger.warning(f"카카오 지도 API 호출 실패: {api_e}")
                
                # 설명 구성 개선
                description_parts = []
                
                participants = str(row.get('인원', '')).strip()
                if participants and participants.isdigit():
                    description_parts.append(f"참가인원: {participants}명")
                elif participants:
                    description_parts.append(f"참가인원: {participants}")
                
                remarks = str(row.get('비고', '')).strip()
                if remarks:
                    description_parts.append(f"추가정보: {remarks}")
                
                description_parts.append("데이터 출처: SMPA(서울경찰청)")
                description = " | ".join(description_parts)
                
                # 제목 생성 개선
                title = f"{location_name} 집회"
                if participants and participants.isdigit():
                    title += f" (참가자 {participants}명)"
                
                # 주소 생성 개선
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
                    'severity_level': 2,  # 중간 수준
                    'status': 'active'
                }
                
                events.append(event)
                
            except Exception as e:
                error_msg = f"행 {i+1} 변환 실패: {e}"
                logger.warning(error_msg)
                conversion_errors.append(error_msg)
                continue
        
        # 변환 결과 로깅
        logger.info(f"데이터 변환 완료: {len(events)}개 성공, {len(conversion_errors)}개 실패")
        if conversion_errors:
            logger.warning(f"변환 실패 상세: {conversion_errors[:5]}...")  # 처음 5개만 로그
        
        return events