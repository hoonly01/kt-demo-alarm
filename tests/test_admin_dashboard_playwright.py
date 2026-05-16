import pytest
from playwright.sync_api import expect, sync_playwright

from app.config.settings import settings


ADMIN_USER = "admin"
ADMIN_PASS = f"{ADMIN_USER}-playwright-auth"
ADMIN_AUTH = (ADMIN_USER, ADMIN_PASS)

ADMIN_SECTION_TEST_IDS = [
    "overview-section",
    "collection-section",
    "alarm-section",
    "user-readiness-section",
    "action-section",
    "event-explorer-section",
    "bus-section",
]

ADMIN_ACTION_ENDPOINTS = [
    "/admin/trigger-crawling",
    "/admin/trigger-bus-notice",
    "/admin/trigger-route-check",
    "/admin/trigger-zone-check",
    "/admin/trigger-test-alarm-for-user",
]


@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_playwright_smoke_blocks_non_local_requests(test_client, monkeypatch):
    """Playwright smoke: 주요 섹션은 보이고 trigger 클릭 없이 endpoint wiring만 확인한다."""
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)
    assert response.status_code == 200

    console_errors = []
    blocked_non_local_requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(base_url="http://testserver")

        def route_non_local_requests(route):
            request_url = route.request.url
            if request_url.startswith(("http://testserver", "data:", "blob:", "about:")):
                route.continue_()
                return
            blocked_non_local_requests.append(request_url)
            route.abort()

        page.route("**/*", route_non_local_requests)
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )

        page.set_content(response.text, wait_until="domcontentloaded")

        expect(page.get_by_role("heading", name="KT Demo Alarm Back-office")).to_be_visible()
        expect(page.locator("section.section")).to_have_count(len(ADMIN_SECTION_TEST_IDS))
        for test_id in ADMIN_SECTION_TEST_IDS:
            expect(page.get_by_test_id(test_id)).to_be_visible()
        expect(page.get_by_text("Scheduler 상태")).to_be_visible()
        for endpoint in ADMIN_ACTION_ENDPOINTS:
            expect(page.get_by_text(endpoint, exact=True)).to_be_visible()

        browser.close()

    assert console_errors == []
    assert blocked_non_local_requests == []
