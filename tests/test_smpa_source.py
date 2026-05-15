import httpx
import pytest

from app.services.crawling import smpa_source


@pytest.mark.asyncio
async def test_fetch_smpa_text_uses_urllib_fallback_when_httpx_connect_fails(monkeypatch):
    """SMPA 서버의 TLS 연결 특성으로 httpx가 실패해도 표준 urllib 경로를 검증 가능하게 유지한다."""

    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("TLS handshake failed")

    monkeypatch.setattr(smpa_source.httpx, "AsyncClient", FailingAsyncClient)
    monkeypatch.setattr(
        smpa_source,
        "_fetch_text_with_urllib",
        lambda url, config: "fallback-body",
    )

    body = await smpa_source.fetch_smpa_text("https://smpa.go.kr/user/nd54882.do")

    assert body == "fallback-body"
