from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from ..config import Settings


@dataclass
class CapturedNetworkResponse:
    url: str
    status: int
    mime_type: str
    body: str


@dataclass
class RenderedPage:
    final_url: str
    title: str
    html: str
    body_text: str
    visible_title: str
    resource_urls: List[str]
    api_responses: List[CapturedNetworkResponse]


@dataclass
class ApplicationWalkthrough:
    url: str
    final_url: str
    error_text: str
    request_payload: dict
    response_status: Optional[int]
    response_body: str


class BrowserRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.driver: Optional[webdriver.Chrome] = None

    def __enter__(self) -> "BrowserRenderer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None

    def render(self, url: str) -> RenderedPage:
        if self.driver is None:
            self.driver = webdriver.Chrome(options=self._build_options())
            self.driver.execute_cdp_cmd("Network.enable", {})

        self._drain_performance_log()
        self.driver.get(url)
        best_html = self.driver.page_source
        best_title = self.driver.title
        best_url = self.driver.current_url
        best_body_text = ""
        deadline = time.time() + self.settings.render_timeout_seconds

        while time.time() < deadline:
            self._dismiss_cookie_banner()
            time.sleep(1)

            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text.strip()
            except Exception:
                body_text = ""

            current_html = self.driver.page_source
            if len(body_text) > len(best_body_text):
                best_body_text = body_text
            if len(current_html) > len(best_html):
                best_html = current_html
                best_title = self.driver.title
                best_url = self.driver.current_url

            if self._looks_rendered(body_text, current_html):
                best_html = current_html
                best_title = self.driver.title
                best_url = self.driver.current_url
                best_body_text = body_text
                break

        resource_urls = self._capture_resource_urls()
        api_responses = self._capture_api_responses()
        return RenderedPage(
            final_url=best_url,
            title=best_title,
            html=best_html,
            body_text=best_body_text,
            visible_title=_derive_visible_title(best_body_text),
            resource_urls=resource_urls,
            api_responses=api_responses,
        )

    def walk_membership_application(self, url: str) -> Optional[ApplicationWalkthrough]:
        parsed = urlparse(url)
        if parsed.netloc != "apply.medicalprotection.org" or parsed.path.rstrip("/") != "/20":
            return None

        for _ in range(3):
            self.render(url)
            if self.driver is None:
                return None

            time.sleep(4)
            self._drain_performance_log()
            self._populate_scheme_20_personal_step()
            time.sleep(1)
            self._click("#NextButton")
            time.sleep(6)

            error_text = self._body_error_text()
            entries = self._performance_log_entries()
            request_payload = self._capture_prospect_request_payload(entries)
            response_status, response_body = self._capture_prospect_response(entries)

            if request_payload or response_status is not None or error_text:
                return ApplicationWalkthrough(
                    url=url,
                    final_url=self.driver.current_url,
                    error_text=error_text,
                    request_payload=request_payload,
                    response_status=response_status,
                    response_body=response_body,
                )

        return None

    def _build_options(self) -> Options:
        options = Options()
        options.binary_location = self.settings.chrome_binary_path
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1600,1600")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        return options

    def _dismiss_cookie_banner(self) -> None:
        if self.driver is None:
            return

        for selector in [
            "//button[normalize-space()='Accept']",
            "//button[contains(., 'Accept')]",
        ]:
            try:
                buttons = self.driver.find_elements(By.XPATH, selector)
                for button in buttons:
                    if button.is_displayed():
                        self.driver.execute_script("arguments[0].click();", button)
                        return
            except Exception:
                continue

    def _looks_rendered(self, body_text: str, html: str) -> bool:
        if len(body_text) < 150:
            return False
        keywords = (
            "membership application",
            "student application",
            "personal details",
            "join today",
        )
        if any(keyword in body_text.lower() for keyword in keywords):
            return True
        return "<form" in html.lower()

    def _drain_performance_log(self) -> None:
        if self.driver is None:
            return
        try:
            self.driver.get_log("performance")
        except Exception:
            return

    def _capture_resource_urls(self) -> List[str]:
        if self.driver is None:
            return []

        try:
            urls = self.driver.execute_script(
                """
                return performance.getEntriesByType('resource')
                    .map((entry) => entry.name)
                    .filter(Boolean);
                """
            )
        except Exception:
            return []

        seen = set()
        ordered: List[str] = []
        for url in urls or []:
            if not isinstance(url, str):
                continue
            if url in seen:
                continue
            seen.add(url)
            ordered.append(url)
        return ordered

    def _capture_api_responses(self) -> List[CapturedNetworkResponse]:
        if self.driver is None:
            return []

        responses: List[CapturedNetworkResponse] = []
        seen = set()
        for entry in self._performance_log_entries():
            if entry.get("method") != "Network.responseReceived":
                continue
            params = entry.get("params", {})
            response = params.get("response", {})
            url = str(response.get("url") or "")
            mime_type = str(response.get("mimeType") or "")
            status = int(response.get("status") or 0)
            if not url or status < 200 or status >= 300:
                continue
            if not (
                "/api/" in url
                or url.endswith("/appsettings.json")
                or "application/json" in mime_type.lower()
                or "problem+json" in mime_type.lower()
            ):
                continue
            request_id = params.get("requestId")
            body = self._response_body(request_id)
            key = (url, status, body[:120])
            if key in seen:
                continue
            seen.add(key)
            responses.append(
                CapturedNetworkResponse(
                    url=url,
                    status=status,
                    mime_type=mime_type,
                    body=body,
                )
            )
        return responses

    def _performance_log_entries(self) -> List[dict]:
        if self.driver is None:
            return []

        try:
            raw_entries = self.driver.get_log("performance")
        except Exception:
            return []

        entries: List[dict] = []
        for raw in raw_entries:
            try:
                entries.append(json.loads(raw["message"])["message"])
            except Exception:
                continue
        return entries

    def _response_body(self, request_id: Optional[str]) -> str:
        if self.driver is None or not request_id:
            return ""
        try:
            payload = self.driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        except Exception:
            return ""
        body = payload.get("body")
        return body if isinstance(body, str) else ""

    def _populate_scheme_20_personal_step(self) -> None:
        if self.driver is None:
            return

        future = date.today() + timedelta(days=14)
        membership_start = [str(future.day), str(future.month), str(future.year)]
        date_of_birth = ["1", "1", "1990"]

        self._set_number_inputs(membership_start, start_index=0)
        self._set_value("#prospectTitleId", "8")
        self._set_value("#firstName", "Test")
        self._set_value("#middleName", "Flow")
        self._set_value("#lastName", "Member")
        self._click("#gender1")
        self._set_number_inputs(date_of_birth, start_index=3)
        self._set_value("#address1", "1 Demo Street")
        self._set_value("#city", "Pretoria")
        self._set_value("#county", "Gauteng")
        self._set_value("#postcode", "0001")
        self._set_value("#email", "dummy@example.com")
        self._set_value("#emailConfirmation", "dummy@example.com")
        self._set_value("#mobilePhone", "0820000000")
        self._set_value("#homePhone", "0120000000")
        self._set_value("#workPhone", "0110000000")
        self._set_value("#idNumber", "9001015009087")
        self._click("#marketingNo")
        self._click("#consentYes")

    def _set_number_inputs(self, values: List[str], start_index: int) -> None:
        if self.driver is None:
            return
        elements = self.driver.find_elements(By.CSS_SELECTOR, "input[type='number']")
        for offset, value in enumerate(values):
            index = start_index + offset
            if index >= len(elements):
                return
            self.driver.execute_script(
                """
                const el = arguments[0];
                const value = arguments[1];
                const descriptor =
                    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')
                    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
                descriptor.set.call(el, value);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                """,
                elements[index],
                value,
            )

    def _set_value(self, selector: str, value: str) -> None:
        if self.driver is None:
            return
        self.driver.execute_script(
            """
            const el = document.querySelector(arguments[0]);
            if (!el) {
                return;
            }
            const descriptor =
                Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')
                || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
                || Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
            descriptor.set.call(el, arguments[1]);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            """,
            selector,
            value,
        )

    def _click(self, selector: str) -> None:
        if self.driver is None:
            return
        self.driver.execute_script(
            """
            const el = document.querySelector(arguments[0]);
            if (!el) {
                return;
            }
            el.click();
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            selector,
        )

    def _body_error_text(self) -> str:
        if self.driver is None:
            return ""
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            return ""
        for line in body_text.splitlines():
            cleaned = " ".join(line.split())
            if cleaned == "An error occurred submitting your application, please try again.":
                return cleaned
        return ""

    def _capture_prospect_request_payload(self, entries: List[dict]) -> dict:
        for entry in entries:
            if entry.get("method") != "Network.requestWillBeSent":
                continue
            request = entry.get("params", {}).get("request", {})
            if request.get("url") != "https://apply.medicalprotection.org/api/Prospect":
                continue
            post_data = request.get("postData")
            if not isinstance(post_data, str) or not post_data:
                continue
            try:
                payload = json.loads(post_data)
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}
        return {}

    def _capture_prospect_response(self, entries: List[dict]) -> tuple[Optional[int], str]:
        for entry in entries:
            if entry.get("method") != "Network.responseReceived":
                continue
            params = entry.get("params", {})
            response = params.get("response", {})
            if response.get("url") != "https://apply.medicalprotection.org/api/Prospect":
                continue
            status = int(response.get("status") or 0)
            body = self._response_body(params.get("requestId"))
            return status, body
        return None, ""


def _derive_visible_title(body_text: str) -> str:
    lowered = body_text.lower()
    if "student application" in lowered:
        return "Student application"
    if "membership application" in lowered:
        return "Membership application"

    ignored_lines = {
        "cookies button",
        "accept",
        "reject all",
        "let me choose",
        "south africa",
    }
    for raw_line in body_text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        if line.lower() in ignored_lines:
            continue
        if line.lower().startswith("by clicking “accept”") or line.lower().startswith('by clicking "accept"'):
            continue
        return line
    return ""
