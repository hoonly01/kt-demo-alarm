from collections.abc import Generator, Sequence
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import TracebackType
from typing import Self, override

import httpx
import pytest

from app.services.crawling import smpa_source


@contextmanager
def local_http_responses(
    responses: Sequence[tuple[int, str]],
) -> Generator[tuple[str, dict[str, int]], None, None]:
    """테스트용 로컬 HTTP 서버에서 요청 순서대로 응답한다."""

    request_count = {"value": 0}

    class SequenceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            index = min(request_count["value"], len(responses) - 1)
            request_count["value"] += 1
            status, body = responses[index]
            encoded_body = body.encode("utf-8")

            self.send_response(int(status))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded_body)))
            self.end_headers()
            _ = self.wfile.write(encoded_body)

        @override
        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SequenceHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", request_count
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.mark.asyncio
async def test_fetch_smpa_text_uses_urllib_fallback_when_httpx_connect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMPA 서버의 TLS 연결 특성으로 httpx가 실패해도 표준 urllib 경로를 검증 가능하게 유지한다."""

    class FailingAsyncClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool:
            return False

        async def get(self, *_args: object, **_kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("TLS handshake failed")

    def fetch_text_with_urllib(_url: str, _config: smpa_source.SmpaHttpConfig) -> str:
        return "fallback-body"

    monkeypatch.setattr(httpx, "AsyncClient", FailingAsyncClient)
    monkeypatch.setattr(smpa_source, "_fetch_text_with_urllib", fetch_text_with_urllib)

    body = await smpa_source.fetch_smpa_text("https://smpa.go.kr/user/nd54882.do")

    assert body == "fallback-body"


@pytest.mark.asyncio
async def test_fetch_smpa_text_uses_urllib_fallback_for_transient_status() -> None:
    """429/5xx 응답은 httpx 상태 오류여도 fallback 경로로 복구한다."""

    with local_http_responses(
        [
            (HTTPStatus.INTERNAL_SERVER_ERROR, "temporary failure"),
            (HTTPStatus.OK, "fallback-body"),
        ]
    ) as (base_url, request_count):
        config = smpa_source.SmpaHttpConfig(base_url=base_url, list_path="/list")

        body = await smpa_source.fetch_smpa_text(f"{base_url}/list", config)

    assert body == "fallback-body"
    assert request_count["value"] == 2


@pytest.mark.asyncio
async def test_fetch_recent_smpa_posts_honors_zero_limit() -> None:
    """limit=0은 기본값으로 치환하지 않고 빈 목록을 반환한다."""

    list_html = """
    <table>
      <tr>
        <td><a href="javascript:goBoardView('bbs','ntt','1001')">보기</a></td>
        <td>오늘의 집회 260515 금</td>
        <td>작성자</td>
        <td>2026-05-15</td>
      </tr>
    </table>
    """

    with local_http_responses([(HTTPStatus.OK, list_html)]) as (base_url, request_count):
        config = smpa_source.SmpaHttpConfig(base_url=base_url, list_path="/list")

        posts = await smpa_source.fetch_recent_smpa_posts(limit=0, config=config)

    assert posts == []
    assert request_count["value"] == 1
