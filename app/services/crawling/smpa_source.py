"""서울경찰청 오늘의 집회/시위 게시판 HTML 수집."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from http import HTTPStatus
from typing import cast
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import httpx

from app.config.settings import settings
from app.services.crawling.smpa_parser import SmpaListPost, parse_smpa_list_posts

logger = logging.getLogger(__name__)

TRANSIENT_HTTP_STATUS_CODES = {HTTPStatus.TOO_MANY_REQUESTS}
TRANSIENT_HTTP_STATUS_MIN = HTTPStatus.INTERNAL_SERVER_ERROR

SMPA_DETAIL_QUERY_TEMPLATE = (
    "{list_path}?View&pageST=SUBJECT&pageSV=&imsi=imsi&page=1"
    "&pageSC=SORT_ORDER&pageSO=DESC&dmlType=&boardNo={board_no}"
)


@dataclass(frozen=True)
class SmpaHttpConfig:
    """SMPA HTTP 수집 설정."""

    base_url: str = settings.SMPA_BASE_URL
    list_path: str = settings.SMPA_LIST_PATH
    timeout_seconds: float = settings.SMPA_HTTP_TIMEOUT_SECONDS
    user_agent: str = settings.SMPA_USER_AGENT

    @property
    def list_url(self) -> str:
        return urljoin(self.base_url, self.list_path)


def build_smpa_detail_url(
    board_no: str,
    config: SmpaHttpConfig | None = None,
) -> str:
    """SMPA boardNo를 상세 조회 URL로 변환한다."""
    active_config = config or SmpaHttpConfig()
    query = SMPA_DETAIL_QUERY_TEMPLATE.format(
        list_path=active_config.list_path,
        board_no=board_no,
    )
    return urljoin(active_config.base_url, query)


def _fetch_text_with_urllib(url: str, config: SmpaHttpConfig) -> str:
    """httpx TLS 연결 실패 시 표준 라이브러리로 한 번 더 수집한다."""
    request = Request(
        url,
        headers={
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return cast(bytes, response.read()).decode(charset, errors="replace")
    except URLError:
        logger.exception("SMPA urllib fallback 수집 실패: %s", url)
        raise


def _is_transient_http_status_error(error: httpx.HTTPStatusError) -> bool:
    """재시도 또는 fallback 대상인 일시적 HTTP 상태 오류인지 판단한다."""
    status_code = error.response.status_code
    return status_code in TRANSIENT_HTTP_STATUS_CODES or status_code >= TRANSIENT_HTTP_STATUS_MIN


async def fetch_smpa_text(
    url: str,
    config: SmpaHttpConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """SMPA HTML 문서를 UTF-8 텍스트로 가져온다."""
    active_config = config or SmpaHttpConfig()
    headers = {
        "User-Agent": active_config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    last_error: Exception | None = None
    for attempt in range(1, settings.SMPA_HTTP_RETRY_COUNT + 1):
        try:
            if client is not None:
                response = await client.get(url, headers=headers, timeout=active_config.timeout_seconds)
            else:
                async with httpx.AsyncClient(follow_redirects=True) as new_client:
                    response = await new_client.get(
                        url,
                        headers=headers,
                        timeout=active_config.timeout_seconds,
                    )

            _ = response.raise_for_status()
            return response.text
        except (httpx.RequestError, httpx.HTTPStatusError) as error:
            if isinstance(error, httpx.HTTPStatusError) and not _is_transient_http_status_error(error):
                raise
            if client is not None:
                raise
            last_error = error
            logger.warning(
                "SMPA httpx 수집 실패, urllib fallback 실행: %s (attempt=%s)",
                url,
                attempt,
            )
            try:
                return await asyncio.to_thread(_fetch_text_with_urllib, url, active_config)
            except URLError as urllib_error:
                last_error = urllib_error
                if attempt < settings.SMPA_HTTP_RETRY_COUNT:
                    await asyncio.sleep(settings.SMPA_HTTP_RETRY_DELAY_SECONDS)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"SMPA 수집 실패: {url}")


async def fetch_recent_smpa_posts(
    limit: int | None = None,
    config: SmpaHttpConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[SmpaListPost]:
    """최근 SMPA 게시글 목록을 수집해 상세 URL까지 채운다."""
    active_config = config or SmpaHttpConfig()
    list_html = await fetch_smpa_text(active_config.list_url, active_config, client)
    posts = parse_smpa_list_posts(list_html)
    effective_limit = settings.SMPA_LIST_LIMIT if limit is None else limit
    selected_posts: Iterable[SmpaListPost] = posts[:effective_limit]
    return [
        post.with_detail_url(build_smpa_detail_url(post.board_no, active_config))
        for post in selected_posts
    ]
