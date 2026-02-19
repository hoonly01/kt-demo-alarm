"""SPATIC 집회 데이터 크롤링 모듈

서울경찰청 집회 안내 시스템(SPATIC)에서 집회 정보를 수집합니다.
Selenium 기반으로 동적 페이지를 처리합니다.
"""
import re
import logging
from collections import OrderedDict
from datetime import datetime
from typing import List, Dict, Tuple, Optional

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)

# Selenium 선택적 임포트
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# SPATIC 상수
SPATIC_BASE_URL = "https://www.spatic.go.kr"
SPATIC_LIST_URL = f"{SPATIC_BASE_URL}/spatic/main/assem.do"
SPATIC_DETAIL_FMT = f"{SPATIC_BASE_URL}/spatic/assem/getInfoView.do?mgrSeq={{mgrSeq}}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


# ========================== 유틸리티 ==========================

def _clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _normalize_label(s: str) -> str:
    return re.sub(r"\s+", "", s or "").strip()


def _parse_date_any(s: str) -> Optional[Tuple[str, str, str]]:
    """다양한 날짜 형식에서 (YYYY, MM, DD) 추출"""
    s = _clean_text(s)
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s)
    if m:
        return m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return None


def _time_range_to_tuple(s: str) -> Optional[Tuple[str, str]]:
    """시간 범위 문자열을 (시작, 종료) 튜플로 변환"""
    if not s:
        return None
    s = _clean_text(s).replace("∼", "~").replace("〜", "~").replace("–", "-").replace("—", "-")

    m = re.search(r"(\d{1,2}\s*:\s*\d{2})\s*[~\-–—]\s*(\d{1,2}\s*:\s*\d{2})", s)
    if m:
        return re.sub(r"\s*", "", m.group(1)), re.sub(r"\s*", "", m.group(2))

    m = re.search(r"(\d{1,2}\s*:\s*\d{2})", s)
    if m:
        t_str = re.sub(r"\s*", "", m.group(1))
        if re.search(r"종료\s*시|끝날?\s*때|해산\s*시", s):
            return t_str, "종료시"
        return t_str, "미정"

    m = re.search(r"(오전|오후)\s*(\d{1,2})\s*시", s)
    if m:
        period, hour = m.group(1), int(m.group(2))
        if period == "오후" and hour != 12:
            hour += 12
        elif period == "오전" and hour == 12:
            hour = 0
        return f"{hour:02d}:00", "미정"
    return None


def split_places(s: str) -> List[str]:
    """장소 텍스트를 개별 장소 토큰으로 분리 (v2 개선 로직)"""
    s = _clean_text(s)
    s = s.replace("\n", " / ")
    parts = re.split(r"\s*(?:→|↔|⟷|↦|↪|➝|➔|⇒|~|〜|∼|–|—|/|,|▶|⇄)\s*", s)
    filtered = []
    for p in parts:
        p = p.strip()
        if len(p) <= 1 and not re.search(r"[가-힣A-Za-z]", p):
            continue
        if p in ["출", "구", "로", "길"]:
            continue
        if re.search(r'\d+\s*개?차로', p):
            continue
        filtered.append(p)

    final = []
    seen = set()
    for p in filtered:
        if p not in seen:
            final.append(p)
            seen.add(p)
    return final


def _is_event_title(title: str) -> bool:
    t = re.sub(r"\s+", " ", title or "").strip()
    if "집회" in t:
        return True
    if "행사" in t and ("안내" in t or "정보" in t):
        return True
    return False


# ========================== HTML 파싱 ==========================

def _extract_text_with_structure(element) -> str:
    """HTML 요소에서 구조를 유지한 텍스트 추출"""
    if element is None:
        return ""
    result = []

    def traverse(node):
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                result.append(text)
        elif isinstance(node, Tag):
            if node.name == "br":
                result.append("\n")
            elif node.name in ["p", "div", "li", "tr"]:
                if result and result[-1] != "\n":
                    result.append("\n")
            for child in node.children:
                traverse(child)
            if node.name in ["p", "div", "li", "tr", "td", "th"]:
                if result and result[-1] != "\n":
                    result.append("\n")

    traverse(element)
    text = "".join(result)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _find_detail_table(soup: BeautifulSoup) -> Optional[Tag]:
    """상세 페이지에서 집회 정보 테이블 탐색"""
    selectors = [
        "div.police_main_wrap.detail.flex.flex_column > section > div > div > "
        "ul.notice_datail.flex.flex_wrap > li.notice_contents > div > table",
        "ul.notice_datail.flex.flex_wrap li.notice_contents > div > table",
        "li.notice_contents > div > table",
        "div.detail_contents table",
    ]
    for sel in selectors:
        node = soup.select_one(sel)
        if node and node.name == "table":
            return node

    for tb in soup.find_all("table"):
        text_normalized = _normalize_label(tb.get_text(" ", strip=True))
        if "시간" in text_normalized and "장소" in text_normalized:
            return tb

    nc = soup.select_one("li.notice_contents")
    if nc:
        t = nc.select_one("table")
        if t:
            return t
    return None


def _header_index_map(tr) -> Dict[str, int]:
    """테이블 헤더 행에서 컬럼 인덱스 매핑"""
    cells = tr.find_all(["th", "td"])
    labels = [_normalize_label(c.get_text(" ", strip=True)) for c in cells]
    hmap = {}
    for i, lab in enumerate(labels):
        if any(kw in lab for kw in ["시간", "집회시간", "집결시간"]):
            hmap["time"] = i
        if any(kw in lab for kw in ["장소", "집회장소", "집결장소", "집결지"]):
            hmap["place"] = i
        if any(kw in lab for kw in ["행진", "경로", "이동"]):
            hmap["route"] = i
    return hmap


def _parse_detail_to_groups(html: str) -> Dict[Tuple[str, str], List[str]]:
    """상세 페이지 HTML에서 시간-장소 그룹 추출"""
    soup = BeautifulSoup(html, "html.parser")
    tb = _find_detail_table(soup)
    if not tb:
        return {}

    body = tb.find("tbody") or tb
    rows = body.find_all("tr")
    if not rows:
        return {}

    hmap = _header_index_map(rows[0])
    if "time" not in hmap or "place" not in hmap:
        first_cells_cnt = len(rows[0].find_all(["td", "th"]))
        hmap.setdefault("time", 0 if first_cells_cnt <= 2 else 1)
        hmap.setdefault("place", 1 if first_cells_cnt <= 2 else 2)

    groups: OrderedDict = OrderedDict()

    for tr in rows[1:]:
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue

        time_text = ""
        if hmap["time"] < len(tds):
            time_text = _extract_text_with_structure(tds[hmap["time"]])

        trange = _time_range_to_tuple(time_text)
        if not trange:
            trange = _time_range_to_tuple(_extract_text_with_structure(tr))
        if not trange:
            continue

        start, end = trange
        place_tokens = []

        if hmap["place"] < len(tds):
            place_raw = _extract_text_with_structure(tds[hmap["place"]])
            place_raw = re.sub(r"※\s*행진\s*[:：]?\s*", " ", place_raw)
            place_tokens = split_places(place_raw)

        if "route" in hmap and hmap["route"] < len(tds):
            place_tokens.extend(split_places(
                _extract_text_with_structure(tds[hmap["route"]])
            ))

        if not place_tokens:
            place_tokens = split_places(_extract_text_with_structure(tr))
        if not place_tokens:
            continue

        key = (start, end)
        if key not in groups:
            groups[key] = []
        for p in place_tokens:
            if p not in groups[key]:
                groups[key].append(p)

    return groups


# ========================== Selenium 목록 수집 ==========================

def _fetch_list_selenium() -> List[Dict]:
    """Selenium으로 SPATIC 동적 페이지에서 목록 수집"""
    posts: List[Dict] = []

    if not SELENIUM_AVAILABLE:
        logger.warning("Selenium이 설치되지 않아 SPATIC 크롤링을 건너뜁니다.")
        return posts

    driver = None
    try:
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("user-agent=Mozilla/5.0")
        driver = webdriver.Chrome(options=opts)
        driver.get(SPATIC_LIST_URL)

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".assem_content tr"))
            )
        except Exception:
            logger.warning("SPATIC 테이블 로딩 시간 초과")

        rows = driver.find_elements(By.CSS_SELECTOR, ".assem_content tr")
        logger.info(f"SPATIC 발견된 행: {len(rows)}")

        for row in rows:
            try:
                mgr = row.get_attribute("key")
                if not mgr:
                    full_html = row.get_attribute("outerHTML")
                    m = re.search(r"mgrSeq=(\d+)", full_html)
                    if m:
                        mgr = m.group(1)
                if not mgr:
                    onclick = row.get_attribute("onclick") or ""
                    m = re.search(r"['\"]?(\d{4,})['\"]?", onclick)
                    if m:
                        mgr = m.group(1)

                tds = row.find_elements(By.CSS_SELECTOR, "td")
                if len(tds) < 3:
                    continue
                title = tds[1].text.strip()
                date_txt = tds[2].text.strip()
                if not mgr:
                    continue

                parsed_date = _parse_date_any(date_txt)
                final_date = (
                    f"{parsed_date[0]}-{parsed_date[1]}-{parsed_date[2]}"
                    if parsed_date else ""
                )
                posts.append({"number": mgr, "title": title, "date": final_date})
            except Exception:
                continue

    except Exception as e:
        logger.error(f"SPATIC Selenium 크롤링 오류: {e}")
    finally:
        if driver:
            driver.quit()

    # 중복 제거
    uniq = {}
    for p in posts:
        if p.get("number"):
            uniq[p["number"]] = p
    return list(uniq.values())


def _select_latest_event(posts: List[Dict]) -> Optional[Tuple[int, Tuple[str, str, str]]]:
    """집회 관련 최신 게시글 선택"""
    if not posts:
        return None
    event_posts = [p for p in posts if _is_event_title(p.get("title", ""))]
    if not event_posts:
        logger.info(f"SPATIC {len(posts)}개 게시글 중 집회 관련 없음")
        return None

    nums = []
    for p in event_posts:
        m = re.search(r"\d+", p.get("number", ""))
        if m:
            nums.append((int(m.group(0)), p))
    if not nums:
        return None

    nums.sort(key=lambda x: x[0], reverse=True)
    mgr, post = nums[0]
    ymd = _parse_date_any(post.get("date", "")) or _parse_date_any(
        datetime.now().strftime("%Y-%m-%d")
    )
    return mgr, ymd


# ========================== 공개 API ==========================

def scrape_spatic() -> List[Dict]:
    """
    SPATIC에서 집회 데이터를 수집합니다.

    Returns:
        List[Dict]: 파싱된 집회 행 목록.
        각 행은 { 년, 월, 일, start_time, end_time, 장소_원본, 인원, 비고 } 형태.
    """
    if not SELENIUM_AVAILABLE:
        logger.info("Selenium 미설치로 SPATIC 크롤링 건너뜀")
        return []

    logger.info("SPATIC 목록 수집 시작...")
    posts = _fetch_list_selenium()
    selected = _select_latest_event(posts)
    if not selected:
        logger.info("SPATIC에서 집회 게시글을 찾을 수 없음")
        return []

    mgr_seq, (y, m, d) = selected
    logger.info(f"SPATIC 상세 파싱: mgrSeq={mgr_seq} ({y}-{m}-{d})")

    with requests.Session() as session:
        url = SPATIC_DETAIL_FMT.format(mgrSeq=mgr_seq)
        r = session.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        groups = _parse_detail_to_groups(r.text)

    rows = []
    for (start, end), places in groups.items():
        rows.append({
            "년": y, "월": m, "일": d,
            "start_time": start, "end_time": end,
            "장소_원본": places,
            "인원": "",
            "비고": "SPATIC",
        })

    logger.info(f"SPATIC 파싱 완료: {len(rows)}건")
    return rows
