#!/usr/bin/env python3
"""Bounded real-service History acceptance in Docker Chromium."""

import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8088")
    parser.add_argument("--output", default="/output")
    parser.add_argument("--continuous-seconds", type=int, default=30)
    args = parser.parse_args()
    if not 15 <= args.continuous_seconds <= 120: parser.error("choose 15–120 continuous seconds")
    output = Path(args.output); output.mkdir(mode=0o700, parents=True, exist_ok=True)
    options = webdriver.ChromeOptions()
    for flag in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                 "--disable-background-networking", "--disable-sync", "--no-first-run", "--user-data-dir=/tmp/history-browser"):
        options.add_argument(flag)
    driver = webdriver.Chrome(options=options); wait = WebDriverWait(driver, 30)
    try:
        driver.set_window_size(1500, 1100); driver.get(args.url)
        shortcut = wait.until(lambda _:driver.find_element(By.CSS_SELECTOR, '.camera-tile[data-camera-id="camera-1"] .camera-history'))
        shortcut.click()
        wait.until(lambda _:driver.find_element(By.ID, "history-camera").is_enabled())
        Select(driver.find_element(By.ID, "history-camera")).select_by_value("camera-1")
        wait.until(lambda _:driver.find_element(By.ID, "history-recordings").get_attribute("data-state") == "ready")
        driver.execute_script("const input=document.getElementById('history-position');input.value=7200;input.dispatchEvent(new Event('change',{bubbles:true}));")
        wait.until(lambda _:driver.execute_script("return !document.getElementById('history-image').hidden && document.getElementById('history-image').naturalWidth > 0"))
        def pixels():
            return driver.execute_script("const i=document.getElementById('history-image'),c=document.createElement('canvas');c.width=i.naturalWidth;c.height=i.naturalHeight;c.getContext('2d').drawImage(i,0,0);return c.toDataURL();")
        before = hashlib.sha256(pixels().encode()).hexdigest()
        wait.until(lambda _:hashlib.sha256(pixels().encode()).hexdigest() != before)
        started = time.monotonic()
        while time.monotonic() - started < args.continuous_seconds:
            assert driver.find_element(By.ID, "history-player").get_attribute("data-state") == "playing"
            time.sleep(.5)
        assert hashlib.sha256(pixels().encode()).hexdigest() != before
        rates = []
        for rate in ("0.5", "1", "2", "4"):
            button = driver.find_element(By.CSS_SELECTOR, f'#history-speeds button[data-rate="{rate}"]')
            wait.until(lambda _:button.is_enabled()); button.click()
            wait.until(lambda _:button.get_attribute("aria-pressed") == "true" and button.is_enabled())
            picture = pixels(); wait.until(lambda _:pixels() != picture)
            rates.append(float(rate))
        player = driver.find_element(By.ID, "history-pause"); wait.until(lambda _:player.is_enabled()); player.click()
        wait.until(lambda _:driver.find_element(By.ID, "history-player").get_attribute("data-state") == "paused")
        time.sleep(.3); paused = pixels(); time.sleep(.6); assert pixels() == paused
        dimensions = driver.execute_script("const i=document.getElementById('history-image'),r=i.getBoundingClientRect();return {width:i.naturalWidth,height:i.naturalHeight,ratio:r.width/r.height};")
        driver.save_screenshot(str(output / "history-playback.png"))
        assert abs(dimensions["ratio"] - 16/9) < .01
        driver.find_element(By.ID, "history-stop").click()
        wait.until(lambda _:driver.find_element(By.ID, "history-player").get_attribute("data-state") == "idle")
        with urlopen(args.url + "/api/status", timeout=5) as response: status = json.load(response)
        report = dict(moving_picture=True, camera_history_shortcut=True, playback_rates=rates,
                      continuous_seconds=args.continuous_seconds,
                      pause_holds_picture=True, sdk_login_calls=status["sdk_login_calls"],
                      playback_sessions_after_stop=status["playback_sessions"], **dimensions)
        file = output / "report.json"; file.write_text(json.dumps(report, indent=2)); file.chmod(0o600)
        for image in output.glob("*.png"): image.chmod(0o600)
        print(json.dumps(report))
    finally:
        try: driver.find_element(By.ID, "history-stop").click()
        except Exception: pass
        driver.quit()


if __name__ == "__main__": main()
