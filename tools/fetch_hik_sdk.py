#!/usr/bin/env python3
"""Inspect the public SDK download page in the temporary browser container."""

import json
import os
import argparse
from pathlib import Path
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/cam-chromium-config")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/cam-chromium-cache")
    options = Options()
    for option in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,900"):
        options.add_argument(option)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    try:
        driver.get("https://www.hikvision.com/en/support/tools/hitools/clf4633a00e385d6ea/")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if "SDK" in driver.title or "Device Network SDK" in driver.page_source:
                break
            time.sleep(2)
        output = Path("/output")
        output.mkdir(exist_ok=True)
        (output / "sdk-page.html").write_text(driver.page_source)
        (output / "sdk-page-network.json").write_text(json.dumps(driver.get_log("performance")))
        cookies_file = output / "sdk-page-cookies.json"
        cookies_file.write_text(json.dumps(driver.get_cookies()))
        cookies_file.chmod(0o600)
        links = driver.execute_script("return Array.from(document.querySelectorAll('a[href],button[data-href]')).map(a=>({text:a.innerText,url:a.getAttribute('data-href')||a.href}));")
        selected = [item for item in links if any(term in (item["url"] + item["text"]).lower() for term in ("linux", "hcnetsdk", ".zip", ".tar"))]
        print(json.dumps({"title": driver.title, "page_bytes": len(driver.page_source), "download_links": selected[:25]}, indent=2), flush=True)
        if args.download:
            candidates = [item["url"] for item in selected
                          if item["url"].startswith("https://assets.hikvision.com/")
                          and item["url"].endswith("_linux64.zip")]
            if not candidates:
                raise RuntimeError("official Linux SDK download URL not found")
            driver.execute_cdp_cmd("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(output)})
            button = driver.find_element(By.CSS_SELECTOR, "button.download-button-mobile-view[data-href]")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'})", button)
            time.sleep(2)
            button.click()
            time.sleep(3)
            agreements = driver.find_elements(By.CSS_SELECTOR, "a.agree.a-download-href")
            matching = [element for element in agreements if element.get_attribute("href") == candidates[0]]
            if not matching:
                (output / "sdk-download-dialog.html").write_text(driver.page_source)
                print(json.dumps({"download_dialog": [
                    {"visible": element.is_displayed(), "href": element.get_attribute("href")}
                    for element in agreements
                ], "window_titles": [driver.title], "window_count": len(driver.window_handles)}), flush=True)
                for entry in driver.get_log("performance"):
                    message = json.loads(entry["message"])["message"]
                    if message["method"] == "Network.responseReceived":
                        params = message["params"]
                        url = params["response"]["url"]
                        if "all-components.min." in url or "clientlib-common.min." in url:
                            try:
                                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": params["requestId"]})
                                (output / url.rsplit('/', 1)[-1]).write_text(body["body"])
                            except Exception:
                                pass
                return
            agreement = next((element for element in matching if element.is_displayed()), matching[0])
            driver.execute_script("arguments[0].click()", agreement)
            filename = candidates[0].rsplit("/", 1)[-1]
            downloaded = output / filename
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if downloaded.is_file() and not list(output.glob("*.crdownload")):
                    print(json.dumps({"downloaded_file": filename, "bytes": downloaded.stat().st_size}), flush=True)
                    return
                time.sleep(1)
            (output / "sdk-download-response.html").write_text(driver.page_source)
            print(json.dumps({"download_error": "no completed archive after 120 seconds", "page_title": driver.title}), flush=True)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
