#!/usr/bin/env python3
"""Verify the real live grid and shared viewer lifetimes in Docker Chromium."""

import argparse
import hashlib
import json
import signal
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
    parser.add_argument("--sustain-seconds", type=int, default=0,
                        help="Explicitly add a 180-900 second reliability check (requires high-quality headroom)")
    args = parser.parse_args()
    if args.sustain_seconds and not 180 <= args.sustain_seconds <= 900:
        parser.error("sustained duration must be 180-900 seconds")
    if args.sustain_seconds:
        # Give the scoped cleanup below a chance to run on a resource stop.
        def interrupted(*_): raise KeyboardInterrupt("Reliability check interrupted")
        signal.signal(signal.SIGTERM, interrupted)
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
        if args.sustain_seconds:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                {"source":Path(__file__).with_name("browser_feed_fault.js").read_text()})
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
        can_upgrade = results["one_view"]["high_quality_limit"] > 0 and len(online) < results["one_view"]["source_limit"]
        def quality(value):
            return driver.find_element(By.CSS_SELECTOR, '.camera-tile[data-camera-id="camera-1"]').get_attribute("data-quality") == value
        if can_upgrade:
            wait.until(lambda _: quality("high"))
            results["expanded_quality"] = next(pic for pic in pictures() if pic["id"]=="camera-1")
            assert backend()["active_live_sources"] == len(online)+1
            assert backend()["sources_by_quality"]["high"] == 1
            assert "1 high quality" in driver.find_element(By.ID,"view-note").text
            assert abs(results["expanded_quality"]["ratio"]-16/9)<.01
            before = hashlib.sha256(pixels().encode()).hexdigest(); time.sleep(1)
            assert hashlib.sha256(pixels().encode()).hexdigest()!=before
        else:
            wait.until(lambda _: "High quality unavailable" in driver.find_element(By.CSS_SELECTOR,'.camera-tile[data-camera-id="camera-1"] .tile-metrics').text)
            assert backend()["active_live_sources"] == len(online)
        driver.save_screenshot(str(output / "grid-expanded.png"))
        driver.find_element(By.CSS_SELECTOR, '.camera-tile[data-camera-id="camera-1"] .camera-view').click()
        wait.until(lambda _: quality("overview") and backend()["sources_by_quality"]["high"]==0)
        driver.set_window_size(390, 844)
        wait.until(lambda _: all(pic["fits"] for pic in pictures() if pic["displayed"]))
        driver.save_screenshot(str(output / "grid-mobile.png"))
        driver.set_window_size(1600, 1100)
        driver.switch_to.new_window("tab"); driver.get(args.url)
        wait.until(lambda _: backend()["viewer_sessions"] == 2 and all(any(pic["id"]==key and pic["displayed"] for pic in pictures()) for key in online))
        results["two_views"] = backend()
        assert results["two_views"]["active_live_sources"] == len(online)
        assert results["two_views"]["sdk_login_calls"] == results["one_view"]["sdk_login_calls"] == 1
        second_tab = driver.current_window_handle
        if can_upgrade:
            driver.find_element(By.CSS_SELECTOR,'.camera-tile[data-camera-id="camera-1"] .camera-view').click()
            wait.until(lambda _:quality("high"))
            driver.switch_to.window(first_tab)
            driver.find_element(By.CSS_SELECTOR,'.camera-tile[data-camera-id="camera-1"] .camera-view').click()
            wait.until(lambda _:quality("high"))
            results["two_high_views"] = backend()
            assert results["two_high_views"]["active_live_sources"] == len(online)+1
            assert results["two_high_views"]["sources_by_quality"]["high"] == 1
            driver.switch_to.window(second_tab)
        driver.find_element(By.ID, "stop").click()
        wait.until(lambda _: backend()["viewer_sessions"] == 1)
        assert backend()["active_live_sources"] == len(online)+int(can_upgrade)
        driver.close(); driver.switch_to.window(first_tab)
        wait.until(lambda _: all(pic["state"] == "live" for pic in pictures() if pic["id"] in online))
        results["closing_one_view_preserves_other"] = True
        if can_upgrade:
            wait.until(lambda _:quality("high"))
            before = hashlib.sha256(pixels().encode()).hexdigest(); time.sleep(1)
            assert hashlib.sha256(pixels().encode()).hexdigest()!=before
            if args.sustain_seconds:
                from live_reliability import sustain
                results["reliability"] = sustain(driver, wait, backend, online,
                    args.url, output, args.sustain_seconds)
            driver.find_element(By.CSS_SELECTOR,'.camera-tile[data-camera-id="camera-1"] .camera-view').click()
            wait.until(lambda _:quality("overview") and backend()["sources_by_quality"]["high"]==0)
        elif args.sustain_seconds:
            raise RuntimeError("Sustained quality check needs an available high-quality slot")
        driver.find_element(By.ID, "history-tab").click()
        wait.until(lambda _: backend()["active_live_sources"] == 0)
        if args.sustain_seconds:
            wait.until(lambda _:backend()["active_media_feeds"]==0)
        wait.until(lambda _: all(driver.find_element(By.ID, "history-" + name).get_attribute("data-state")
            in ("ready", "unsupported", "error") for name in ("recordings", "motion")))
        results["history_timeline"] = {name:dict(
            state=driver.find_element(By.ID, "history-" + name).get_attribute("data-state"),
            intervals=len(driver.find_elements(By.CSS_SELECTOR, "#history-" + name + " button")))
            for name in ("recordings", "motion")}
        assert backend()["sdk_login_calls"] == 1
        driver.save_screenshot(str(output / "history-timeline.png"))
        errors = [entry for entry in driver.get_log("browser") if entry["level"] == "SEVERE" and "favicon.ico" not in entry["message"] and
            not (args.sustain_seconds and entry.get("source")=="network" and "/media/" in entry["message"] and "409" in entry["message"])]
        assert not errors, str(errors)
        results["browser_errors"] = errors
        results["final_backend"] = backend()
        (output / "grid-check.json").write_text(json.dumps(results, indent=2) + "\n")
        for path in output.iterdir():
            if path.is_file(): path.chmod(0o600)
        print(json.dumps(results, indent=2))
    except BaseException as error:
        if args.sustain_seconds:
            failure=dict(error=str(error),tabs=[])
            for index,tab in enumerate(driver.window_handles):
                try:
                    driver.switch_to.window(tab)
                    failure["tabs"].append(driver.execute_script("""
                        const player=document.getElementById('history-player'),img=document.getElementById('history-image');
                        return {history_state:player?.dataset.state,history_message:document.getElementById('history-playback-status')?.textContent,
                          image:{width:img?.naturalWidth,complete:img?.complete,hidden:img?.hidden},
                          tiles:[...document.querySelectorAll('.camera-tile')].map(tile=>({id:tile.dataset.cameraId,state:tile.dataset.state,quality:tile.dataset.quality})),
                          media:window.mediaFault?{attempts:mediaFault.attempts,bytes:mediaFault.bytes}:null};
                    """))
                    driver.save_screenshot(str(output/f"failure-tab-{index}.png"))
                except Exception: pass
            (output/"failure.json").write_text(json.dumps(failure,indent=2)+"\n")
        raise
    finally:
        if args.sustain_seconds:
            for tab in driver.window_handles:
                try:
                    driver.switch_to.window(tab)
                    driver.execute_async_script("""
                        const done=arguments[0];Promise.all((window.checkOwnedSessions||[]).map(path=>
                          fetch(path,{method:'DELETE'}).catch(()=>{}))).then(()=>done());
                    """)
                except Exception:
                    pass  # Closing the browser leaves leases as the fallback.
        driver.quit()


if __name__ == "__main__": main()
