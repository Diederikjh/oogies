"""Browser acceptance tests against the real service and a synthetic recorder."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait

from fixture import COLORS, SyntheticMedia, ViewerFixture


class ViewerUITests(unittest.TestCase):
    OPTIONS = {
        "test_capacity_limit_keeps_admitted_cameras_live": {"limit": 2},
        "test_camera_start_failure_is_local_to_its_tile": {"failed_camera": "camera-2"},
        "test_recorder_rejection_has_no_automatic_retries": {"failure": True},
        "test_fresh_install_without_a_recording": {"recording": False},
        "test_switching_views_during_discovery_recovers": {"delayed": True},
        "test_offline_camera_recovers_after_one_minute_in_both_tabs": {"offline_camera":"camera-3"},
    }

    @classmethod
    def setUpClass(cls):
        cls.media_directory = tempfile.TemporaryDirectory(prefix="ui-media-")
        try:
            cls.media = SyntheticMedia(Path(cls.media_directory.name) / "fixtures")
        except Exception:
            cls.media_directory.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.media_directory.cleanup()

    def setUp(self):
        self.fixture = ViewerFixture(self.media, **self.OPTIONS.get(self._testMethodName, {}))
        self.addCleanup(self.fixture.close)
        self.profile = tempfile.TemporaryDirectory(prefix="ui-browser-")
        self.addCleanup(self.profile.cleanup)
        options = webdriver.ChromeOptions()
        for flag in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                     "--disable-background-networking", "--disable-sync", "--no-first-run",
                     "--autoplay-policy=no-user-gesture-required", "--user-data-dir=" + self.profile.name):
            options.add_argument(flag)
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        self.driver = webdriver.Chrome(options=options)
        self.addCleanup(self.driver.quit)
        self.wait = WebDriverWait(self.driver, 12)
        self.driver.set_window_size(1600, 1100)
        self.driver.get(self.fixture.url)

    def tearDown(self):
        output = Path("/output")
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.driver.save_screenshot(str(output / (self._testMethodName + ".png")))
        errors = [entry for entry in self.driver.get_log("browser") if entry["level"] == "SEVERE"
                  and "favicon.ico" not in entry["message"]]
        expected = ("503",) if "rejection" in self._testMethodName else (("404",) if "expiry" in self._testMethodName else ())
        unexpected = [entry for entry in errors if not (entry.get("source") == "network" and
                       any(code in entry["message"] for code in expected))]
        self.assertEqual(unexpected, [], "Unexpected browser console errors")
        self.assertEqual(self.fixture.worker.login_calls, 0, "UI tests must never log into an SDK")

    def tile(self, channel=1):
        return f'.camera-tile[data-camera-id="camera-{channel}"]'

    def element(self, selector):
        return self.driver.find_element(By.CSS_SELECTOR, selector)

    def state(self, channel):
        elements = self.driver.find_elements(By.CSS_SELECTOR, self.tile(channel))
        return elements[0].get_attribute("data-state") if elements else None

    def wait_live(self, channels=range(1, 9)):
        self.wait.until(lambda _: all(self.state(channel) == "live" and
            self.driver.execute_script("return document.querySelector(arguments[0]+' img')?.naturalWidth > 0;", self.tile(channel))
            for channel in channels))

    def ratio(self, selector):
        return self.driver.execute_script("const r=document.querySelector(arguments[0]).getBoundingClientRect();return r.width/r.height;", selector)

    def pixels(self, channel=1):
        return self.driver.execute_script("""
            const img=document.querySelector(arguments[0]+' img'), canvas=document.createElement('canvas');
            canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
            canvas.getContext('2d').drawImage(img,0,0);return canvas.toDataURL();
        """, self.tile(channel))

    def open_settings(self):
        self.driver.find_element(By.ID, "settings-open").click()
        self.wait.until(lambda _: self.driver.execute_script("return document.getElementById('display-settings').open"))

    def aspect(self, value, channel=1):
        Select(self.element(f'#aspect-settings select[data-camera-id="camera-{channel}"]')).select_by_value(value)

    def close_settings(self):
        self.driver.find_element(By.ID, "settings-close").click()

    def wait_counts(self, viewers, sources):
        self.wait.until(lambda _: self.fixture.snapshot()["viewers"] == viewers and
                        self.fixture.snapshot()["sources"] == sources)

    def test_eight_moving_cameras_have_correct_identity_and_offline_tile(self):
        self.wait_live()
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, ".camera-tile")), 9)
        self.assertEqual(self.state(9), "offline")
        self.assertEqual(self.element(self.tile(2) + " h2").text, "Front <porch> & gate")
        self.assertEqual(self.driver.find_elements(By.CSS_SELECTOR, self.tile(2) + " h2 porch"), [])
        for channel, color in enumerate(COLORS, 1):
            actual = self.driver.execute_script("""
                const img=document.querySelector(arguments[0]+' img'), c=document.createElement('canvas');
                c.width=352;c.height=288;const x=c.getContext('2d');x.drawImage(img,0,0);
                return [...x.getImageData(20,20,1,1).data].slice(0,3);
            """, self.tile(channel))
            self.assertTrue(all(abs(a-b) < 12 for a,b in zip(actual, color)), (channel, actual, color))
        before = hashlib.sha256(self.pixels().encode()).hexdigest()
        self.wait.until(lambda _: hashlib.sha256(self.pixels().encode()).hexdigest() != before)
        with self.fixture.worker.condition:
            self.assertEqual(len(self.fixture.server.feeds), 1, "Eight cameras use one media connection")
        self.assertEqual(self.fixture.worker.connection_attempts, 1)
        self.assertIn("8 live", self.driver.find_element(By.ID, "grid-summary").text)

    def test_picture_click_and_keyboard_toggle_expansion(self):
        self.wait_live()
        view = self.tile() + " .camera-view"
        self.element(self.tile() + " img").click()
        self.assertEqual(self.element(view).get_attribute("aria-expanded"), "true")
        self.assertEqual(self.element(view).get_attribute("aria-label"), "Collapse Driveway")
        self.element(self.tile() + " img").click()
        self.assertEqual(self.element(view).get_attribute("aria-expanded"), "false")
        self.element(view).send_keys(Keys.ENTER)
        self.assertEqual(self.element(view).get_attribute("aria-expanded"), "true")
        self.element(view).send_keys(Keys.SPACE)
        self.assertEqual(self.element(view).get_attribute("aria-expanded"), "false")
        self.assertTrue(all(count == 1 for count in self.fixture.worker.started.values()))

    def test_settings_are_per_camera_persisted_and_keyboard_accessible(self):
        self.wait_live()
        self.assertEqual(self.driver.find_elements(By.CSS_SELECTOR, "#live-panel select, #recording-panel select"), [])
        self.open_settings()
        self.assertEqual(self.driver.execute_script("return document.activeElement.id"), "settings-close")
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, "#aspect-settings select")), 9)
        self.aspect("4:3"); self.close_settings()
        self.wait.until(lambda _: abs(self.ratio(self.tile() + " img") - 4/3) < .01)
        self.assertEqual(self.driver.execute_script("return document.activeElement.id"), "settings-open")
        self.driver.refresh(); self.wait_live()
        self.assertAlmostEqual(self.ratio(self.tile() + " img"), 4/3, delta=.01)
        self.assertAlmostEqual(self.ratio(self.tile(2) + " img"), 16/9, delta=.01)
        self.open_settings(); self.aspect("original")
        self.driver.find_element(By.ID, "settings-close").send_keys(Keys.ESCAPE)
        self.wait.until(lambda _: not self.driver.execute_script("return document.getElementById('display-settings').open"))
        self.wait.until(lambda _: abs(self.ratio(self.tile() + " img") - 352/288) < .01)

    def test_mobile_settings_and_expanded_picture_fit(self):
        self.wait_live(); self.driver.set_window_size(390, 844)
        self.open_settings()
        self.assertTrue(self.driver.execute_script("const r=document.querySelector('dialog').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;"))
        self.close_settings(); self.element(self.tile() + " img").click()
        self.wait.until(lambda _: self.driver.execute_script("""
            const i=document.querySelector(arguments[0]+' img').getBoundingClientRect(),
                  v=document.querySelector(arguments[0]+' .viewer').getBoundingClientRect();
            return i.left>=v.left && i.right<=v.right+1 && i.top>=v.top && i.bottom<=v.bottom+1;
        """, self.tile()))
        self.assertAlmostEqual(self.ratio(self.tile() + " img"), 16/9, delta=.01)

    def test_tabs_share_sources_and_pause_refresh_close_independently(self):
        self.wait_live(); first = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url); self.wait_live()
        self.wait_counts(2, 8)
        self.driver.refresh(); self.wait_live(); self.wait_counts(2, 8)
        self.assertTrue(all(count == 1 for count in self.fixture.worker.started.values()))
        self.driver.find_element(By.ID, "stop").click(); self.wait_counts(1, 8)
        self.driver.find_element(By.ID, "start").click(); self.wait_live(); self.wait_counts(2, 8)
        self.assertEqual(dict(self.fixture.worker.stopped), {})
        self.driver.close(); self.driver.switch_to.window(first)
        self.wait_counts(1, 8); self.wait_live()
        self.driver.find_element(By.ID, "stop").click(); self.wait_counts(0, 0)
        self.assertTrue(all(count == 1 for count in self.fixture.worker.stopped.values()))

    def test_recorded_playback_shares_aspect_and_releases_live_view(self):
        self.wait_live(); self.open_settings(); self.aspect("4:3"); self.close_settings()
        self.driver.find_element(By.ID, "recording-tab").click(); self.wait_counts(0, 0)
        # Source assignment follows asynchronous release of this view's lease.
        self.wait.until(lambda _: self.driver.find_element(By.ID, "recording").get_dom_attribute("src") == "/recording.mp4")
        error = self.driver.execute_async_script("""
            const done=arguments[0];document.getElementById('recording').play()
                .then(()=>done(null)).catch(error=>done(error.message));
        """)
        self.assertIsNone(error, "Playback must start after its source is attached")
        self.wait.until(lambda _: self.driver.execute_script("return document.getElementById('recording').currentTime > .4"))
        self.assertAlmostEqual(self.ratio("#recording"), 4/3, delta=.01)
        self.open_settings(); self.aspect("16:9"); self.close_settings()
        self.wait.until(lambda _: abs(self.ratio("#recording") - 16/9) < .01)
        self.driver.find_element(By.ID, "live-tab").click(); self.wait_live()
        self.assertTrue(self.driver.execute_script("return document.getElementById('recording').paused"))
        self.assertAlmostEqual(self.ratio(self.tile() + " img"), 16/9, delta=.01)

    def test_stale_and_failed_camera_do_not_hide_healthy_streams(self):
        self.wait_live()
        self.fixture.worker.set_state("camera-2", "stale")
        self.wait.until(lambda _: self.state(2) == "stale")
        self.assertEqual(self.element(self.tile(2) + " .tile-badge").text, "Video delayed")
        self.fixture.worker.set_state("camera-3", "error")
        self.wait.until(lambda _: self.state(3) == "error")
        self.assertEqual(self.element(self.tile(3) + " .tile-badge").text, "Unavailable")
        self.wait_live([1,4,5,6,7,8])
        self.fixture.worker.set_state("camera-2", "live")
        self.wait_live([2]); self.assertEqual(self.fixture.worker.connection_attempts, 1)

    def test_capacity_limit_keeps_admitted_cameras_live(self):
        self.wait_live([1,2])
        self.wait.until(lambda _: all(self.state(channel) == "capacity_limited" for channel in range(3,9)))
        self.assertEqual(self.state(9), "offline")
        self.assertEqual(self.fixture.snapshot()["sources"], 2)
        self.assertEqual(set(self.fixture.worker.started), {"camera-1","camera-2"})

    def test_camera_start_failure_is_local_to_its_tile(self):
        self.wait_live([1,3,4,5,6,7,8])
        self.assertEqual(self.state(2), "error")
        self.assertEqual(self.element(self.tile(2) + " .tile-placeholder").text, "Simulated camera stream failure.")

    def test_recorder_rejection_has_no_automatic_retries(self):
        self.wait.until(lambda _: "no automatic login retry" in self.driver.find_element(By.ID,"message").text)
        self.driver.execute_async_script("const done=arguments[0];setTimeout(done,2200);")
        self.assertEqual(self.fixture.worker.ensure_calls, 1, "Rejected discovery must not be polled automatically")
        self.assertTrue(self.driver.find_element(By.ID,"start").is_enabled())
        self.driver.find_element(By.ID,"start").click()
        self.wait.until(lambda _: self.fixture.worker.ensure_calls == 2)
        self.wait.until(lambda _: "no automatic login retry" in self.driver.find_element(By.ID,"message").text)
        self.assertEqual(self.fixture.worker.connection_attempts, 1)
        self.assertEqual(self.fixture.snapshot()["sources"], 0)

    def test_fresh_install_without_a_recording(self):
        self.wait_live()
        self.assertFalse(self.driver.find_element(By.ID,"recording-tab").is_enabled())
        self.assertIsNone(self.driver.find_element(By.ID,"recording").get_dom_attribute("src"))

    def test_lease_expiry_releases_only_the_unrenewed_view(self):
        self.wait_live(); first = self.driver.current_window_handle
        with self.fixture.worker.condition:
            first_id = next(iter(self.fixture.sessions.sessions))
        self.driver.switch_to.new_window("tab")
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": """
            const interval=window.setInterval.bind(window);
            window.setInterval=(fn,delay,...args)=>delay>=3000?0:interval(fn,delay,...args);
        """})
        self.driver.get(self.fixture.url); self.wait_live(); self.wait_counts(2,8)
        abandoned_tab = self.driver.current_window_handle
        self.driver.switch_to.window(first)
        self.wait_counts(1,8); self.wait_live()
        with self.fixture.worker.condition:
            self.assertIn(first_id, self.fixture.sessions.sessions)
        self.driver.switch_to.window(abandoned_tab)
        self.wait.until(lambda _: self.driver.find_element(By.ID,"grid-summary").text == "View paused")
        self.assertTrue(self.driver.find_element(By.ID,"start").is_enabled())
        self.assertEqual(dict(self.fixture.worker.stopped), {})
        self.driver.find_element(By.ID,"start").click(); self.wait_live(); self.wait_counts(2,8)
        self.assertTrue(all(count == 1 for count in self.fixture.worker.started.values()))

    def test_switching_views_during_discovery_recovers(self):
        self.wait.until(lambda _: self.driver.find_element(By.ID,"recording-tab").is_enabled())
        self.driver.find_element(By.ID,"recording-tab").click()
        self.driver.find_element(By.ID,"live-tab").click()
        self.fixture.worker.discovery_gate.set()
        self.wait_live(); self.wait_counts(1,8)

    def test_offline_camera_recovers_after_one_minute_in_both_tabs(self):
        healthy = [1,2,4,5,6,7,8]
        self.wait_live(healthy)
        self.assertEqual(self.state(3), "offline")
        first = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab")
        self.driver.get(self.fixture.url)
        self.wait_live(healthy); self.wait_counts(2,7)
        second = self.driver.current_window_handle
        with self.fixture.worker.condition:
            self.fixture.worker.device_online["camera-3"] = True
            self.fixture.worker.cache_now = 59.999
        self.fixture.sessions.maintain()
        self.assertEqual(self.fixture.worker.refresh_calls, 0)
        self.assertEqual(self.state(3), "offline")
        with self.fixture.worker.condition:
            self.fixture.worker.cache_now = 60
        self.fixture.sessions.maintain()
        self.wait_live(); self.wait_counts(2,8)
        self.driver.switch_to.window(first)
        self.wait_live()
        self.assertEqual(self.fixture.worker.refresh_calls, 1)
        self.assertEqual(self.fixture.worker.connection_attempts, 1)
        self.assertTrue(all(count==1 for count in self.fixture.worker.started.values()))
        self.assertEqual(dict(self.fixture.worker.stopped), {})
        self.driver.switch_to.window(second)
