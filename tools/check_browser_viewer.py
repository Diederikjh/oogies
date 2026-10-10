#!/usr/bin/env python3
"""Run in the existing browser Docker image. --live starts exactly one camera session."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8088")
    parser.add_argument("--output", default="/output")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    options = webdriver.ChromeOptions()
    for argument in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                     "--disable-background-networking", "--disable-sync", "--no-first-run",
                     "--user-data-dir=/tmp/camera-browser", "--autoplay-policy=no-user-gesture-required"):
        options.add_argument(argument)
    options.add_experimental_option("prefs", {"credentials_enable_service": False})
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 20)
    started = False
    result = {}
    def status():
        with urlopen(args.url + "/api/status", timeout=5) as response:
            return json.load(response)
    try:
        driver.set_window_size(1280, 960)
        driver.get(args.url)
        wait.until(lambda d: d.find_element(By.ID, "start").is_enabled())
        assert status()["state"] == "stopped", "Page load must not start the SDK"
        result["page_load_starts_camera"] = False
        driver.find_element(By.ID, "recording-tab").click()
        driver.execute_script("document.getElementById('recording').play()")
        wait.until(lambda d: d.execute_script("return document.getElementById('recording').readyState >= 2"))
        wait.until(lambda d: d.execute_script("return document.getElementById('recording').currentTime > 0.8"))
        result["recording"] = driver.execute_script("const v=document.getElementById('recording'); return {time:v.currentTime,width:v.videoWidth,height:v.videoHeight,frames:v.webkitDecodedFrameCount,duration:v.duration}")
        driver.save_screenshot(str(output / "recording.png"))
        driver.find_element(By.ID, "live-tab").click()
        if args.live:
            driver.find_element(By.ID, "start").click()
            started = True
            wait.until(lambda d: status()["frames"] >= 20)
            wait.until(lambda d: d.execute_script("return document.getElementById('live-image').naturalWidth > 0"))
            first = status()
            def pixels():
                return driver.execute_script("const i=document.getElementById('live-image'),c=document.createElement('canvas'); c.width=i.naturalWidth;c.height=i.naturalHeight;c.getContext('2d').drawImage(i,0,0);return c.toDataURL('image/png')")
            before = hashlib.sha256(pixels().encode()).hexdigest()
            time.sleep(2)
            after = hashlib.sha256(pixels().encode()).hexdigest()
            assert before != after, "Displayed live pixels did not change"
            driver.save_screenshot(str(output / "live.png"))
            # Duplicate Start must be idempotent; refresh must attach to the same source.
            request = Request(args.url + "/api/start", data=b"{}", headers={"Content-Type":"application/json"})
            with urlopen(request, timeout=5) as response:
                assert json.load(response)["session"] == first["session"]
            driver.refresh()
            wait.until(lambda d: d.execute_script("return document.getElementById('live-image').naturalWidth > 0"))
            second = status()
            assert second["session"] == first["session"] and second["frames"] > first["frames"]
            result["live"] = dict(second, displayed_pixels_changed=True, refresh_reuses_session=True)
            driver.find_element(By.ID, "stop").click()
            wait.until(lambda d: status()["state"] == "stopped")
            result["stop_state"] = status()["state"]
    finally:
        if started:
            try:
                request = Request(args.url + "/api/stop", data=b"{}", headers={"Content-Type":"application/json"})
                with urlopen(request, timeout=15) as response:
                    response.read()
            except OSError:
                pass
        driver.quit()
    (output / "browser-check.json").write_text(json.dumps(result, indent=2) + "\n")
    for file in output.iterdir():
        if file.is_file():
            file.chmod(0o600)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
