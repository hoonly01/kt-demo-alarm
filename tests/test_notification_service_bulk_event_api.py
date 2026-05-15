import json
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models.alarm import AlarmRequest
from app.services import notification_service as notification_module
from app.services.notification_service import NotificationService


class CapturingKakaoTransport(httpx.AsyncBaseTransport):
    """실제 AsyncClient가 사용하는 인프로세스 카카오 API 전송 하네스"""

    def __init__(
        self,
        post_responses: Optional[List[Dict[str, Any]]] = None,
        task_responses: Optional[Dict[str, Any]] = None,
    ):
        self.post_responses = list(post_responses or [])
        self.task_responses = task_responses or {}
        self.requests: List[Dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        captured = {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "headers": dict(request.headers),
            "json": json.loads(body.decode()) if body else None,
        }
        self.requests.append(captured)

        if request.method == "POST" and request.url.path.endswith("/talk"):
            response_spec = self.post_responses.pop(0)
            return self._build_response(request, response_spec)

        if request.method == "GET" and request.url.path.startswith("/v1/tasks/"):
            task_id = request.url.path.rsplit("/", 1)[-1]
            response_spec = self._next_task_response(task_id)
            return self._build_response(request, response_spec)

        return httpx.Response(404, json={"error": "unexpected request"}, request=request)

    @staticmethod
    def _build_response(request: httpx.Request, response_spec: Dict[str, Any]) -> httpx.Response:
        if "exception" in response_spec:
            exception_type = response_spec["exception"]
            raise exception_type("transport failure", request=request)

        status_code = response_spec.get("status_code", 200)
        if "content" in response_spec:
            return httpx.Response(status_code, content=response_spec["content"], request=request)

        return httpx.Response(status_code, json=response_spec.get("json", {}), request=request)

    def _next_task_response(self, task_id: str) -> Dict[str, Any]:
        response_spec = self.task_responses[task_id]
        if isinstance(response_spec, list):
            if len(response_spec) > 1:
                return response_spec.pop(0)
            return response_spec[0]

        return response_spec

    def post_requests(self) -> List[Dict[str, Any]]:
        return [request for request in self.requests if request["method"] == "POST"]

    def task_requests(self) -> List[Dict[str, Any]]:
        return [request for request in self.requests if request["method"] == "GET"]


@pytest.fixture
def kakao_settings(monkeypatch):
    monkeypatch.setattr(notification_module.settings, "BOT_ID", "test-bot")
    monkeypatch.setattr(notification_module.settings, "KAKAO_EVENT_API_KEY", "test-rest-api-key")
    monkeypatch.setattr(notification_module.settings, "NOTIFICATION_TIMEOUT", 1.0)
    monkeypatch.setattr(notification_module.settings, "BATCH_SIZE", 100)
    monkeypatch.setattr(notification_module, "KAKAO_TASK_RESULT_POLL_DELAY_SECONDS", 0.0)


async def send_with_transport(
    user_ids: List[str],
    transport: CapturingKakaoTransport,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    async with httpx.AsyncClient(transport=transport) as client:
        return await NotificationService.send_bulk_alarm(
            user_ids=user_ids,
            event_name="test_event",
            data={"message": "hello"},
            batch_size=batch_size,
            client=client,
        )


@pytest.mark.asyncio
async def test_bulk_alarm_sends_three_users_in_one_post_and_reads_task_result(kakao_settings):
    transport = CapturingKakaoTransport(
        post_responses=[{"json": {"status": "SUCCESS", "taskId": "task-1"}}],
        task_responses={"task-1": {"json": {"allRequestCount": 3, "successCount": 3}}},
    )

    result = await send_with_transport(["u1", "u2", "u3"], transport)

    assert result == {"success": True, "total_sent": 3, "total_failed": 0, "total_users": 3}
    assert len(transport.post_requests()) == 1
    assert len(transport.task_requests()) == 1
    assert len(transport.post_requests()[0]["json"]["user"]) == 3


@pytest.mark.asyncio
async def test_bulk_alarm_caps_posts_at_kakao_limit_when_batch_size_is_oversized(kakao_settings):
    user_ids = [f"u{i}" for i in range(205)]
    post_responses = [
        {"json": {"status": "SUCCESS", "taskId": "task-1"}},
        {"json": {"status": "SUCCESS", "taskId": "task-2"}},
        {"json": {"status": "SUCCESS", "taskId": "task-3"}},
    ]
    task_responses = {
        "task-1": {"json": {"allRequestCount": 100, "successCount": 100}},
        "task-2": {"json": {"allRequestCount": 100, "successCount": 100}},
        "task-3": {"json": {"allRequestCount": 5, "successCount": 5}},
    }
    transport = CapturingKakaoTransport(post_responses=post_responses, task_responses=task_responses)

    result = await send_with_transport(user_ids, transport, batch_size=1_000)

    post_user_lengths = [len(request["json"]["user"]) for request in transport.post_requests()]
    assert result == {"success": True, "total_sent": 205, "total_failed": 0, "total_users": 205}
    assert post_user_lengths == [100, 100, 5]
    assert all(length <= 100 for length in post_user_lengths)


@pytest.mark.asyncio
async def test_bulk_alarm_preserves_duplicate_input_without_duplicate_ids_in_one_post(kakao_settings):
    user_ids = ["dup", "other", "dup", "third", "other"]
    transport = CapturingKakaoTransport(
        post_responses=[
            {"json": {"status": "SUCCESS", "taskId": "task-1"}},
            {"json": {"status": "SUCCESS", "taskId": "task-2"}},
        ],
        task_responses={
            "task-1": {"json": {"allRequestCount": 2, "successCount": 2}},
            "task-2": {"json": {"allRequestCount": 3, "successCount": 3}},
        },
    )

    result = await send_with_transport(user_ids, transport)

    posted_user_lists = [[user["id"] for user in request["json"]["user"]] for request in transport.post_requests()]
    assert result == {"success": True, "total_sent": 5, "total_failed": 0, "total_users": 5}
    assert sum(len(user_list) for user_list in posted_user_lists) == len(user_ids)
    assert all(len(user_list) == len(set(user_list)) for user_list in posted_user_lists)


@pytest.mark.asyncio
async def test_bulk_alarm_aggregates_task_success_and_fail_counts(kakao_settings):
    transport = CapturingKakaoTransport(
        post_responses=[{"json": {"status": "SUCCESS", "taskId": "task-1"}}],
        task_responses={"task-1": {"json": {"successCount": 3, "fail": {"count": 2, "list": []}}}},
    )

    result = await send_with_transport(["u1", "u2", "u3", "u4", "u5"], transport)

    assert result == {"success": True, "total_sent": 3, "total_failed": 2, "total_users": 5}


@pytest.mark.asyncio
async def test_bulk_alarm_polls_task_result_until_counts_are_parseable(kakao_settings):
    transport = CapturingKakaoTransport(
        post_responses=[{"json": {"status": "SUCCESS", "taskId": "task-1"}}],
        task_responses={
            "task-1": [
                {"json": {"status": "RUNNING"}},
                {"json": {"successCount": 4, "fail": {"count": 1, "list": []}}},
            ],
        },
    )

    result = await send_with_transport(["u1", "u2", "u3", "u4", "u5"], transport)

    task_requests = transport.task_requests()
    assert result == {"success": True, "total_sent": 4, "total_failed": 1, "total_users": 5}
    assert len(task_requests) == 2
    assert all(request["path"] == "/v1/tasks/task-1" for request in task_requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_response",
    [
        {"exception": httpx.ReadTimeout},
        {"status_code": 500, "json": {"error": "temporary"}},
        {"status_code": 200, "content": b"not-json"},
        {"json": {"successCount": 3, "fail": {"count": 3}}},
    ],
)
async def test_bulk_alarm_counts_task_lookup_failures_as_full_batch_failure(kakao_settings, task_response):
    transport = CapturingKakaoTransport(
        post_responses=[{"json": {"status": "SUCCESS", "taskId": "task-1"}}],
        task_responses={"task-1": task_response},
    )

    result = await send_with_transport(["u1", "u2", "u3", "u4"], transport)

    assert result == {"success": True, "total_sent": 0, "total_failed": 4, "total_users": 4}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "post_response",
    [
        {"status_code": 500, "json": {"status": "ERROR"}},
        {"json": {"status": "FAIL", "taskId": "task-1"}},
        {"json": {"status": "SUCCESS"}},
    ],
)
async def test_bulk_alarm_counts_post_failures_as_batch_failure(kakao_settings, post_response):
    transport = CapturingKakaoTransport(post_responses=[post_response])

    result = await send_with_transport(["u1", "u2"], transport)

    assert result == {"success": True, "total_sent": 0, "total_failed": 2, "total_users": 2}
    assert len(transport.task_requests()) == 0


@pytest.mark.asyncio
async def test_individual_alarm_still_sends_single_user_payload_with_injected_client(kakao_settings):
    transport = CapturingKakaoTransport(post_responses=[{"json": {"status": "SUCCESS", "taskId": "task-1"}}])
    async with httpx.AsyncClient(transport=transport) as client:
        result = await NotificationService.send_individual_alarm(
            AlarmRequest(user_id="u1", event_name="test_event", data={"message": "hello"}),
            client=client,
        )

    post_request = transport.post_requests()[0]
    assert result == {"success": True, "response": {"status": "SUCCESS", "taskId": "task-1"}}
    assert len(post_request["json"]["user"]) == 1
    assert post_request["json"]["user"][0]["id"] == "u1"
    assert len(transport.task_requests()) == 0


@pytest.mark.asyncio
async def test_bulk_alarm_missing_api_key_does_not_attempt_network(monkeypatch):
    monkeypatch.setattr(notification_module.settings, "BOT_ID", "test-bot")
    monkeypatch.setattr(notification_module.settings, "KAKAO_EVENT_API_KEY", "")
    transport = CapturingKakaoTransport()

    result = await send_with_transport(["u1"], transport)

    assert result == {"success": False, "error": "KAKAO_EVENT_API_KEY가 설정되지 않았습니다"}
    assert transport.requests == []


@pytest.mark.asyncio
async def test_bulk_alarm_missing_bot_id_does_not_attempt_network(monkeypatch):
    monkeypatch.setattr(notification_module.settings, "BOT_ID", "")
    monkeypatch.setattr(notification_module.settings, "KAKAO_EVENT_API_KEY", "test-rest-api-key")
    transport = CapturingKakaoTransport()

    result = await send_with_transport(["u1"], transport)

    assert result == {"success": False, "error": "BOT_ID가 설정되지 않았습니다"}
    assert transport.requests == []
