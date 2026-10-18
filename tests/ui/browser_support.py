"""Shared browser setup and helpers; this base deliberately contains no tests."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from fixture import SyntheticMedia, ViewerFixture


class BrowserTestCase(unittest.TestCase):
    WINDOW_SIZES = {"test_history_mobile_collapsed_events_can_play_seek_and_mark":(390,844)}

    OPTIONS = {
        "test_picture_click_and_keyboard_toggle_expansion": {"limit":9},
        "test_expansion_and_collapse_animate_and_keep_picture_in_focus": {"limit":9},
        "test_rapid_reversal_and_reduced_motion_leave_stable_layout": {"limit":9},
        "test_live_quality_disabled_unsupported_and_offline_are_explicit": {"limit":9,"high_limit":0},
        "test_live_expansion_switches_actual_frames_and_ignores_old_poll": {"limit":9},
        "test_live_quality_shared_tabs_and_expiry_keep_other_view_moving": {"limit":9},
        "test_live_quality_refused_camera_is_not_retried_by_other_expansions": {"limit":9},
        "test_live_quality_decoder_failure_and_stall_keep_overview_moving": {"limit":9},
        "test_live_quality_collapse_ignores_delayed_upgrade_reply": {"limit":9},
        "test_live_quality_old_decode_cannot_replace_new_generation": {"limit":9},
        "test_live_quality_pending_reply_cannot_modify_replacement_lease": {"limit":9},
        "test_live_quality_lost_reply_releases_unconfirmed_high_source": {"limit":9},
        "test_live_quality_lost_reply_preserves_acknowledged_other_camera": {"limit":9},
        "test_live_quality_mobile_keyboard_and_reduced_motion": {"limit":9},
        "test_live_media_disconnect_recovers_without_restarting_high_source": {"limit":9},
        "test_live_media_stall_is_delayed_and_recovers": {"limit":9},
        "test_live_media_retry_exhaustion_and_manual_resume": {"limit":9},
        "test_live_media_pause_cancels_reconnect": {"limit":9},
        "test_live_media_forbidden_response_stops_without_retrying_auth": {"limit":9},
        "test_history_media_reconnect_preserves_high_live_view_and_pause": {"limit":10},
        "test_live_quality_api_shares_main_stream_without_changing_overview": {"limit":9},
        "test_two_distinct_high_streams_share_and_release_independently": {"limit":10,"high_limit":2},
        "test_two_high_streams_need_total_budget_for_seven_overviews": {"limit":8,"high_limit":2,"offline_camera":"camera-3"},
        "test_capacity_limit_keeps_admitted_cameras_live": {"limit": 2},
        "test_camera_start_failure_is_local_to_its_tile": {"failed_camera": "camera-2"},
        "test_recorder_rejection_has_no_automatic_retries": {"failure": True},
        "test_fresh_install_without_a_recording": {"recording": False},
        "test_switching_views_during_discovery_recovers": {"delayed": True},
        "test_offline_camera_recovers_after_one_minute_in_both_tabs": {"offline_camera":"camera-3"},
        "test_history_playback_preserves_another_live_tab": {"limit":9},
        "test_history_playback_positions_are_independent_between_tabs": {"playback_limit":2},
        "test_history_settings_work_before_live_discovery_finishes": {"delayed":True},
        "test_history_exports_preserve_another_live_tab": {"limit":9},
        "test_history_clip_handles_respect_configured_limit": {"exports_config":{"max_duration_seconds":120}},
    }

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
        self.downloads = Path(self.profile.name) / "downloads"
        self.downloads.mkdir()
        options.add_experimental_option("prefs", {"download.default_directory":str(self.downloads),
                                                   "download.prompt_for_download":False})
        self.driver = webdriver.Chrome(options=options)
        self.addCleanup(self.driver.quit)
        self.wait = WebDriverWait(self.driver, 12)
        self.driver.set_window_size(*self.WINDOW_SIZES.get(self._testMethodName,(1600,1100)))
        if "media_" in self._testMethodName:
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                {"source":Path("/support/browser_feed_fault.js").read_text()})
        self.driver.get(self.fixture.url)

    def tearDown(self):
        output = Path("/output")
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.driver.save_screenshot(str(output / (self._testMethodName + ".png")))
        errors = [entry for entry in self.driver.get_log("browser") if entry["level"] == "SEVERE"
                  and "favicon.ico" not in entry["message"]]
        expected = ("503",) if "rejection" in self._testMethodName else (("404",) if "expiry" in self._testMethodName else
            (("422",) if "date_rejected" in self._testMethodName else ()))
        unexpected = [entry for entry in errors if not (entry.get("source") == "network" and
                       (any(code in entry["message"] for code in expected) or
                        ("media_" in self._testMethodName and "/media/" in entry["message"] and "409" in entry["message"])))]
        self.assertEqual(unexpected, [], "Unexpected browser console errors")
        self.assertEqual(self.fixture.worker.login_calls, 0, "UI tests must never log into an SDK")

    def tile(self, channel=1):
        return f'.camera-tile[data-camera-id="camera-{channel}"]'

    def element(self, selector):
        return self.driver.find_element(By.CSS_SELECTOR, selector)

    def rendered(self, selector):
        # Chromium hides closed <details> with content-visibility. Selenium's
        # legacy is_displayed() reports those descendants as visible.
        return self.driver.execute_script("return document.querySelector(arguments[0]).checkVisibility()",selector)

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

    def live_page_state(self):
        return self.driver.execute_script("""
            return {summary:document.getElementById('grid-summary').textContent,
                stopDisabled:document.getElementById('stop').disabled,
                animating:document.querySelectorAll('.camera-tile.is-animating').length,
                scrollY:window.scrollY};
        """)

    def wait_counts(self, viewers, sources):
        latest = None
        def reached(_):
            nonlocal latest
            latest = self.fixture.snapshot()
            return latest["viewers"] == viewers and latest["sources"] == sources
        try:
            self.wait.until(reached)
        except TimeoutException as error:
            page = self.live_page_state()
            error.msg += f" Expected viewers={viewers}, sources={sources}; last backend snapshot={latest}; page={page}"
            raise

    def pause_live_view(self):
        # Ownership tests must not depend on pointer coordinates during focus scrolling.
        self.element("#stop").send_keys(Keys.ENTER)
        try:
            self.wait.until(lambda _:self.element("#grid-summary").text == "View paused" and
                            not self.element("#stop").is_enabled(),
                            "Stop action did not reach a paused page with its Stop button disabled.")
        except TimeoutException as error:
            error.msg += f" Backend={self.fixture.snapshot()}; page={self.live_page_state()}"
            raise

    def wait_quality(self, channel=1, quality="high"):
        selector = self.tile(channel)
        width = 704 if quality == "high" else 352
        self.wait.until(lambda _:self.element(selector).get_attribute("data-quality") == quality and
                        self.driver.execute_script("return document.querySelector(arguments[0]+' img').naturalWidth",selector)==width)

    def picture_click(self, channel=1):
        self.element(self.tile(channel)+" .camera-view").click()

    def hold_quality_reply(self, lose=False):
        self.driver.execute_script("""
            const original=window.fetch;window.qualityHeld=false;
            window.fetch=async (...args)=>{
              const response=await original(...args);
              if(!qualityHeld && args[1]?.method==='PATCH' && args[1].body?.includes('"cameras"')){
                const body=await response.text();window.qualityHeld=true;
                await new Promise(resolve=>window.releaseQuality=resolve);
                if(arguments[0])throw new TypeError('Simulated lost quality reply');
                return new Response(body,{status:response.status,headers:{'Content-Type':'application/json'}});
              }
              return response;
            };
        """,lose)

    def open_history(self):
        self.driver.find_element(By.ID,"history-tab").click()
        self.history_ready()

    def history_ready(self):
        self.wait.until(lambda _: self.element("#history-recordings").get_attribute("data-state") == "ready" and
                        self.element("#history-motion").get_attribute("data-state") != "pending")

    def assert_history_controls_in_view(self):
        selectors = ["#history-viewer", "#history-position", "#history-pause", "#history-speeds",
                     "#clip-start", "#clip-end", "#clip-queue", "#clip-clear"]
        layout = self.driver.execute_script("""
            return {height:innerHeight, width:innerWidth, pageHeight:document.documentElement.scrollHeight,
              pageWidth:document.documentElement.scrollWidth, scroll:scrollY,
              parts:arguments[0].map(selector=>{const r=document.querySelector(selector).getBoundingClientRect();
                return {selector,top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height};})};
        """, selectors)
        self.assertEqual(layout["scroll"],0,"History should not need page scrolling")
        self.assertLessEqual(layout["pageHeight"],layout["height"]+1)
        self.assertLessEqual(layout["pageWidth"],layout["width"])
        for rect in layout["parts"]:
            with self.subTest(control=rect["selector"]):
                self.assertGreater(rect["height"],0)
                self.assertGreaterEqual(rect["top"],0)
                self.assertLessEqual(rect["bottom"],layout["height"]+1)
                self.assertGreaterEqual(rect["left"],0)
                self.assertLessEqual(rect["right"],layout["width"]+1)
        self.assertGreaterEqual(layout["parts"][0]["height"],100)

    def history_playing(self):
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "playing" and
            self.driver.execute_script("return document.getElementById('history-image').naturalWidth > 0 && !document.getElementById('history-image').hidden"))

    def paused_history(self):
        self.wait_live(); self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR, "#history-events button")[0].click(); self.history_playing()
        self.wait.until(lambda _:self.element("#history-pause").is_enabled())
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        self.wait.until(lambda _:self.element("#clip-start").is_enabled())

    def clip_seconds(self):
        start=self.element('#history-clip-marks .clip-marker[data-bound="from"]')
        end=self.element('#history-clip-marks .clip-marker[data-bound="to"]')
        return float(end.get_attribute("aria-valuenow"))-float(start.get_attribute("aria-valuenow"))

    def mark_clip(self, seconds=30):
        self.paused_history(); self.element("#clip-start").click()
        self.driver.execute_script("const s=document.getElementById('history-position');s.value=Number(s.value)+arguments[0];s.dispatchEvent(new Event('change',{bubbles:true}))",seconds)
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click()

    def drag_clip(self, name, direction):
        flag=self.element(f'#history-clip-marks .clip-marker[data-bound="{name}"]')
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",flag)
        offset=self.driver.execute_script("const f=arguments[0].getBoundingClientRect(),t=arguments[0].parentElement.getBoundingClientRect();return (arguments[1]<0?t.left+2:t.right-2)-(f.left+f.width/2)",flag,direction)
        ActionChains(self.driver).move_to_element(flag).click_and_hold().move_by_offset(int(offset),0).release().perform()

    def hold_export_response(self):
        self.driver.execute_script("""
            const original=window.fetch;
            window.fetch=async (...args)=>{
              const response=await original(...args);
              if(String(args[0])==='/api/exports' && args[1]?.method==='POST'){
                window.heldExportKey=args[1].headers['Idempotency-Key'];
                await new Promise(resolve=>window.releaseExport=resolve);
              }
              return response;
            };
        """)
        self.element("#clip-queue").click()
        self.wait.until(lambda _:self.driver.execute_script("return Boolean(window.releaseExport)"))
        self.assertIn("Queueing export",self.element("#clip-message").text)

    def date_value(self, days=1):
        return (datetime.now(ZoneInfo("Africa/Johannesburg")) - timedelta(days=days)).replace(
            hour=0, minute=15, second=30, microsecond=0)

    def open_date_picker(self):
        if not self.element(".history-date-picker").get_attribute("open"):
            self.element(".history-date-picker summary").click()
        self.wait.until(lambda _:self.rendered("#history-date-time"))

    def go_to_date(self, value):
        self.open_date_picker()
        self.wait.until(lambda _:self.element("#history-go-time").is_enabled())
        self.driver.execute_script("document.getElementById('history-date-time').value=arguments[0]", value.replace(tzinfo=None).isoformat())
        self.element("#history-go-time").click()

    def history_pixels(self):
        return self.driver.execute_script("""
            const img=document.getElementById('history-image'), c=document.createElement('canvas');
            c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext('2d').drawImage(img,0,0);return c.toDataURL();
        """)


@contextmanager
def browser_media():
    """Share generated input media explicitly within one runner invocation."""
    with tempfile.TemporaryDirectory(prefix="ui-media-") as directory:
        BrowserTestCase.media = SyntheticMedia(Path(directory) / "fixtures")
        try:
            yield
        finally:
            del BrowserTestCase.media
