from __future__ import annotations

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


@dataclass
class AppServer:
    host: str
    port: int
    process: subprocess.Popen[str]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run browser smoke tests for the MPS Assistant chat UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8013)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    server = start_server(args.host, args.port, args.timeout)
    try:
        run_desktop_scenarios(server.base_url, args.timeout)
        run_mobile_scenarios(server.base_url, args.timeout)
    finally:
        stop_server(server)

    print("Chat UI smoke tests passed.")
    return 0


def start_server(host: str, port: int, timeout: int) -> AppServer:
    if _is_port_open(host, port):
        raise RuntimeError(f"Port {port} is already in use.")

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mps_assistant.app:app", "--host", host, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    server = AppServer(host=host, port=port, process=process)
    wait_for_server(server, timeout)
    return server


def stop_server(server: AppServer) -> None:
    if server.process.poll() is not None:
        return

    server.process.terminate()
    try:
        server.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.process.kill()
        server.process.wait(timeout=5)


def wait_for_server(server: AppServer, timeout: int) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        if server.process.poll() is not None:
            output = ""
            if server.process.stdout is not None:
                output = server.process.stdout.read()
            raise RuntimeError(f"Server exited early.\n{output}")

        try:
            with urllib.request.urlopen(f"{server.base_url}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except urllib.error.URLError as error:
            last_error = str(error)
        time.sleep(0.5)

    output = ""
    if server.process.stdout is not None:
        output = _drain_process_output(server.process)
    raise RuntimeError(f"Timed out waiting for server. Last error: {last_error}\n{output}")


def run_desktop_scenarios(base_url: str, timeout: int) -> None:
    with build_driver(1600, 1200) as driver:
        open_chat(driver, base_url, timeout)
        clear_session_state(driver)
        open_chat(driver, base_url, timeout)

        assert driver.find_element(By.ID, "ask-button").text == "Send"
        WebDriverWait(driver, timeout).until(lambda d: count_visible(d, ".starter-chip") == 3)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".confidence-pill")) == 0
        assert len(driver.find_elements(By.CSS_SELECTOR, ".message-row-assistant")) == 1
        assert application_panel_visible(driver) is False

        ask_question(driver, "What should I do if I receive a complaint?", timeout)
        wait_for_message_count(driver, 3, timeout)
        wait_for_assistant_sources(driver, timeout)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".message-row-user")) == 1
        assert application_panel_visible(driver) is False

        ask_question(driver, "How much does it cost to join?", timeout)
        wait_for_message_count(driver, 5, timeout)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".message-row-user")) == 2

        driver.refresh()
        WebDriverWait(driver, timeout).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".message-row-user")) == 2)

        ask_question(driver, "Open the application", timeout)
        wait_for_message_count(driver, 7, timeout)
        wait_for_application_panel(driver, timeout)
        assert application_panel_visible(driver) is True

        driver.find_element(By.ID, "toggle-chatbox").click()
        WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.ID, "chat-launcher").is_displayed())
        driver.find_element(By.ID, "chat-launcher").click()
        WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.ID, "chatbox-shell").get_attribute("class").find("is-open") >= 0)

        driver.find_element(By.ID, "new-chat").click()
        WebDriverWait(driver, timeout).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".message-row-user")) == 0)
        WebDriverWait(driver, timeout).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".message-row-assistant")) == 1)
        WebDriverWait(driver, timeout).until(lambda d: application_panel_visible(d) is False)
        assert count_visible(driver, ".starter-chip") == 3

        driver.find_element(By.CSS_SELECTOR, ".starter-more-button").click()
        WebDriverWait(driver, timeout).until(lambda d: count_visible(d, ".starter-chip") == 5)


def run_mobile_scenarios(base_url: str, timeout: int) -> None:
    with build_driver(390, 844) as driver:
        open_chat(driver, base_url, timeout)
        clear_session_state(driver)
        open_chat(driver, base_url, timeout)

        assert driver.find_element(By.ID, "ask-button").text == "Send"
        WebDriverWait(driver, timeout).until(lambda d: count_visible(d, ".starter-chip") == 3)
        ask_question(driver, "What file types can I upload in the application?", timeout)
        wait_for_message_count(driver, 3, timeout)
        wait_for_assistant_sources(driver, timeout)
        assert driver.find_element(By.ID, "ask-button").text == "Send"

        ask_question(driver, "Open the application", timeout)
        wait_for_application_panel(driver, timeout)
        assert application_panel_visible(driver) is True


def build_driver(width: int, height: int) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument(f"--window-size={width},{height}")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=options)


def open_chat(driver: webdriver.Chrome, base_url: str, timeout: int) -> None:
    driver.get(base_url)
    WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.ID, "question-input"))
    WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.ID, "new-chat"))


def clear_session_state(driver: webdriver.Chrome) -> None:
    driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")


def ask_question(driver: webdriver.Chrome, question: str, timeout: int) -> None:
    question_input = driver.find_element(By.ID, "question-input")
    question_input.clear()
    question_input.send_keys(question)
    question_input.send_keys(Keys.ENTER)
    WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.ID, "ask-button").text in {"Thinking...", "Send"})
    WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.ID, "ask-button").text == "Send")


def wait_for_message_count(driver: webdriver.Chrome, count: int, timeout: int) -> None:
    WebDriverWait(driver, timeout).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".message-row")) >= count)


def wait_for_assistant_sources(driver: webdriver.Chrome, timeout: int) -> None:
    WebDriverWait(driver, timeout).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".message-row-assistant .message-sources")) >= 1)


def wait_for_application_panel(driver: webdriver.Chrome, timeout: int) -> None:
    WebDriverWait(driver, timeout).until(lambda d: application_panel_visible(d) is True)


def application_panel_visible(driver: webdriver.Chrome) -> bool:
    stage = driver.find_element(By.ID, "application-stage")
    classes = stage.get_attribute("class") or ""
    return "hidden" not in classes and len(driver.find_elements(By.CSS_SELECTOR, ".application-panel-shell")) == 1


def count_visible(driver: webdriver.Chrome, selector: str) -> int:
    return sum(1 for element in driver.find_elements(By.CSS_SELECTOR, selector) if element.is_displayed())


def _is_port_open(host: str, port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _drain_process_output(process: subprocess.Popen[str]) -> str:
    if process.stdout is None:
        return ""
    time.sleep(0.2)
    chunks = []
    while True:
        chunk = process.stdout.read()
        if not chunk:
            break
        chunks.append(chunk)
    return "".join(chunks)


if __name__ == "__main__":
    raise SystemExit(main())
