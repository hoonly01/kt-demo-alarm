import pytest
from playwright.sync_api import expect, sync_playwright

from app.config.settings import settings


ADMIN_USER = "admin"
ADMIN_PASS = f"{ADMIN_USER}-playwright-auth"
ADMIN_AUTH = (ADMIN_USER, ADMIN_PASS)

ADMIN_SECTION_TEST_IDS = [
    "overview-section",
    "collection-section",
    "bus-section",
    "alarm-section",
    "user-readiness-section",
    "action-section",
    "event-explorer-section",
]

ADMIN_DETAIL_BUTTONS = {
    "collection": "collection-section",
    "bus": "bus-section",
    "alarms": "alarm-section",
    "readiness": "user-readiness-section",
    "events": "event-explorer-section",
}

ADMIN_DETAIL_SECTION_TEST_IDS = list(ADMIN_DETAIL_BUTTONS.values())

ADMIN_ACTION_ENDPOINTS = [
    "/admin/trigger-crawling",
    "/admin/trigger-bus-notice",
    "/admin/trigger-route-check",
    "/admin/trigger-zone-check",
    "/admin/trigger-test-alarm-for-user",
]


@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_playwright_smoke_blocks_non_local_requests(test_client, monkeypatch):
    """Playwright smoke: 기본 hidden 업무 패널, disclosure 전환, hash 복원을 검증한다."""
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)
    assert response.status_code == 200

    console_errors = []
    blocked_non_local_requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(base_url="http://testserver")

        def route_dashboard_and_block_non_local_requests(route):
            request_url = route.request.url
            if request_url.startswith("http://testserver/admin/dashboard"):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=response.text)
                return
            if request_url.startswith(("http://testserver", "data:", "blob:", "about:")):
                route.abort()
                return
            blocked_non_local_requests.append(request_url)
            route.abort()

        page.route("**/*", route_dashboard_and_block_non_local_requests)
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )

        page.set_content(response.text, wait_until="domcontentloaded")

        expect(page.get_by_role("heading", name="KT Demo Alarm Back-office")).to_be_visible()
        expect(page.locator("section.section")).to_have_count(len(ADMIN_SECTION_TEST_IDS))
        expect(page.get_by_test_id("overview-section")).to_be_visible()
        expect(page.get_by_test_id("action-section")).to_be_visible()
        for test_id in ADMIN_DETAIL_SECTION_TEST_IDS:
            expect(page.get_by_test_id(test_id)).to_be_hidden()
        expect(page.get_by_text("Scheduler 상태")).to_be_visible()
        for endpoint in ADMIN_ACTION_ENDPOINTS:
            expect(page.get_by_text(endpoint, exact=True)).to_be_visible()

        for button_key, selected_test_id in ADMIN_DETAIL_BUTTONS.items():
            button = page.get_by_test_id(f"dashboard-task-button-{button_key}")
            controls = button.get_attribute("aria-controls")
            assert controls
            expect(button).to_have_attribute("aria-expanded", "false")
            expect(page.locator(f"#{controls}")).to_have_attribute("data-testid", selected_test_id)

            button.click()
            expect(button).to_have_attribute("aria-expanded", "true")
            expect(page.locator(f"#{controls}")).to_be_visible()
            for other_key, other_test_id in ADMIN_DETAIL_BUTTONS.items():
                if other_key == button_key:
                    continue
                expect(page.get_by_test_id(other_test_id)).to_be_hidden()
                expect(page.get_by_test_id(f"dashboard-task-button-{other_key}")).to_have_attribute(
                    "aria-expanded",
                    "false",
                )

        page.goto("http://testserver/admin/dashboard#readiness", wait_until="domcontentloaded")
        expect(page.get_by_test_id("user-readiness-section")).to_be_visible()
        expect(page.get_by_test_id("dashboard-task-button-readiness")).to_have_attribute(
            "aria-expanded",
            "true",
        )
        for test_id in (
            "collection-section",
            "bus-section",
            "alarm-section",
            "event-explorer-section",
        ):
            expect(page.get_by_test_id(test_id)).to_be_hidden()

        browser.close()

    assert console_errors == []
    assert blocked_non_local_requests == []
