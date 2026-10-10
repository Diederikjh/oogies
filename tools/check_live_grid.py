#!/usr/bin/env python3
"""Verify the real live grid and shared viewer lifetimes in Docker Chromium."""

import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8088")
    parser.add_argument("--output", default="/output")
    args = parser.parse_args()
    output = Path(args.output); output.mkdir(mode=0o700, parents=True, exist_ok=True)
    def backend():
        with urlopen(args.url + "/api/status", timeout=5) as response: return json.load(response)
    with urlopen(args.url + "/api/cameras", timeout=35) as response: inventory = json.load(response)["cameras"]
    online = [camera["id"] for camera in inventory if camera["online"] is not False]
    options = webdriver.ChromeOptions()
    for flag in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                 "--disable-background-networking", "--disable-sync", "--no-first-run",
                 "--user-data-dir=/tmp/grid-browser", "--autoplay-policy=no-user-gesture-required"):
        options.add_argument(flag)
    options.set_capability("goog:loggingPrefs", {"browser":"ALL"})
    driver = webdriver.Chrome(options=options); wait = WebDriverWait(driver, 25)
    results = {}
    try:
        driver.set_window_size(1600, 1100)
        driver.get(args.url)
        first_tab = driver.current_window_handle
        def pictures():
            return driver.execute_script("""
                return [...document.querySelectorAll('.camera-tile')].map(tile => {
                    const img=tile.querySelector('img'), rect=img.getBoundingClientRect(), view=img.parentElement.getBoundingClientRect();
                    return {id:tile.dataset.cameraId,state:tile.dataset.state,
                        source_width:img.naturalWidth,source_height:img.naturalHeight,
                        displayed:!img.hidden && img.naturalWidth>0,
                        ratio:rect.height?rect.width/rect.height:null,
                        fits:rect.left>=view.left && rect.right<=view.right+1 && rect.top>=view.top && rect.bottom<=view.bottom+1};
                });
            """)
        wait.until(lambda _: all(any(pic["id"] == key and pic["displayed"] and pic["state"] == "live" for pic in pictures()) for key in online))
        results["cameras"] = pictures()
        assert len(results["cameras"]) == len(inventory)
        assert all(pic["fits"] and abs(pic["ratio"] - 16/9) < 0.01 for pic in results["cameras"] if pic["displayed"])
        results["one_view"] = backend()
        assert results["one_view"]["active_live_sources"] == len(online)
        assert results["one_view"]["viewer_sessions"] == 1
        def pixels():
            return driver.execute_script("const img=document.querySelector('.camera-tile[data-camera-id=\"camera-1\"] img'), c=document.createElement('canvas'); c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext('2d').drawImage(img,0,0);return c.toDataURL('image/png');")
        before = hashlib.sha256(pixels().encode()).hexdigest(); time.sleep(2)
        assert before != hashlib.sha256(pixels().encode()).hexdigest()
        results["live_pixels_change"] = True
        driver.save_screenshot(str(output / "grid-desktop.png"))
        driver.find_element(By.CSS_SELECTOR, '.camera-tile[data-camera-id="camera-1"] .camera-view').click()
        wait.until(lambda _: driver.find_element(By.CSS_SELECTOR, '.camera-tile[data-camera-id="camera-1"]').get_attribute("class").endswith("is-expanded"))
        assert backend()["active_live_sources"] == len(online)
        driver.find_element(By.CSS_SELECTOR, '.camera-tile[data-camera-id="camera-1"] .camera-view').click()
        driver.set_window_size(390, 844)
        wait.until(lambda _: all(pic["fits"] for pic in pictures() if pic["displayed"]))
        driver.save_screenshot(str(output / "grid-mobile.png"))
        driver.set_window_size(1600, 1100)
        driver.switch_to.new_window("tab"); driver.get(args.url)
        wait.until(lambda _: backend()["viewer_sessions"] == 2 and all(any(pic["id"]==key and pic["displayed"] for pic in pictures()) for key in online))
        results["two_views"] = backend()
        assert results["two_views"]["active_live_sources"] == len(online)
        assert results["two_views"]["sdk_login_calls"] == results["one_view"]["sdk_login_calls"] == 1
        driver.find_element(By.ID, "stop").click()
        wait.until(lambda _: backend()["viewer_sessions"] == 1)
        assert backend()["active_live_sources"] == len(online)
        driver.close(); driver.switch_to.window(first_tab)
        wait.until(lambda _: all(pic["state"] == "live" for pic in pictures() if pic["id"] in online))
        results["closing_one_view_preserves_other"] = True
        if backend()["recording_available"]:
            driver.find_element(By.ID, "recording-tab").click()
            wait.until(lambda _: backend()["active_live_sources"] == 0)
            driver.execute_script("document.getElementById('recording').play();")
            wait.until(lambda _: driver.execute_script("return document.getElementById('recording').currentTime > 0.5"))
            results["recorded_clip_plays"] = True
            driver.save_screenshot(str(output / "recorded-clip.png"))
        else:
            driver.find_element(By.ID, "stop").click()
            wait.until(lambda _: backend()["active_live_sources"] == 0)
            results["recorded_clip_plays"] = "not_run: no private clip"
        errors = [entry for entry in driver.get_log("browser") if entry["level"] == "SEVERE" and "favicon.ico" not in entry["message"]]
        assert not errors, str(errors)
        results["browser_errors"] = errors
        results["final_backend"] = backend()
        (output / "grid-check.json").write_text(json.dumps(results, indent=2) + "\n")
        for path in output.iterdir():
            if path.is_file(): path.chmod(0o600)
        print(json.dumps(results, indent=2))
    finally:
        driver.quit()


if __name__ == "__main__": main()
