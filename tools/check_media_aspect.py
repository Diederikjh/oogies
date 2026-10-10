#!/usr/bin/env python3
"""Verify picture proportions in Docker Chromium using saved media, without an NVR."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True)
    parser.add_argument("--recording", required=True)
    parser.add_argument("--output", default="/output")
    args = parser.parse_args()
    frame, recording = Path(args.frame), Path(args.recording)
    output = Path(args.output)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    assets = {"/": Path("/web/index.html"), "/app.js": Path("/web/app.js"),
              "/style.css": Path("/web/style.css"),
              "/shared/media-player.js": Path("/web/shared/media-player.js"),
              "/stream.mjpeg": frame, "/recording.mp4": recording}
    types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
             ".jpg": "image/jpeg", ".mp4": "video/mp4"}
    requests = []

    class FixtureHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            requests.append(("GET", path))
            if path == "/api/status":
                body = json.dumps({"state": "live", "session": "saved-frame-fixture",
                    "frames": 1, "width": 352, "height": 288, "error": None,
                    "session_seconds": 600, "recording_available": True}).encode()
                content_type = "application/json"
            elif path in assets:
                body = assets[path].read_bytes()
                content_type = types[assets[path].suffix]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            requests.append(("POST", urlsplit(self.path).path))
            self.send_error(405, "Fixture never starts a camera")

    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    options = webdriver.ChromeOptions()
    for flag in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                 "--disable-background-networking", "--disable-sync", "--no-first-run",
                 "--user-data-dir=/tmp/aspect-browser"):
        options.add_argument(flag)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    driver = None
    results = []
    try:
        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 15)
        driver.set_window_size(1280, 960)
        driver.get(f"http://127.0.0.1:{server.server_port}/")
        wait.until(lambda d: d.execute_script("return document.getElementById('live-image').naturalWidth > 0"))
        driver.execute_script("localStorage.setItem('home-cameras.camera-1.display-aspect', 'original');")
        driver.refresh()
        wait.until(lambda d: d.execute_script("return document.getElementById('live-image').naturalWidth > 0"))
        assert Select(driver.find_element(By.ID, "picture-aspect")).first_selected_option.get_attribute("value") == "16:9", "Old comparison choices must not override the confirmed default"

        def geometry(element_id):
            return driver.execute_script("""
                const media = document.getElementById(arguments[0]);
                const rect = media.getBoundingClientRect();
                const viewport = media.parentElement.getBoundingClientRect();
                return {width:rect.width, height:rect.height,
                    natural_width:media.naturalWidth || media.videoWidth,
                    natural_height:media.naturalHeight || media.videoHeight,
                    within_viewport:rect.left >= viewport.left && rect.right <= viewport.right + 1 &&
                        rect.top >= viewport.top && rect.bottom <= viewport.bottom + 1,
                    object_fit:getComputedStyle(media).objectFit};
            """, element_id)

        def check(element_id, mode, ratio, label):
            Select(driver.find_element(By.ID, "picture-aspect")).select_by_value(mode)
            wait.until(lambda d: abs(geometry(element_id)["width"] / geometry(element_id)["height"] - ratio) < 0.01)
            data = geometry(element_id)
            assert data["within_viewport"], "Picture must fit inside the viewer"
            assert data["object_fit"] == "fill", "Display box must correct non-square raster proportions"
            results.append(dict(data, mode=mode, case=label))
            driver.save_screenshot(str(output / (label + ".png")))

        check("live-image", "16:9", 16 / 9, "live-widescreen-desktop")
        check("live-image", "original", 352 / 288, "live-original-desktop")
        check("live-image", "4:3", 4 / 3, "live-standard-desktop")
        driver.refresh()
        wait.until(lambda d: d.execute_script("return document.getElementById('live-image').naturalWidth > 0"))
        assert Select(driver.find_element(By.ID, "picture-aspect")).first_selected_option.get_attribute("value") == "4:3"
        assert abs(geometry("live-image")["width"] / geometry("live-image")["height"] - 4 / 3) < 0.01

        Select(driver.find_element(By.ID, "picture-aspect")).select_by_value("16:9")
        driver.set_window_size(390, 844)
        check("live-image", "16:9", 16 / 9, "live-widescreen-mobile")
        driver.find_element(By.ID, "recording-tab").click()
        driver.execute_script("const v=document.getElementById('recording'); v.preload='metadata'; v.load();")
        wait.until(lambda d: d.execute_script("return document.getElementById('recording').videoWidth > 0"))
        check("recording", "16:9", 16 / 9, "recording-widescreen-mobile")
        driver.set_window_size(1280, 960)
        check("recording", "16:9", 16 / 9, "recording-widescreen-desktop")
        check("recording", "original", 960 / 1088, "recording-original-desktop")
        driver.find_element(By.ID, "live-tab").click()
        wait.until(lambda d: d.execute_script("return document.getElementById('live-image').naturalWidth > 0"))
        check("live-image", "16:9", 16 / 9, "live-after-mode-switch")
        errors = [entry for entry in driver.get_log("browser") if entry["level"] == "SEVERE"
                  and "favicon.ico" not in entry["message"]]
        assert not errors, "Browser reported a script or media error"
        assert not any(method == "POST" for method, _ in requests), "Check must not start a camera"
        report = {"cases": results, "preference_survives_refresh": True,
                  "legacy_comparison_preference_ignored": True,
                  "camera_start_requests": 0, "browser_errors": errors}
        (output / "aspect-check.json").write_text(json.dumps(report, indent=2) + "\n")
        for path in output.iterdir():
            if path.is_file():
                path.chmod(0o600)
        print(json.dumps(report, indent=2))
    finally:
        if driver is not None:
            driver.quit()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
