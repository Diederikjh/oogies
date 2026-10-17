"""Browser acceptance tests against the real service and a synthetic recorder."""

import hashlib
import json
import struct
import subprocess
from datetime import datetime, timedelta, timezone
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

from fixture import COLORS, SyntheticMedia, ViewerFixture


class ViewerUITests(unittest.TestCase):
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
        self.wait_quality(quality="overview"); self.wait_counts(1,8)
        self.assertTrue(all(count == 1 for key,count in self.fixture.worker.started.items() if not key.endswith('-high')))

    def test_live_quality_api_shares_main_stream_without_changing_overview(self):
        self.wait_live()
        def api(path, method="GET", body=None):
            return self.driver.execute_async_script("""
                const [path,method,body,done]=arguments;
                fetch(path,{method,headers:{'Content-Type':'application/json'},
                  ...(body===null?{}:{body:JSON.stringify(body)})})
                  .then(async response=>done({status:response.status,body:response.status===204?null:await response.json()}))
                  .catch(error=>done({error:error.message}));
            """,path,method,body)
        def selection(camera): return {"cameras":[{"id":camera,"quality":"high"}]}
        views = []
        try:
            first = api("/api/live/sessions","POST",selection("camera-1"))
            self.assertEqual(first["status"],201); views.append(first["body"]["id"])
            second = api("/api/live/sessions","POST",selection("camera-1"))
            self.assertEqual(second["status"],201); views.append(second["body"]["id"])
            refused = api("/api/live/sessions","POST",selection("camera-2"))
            self.assertEqual(refused["status"],201); views.append(refused["body"]["id"])
            self.assertEqual(refused["body"]["cameras"][0]["upgrade_state"],"capacity_limited")
            self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
            self.driver.execute_async_script("""
                const [url,done]=arguments;
                import('/shared/frame-feed.js').then(({FrameFeed})=>{
                  window.testQualityFrames=[];
                  window.testQualityFeed=new FrameFeed(url,async (id,jpeg,header)=>{
                    const bitmap=await createImageBitmap(new Blob([jpeg],{type:'image/jpeg'}));
                    const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
                    const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0);
                    testQualityFrames.push({header,width:bitmap.width,height:bitmap.height,
                      color:[...ctx.getImageData(20,20,1,1).data].slice(0,3)});bitmap.close();
                  });
                  testQualityFeed.run().catch(error=>{if(error.name!=='AbortError')window.testQualityError=error.message});
                  done();
                }).catch(error=>done(error.message));
            """,first["body"]["media"]["url"])
            self.wait.until(lambda _:self.driver.execute_script("return testQualityFrames.filter(f=>f.header.quality==='high').length>=2"))
            actual = self.driver.execute_script("return testQualityFrames.filter(f=>f.header.quality==='high').at(-1)")
            self.assertEqual((actual["width"],actual["height"]),(704,576))
            self.assertEqual(actual["header"]["camera_id"],"camera-1")
            self.assertTrue(all(abs(value-(255-color))<15 for value,color in zip(actual["color"],COLORS[0])))
            self.assertEqual(self.driver.execute_script("return document.querySelector(arguments[0]+' img').naturalWidth",self.tile()),352)
            self.assertEqual(self.fixture.snapshot()["sources"],9)
            api("/api/live/sessions/"+views[0],"DELETE"); self.assertEqual(self.fixture.snapshot()["sources"],9)
            api("/api/live/sessions/"+views[1],"DELETE"); self.wait_counts(2,8)
            self.assertNotIn("camera-2-high",self.fixture.sessions.wanted)
            self.wait_live()
            self.assertIsNone(self.driver.execute_script("return window.testQualityError||null"))
        finally:
            self.driver.execute_script("window.testQualityFeed?.close()")
            for identifier in views: api("/api/live/sessions/"+identifier,"DELETE")

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

    def test_live_expansion_switches_actual_frames_and_ignores_old_poll(self):
        self.wait_live()
        self.driver.execute_script("""
            const original=window.fetch;window.oldQualityPollHeld=false;
            window.fetch=async (...args)=>{
              const response=await original(...args);
              if(!oldQualityPollHeld && String(args[0]).includes('/api/live/sessions/') && args[1]?.method==='GET'){
                const body=await response.text();window.oldQualityPollHeld=true;
                await new Promise(resolve=>window.releaseOldQualityPoll=resolve);
                return new Response(body,{status:response.status,headers:{'Content-Type':'application/json'}});
              }return response;
            };
        """)
        self.wait.until(lambda _:self.driver.execute_script("return window.oldQualityPollHeld"))
        self.fixture.worker.high_gate.clear(); self.picture_click()
        self.wait.until(lambda _:"Upgrading" in self.element(self.tile()+" .tile-metrics").text)
        self.wait_quality(quality="overview")
        before = self.pixels(); self.wait.until(lambda _:self.pixels()!=before)
        self.fixture.worker.high_gate.set(); self.wait_quality()
        self.assertIn("704 × 576 · High quality",self.element(self.tile()+" .tile-metrics").text)
        self.assertIn("1 high quality",self.element("#view-note").text)
        self.driver.execute_script("window.releaseOldQualityPoll()")
        self.wait_quality(); self.wait_live()
        self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
        self.picture_click(); self.wait_quality(quality="overview"); self.wait_counts(1,8)
        self.assertEqual(self.element("#view-note").text,"Video only · Overview quality")
        self.assertTrue(all(count==1 for key,count in self.fixture.worker.started.items() if not key.endswith('-high')))

    def test_live_quality_refused_camera_is_not_retried_by_other_expansions(self):
        def click(channel=1):
            # Admission is under test here. A prior tile's focus animation can
            # move the target between Selenium's scroll/press/release steps.
            self.wait.until(lambda _:not self.driver.execute_script("return Boolean(document.querySelector('.camera-tile.is-animating'))"))
            view=self.tile(channel)+" .camera-view"
            before=self.element(view).get_attribute("aria-expanded")
            self.picture_click(channel)
            self.assertEqual(self.element(view).get_attribute("aria-expanded"),"false" if before=="true" else "true")
        self.wait_live(); click(); self.wait_quality()
        click(2)
        self.wait.until(lambda _:"High quality unavailable" in self.element(self.tile(2)+" .tile-metrics").text)
        self.assertEqual(self.element(self.tile(2)+" .tile-metrics").get_attribute("role"),"status")
        self.assertIn("High quality unavailable (high-quality limit)",self.element(self.tile(2)+" .tile-metrics").text)
        self.assertIn("High-quality stream limit (1)",self.element(self.tile(2)+" .tile-metrics").get_attribute("title"))
        self.wait_quality(2,"overview"); click(); self.wait_counts(1,8)
        click(3); self.wait_quality(3)
        self.assertNotIn("camera-2-high",self.fixture.worker.started)
        self.assertIn("High quality unavailable",self.element(self.tile(2)+" .tile-metrics").text)
        click(3); self.wait_counts(1,8)
        click(2); click(2); self.wait_quality(2)
        self.assertEqual(self.fixture.worker.started["camera-2-high"],1)

    def test_two_distinct_high_streams_share_and_release_independently(self):
        def expand(channel):
            self.element(self.tile(channel)+" .camera-view").send_keys(Keys.ENTER)
            self.wait_quality(channel)
        self.wait_live(); expand(1); expand(2); self.wait_counts(1,10)
        self.assertIn("2 high quality",self.element("#view-note").text)
        first=self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url)
        self.wait_live(); expand(1); expand(2); self.wait_counts(2,10)
        self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
        self.assertEqual(self.fixture.worker.started["camera-2-high"],1)
        self.pause_live_view(); self.wait_counts(1,10)
        self.driver.close(); self.driver.switch_to.window(first)
        self.wait_quality(1); self.wait_quality(2)
        before=self.pixels(2); self.wait.until(lambda _:self.pixels(2)!=before)
        self.element(self.tile(1)+" .camera-view").send_keys(Keys.ENTER)
        self.wait_quality(1,"overview"); self.wait_counts(1,9); self.wait_quality(2)
        self.assertEqual(self.fixture.worker.stopped["camera-2-high"],0)
        self.pause_live_view(); self.wait_counts(0,0)

    def test_two_high_streams_need_total_budget_for_seven_overviews(self):
        channels=[1,2,4,5,6,7,8]
        self.wait_live(channels); self.wait_counts(1,7)
        self.element(self.tile(1)+" .camera-view").send_keys(Keys.ENTER)
        self.wait_quality(1); self.wait_counts(1,8)
        self.element(self.tile(2)+" .camera-view").send_keys(Keys.ENTER)
        metrics=self.tile(2)+" .tile-metrics"
        self.wait.until(lambda _:"High quality unavailable (total stream limit)" in self.element(metrics).text)
        self.assertIn("Total stream budget (8)",self.element(metrics).get_attribute("title"))
        self.assertEqual(self.fixture.sessions.high_limit,2)
        self.wait_quality(2,"overview"); self.wait_live(channels)
        with self.fixture.worker.condition:
            self.fixture.sessions.budget.limit=10
        self.element(self.tile(2)+" .camera-view").send_keys(Keys.ENTER)
        self.wait.until(lambda _:self.element(self.tile(2)+" .camera-view").get_attribute("aria-expanded")=="false")
        self.element(self.tile(2)+" .camera-view").send_keys(Keys.ENTER)
        self.wait_quality(2); self.wait_quality(1); self.wait_counts(1,9)
        self.assertIn("2 high quality",self.element("#view-note").text)
        self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
        self.assertEqual(self.fixture.worker.started["camera-2-high"],1)
        self.wait_live(channels)
        self.pause_live_view(); self.wait_counts(0,0)

    def test_live_quality_decoder_failure_and_stall_keep_overview_moving(self):
        self.wait_live(); self.fixture.worker.failed_camera="camera-1-high"
        self.picture_click()
        self.wait.until(lambda _:"High quality unavailable" in self.element(self.tile()+" .tile-metrics").text)
        self.wait_counts(1,8); self.wait_live()
        self.assertIn("Simulated",self.element(self.tile()+" .tile-metrics").get_attribute("title"))
        self.fixture.worker.failed_camera=None; self.picture_click(); self.picture_click(); self.wait_quality()
        self.fixture.worker.set_state("camera-1-high","stale")
        self.wait.until(lambda _:"High quality unavailable" in self.element(self.tile()+" .tile-metrics").text)
        self.wait_quality(quality="overview"); self.wait_counts(1,8); self.wait_live()
        before=self.pixels(2); self.wait.until(lambda _:self.pixels(2)!=before)
        self.assertEqual(self.element(self.tile()).get_attribute("data-state"),"live")
        self.assertEqual(self.fixture.worker.started["camera-1-high"],2)

    def test_live_quality_disabled_unsupported_and_offline_are_explicit(self):
        self.wait_live(); self.picture_click()
        self.wait.until(lambda _:"High quality unavailable" in self.element(self.tile()+" .tile-metrics").text)
        self.fixture.sessions.budget.high_limit=1
        self.fixture.worker.cameras["camera-2"]["live_qualities"]=["overview"]
        self.picture_click(2)
        self.wait.until(lambda _:"unsupported" in self.element(self.tile(2)+" .tile-metrics").get_attribute("title"))
        self.picture_click(9)
        self.wait.until(lambda _:"offline" in self.element(self.tile(9)+" .tile-metrics").get_attribute("title"))
        self.assertEqual(self.state(9),"offline"); self.wait_counts(1,8); self.wait_live()
        self.assertFalse(any(key.endswith('-high') for key in self.fixture.worker.started))

    def test_live_quality_collapse_ignores_delayed_upgrade_reply(self):
        self.wait_live(); self.fixture.worker.high_gate.clear(); self.hold_quality_reply()
        self.picture_click(); self.wait.until(lambda _:self.driver.execute_script("return window.qualityHeld"))
        self.picture_click(); self.fixture.worker.high_gate.set()
        self.wait.until(lambda _:self.fixture.worker.sources["camera-1-high"]["received"]>=3)
        self.wait_quality(quality="overview")
        self.assertNotIn("Upgrading",self.element(self.tile()+" .tile-metrics").text)
        self.driver.execute_script("window.releaseQuality()")
        self.wait_counts(1,8); self.wait_quality(quality="overview")
        self.assertEqual(self.element(self.tile()+" .camera-view").get_attribute("aria-expanded"),"false")

    def test_live_quality_old_decode_cannot_replace_new_generation(self):
        self.wait_live()
        self.driver.execute_script("""
            const original=HTMLImageElement.prototype.decode;window.qualityDecodeHeld=false;window.revokedQualityUrls=[];
            const revoke=URL.revokeObjectURL.bind(URL);URL.revokeObjectURL=url=>{revokedQualityUrls.push(url);revoke(url)};
            HTMLImageElement.prototype.decode=function(){return original.call(this).then(()=>{
              if(this.naturalWidth===704 && !qualityDecodeHeld){window.qualityDecodeHeld=true;window.heldQualityUrl=this.src;
                return new Promise(resolve=>window.releaseQualityDecode=resolve)};
            })};
        """)
        self.picture_click(); self.wait.until(lambda _:self.driver.execute_script("return window.qualityDecodeHeld"))
        self.wait_quality(quality="overview"); self.picture_click(); self.wait_counts(1,8)
        self.wait.until(lambda _:self.driver.execute_script("return revokedQualityUrls.includes(heldQualityUrl)"))
        self.picture_click(); self.wait_quality()
        self.assertEqual(self.element(self.tile()).get_attribute("data-source-generation"),"2")
        self.driver.execute_script("window.releaseQualityDecode()")
        self.wait_quality()
        self.assertTrue(self.driver.execute_script("return document.querySelector(arguments[0]+' img').src!==heldQualityUrl",self.tile()))
        self.assertEqual(self.element(self.tile()).get_attribute("data-source-generation"),"2")

    def test_live_quality_pending_reply_cannot_modify_replacement_lease(self):
        self.wait_live(); self.fixture.worker.high_gate.clear(); self.hold_quality_reply()
        first=next(iter(self.fixture.sessions.sessions))
        self.picture_click(); self.wait.until(lambda _:self.driver.execute_script("return window.qualityHeld"))
        # The reply gate is independent of expansion/focus scrolling. Keep the
        # stale-response race active while using controls without pointer geometry.
        self.pause_live_view(); self.wait_counts(0,0)
        self.element(self.tile()+" .camera-view").send_keys(Keys.ENTER)
        self.assertEqual(self.element(self.tile()+" .camera-view").get_attribute("aria-expanded"),"false")
        self.element("#start").send_keys(Keys.ENTER); self.wait_live(); self.wait_counts(1,8)
        second=next(iter(self.fixture.sessions.sessions)); self.assertNotEqual(first,second)
        self.driver.execute_script("window.releaseQuality()"); self.fixture.worker.high_gate.set()
        self.wait_live(); self.wait_quality(quality="overview"); self.wait_counts(1,8)
        self.assertEqual(next(iter(self.fixture.sessions.sessions)),second)

    def test_live_quality_lost_reply_releases_unconfirmed_high_source(self):
        self.wait_live(); self.hold_quality_reply(lose=True); self.picture_click()
        self.wait.until(lambda _:self.driver.execute_script("return window.qualityHeld"))
        self.wait_quality(); self.driver.execute_script("window.releaseQuality()")
        self.wait.until(lambda _:"High quality unavailable" in self.element(self.tile()+" .tile-metrics").text)
        self.wait_counts(1,8); self.wait_quality(quality="overview"); self.wait_live()
        self.assertEqual(self.fixture.worker.started["camera-1-high"],1)

    def test_live_quality_lost_reply_preserves_acknowledged_other_camera(self):
        self.wait_live()
        self.driver.execute_script("""
            const original=window.fetch;window.firstQualityAcknowledged=false;
            window.fetch=async (...args)=>{
              const response=await original(...args);
              if(args[1]?.method==='PATCH' && args[1].body?.includes('"cameras"')){
                const json=response.json.bind(response);
                response.json=async()=>{const data=await json();window.firstQualityAcknowledged=true;return data};
              }return response;
            };
        """)
        self.picture_click(); self.wait_quality()
        self.wait.until(lambda _:self.driver.execute_script("return window.firstQualityAcknowledged"))
        self.hold_quality_reply(lose=True); self.picture_click(2)
        self.wait.until(lambda _:self.driver.execute_script("return window.qualityHeld"))
        self.driver.execute_script("window.releaseQuality()")
        self.wait.until(lambda _:"High quality unavailable" in self.element(self.tile(2)+" .tile-metrics").text)
        self.wait.until(lambda _:not any(camera=="camera-2" and quality=="high" for session in self.fixture.sessions.sessions.values() for camera,quality in session["cameras"]))
        self.wait_quality(); self.wait_counts(1,9); self.wait_live()
        self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
        self.assertEqual(self.fixture.worker.stopped["camera-1-high"],0)

    def test_live_quality_mobile_keyboard_and_reduced_motion(self):
        self.wait_live(); self.driver.set_window_size(390,844)
        self.driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features":[{"name":"prefers-reduced-motion","value":"reduce"}]})
        self.element(self.tile()+" .camera-view").send_keys(Keys.ENTER); self.wait_quality()
        self.assertAlmostEqual(self.ratio(self.tile()+" img"),16/9,delta=.01)
        self.assertTrue(self.driver.execute_script("return document.documentElement.scrollWidth<=innerWidth"))
        self.assertEqual(self.driver.execute_script("return document.getAnimations().length"),0)
        self.element(self.tile()+" .camera-view").send_keys(Keys.SPACE); self.wait_quality(quality="overview"); self.wait_counts(1,8)

    def test_live_quality_shared_tabs_and_expiry_keep_other_view_moving(self):
        self.wait_live(); self.picture_click(); self.wait_quality(); first=self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",{"source":"""
            const interval=window.setInterval.bind(window);
            window.setInterval=(fn,delay,...args)=>delay>=3000?0:interval(fn,delay,...args);
        """})
        self.driver.get(self.fixture.url); self.wait_live(); self.picture_click(); self.wait_quality(); self.wait_counts(2,9)
        self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
        self.driver.switch_to.window(first); self.wait_counts(1,9); self.wait_quality()
        before=self.pixels(); self.wait.until(lambda _:self.pixels()!=before)
        self.picture_click(); self.wait_quality(quality="overview"); self.wait_counts(1,8)

    def test_live_media_disconnect_recovers_without_restarting_high_source(self):
        self.wait_live(); self.picture_click(); self.wait_quality()
        identifier = next(iter(self.fixture.sessions.sessions))
        for kind in ("eof", "error"):
            with self.subTest(kind=kind):
                attempts = self.driver.execute_script("return mediaFault.attempts")
                self.driver.execute_script("mediaFault.active(arguments[0])",kind)
                self.wait.until(lambda _:self.state(1)=="stale")
                self.assertIn("Reconnecting",self.element(self.tile()+" .tile-badge").text)
                self.wait.until(lambda _:self.driver.execute_script("return mediaFault.attempts")>attempts)
                self.wait_live(); self.wait_quality(); self.wait_counts(1,9)
                before=self.pixels(); self.wait.until(lambda _:self.pixels()!=before)
                self.assertEqual(next(iter(self.fixture.sessions.sessions)),identifier)
                self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
                self.assertTrue(all(count==1 for count in self.fixture.worker.started.values()))

    def test_live_media_stall_is_delayed_and_recovers(self):
        self.wait_live(); self.picture_click(); self.wait_quality()
        self.driver.execute_script("mediaFault.active('stall')")
        self.wait.until(lambda _:self.state(1)=="stale")
        self.assertIn("Video delayed",self.element(self.tile()+" .tile-badge").text)
        self.assertNotIn("8 live",self.element("#grid-summary").text)
        WebDriverWait(self.driver,18).until(lambda _:self.driver.execute_script("return mediaFault.attempts")>=2)
        self.wait_live(); self.wait_quality(); self.wait_counts(1,9)
        self.assertTrue(all(count==1 for count in self.fixture.worker.started.values()))

    def test_live_media_retry_exhaustion_and_manual_resume(self):
        self.wait_live(); self.picture_click(); self.wait_quality()
        self.driver.execute_script("mediaFault.next='empty';mediaFault.active('eof')")
        self.wait_counts(0,0)
        self.assertEqual(self.driver.execute_script("return mediaFault.attempts"),4)
        self.assertIn("Resume",self.element("#message").text)
        self.assertEqual(self.state(1),"stopped")
        self.driver.execute_async_script("const done=arguments[0];setTimeout(done,1100)")
        self.assertEqual(self.driver.execute_script("return mediaFault.attempts"),4)
        self.driver.execute_script("mediaFault.next=null")
        self.element("#start").click(); self.wait_live(); self.wait_quality(); self.wait_counts(1,9)
        self.assertEqual(self.fixture.worker.connection_attempts,1)

    def test_live_media_pause_cancels_reconnect(self):
        self.wait_live(); self.picture_click(); self.wait_quality()
        self.driver.execute_script("mediaFault.next='empty';mediaFault.active('eof')")
        self.wait.until(lambda _:self.state(1)=="stale")
        self.pause_live_view(); self.wait_counts(0,0)
        attempts=self.driver.execute_script("return mediaFault.attempts")
        self.driver.execute_async_script("const done=arguments[0];setTimeout(done,1400)")
        self.assertEqual(self.driver.execute_script("return mediaFault.attempts"),attempts)
        self.assertEqual(self.state(1),"stopped")
        self.driver.execute_script("mediaFault.next=null")
        self.element("#start").click(); self.wait_live(); self.wait_quality()
        self.driver.execute_script("mediaFault.next='empty';mediaFault.active('eof')")
        self.wait.until(lambda _:self.state(1)=="stale")
        self.open_history(); self.wait_counts(0,0)
        attempts=self.driver.execute_script("return mediaFault.attempts")
        self.driver.execute_async_script("const done=arguments[0];setTimeout(done,1400)")
        self.assertEqual(self.driver.execute_script("return mediaFault.attempts"),attempts)

    def test_live_media_forbidden_response_stops_without_retrying_auth(self):
        self.wait_live(); self.picture_click(); self.wait_quality()
        self.driver.execute_script("mediaFault.next='forbidden';mediaFault.active('eof')")
        self.wait_counts(0,0)
        self.assertEqual(self.driver.execute_script("return mediaFault.attempts"),2)
        self.assertEqual(self.fixture.worker.connection_attempts,1)
        self.assertIn("Resume",self.element("#message").text)

    def test_history_media_reconnect_preserves_high_live_view_and_pause(self):
        self.wait_live(); self.picture_click(); self.wait_quality(); first=self.driver.current_window_handle
        self.driver.switch_to.new_window("tab")
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source":Path("/support/browser_feed_fault.js").read_text()})
        self.driver.get(self.fixture.url); self.wait_live()
        self.open_history(); self.wait_counts(1,9)
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click(); self.history_playing()
        identifier=next(iter(self.fixture.worker.playbacks)); generation=self.fixture.worker.playbacks[identifier]["generation"]
        self.driver.execute_script("mediaFault.active('eof')")
        self.wait.until(lambda _:"Reconnecting" in self.element("#history-playback-status").text)
        self.wait.until(lambda _:self.driver.execute_script("return mediaFault.attempts")>=2)
        self.history_playing(); before=self.history_pixels(); self.wait.until(lambda _:self.history_pixels()!=before)
        self.assertEqual(next(iter(self.fixture.worker.playbacks)),identifier)
        self.assertEqual(self.fixture.worker.playbacks[identifier]["generation"],generation)
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state")=="paused")
        attempts=self.driver.execute_script("return mediaFault.attempts")
        self.driver.execute_async_script("const done=arguments[0];setTimeout(done,11000)")
        self.assertEqual(self.driver.execute_script("return mediaFault.attempts"),attempts)
        self.driver.execute_script("mediaFault.next='hang-once';mediaFault.active('eof')")
        WebDriverWait(self.driver,22).until(lambda _:self.driver.execute_script("return mediaFault.attempts")>=attempts+2 and
            self.element("#history-pause").is_enabled())
        self.assertEqual(self.element("#history-player").get_attribute("data-state"),"paused")
        self.assertEqual(self.fixture.worker.playbacks[identifier]["generation"],generation)
        self.driver.switch_to.window(first); self.wait_live(); self.wait_quality(); self.wait_counts(1,9)
        self.assertEqual(self.fixture.worker.started["camera-1-high"],1)
        self.driver.switch_to.window(self.driver.window_handles[1])
        self.driver.execute_script("mediaFault.next='empty';mediaFault.active('eof')")
        self.wait.until(lambda _:not self.fixture.worker.playbacks)
        self.wait.until(lambda _:"Select a time" in self.element("#history-playback-status").text)
        self.driver.execute_script("mediaFault.next=null")
        self.element("#live-tab").click(); self.wait_live()
        self.wait.until(lambda _:not self.fixture.worker.playbacks)

    def test_expansion_and_collapse_animate_and_keep_picture_in_focus(self):
        self.wait_live()
        view = self.tile(6) + " .camera-view"
        self.driver.execute_script("document.querySelector(arguments[0]).scrollIntoView({block:'center',behavior:'instant'});", view)
        def sample():
            return self.driver.execute_async_script("""
                const view=document.querySelector(arguments[0]), done=arguments[1], tile=view.closest('article');
                const before=tile.getBoundingClientRect(), samples=[], start=performance.now();
                view.click();
                const collect=now=>{
                    const box=tile.getBoundingClientRect(), picture=view.querySelector('img').getBoundingClientRect();
                    samples.push({time:now-start,width:box.width,height:box.height,ratio:picture.width/picture.height});
                    if(now-start<550) requestAnimationFrame(collect);
                    else done({before:{width:before.width,height:before.height},samples,
                        focused:box.top>=-1 && box.bottom<=innerHeight+1});
                };requestAnimationFrame(collect);
            """, view)
        expanded = sample()
        final = expanded["samples"][-1]
        self.assertGreater(final["width"], expanded["before"]["width"] * 2)
        self.assertTrue(any(expanded["before"]["width"]+10 < item["width"] < final["width"]-10
                            for item in expanded["samples"]), "Expansion must have intermediate sizes")
        self.assertTrue(expanded["focused"], "Expanded camera must fit in the viewport")
        self.assertTrue(all(abs(item["ratio"]-16/9)<.02 for item in expanded["samples"]))
        collapsed = sample()
        final = collapsed["samples"][-1]
        self.assertTrue(any(final["width"]+10 < item["width"] < collapsed["before"]["width"]-10
                            for item in collapsed["samples"]), "Collapse must have intermediate sizes")
        self.assertTrue(collapsed["focused"])
        self.assertEqual(self.element(view).get_attribute("aria-expanded"), "false")
        self.assertTrue(all(count==1 for count in self.fixture.worker.started.values()))

    def test_manual_wheel_scroll_cancels_focus_without_stopping_expansion(self):
        self.wait_live()
        view = self.tile(6) + " .camera-view"
        self.driver.execute_script("document.querySelector(arguments[0]).scrollIntoView({block:'center',behavior:'instant'});document.querySelector(arguments[0]).click();", view)
        self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type":"mouseWheel", "x":20,"y":100,"deltaX":0,"deltaY":180})
        positions = self.driver.execute_async_script("""
            const done=arguments[0];setTimeout(()=>{
                const chosen=scrollY;setTimeout(()=>done({chosen,after:scrollY}),500);
            },100);
        """)
        self.assertAlmostEqual(positions["after"], positions["chosen"], delta=2)
        self.assertEqual(self.element(view).get_attribute("aria-expanded"), "true")
        self.assertGreater(self.element(view).rect["width"], 1000)

    def test_manual_keyboard_touch_and_scrollbar_changes_cancel_focus(self):
        self.wait_live()
        view = self.tile(6) + " .camera-view"
        for gesture in ("keyboard", "touch", "scrollbar"):
            with self.subTest(gesture=gesture):
                if gesture == "touch":
                    self.driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {"enabled":True})
                self.driver.execute_script("""
                    const view=document.querySelector(arguments[0]);
                    view.scrollIntoView({block:'center',behavior:'instant'});
                    const monitor=window.scrollMonitor={original:window.scrollTo,calls:[],inputAt:null,
                        started:performance.now(),events:new AbortController()};
                    for(const name of ['keydown','touchstart','pointerdown']) window.addEventListener(name,()=>{
                        monitor.inputAt ??= performance.now()-monitor.started;
                    },{capture:true,passive:true,signal:monitor.events.signal});
                    window.scrollTo=(...args)=>{
                        if(monitor.inputAt!==null)monitor.calls.push(performance.now()-monitor.started);
                        return monitor.original.apply(window,args);
                    };view.click();
                """, view)
                try:
                    if gesture == "keyboard":
                        ActionChains(self.driver).send_keys(Keys.ARROW_DOWN).perform()
                    elif gesture == "touch":
                        self.driver.execute_cdp_cmd("Input.dispatchTouchEvent", {"type":"touchStart","touchPoints":[{"x":20,"y":300}]})
                        self.driver.execute_cdp_cmd("Input.dispatchTouchEvent", {"type":"touchMove","touchPoints":[{"x":20,"y":220}]})
                        self.driver.execute_cdp_cmd("Input.dispatchTouchEvent", {"type":"touchEnd","touchPoints":[]})
                    else:
                        # Scrollbar offsets change without a wheel/key event.
                        self.driver.execute_script("""
                            scrollMonitor.inputAt=performance.now()-scrollMonitor.started;
                            scrollMonitor.original.call(window,{top:scrollY+160,behavior:'instant'});
                        """)
                    result = self.driver.execute_async_script("""
                        const done=arguments[0];setTimeout(()=>{
                            const chosen=scrollY;setTimeout(()=>done({chosen,after:scrollY,
                                inputAt:scrollMonitor.inputAt,calls:scrollMonitor.calls}),500);
                        },150);
                    """)
                    self.assertIsNotNone(result["inputAt"], "A real manual input must arrive")
                    self.assertLess(result["inputAt"],360,"Input must interrupt an active transition")
                    self.assertEqual(result["calls"], [], "Automatic scroll requests must stop after user input")
                    if gesture == "scrollbar":
                        self.assertAlmostEqual(result["after"], result["chosen"], delta=2)
                    self.assertEqual(self.element(view).get_attribute("aria-expanded"), "true")
                finally:
                    self.driver.execute_script("window.scrollTo=scrollMonitor.original;scrollMonitor.events.abort();delete window.scrollMonitor;")
                    self.driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {"enabled":False})
                    self.driver.execute_async_script("""
                        const view=document.querySelector(arguments[0]);
                        if(view.getAttribute('aria-expanded')==='true')view.click();
                        setTimeout(arguments[1],550);
                    """, view)

    def test_rapid_reversal_and_reduced_motion_leave_stable_layout(self):
        self.wait_live()
        view = self.tile(6) + " .camera-view"
        result = self.driver.execute_async_script("""
            const view=document.querySelector(arguments[0]),done=arguments[1];
            view.scrollIntoView({block:'center',behavior:'instant'});view.click();
            setTimeout(()=>{view.click();setTimeout(()=>{
                view.click();setTimeout(()=>done({expanded:view.getAttribute('aria-expanded'),
                    animations:document.getAnimations().length}),550);
            },60);},60);
        """, view)
        self.assertEqual(result, {"expanded":"true","animations":0})
        self.wait_quality(6)
        self.assertAlmostEqual(self.ratio(self.tile(6)+" img"),16/9,delta=.01)
        self.driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features":[{"name":"prefers-reduced-motion","value":"reduce"}]})
        result = self.driver.execute_script("""
            const view=document.querySelector(arguments[0]);view.click();
            return {expanded:view.getAttribute('aria-expanded'),animations:document.getAnimations().length};
        """, view)
        self.assertEqual(result, {"expanded":"false","animations":0})
        self.wait_quality(6,"overview"); self.wait_counts(1,8)
        self.assertTrue(all(count==1 for key,count in self.fixture.worker.started.items() if not key.endswith('-high')))

    def test_settings_are_per_camera_persisted_and_keyboard_accessible(self):
        self.wait_live()
        self.assertEqual(self.driver.find_elements(By.CSS_SELECTOR, "#live-panel select"), [])
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

    def test_history_timeline_releases_only_its_live_view_and_preserves_settings(self):
        self.wait_live(); self.open_settings(); self.aspect("4:3"); self.close_settings()
        first = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url); self.wait_live(); self.wait_counts(2,8)
        self.driver.find_element(By.ID, "history-tab").click(); self.wait_counts(1, 8)
        self.wait.until(lambda _: self.element("#history-motion").get_attribute("data-state") == "ready")
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")), 2)
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")), 3)
        self.assertEqual(self.element("#history-hours").get_attribute("value"), "3")
        self.assertEqual(self.element("#view-title").text, "Camera history")
        self.assertIn("Africa/Johannesburg", self.element("#history-range").text)
        self.open_settings(); self.aspect("16:9"); self.close_settings()
        self.driver.find_element(By.ID, "live-tab").click(); self.wait_live()
        self.assertAlmostEqual(self.ratio(self.tile() + " img"), 16/9, delta=.01)
        self.driver.switch_to.window(first); self.wait_live()
        self.assertTrue(all(count == 1 for count in self.fixture.worker.started.values()))

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
        self.assertTrue(self.driver.find_element(By.ID,"history-tab").is_enabled())
        self.driver.find_element(By.ID,"history-tab").click()
        self.wait.until(lambda _: self.element("#history-recordings").get_attribute("data-state") == "ready")
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")), 2)

    def open_history(self):
        self.driver.find_element(By.ID,"history-tab").click()
        self.history_ready()

    def history_ready(self):
        self.wait.until(lambda _: self.element("#history-recordings").get_attribute("data-state") == "ready" and
                        self.element("#history-motion").get_attribute("data-state") != "pending")

    def test_history_camera_ranges_include_offline_inputs(self):
        # A fixed page clock makes the wiring check deterministic. Minute/year
        # transitions and fixed/recent calculations are covered in Node.
        self.driver.execute_script("""
            Date.now = () => Date.parse('2025-01-15T10:00:00Z');
        """)
        self.wait_live(); self.open_history()
        Select(self.element("#history-camera")).select_by_value("camera-9"); self.history_ready()
        self.assertEqual(self.fixture.worker.timeline_calls[-1][0], "camera-9")
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")), 2)
        Select(self.element("#history-hours")).select_by_value("1"); self.history_ready()
        self.assertEqual(self.element("#history-position").get_attribute("max"), "3599")
        initial = self.element("#history-range").text
        self.assertEqual(self.fixture.worker.timeline_calls[-1],
                         ("camera-9", "2025-01-15T11:00:00", "2025-01-15T12:00:00"))
        self.element("#history-earlier").click(); self.history_ready()
        self.assertNotEqual(self.element("#history-range").text, initial)
        self.assertTrue(self.element("#history-later").is_enabled())
        self.element("#history-later").click(); self.history_ready()
        self.assertEqual(self.element("#history-range").text, initial)
        self.element("#history-earlier").click(); self.history_ready()
        self.element("#history-recent").click(); self.history_ready()
        self.assertEqual(self.element("#history-range").text, initial)
        self.assertFalse(self.element("#history-later").is_enabled())

    def test_history_empty_unsupported_and_error_motion_are_distinct(self):
        self.wait_live()
        self.fixture.worker.timeline_states.update({"camera-1":"empty", "camera-2":"unsupported", "camera-3":"error"})
        self.open_history()
        self.assertIn("No motion intervals", self.element("#history-motion-status").text)
        self.assertFalse(self.element("#history-next").is_enabled())
        for camera, state in [("camera-2", "unsupported"), ("camera-3", "error")]:
            Select(self.element("#history-camera")).select_by_value(camera); self.history_ready()
            self.assertEqual(self.element("#history-motion").get_attribute("data-state"), state)
            self.assertIn("unavailable", self.element("#history-motion-status").text)
            self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")), 2)
            self.assertFalse(self.element("#history-previous").is_enabled())

    def test_history_event_selection_keyboard_and_motion_navigation_are_local(self):
        self.wait_live(); self.open_history()
        calls = len(self.fixture.worker.timeline_calls)
        entries = self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")
        entries[1].click()
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,"#history-motion .is-point")), 1)
        position = float(self.element("#history-position").get_attribute("value"))
        self.element("#history-previous").click()
        self.assertLess(float(self.element("#history-position").get_attribute("value")), position)
        self.element("#history-next").click()
        self.assertEqual(float(self.element("#history-position").get_attribute("value")), position)
        self.element("#history-position").send_keys(Keys.ARROW_RIGHT)
        self.assertEqual(float(self.element("#history-position").get_attribute("value")), position + 1)
        self.assertEqual(len(self.fixture.worker.timeline_calls), calls)
        self.assertNotEqual(self.element("#history-selected").text, "Choose a time")

    def test_history_refresh_preserves_fixed_range_and_selected_time(self):
        self.wait_live(); self.open_history()
        self.element("#history-earlier").click(); self.history_ready()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click()
        self.history_playing(); self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        selected, span = self.element("#history-selected").text, self.element("#history-range").text
        count = len(self.fixture.worker.timeline_calls)
        self.element("#history-refresh").click(); self.history_ready()
        self.assertEqual(len(self.fixture.worker.timeline_calls), count + 1)
        self.assertEqual(self.element("#history-selected").text, selected)
        self.assertEqual(self.element("#history-range").text, span)

    def test_history_delayed_old_camera_response_cannot_replace_new_selection(self):
        self.wait_live()
        self.fixture.worker.timeline_states.update({"camera-1":"error", "camera-2":"empty"})
        self.fixture.worker.timeline_gate.clear()
        self.driver.find_element(By.ID,"history-tab").click()
        self.wait.until(lambda _: len(self.fixture.worker.timeline_calls) == 1)
        Select(self.element("#history-camera")).select_by_value("camera-2")
        self.fixture.worker.timeline_gate.set(); self.history_ready()
        self.assertEqual(self.element("#history-camera").get_attribute("value"), "camera-2")
        self.assertIn("No motion intervals", self.element("#history-motion-status").text)
        self.assertEqual([call[0] for call in self.fixture.worker.timeline_calls], ["camera-1", "camera-2"])

    def test_history_mobile_timeline_fits_and_can_select_recording(self):
        self.wait_live(); self.driver.set_window_size(390, 844); self.open_history()
        self.assertTrue(self.driver.execute_script("return document.documentElement.scrollWidth <= innerWidth"))
        self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")[1].click()
        self.assertGreater(float(self.element("#history-position").get_attribute("value")), 0)
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,".timeline-cursor")), 2)

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

    def test_history_compact_workspace_keeps_video_seek_and_marks_in_view(self):
        self.mark_clip(10)
        self.assertEqual(self.element("#clip-queue").text,"Save clip")
        for width,height in ((1600,1100),(1366,768)):
            with self.subTest(window=(width,height)):
                self.driver.set_window_size(width,height)
                self.assert_history_controls_in_view()
                self.assertAlmostEqual(self.ratio("#history-image"),16/9,delta=.01)
                markers=self.driver.find_elements(By.CSS_SELECTOR,".clip-marker")
                self.assertEqual(sum(marker.is_displayed() for marker in markers),2)
                self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,".clip-shade")),2)
        self.fixture.worker.export_gate.clear()
        self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        self.assert_history_controls_in_view()
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["state"],"paused")
        self.element("#clip-clear").click()
        self.assert_history_controls_in_view()
        self.assertEqual(self.element("#clip-message").text,"")

    def test_history_motion_list_scroll_preserves_video_and_can_seek(self):
        original=self.fixture.worker.query_timeline
        def many_events(camera,begin,end):
            data=original(camera,begin,end)
            start,stop=datetime.fromisoformat(begin),datetime.fromisoformat(end)
            data["motion"]["intervals"]=[{
                "start":(start+(stop-start)*(.1+.8*index/36)).isoformat(timespec="seconds"),
                "end":(start+(stop-start)*(.1+.8*index/36)+timedelta(seconds=20)).isoformat(timespec="seconds"),
                "recording_type":1} for index in range(36)]
            return data
        self.fixture.worker.query_timeline=many_events
        self.driver.set_window_size(1366,768); self.wait_live(); self.open_history()
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")),36)
        self.element("#history-recordings button").click(); self.history_playing()
        identifier=next(iter(self.fixture.worker.playbacks))
        generation=self.fixture.worker.playbacks[identifier]["generation"]
        before=len(self.fixture.worker.playback_commands)
        picture=self.history_pixels()
        top=self.element("#history-viewer").rect["y"]
        x,y=self.driver.execute_script("const r=document.querySelector('.history-events-panel').getBoundingClientRect();return [r.left+r.width/2,r.bottom-20]")
        self.driver.execute_cdp_cmd("Input.dispatchMouseEvent",{"type":"mouseWheel","x":x,"y":y,"deltaX":0,"deltaY":500})
        self.wait.until(lambda _:self.driver.execute_script("return document.querySelector('.history-events-panel').scrollTop>0"))
        self.assertEqual(self.element("#history-viewer").rect["y"],top)
        self.assert_history_controls_in_view()
        self.assertEqual(len(self.fixture.worker.playback_commands),before)
        self.wait.until(lambda _:self.history_pixels()!=picture)
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[-1].click()
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1)
        self.history_playing(); self.assert_history_controls_in_view()

    def test_history_collapsed_motion_heading_fits_and_reopens_at_all_sizes(self):
        self.paused_history()
        summary=self.element(".history-events-panel summary")
        for width,height in ((1366,768),(960,800),(390,844)):
            with self.subTest(window=(width,height)):
                self.driver.set_window_size(width,height)
                if self.element(".history-events-panel").get_attribute("open"):
                    summary.click()
                geometry=self.driver.execute_script("""
                    const panel=document.querySelector('.history-events-panel'), summary=panel.querySelector('summary');
                    const p=panel.getBoundingClientRect(), s=summary.getBoundingClientRect();
                    return {panelTop:p.top,panelBottom:p.bottom,summaryTop:s.top,summaryBottom:s.bottom,
                      scrollHeight:panel.scrollHeight,clientHeight:panel.clientHeight};
                """)
                self.assertGreaterEqual(geometry["summaryTop"],geometry["panelTop"])
                self.assertLessEqual(geometry["summaryBottom"],geometry["panelBottom"])
                self.assertLessEqual(geometry["scrollHeight"],geometry["clientHeight"]+1,
                    "The collapsed heading should fit without a scrollbar")
                self.assertFalse(self.rendered("#history-events button"))
                before=len(self.fixture.worker.playback_commands)
                summary.send_keys(Keys.ENTER)
                self.assertTrue(self.rendered("#history-events button"))
                summary.send_keys(Keys.ENTER)
                self.assertFalse(self.rendered("#history-events button"))
                self.assertEqual(len(self.fixture.worker.playback_commands),before)
                self.assertEqual(self.element("#history-player").get_attribute("data-state"),"paused")

    def test_history_date_picker_keyboard_dismissal_and_navigation_preserve_draft(self):
        self.paused_history()
        summary=self.element(".history-date-picker summary")
        self.assertFalse(self.rendered("#history-date-time"))
        commands=len(self.fixture.worker.playback_commands)
        picture=self.history_pixels()
        summary.send_keys(Keys.ENTER)
        self.wait.until(lambda _:self.rendered("#history-date-time"))
        value=self.date_value(2).replace(tzinfo=None).isoformat()
        self.driver.execute_script("document.getElementById('history-date-time').value=arguments[0]",value)
        self.element("#history-date-time").send_keys(Keys.ESCAPE)
        self.assertFalse(self.rendered("#history-date-time"))
        self.assertEqual(self.driver.switch_to.active_element,summary)
        summary.send_keys(Keys.ENTER)
        self.assertEqual(self.element("#history-date-time").get_attribute("value"),value)
        self.element(".history-timeline h2").click()
        self.assertFalse(self.rendered("#history-date-time"))
        self.assertEqual(len(self.fixture.worker.playback_commands),commands)
        self.assertEqual(self.history_pixels(),picture)
        summary.click(); self.element("#exports-tab").click()
        self.open_history()
        self.assertFalse(self.rendered("#history-date-time"))
        self.open_date_picker()
        self.assertEqual(self.element("#history-date-time").get_attribute("value"),value)

    def test_history_mobile_collapsed_events_can_play_seek_and_mark(self):
        self.wait_live(); self.open_history()
        self.assertFalse(self.element(".history-events-panel").get_attribute("open"))
        self.assertFalse(self.rendered("#history-events button"))
        self.element("#history-motion button").click(); self.history_playing()
        self.element(".history-events-panel summary").click()
        self.assertTrue(self.rendered("#history-events button"))
        identifier=next(iter(self.fixture.worker.playbacks))
        generation=self.fixture.worker.playbacks[identifier]["generation"]
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[1].click()
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1)
        self.history_playing()
        self.element(".history-events-panel summary").click()
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state")=="paused" and self.element("#clip-start").is_enabled())
        self.element("#clip-start").click(); self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click()
        self.assertEqual(self.clip_seconds(),10)
        self.assertTrue(self.element("#clip-queue").is_enabled())
        self.assertFalse(self.driver.execute_script("return document.documentElement.scrollWidth>innerWidth"))

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

    def test_history_clip_labels_between_bars_keep_heights_and_preview_stable(self):
        self.paused_history(); self.driver.set_window_size(1366,768)
        def layout():
            return self.driver.execute_script("""
                return Object.fromEntries(['#history-viewer','#history-recordings','#history-motion'].map(selector=>{
                  const r=document.querySelector(selector).getBoundingClientRect();return [selector,{top:r.top,height:r.height}];
                }));
            """)
        before=layout()
        self.element("#clip-start").click()
        self.assertEqual(layout(),before)
        self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click()
        self.assertEqual(layout(),before)
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,".clip-marker")),2)
        for marker in self.driver.find_elements(By.CSS_SELECTOR,".clip-marker"):
            rect=marker.rect
            recording=self.element("#history-recordings").rect
            motion=self.element("#history-motion").rect
            self.assertGreaterEqual(rect["y"],recording["y"]+recording["height"])
            self.assertLessEqual(rect["y"]+rect["height"],motion["y"])
        self.assert_history_controls_in_view()
        self.driver.save_screenshot("/output/history-marks-between-bars.png")
        self.element("#clip-clear").click()
        self.assertEqual(layout(),before)
        self.assertEqual(self.driver.find_elements(By.CSS_SELECTOR,".clip-marker"),[])

    def test_history_clip_marks_steps_and_camera_reset(self):
        self.paused_history()
        before = len(self.fixture.worker.playback_commands)
        self.element("#clip-start").click(); start = self.element("#clip-range").text
        self.assertEqual(len(self.fixture.worker.playback_commands), before)
        self.element('#history-steps button[data-seconds="30"]').click()
        self.wait.until(lambda _:next(iter(self.fixture.worker.playbacks.values()))["generation"] == 2 and self.element("#clip-end").is_enabled())
        self.element("#clip-end").click()
        self.assertEqual(self.element("#clip-duration").text, "30 seconds")
        self.assertIn(start.split(" · End:")[0], self.element("#clip-range").text)
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, ".clip-marker")), 2)
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, ".clip-shade")), 2)
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["state"], "paused")
        self.element("#live-tab").click(); self.wait_live(); self.open_history()
        self.assertEqual(self.element("#clip-duration").text, "30 seconds")
        self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        Select(self.element("#history-camera")).select_by_value("camera-2"); self.history_ready()
        self.assertIn("Start: Not set · End: Not set", self.element("#clip-range").text)
        self.assertFalse(self.element("#clip-queue").is_enabled())
        self.assertEqual(self.element("#clip-message").text, "")
        self.wait.until(lambda _:self.fixture.server.exports.list()["jobs"][0]["state"] == "ready")

    def test_history_frame_download_is_png_with_saved_aspect_and_no_job(self):
        self.paused_history()
        before = len(self.fixture.worker.playback_commands)
        self.element("#history-frame-download").click()
        self.wait.until(lambda _:list(self.downloads.glob("*.png")))
        file = next(self.downloads.glob("*.png")); data = file.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II",data[16:24])
        self.assertAlmostEqual(width/height,16/9,delta=.01)
        self.assertIn("oogies-Driveway_", file.name); self.assertRegex(file.name,r"Z_f[0-9]+\.png$")
        self.assertEqual(self.fixture.server.exports.list()["jobs"], [])
        self.assertEqual(len(self.fixture.worker.playback_commands), before)
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["state"], "paused")
        decoded = subprocess.run(["ffmpeg","-v","error","-i",str(file),"-frames:v","1","-f","rawvideo","-pix_fmt","rgb24","-threads","1","pipe:1"],capture_output=True,check=True,timeout=10).stdout
        self.assertTrue(all(abs(a-b)<12 for a,b in zip(decoded[:3],COLORS[0])),decoded[:3])
        self.element('#history-steps button[data-seconds="10"]').click()
        self.assertFalse(self.element("#history-frame-download").is_enabled())
        self.wait.until(lambda _:self.element("#history-frame-download").is_enabled())
        self.element("#history-pause").click(); self.history_playing()
        commands = len(self.fixture.worker.playback_commands)
        self.element("#history-frame-download").click()
        self.wait.until(lambda _:len(list(self.downloads.glob("*.png"))) == 2)
        self.assertEqual(len(self.fixture.worker.playback_commands),commands)
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["state"],"playing")
        self.assertEqual(self.fixture.server.exports.list()["jobs"],[])

    def test_history_frame_download_freezes_camera_and_aspect_during_conversion(self):
        self.paused_history()
        self.driver.execute_script("""
          const original=HTMLCanvasElement.prototype.toBlob;
          HTMLCanvasElement.prototype.toBlob=function(callback,type){
            window.finishFrame=()=>original.call(this,callback,type);
          };
        """)
        self.element("#history-frame-download").click()
        self.wait.until(lambda _:self.driver.execute_script("return typeof window.finishFrame==='function'"))
        self.open_settings(); self.aspect("4:3"); self.close_settings()
        Select(self.element("#history-camera")).select_by_value("camera-2"); self.history_ready()
        self.driver.execute_script("window.finishFrame()")
        self.wait.until(lambda _:list(self.downloads.glob("*.png")))
        file = next(self.downloads.glob("*.png")); width,height=struct.unpack(">II",file.read_bytes()[16:24])
        self.assertAlmostEqual(width/height,16/9,delta=.01); self.assertIn("oogies-Driveway_",file.name)
        self.assertEqual(self.fixture.worker.export_commands,[])

    def test_history_frame_download_original_and_standard_proportions(self):
        self.paused_history()
        for index, (aspect, ratio) in enumerate((("original",352/288),("4:3",4/3))):
            self.open_settings(); self.aspect(aspect); self.close_settings()
            self.element("#history-frame-download").click()
            self.wait.until(lambda _:len(list(self.downloads.glob("*.png"))) > index)
            file=max(self.downloads.glob("*.png"),key=lambda path:path.stat().st_mtime)
            width,height=struct.unpack(">II",file.read_bytes()[16:24])
            self.assertAlmostEqual(width/height,ratio,delta=.01)
            if aspect=="original": self.assertEqual((width,height),(352,288))

    def test_history_frame_download_sanitizes_camera_names(self):
        self.paused_history()
        Select(self.element("#history-camera")).select_by_value("camera-2"); self.history_ready()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click(); self.history_playing()
        self.element("#history-frame-download").click()
        self.wait.until(lambda _:list(self.downloads.glob("*.png")))
        filename=next(self.downloads.glob("*.png")).name
        self.assertTrue(filename.startswith("oogies-Front -porch- & gate_"),filename)
        self.assertNotRegex(filename,r'[<>:"/\\|?*\x00-\x1f]')

    def test_history_clip_bounds_and_mobile_controls(self):
        self.paused_history(); self.driver.set_window_size(390,844)
        self.element("#clip-start").click()
        # Keep one invalid-state layout check on mobile; the validity matrix is
        # exercised in Node rather than repeated through playback and the DOM.
        self.driver.execute_script("const s=document.getElementById('history-position');s.value=Number(s.value)+601;s.dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click()
        self.assertIn("up to 600 seconds",self.element("#clip-duration").text)
        self.assertFalse(self.element("#clip-queue").is_enabled())
        self.assertEqual(self.fixture.worker.export_commands,[])
        self.assertTrue(self.driver.execute_script("return document.documentElement.scrollWidth<=innerWidth"))

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

    def test_history_clip_drag_clamps_duration_and_order_without_seeking(self):
        self.mark_clip()
        self.assertIn("Zoomed",self.element("#history-range").text)
        window=lambda:float(self.element("#history-recordings").get_attribute("data-view-to"))-float(self.element("#history-recordings").get_attribute("data-view-from"))
        initial_window=window()
        self.element("#history-zoom-out").click()
        self.assertGreater(window(),initial_window)
        self.element("#history-full-range").click()
        self.assertNotIn("Zoomed",self.element("#history-range").text)
        before=len(self.fixture.worker.playback_commands)
        generation=next(iter(self.fixture.worker.playbacks.values()))["generation"]
        selected=self.element("#history-position").get_attribute("value")
        frozen=(self.element("#history-recordings").get_attribute("data-view-from"),self.element("#history-recordings").get_attribute("data-view-to"))
        # One native gesture verifies model-to-marker wiring. All four boundary
        # directions and duration/order combinations live in clip-model tests.
        self.drag_clip("to",1)
        self.assertEqual(self.clip_seconds(),600)
        self.assertEqual(len(self.fixture.worker.playback_commands),before)
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["generation"],generation)
        self.assertEqual(self.element("#history-position").get_attribute("value"),selected)
        self.assertEqual(frozen,(self.element("#history-recordings").get_attribute("data-view-from"),self.element("#history-recordings").get_attribute("data-view-to")))

    def test_history_overlong_clip_zooms_and_can_be_repaired_with_keyboard(self):
        self.mark_clip(1200)
        self.assertEqual(self.clip_seconds(),1200); self.assertFalse(self.element("#clip-queue").is_enabled())
        self.assertIn("Zoomed",self.element("#history-range").text)
        commands=len(self.fixture.worker.playback_commands)
        self.element('#history-clip-marks .clip-marker[data-bound="to"]').send_keys(Keys.ARROW_LEFT)
        self.assertEqual(self.clip_seconds(),600); self.assertTrue(self.element("#clip-queue").is_enabled())
        self.assertEqual(self.driver.switch_to.active_element.get_attribute("data-bound"),"to")
        self.assertEqual(len(self.fixture.worker.playback_commands),commands)

    def test_history_clip_handles_respect_configured_limit(self):
        self.mark_clip(180)
        self.assertIn("up to 120 seconds",self.element("#clip-duration").text)
        self.element('#history-clip-marks .clip-marker[data-bound="to"]').send_keys(Keys.ARROW_LEFT)
        self.assertEqual(self.clip_seconds(),120)
        self.assertTrue(self.element("#clip-queue").is_enabled())

    def test_history_clip_touch_drag_survives_metadata_refresh(self):
        self.mark_clip(); self.driver.set_window_size(390,844)
        flag=self.element('#history-clip-marks .clip-marker[data-bound="to"]')
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",flag)
        x,y,right=self.driver.execute_script("const f=arguments[0].getBoundingClientRect(),t=arguments[0].parentElement.getBoundingClientRect();return [f.left+f.width/2,f.top+f.height/2,t.right-2]",flag)
        before=len(self.fixture.worker.playback_commands); searches=len(self.fixture.worker.timeline_calls)
        self.driver.execute_cdp_cmd("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y}]})
        self.driver.execute_cdp_cmd("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":right,"y":y}]})
        self.assertGreater(self.clip_seconds(),30)
        value=self.clip_seconds()
        self.driver.execute_script("document.getElementById('history-refresh').click()")
        self.wait.until(lambda _:len(self.fixture.worker.timeline_calls)>searches)
        self.driver.execute_cdp_cmd("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        self.history_ready(); self.assertEqual(self.clip_seconds(),value)
        self.assertEqual(len(self.fixture.worker.playback_commands),before)
        self.assertTrue(self.driver.execute_script("return document.documentElement.scrollWidth<=innerWidth"))

    def test_history_zoomed_slider_keeps_sdk_playback_range(self):
        self.mark_clip()
        self.assertEqual(float(self.element("#history-position").get_attribute("max")),59)
        view_from=float(self.element("#history-recordings").get_attribute("data-view-from"))
        identifier=next(iter(self.fixture.worker.playbacks))
        session=self.fixture.server.playback.sessions[identifier]
        bounds=session["begin"],session["end"]
        generation=self.fixture.worker.playbacks[identifier]["generation"]
        self.driver.execute_script("const s=document.getElementById('history-position');s.value=0;s.dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1 and self.element("#clip-start").is_enabled())
        position=datetime.fromisoformat(self.fixture.worker.playbacks[identifier]["position"].replace("Z","+00:00"))
        self.assertEqual(position.timestamp()*1000,view_from)
        self.assertEqual((session["begin"],session["end"]),bounds)
        self.assertEqual(self.fixture.worker.playbacks[identifier]["state"],"paused")

    def test_history_seek_during_delayed_speed_response_keeps_requested_rate(self):
        self.paused_history()
        identifier=next(iter(self.fixture.worker.playbacks))
        generation=self.fixture.worker.playbacks[identifier]["generation"]
        self.driver.execute_script("""
            const original=window.fetch;
            window.fetch=async (...args)=>{
              const response=await original(...args);
              const body=args[1]?.body && JSON.parse(args[1].body);
              if(args[1]?.method==='PATCH' && body?.rate===4 && !('position' in body)){
                const json=response.json.bind(response);
                response.json=async ()=>{const data=await json();window.rateDelivered=true;return data;};
                await new Promise(resolve=>window.releaseRate=resolve);
              }
              return response;
            };
        """)
        self.element('#history-speeds button[data-rate="4"]').click()
        self.wait.until(lambda _:self.driver.execute_script("return Boolean(window.releaseRate)"))
        self.assertEqual(self.fixture.worker.playbacks[identifier]["rate"],4)
        # The timeline remains interactive while the rate response is in flight.
        self.element("#history-position").send_keys(Keys.HOME)
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1 and
            self.element("#history-player").get_attribute("data-state")=="paused" and self.element("#clip-start").is_enabled())
        source=self.fixture.worker.playbacks[identifier]
        self.assertEqual(source["rate"],4)
        self.assertEqual(source["requested_rate"],4)
        self.driver.execute_script("window.releaseRate()")
        self.wait.until(lambda _:self.driver.execute_script("return Boolean(window.rateDelivered)"))
        self.assertEqual(self.fixture.worker.playbacks[identifier]["generation"],generation+1)
        self.assertEqual(self.element('#history-speeds button[data-rate="4"]').get_attribute("aria-pressed"),"true")
        self.assertTrue(self.element('#history-speeds button[data-rate="4"]').is_enabled())

    def test_history_steps_clamp_to_window_and_preserve_speed(self):
        self.paused_history()
        identifier=next(iter(self.fixture.worker.playbacks))
        speed=self.element('#history-speeds button[data-rate="4"]')
        speed.click()
        self.wait.until(lambda _:speed.get_attribute("aria-pressed")=="true" and speed.is_enabled())
        generation=self.fixture.worker.playbacks[identifier]["generation"]
        self.driver.execute_script("const s=document.getElementById('history-position');s.value=0;s.dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1 and self.element("#history-pause").is_enabled())
        self.assertFalse(self.element('#history-steps button[data-seconds="-10"]').is_enabled())
        self.assertFalse(self.element('#history-steps button[data-seconds="-30"]').is_enabled())
        generation=self.fixture.worker.playbacks[identifier]["generation"]
        self.element('#history-steps button[data-seconds="30"]').click()
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1 and self.element("#history-pause").is_enabled())
        source=self.fixture.worker.playbacks[identifier]
        self.assertEqual(source["state"],"paused"); self.assertEqual(source["rate"],4)
        generation=source["generation"]
        self.driver.execute_script("const s=document.getElementById('history-position');s.value=s.max;s.dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1 and self.element("#history-pause").is_enabled())
        self.assertFalse(self.element('#history-steps button[data-seconds="10"]').is_enabled())
        self.assertFalse(self.element('#history-steps button[data-seconds="30"]').is_enabled())
        self.assertEqual(self.fixture.worker.playbacks[identifier]["rate"],4)

    def test_history_speed_request_failure_restores_rate_for_following_seek(self):
        self.paused_history()
        identifier=next(iter(self.fixture.worker.playbacks))
        generation=self.fixture.worker.playbacks[identifier]["generation"]
        self.driver.execute_script("""
            const original=window.fetch;
            window.fetch=(...args)=>{
              const body=args[1]?.body && JSON.parse(args[1].body);
              if(args[1]?.method==='PATCH' && body?.rate===4 && !('position' in body))
                return Promise.reject(new Error('Simulated speed request failure'));
              return original(...args);
            };
        """)
        self.element('#history-speeds button[data-rate="4"]').click()
        self.wait.until(lambda _:"Simulated speed request failure" in self.element("#history-speed-status").text)
        self.assertEqual(self.element('#history-speeds button[data-rate="1"]').get_attribute("aria-pressed"),"true")
        self.element("#history-position").send_keys(Keys.HOME)
        self.wait.until(lambda _:self.fixture.worker.playbacks[identifier]["generation"]==generation+1 and self.element("#history-pause").is_enabled())
        self.assertEqual(self.fixture.worker.playbacks[identifier]["rate"],1)
        self.assertEqual(self.fixture.worker.playbacks[identifier]["requested_rate"],1)

    def test_history_exports_preserve_another_live_tab(self):
        self.wait_live(); first=self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url)
        self.open_history(); self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click(); self.history_playing()
        self.element("#history-pause").click(); self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state")=="paused")
        self.element("#clip-start").click(); self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click(); self.element("#clip-queue").click()
        self.wait.until(lambda _:any(job["waiting_reason"] for job in self.fixture.server.exports.list()["jobs"]))
        self.assertEqual(self.fixture.worker.export_commands,[])
        self.element("#exports-tab").click()
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,'.export-job[data-state="ready"]'))
        self.assertFalse(self.fixture.worker.playbacks); self.assertEqual(len(self.fixture.sessions.wanted),8)
        self.driver.switch_to.window(first); self.wait_live()
        self.assertEqual(self.fixture.snapshot()["viewers"],1)

    def test_history_export_queue_download_and_delete(self):
        self.paused_history()
        self.element("#clip-start").click()
        self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click()
        self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        self.assertTrue(self.element("#history-panel").is_displayed())
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["state"], "paused")
        link = self.element("#clip-message a")
        self.assertEqual(link.text,"Export")
        self.assertEqual(link.get_attribute("aria-label"),"View export jobs")
        link.send_keys(Keys.ENTER)
        self.wait.until(lambda _:self.element("#exports-panel").is_displayed())
        self.assertEqual(self.element("#clip-message").get_attribute("textContent"), "")
        self.assertEqual(self.element("#exports-tab").get_attribute("aria-pressed"),"true")
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,'.export-job[data-state="ready"]'))
        self.assertFalse(self.fixture.worker.playbacks); self.assertFalse(self.fixture.sessions.sessions)
        job = self.fixture.server.exports.list()["jobs"][0]
        self.assertEqual(job["duration_seconds"],10); self.assertEqual(job["display_aspect_ratio"],"16:9")
        self.assertEqual(job["frames"],50)
        self.element(".export-download").click(); self.wait.until(lambda _:list(self.downloads.glob("*.mp4")))
        self.assertEqual(next(self.downloads.glob("*.mp4")).stat().st_size,job["bytes"])
        self.element(".export-job button").click()
        self.wait.until(lambda _:self.element(".export-job").get_attribute("data-state") == "expired")

    def test_export_remains_independent_of_history_navigation_and_tab_close(self):
        self.fixture.worker.export_gate.clear()
        self.addCleanup(self.fixture.worker.export_gate.set)
        self.paused_history()
        self.element("#clip-start").click()
        self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled())
        self.element("#clip-end").click(); self.element("#clip-queue").click()
        self.wait.until(lambda _:self.fixture.server.exports.active is not None)
        identifier = self.fixture.server.exports.active
        request = dict(self.fixture.server.exports.jobs[identifier]["request"])
        self.wait.until(lambda _:bool(self.fixture.worker.export_commands))
        capture = self.fixture.worker.export_commands[0]
        self.element('#history-steps button[data-seconds="30"]').click()
        self.wait.until(lambda _:self.element('#history-steps button[data-seconds="30"]').is_enabled())
        Select(self.element("#history-camera")).select_by_value("camera-2")
        self.wait.until(lambda _:self.element("#history-recordings").get_attribute("data-state")=="ready")
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click()
        self.history_playing()
        self.assertEqual(self.fixture.server.exports.jobs[identifier]["request"],request)
        first=self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url)
        self.element("#exports-tab").click()
        second=self.driver.current_window_handle
        self.driver.switch_to.window(first); self.driver.close(); self.driver.switch_to.window(second)
        self.wait.until(lambda _:not self.fixture.worker.playbacks)
        self.assertEqual(self.fixture.server.exports.get(identifier)["state"],"running")
        self.assertEqual(self.fixture.worker.export_commands,[capture])
        self.assertEqual(self.fixture.server.exports.jobs[identifier]["request"],request)
        self.fixture.worker.export_gate.set()
        self.wait.until(lambda _:self.fixture.server.exports.get(identifier)["state"]=="ready" and
                        self.fixture.sessions.budget.snapshot().reserved==0)
        self.assertEqual(self.fixture.sessions.budget.snapshot().reserved,0)

    def test_history_exports_keep_newest_first_on_return_and_refresh(self):
        self.mark_clip(10); self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        self.element("#exports-tab").click()
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,'.export-job[data-state="ready"]'))
        first = self.fixture.server.exports.list()["jobs"][0]["id"]
        self.driver.execute_script("window.firstExportRow=document.querySelector('.export-job')")
        self.open_history()
        self.wait.until(lambda _:self.element("#clip-queue").is_enabled()); self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        self.element("#clip-message a").click()
        self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,".export-job")) == 2)
        expected = [job["id"] for job in self.fixture.server.exports.list()["jobs"]]
        actual = lambda:[row.get_attribute("data-job-id") for row in self.driver.find_elements(By.CSS_SELECTOR,".export-job")]
        self.assertEqual(actual(),expected)
        self.assertNotEqual(actual()[0],first)
        self.assertTrue(self.driver.execute_script("return firstExportRow===document.querySelector(arguments[0])",
            f'.export-job[data-job-id="{first}"]'))
        # Another browser can enqueue work while this page remains on Exports.
        job = self.fixture.server.exports.list()["jobs"][0]
        self.fixture.server.exports.create({key:job[key] for key in ("camera_id","from","to","aspect_ratio")})
        self.element("#exports-refresh").click()
        self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,".export-job")) == 3)
        self.assertEqual(actual(),[job["id"] for job in self.fixture.server.exports.list()["jobs"]])
        self.assertTrue(self.driver.execute_script("return firstExportRow===document.querySelector(arguments[0])",
            f'.export-job[data-job-id="{first}"]'))

    def test_history_export_confirmation_bounces_restarts_and_respects_reduced_motion(self):
        self.mark_clip(10)
        # Pause real browser animations for deterministic visual samples.
        self.driver.execute_script("""
            const animate=Element.prototype.animate; window.feedbackAnimations=[];
            Element.prototype.animate=function(...args){
              const animation=animate.apply(this,args);
              if(this.id==='clip-message'){animation.pause();feedbackAnimations.push(animation);}
              return animation;
            };
        """)
        self.element("#clip-queue").click()
        self.wait.until(lambda _:self.driver.execute_script("return feedbackAnimations.length===1"))
        samples=self.driver.execute_script("""
            const animation=feedbackAnimations[0], message=document.getElementById('clip-message');
            const duration=animation.effect.getComputedTiming().duration;
            const samples=[0,.2,.4,.6,.8,.9].map(fraction=>{
              animation.currentTime=duration*fraction;
              const style=getComputedStyle(message);
              return {opacity:Number(style.opacity),y:new DOMMatrixReadOnly(style.transform).m42};
            });
            animation.finish();
            return {duration,samples,opacity:Number(getComputedStyle(message).opacity),
              transform:getComputedStyle(message).transform,text:message.textContent};
        """)
        self.assertGreater(samples["duration"],150); self.assertLessEqual(samples["duration"],700)
        self.assertEqual(samples["samples"][0]["opacity"],0)
        self.assertGreater(samples["samples"][0]["y"],0)
        self.assertLess(min(sample["y"] for sample in samples["samples"]),0)
        self.assertEqual(samples["opacity"],1); self.assertEqual(samples["transform"],"none")
        self.assertIn("Export queued",samples["text"])
        self.assert_history_controls_in_view()
        self.element("#clip-queue").click()
        self.wait.until(lambda _:self.driver.execute_script("return feedbackAnimations.length===2"))
        self.element("#clip-clear").click()
        self.assertEqual(self.element("#clip-message").text,"")
        self.assertEqual(self.driver.execute_script("return feedbackAnimations[1].playState"),"idle")
        self.driver.execute_cdp_cmd("Emulation.setEmulatedMedia",{"features":[{"name":"prefers-reduced-motion","value":"reduce"}]})
        self.element("#clip-start").click(); self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click()
        self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        self.assertEqual(self.driver.execute_script("return feedbackAnimations.length"),2)
        self.assertEqual(self.driver.execute_script("return document.getElementById('clip-message').getAnimations().length"),0)
        self.element("#clip-message a").send_keys(Keys.ENTER)
        self.wait.until(lambda _:self.element("#exports-panel").is_displayed())
        self.assertEqual(self.element("#clip-message").get_attribute("textContent"),"")

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

    def test_history_export_confirmation_clear_ignores_delayed_response(self):
        self.mark_clip(10); self.hold_export_response()
        job = self.fixture.server.exports.list()["jobs"][0]
        key = self.driver.execute_script("return window.heldExportKey")
        self.assertTrue(key)
        self.assertEqual(self.fixture.server.exports.jobs[job["id"]]["key"], key)
        self.element("#clip-clear").click()
        self.assertEqual(self.element("#clip-message").text, "")
        # New valid marks must not bypass the outstanding submission guard.
        self.element("#clip-start").click()
        self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled())
        self.element("#clip-end").click()
        self.assertFalse(self.element("#clip-queue").is_enabled())
        self.driver.execute_script("window.releaseExport()")
        # The enabled button acknowledges completion; no arbitrary callback sleep.
        self.wait.until(lambda _:self.element("#clip-queue").is_enabled())
        self.assertEqual(self.element("#clip-message").text,"")
        self.assertEqual(len(self.fixture.server.exports.list()["jobs"]), 1)
        self.wait.until(lambda _:self.fixture.server.exports.list()["jobs"][0]["state"] == "ready")

    def test_history_export_circular_progress_tracks_capture_and_completion(self):
        self.mark_clip(30); self.fixture.worker.export_gate.clear()
        self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        self.element("#exports-tab").click()
        selector='.export-job[data-state="running"] [role="progressbar"]'
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,selector))
        ring=self.element(selector)
        self.assertTrue(ring.is_displayed())
        self.assertEqual(ring.get_attribute("aria-valuemin"),"0")
        self.assertEqual(ring.get_attribute("aria-valuemax"),"100")
        self.assertEqual(ring.get_attribute("aria-valuenow"),"0")
        self.assertEqual(ring.get_attribute("aria-label"),"Export progress for Driveway")
        self.driver.execute_script("window.exportRing=arguments[0]",ring)
        self.fixture.worker.export_gate.set()
        self.wait.until(lambda _:self.fixture.server.exports.list()["jobs"][0]["progress"] >= .25)
        self.fixture.worker.export_gate.clear()
        self.wait.until(lambda _:int(ring.get_attribute("aria-valuenow")) >= 25)
        percent=int(ring.get_attribute("aria-valuenow"))
        self.assertLess(percent,100)
        self.assertEqual(ring.text,f"{percent}%")
        self.assertEqual(ring.find_element(By.CSS_SELECTOR,".export-progress-value").get_attribute("stroke-dasharray"),f"{percent} 100")
        self.assertAlmostEqual(ring.size["width"],ring.size["height"],delta=1)
        self.assertTrue(self.driver.execute_script("return exportRing===document.querySelector('[role=progressbar]')"))
        self.driver.execute_cdp_cmd("Emulation.setEmulatedMedia",{"features":[{"name":"prefers-reduced-motion","value":"reduce"}]})
        self.assertEqual(self.driver.execute_script("return getComputedStyle(document.querySelector('.export-progress-value')).transitionDuration"),"0s")
        self.driver.set_window_size(390,844)
        self.assertTrue(ring.is_displayed())
        self.assertFalse(self.driver.execute_script("return document.documentElement.scrollWidth>window.innerWidth"))
        self.driver.save_screenshot("/output/export-progress-mobile.png")
        self.fixture.worker.export_gate.set()
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,'.export-job[data-state="ready"] .export-download'))
        self.assertFalse(ring.is_displayed())
        self.assertIn("Ready",self.element(".export-status-label").text)

    def test_history_export_cancel_releases_slot_and_removes_partial(self):
        self.paused_history(); self.fixture.worker.export_gate.clear()
        self.element("#clip-start").click()
        self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click()
        self.element("#clip-queue").click(); self.wait.until(lambda _:self.fixture.server.exports.active is not None)
        self.element("#exports-tab").click()
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,'.export-job[data-state="running"] button'))
        self.element(".export-job button").click()
        self.wait.until(lambda _:self.element(".export-job").get_attribute("data-state") == "cancelled" and self.fixture.sessions.budget.snapshot().reserved == 0)
        self.assertFalse(self.element('[role="progressbar"]').is_displayed())
        self.assertEqual(list(self.fixture.server.exports.directory.glob("*/clip*.mp4")),[])

    def test_history_export_file_limit_failure_keeps_viewer_and_can_retry(self):
        self.paused_history(); self.fixture.server.exports.encoder.max_bytes=1024
        self.element("#clip-start").click(); self.element('#history-steps button[data-seconds="10"]').click()
        self.wait.until(lambda _:self.element("#clip-end").is_enabled()); self.element("#clip-end").click(); self.element("#clip-queue").click()
        self.wait.until(lambda _:any(job["state"]=="failed" for job in self.fixture.server.exports.list()["jobs"]))
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["state"],"paused")
        self.assertEqual(self.fixture.sessions.budget.snapshot().reserved,1)
        self.assertEqual(list(self.fixture.server.exports.directory.glob("*/clip*.mp4")),[])
        self.fixture.server.exports.encoder.max_bytes=256*1024**2
        self.wait.until(lambda _:self.element("#clip-queue").is_enabled()); self.element("#clip-queue").click()
        self.element("#exports-tab").click()
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,'.export-job[data-state="ready"]'))
        self.assertEqual(self.fixture.sessions.budget.snapshot().reserved,0)

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

    def test_history_date_jump_uses_recorder_timezone_and_selected_camera(self):
        self.wait_live()
        self.driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId":"America/Los_Angeles"})
        self.open_history(); Select(self.element("#history-camera")).select_by_value("camera-2"); self.history_ready()
        target = self.date_value()
        self.go_to_date(target); self.history_playing(); self.history_ready()
        source = next(iter(self.fixture.worker.playbacks.values()))
        self.assertEqual(source["camera_id"], "camera-2")
        start = [cmd for cmd in self.fixture.worker.playback_commands if cmd.startswith("playback-start")][-1].split()
        self.assertEqual(start[4], target.replace(tzinfo=None).isoformat())
        self.assertFalse(self.element(".history-date-picker").get_attribute("open"))
        self.open_date_picker()
        self.assertIn("Africa/Johannesburg", self.element("#history-date-zone").text)
        self.assertIn(str(target.year), self.element("#history-range").text)
        self.assertEqual(self.element("#history-date-time").get_attribute("value"), target.replace(tzinfo=None).isoformat())
        self.element("#history-date-time").send_keys(Keys.ESCAPE)
        self.assertTrue(self.element("#history-later").is_enabled())
        selected = source["play_time"]
        self.assertLess(abs((selected - target.astimezone(timezone.utc)).total_seconds()), 5)
        before = self.history_pixels(); self.wait.until(lambda _:self.history_pixels() != before)

    def test_history_date_jump_keeps_slot_speed_and_other_live_grid(self):
        self.wait_live(); self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR, "#history-recordings button")[0].click(); self.history_playing()
        self.element('#history-speeds button[data-rate="4"]').click()
        self.wait.until(lambda _:self.element('#history-speeds button[data-rate="4"]').get_attribute("aria-pressed") == "true")
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        identifier = next(iter(self.fixture.worker.playbacks)); original_tab = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url); self.wait_live(range(1,8))
        self.wait.until(lambda _:self.state(8) == "capacity_limited")
        started, stopped = dict(self.fixture.worker.started), dict(self.fixture.worker.stopped)
        self.driver.switch_to.window(original_tab)
        self.go_to_date(self.date_value(days=3)); self.history_playing(); self.history_ready()
        self.assertEqual(list(self.fixture.worker.playbacks), [identifier])
        self.assertEqual(self.fixture.worker.playbacks[identifier]["generation"], 2)
        self.assertEqual(self.fixture.worker.playbacks[identifier]["rate"], 4)
        self.assertEqual(self.fixture.sessions.budget.snapshot().reserved, 1)
        self.assertEqual(len(self.fixture.sessions.wanted), 7)
        self.assertEqual(dict(self.fixture.worker.started), started)
        self.assertEqual(dict(self.fixture.worker.stopped), stopped)
        self.driver.switch_to.window(self.driver.window_handles[1]); self.wait_live(range(1,8))
        before = self.pixels(); self.wait.until(lambda _:self.pixels() != before)

    def test_history_date_rejected_preserves_working_picture_and_window(self):
        self.wait_live(); self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR, "#history-recordings button")[0].click(); self.history_playing()
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        identifier = next(iter(self.fixture.worker.playbacks))
        span, picture = self.element("#history-range").text, self.history_pixels()
        count, commands = len(self.fixture.worker.timeline_calls), len(self.fixture.worker.playback_commands)
        self.go_to_date(self.date_value(days=-1))
        self.wait.until(lambda _:"earlier than now" in self.element("#history-date-message").text)
        self.assertTrue(self.rendered("#history-date-time"))
        self.assertEqual(self.element("#history-range").text, span)
        self.assertEqual(self.history_pixels(), picture)
        self.assertEqual(self.fixture.worker.playbacks[identifier]["generation"], 1)
        self.assertEqual(len(self.fixture.worker.timeline_calls), count)
        self.assertEqual(len(self.fixture.worker.playback_commands), commands)
        self.driver.execute_script("document.getElementById('history-date-time').value=''")
        self.element("#history-go-time").click()
        self.assertEqual(len(self.fixture.worker.playback_commands), commands)
        self.go_to_date(self.date_value()); self.history_playing()
        self.assertEqual(self.element("#history-date-message").text, "")

    def test_history_date_delayed_response_cannot_open_previous_camera(self):
        self.wait_live(); self.open_history()
        self.driver.execute_script("""
            const original=window.fetch;
            window.fetch=async (...args)=>{
              const response=await original(...args);
              if(String(args[0]).includes('local_time=')) {
                const body=await response.text(); window.dateHeld=true;
                await new Promise(resolve=>window.releaseDate=resolve);
                return new Response(body,{status:response.status,headers:{'Content-Type':'application/json'}});
              }
              return response;
            };
        """)
        self.go_to_date(self.date_value()); self.wait.until(lambda _:self.driver.execute_script("return window.dateHeld"))
        Select(self.element("#history-camera")).select_by_value("camera-2"); self.history_ready()
        span = self.element("#history-range").text
        self.driver.execute_script("window.releaseDate()")
        self.driver.execute_async_script("const done=arguments[0];setTimeout(done,400)")
        self.assertEqual(self.element("#history-camera").get_attribute("value"), "camera-2")
        self.assertEqual(self.element("#history-range").text, span)
        self.assertFalse(self.fixture.worker.playbacks)

    def test_history_date_navigation_fits_mobile_and_keyboard_submission_plays(self):
        self.wait_live(); self.driver.set_window_size(390, 844); self.open_history()
        self.open_date_picker()
        self.assertTrue(self.driver.execute_script("return document.documentElement.scrollWidth <= innerWidth"))
        target = self.date_value()
        self.driver.execute_script("document.getElementById('history-date-time').value=arguments[0]", target.replace(tzinfo=None).isoformat())
        self.element("#history-go-time").send_keys(Keys.ENTER); self.history_playing()
        self.assertFalse(self.rendered("#history-date-time"))
        self.assertTrue(self.driver.execute_script("return document.documentElement.scrollWidth <= innerWidth"))

    def test_camera_history_shortcuts_select_clicked_camera_and_work_offline(self):
        self.wait_live()
        buttons = self.driver.find_elements(By.CSS_SELECTOR, ".camera-history")
        self.assertEqual(len(buttons), 9)
        self.element(self.tile(2) + " .camera-history").click(); self.history_ready(); self.wait_counts(0, 0)
        self.assertEqual(self.element("#history-camera").get_attribute("value"), "camera-2")
        self.assertEqual(self.fixture.worker.timeline_calls[-1][0], "camera-2")
        self.assertEqual(self.element("#history-player").get_attribute("data-state"), "idle")
        self.assertFalse(self.fixture.worker.playbacks)
        self.element("#live-tab").click(); self.wait_live()
        # A previous History selection must not override the next tile shortcut.
        button = self.element(self.tile(9) + " .camera-history")
        self.assertIn("Camera 9", button.get_attribute("aria-label"))
        button.send_keys(Keys.ENTER); self.history_ready()
        self.assertEqual(self.element("#history-camera").get_attribute("value"), "camera-9")
        self.assertEqual(self.driver.switch_to.active_element.get_attribute("id"), "history-camera")
        self.assertEqual(self.fixture.worker.timeline_calls[-1][0], "camera-9")
        self.driver.find_elements(By.CSS_SELECTOR, "#history-recordings button")[0].click(); self.history_playing()
        self.assertIn("Camera 9", self.element("#history-image").get_attribute("alt"))

    def test_history_speed_steps_change_clock_and_survive_seek_pause_resume(self):
        self.wait_live(); self.open_history()
        self.assertTrue(all(not b.is_enabled() for b in self.driver.find_elements(By.CSS_SELECTOR, "#history-speeds button")))
        self.driver.find_elements(By.CSS_SELECTOR, "#history-recordings button")[0].click(); self.history_playing()
        source = next(iter(self.fixture.worker.playbacks.values()))
        generation = source["generation"]
        for rate in (0.5, 1, 2, 4):
            button = self.element(f'#history-speeds button[data-rate="{rate}"]')
            self.wait.until(lambda _:button.is_enabled()); button.click()
            self.wait.until(lambda _:button.get_attribute("aria-pressed") == "true" and button.is_enabled())
            self.assertEqual(source["rate"], rate)
            self.assertEqual(source["generation"], generation)
            before, clock = source["sequence"], source["play_time"]
            self.wait.until(lambda _:source["sequence"] >= before + 5)
            ticks = source["sequence"] - before
            self.assertAlmostEqual((source["play_time"] - clock).total_seconds(), ticks * .2 * rate, delta=.01)
        self.driver.find_elements(By.CSS_SELECTOR, "#history-events button")[1].click(); self.history_playing()
        self.wait.until(lambda _:next(iter(self.fixture.worker.playbacks.values()))["generation"] == generation + 1)
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["rate"], 4)
        self.wait.until(lambda _:self.element("#history-pause").is_enabled()); self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        picture = self.history_pixels()
        self.element('#history-speeds button[data-rate="0.5"]').click()
        self.wait.until(lambda _:self.element('#history-speeds button[data-rate="0.5"]').get_attribute("aria-pressed") == "true")
        self.assertEqual(self.element("#history-player").get_attribute("data-state"), "paused")
        self.assertEqual(self.history_pixels(), picture)
        self.element("#history-pause").click(); self.history_playing()
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["rate"], .5)
        self.element("#history-stop").click()
        self.wait.until(lambda _:not self.fixture.worker.playbacks)
        self.assertTrue(all(not b.is_enabled() for b in self.driver.find_elements(By.CSS_SELECTOR, "#history-speeds button")))

    def test_history_speed_failure_shows_error_and_retains_moving_picture(self):
        self.wait_live(); self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR, "#history-recordings button")[0].click(); self.history_playing()
        self.fixture.worker.rate_failure = True
        self.element('#history-speeds button[data-rate="4"]').click()
        self.wait.until(lambda _:"decoder code 2" in self.element("#history-speed-status").text)
        self.assertEqual(self.element('#history-speeds button[data-rate="1"]').get_attribute("aria-pressed"), "true")
        self.assertEqual(self.element("#history-player").get_attribute("data-state"), "playing")
        before = self.history_pixels(); self.wait.until(lambda _:self.history_pixels() != before)
        self.fixture.worker.rate_failure = False
        self.element('#history-speeds button[data-rate="2"]').click()
        self.wait.until(lambda _:self.element('#history-speeds button[data-rate="2"]').get_attribute("aria-pressed") == "true")
        self.assertEqual(self.element("#history-speed-status").text, "")

    def history_pixels(self):
        return self.driver.execute_script("""
            const img=document.getElementById('history-image'), c=document.createElement('canvas');
            c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext('2d').drawImage(img,0,0);return c.toDataURL();
        """)

    def test_history_click_plays_moving_frames_and_pause_resume_seek_work(self):
        self.wait_live(); self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")[0].click(); self.history_playing()
        first = self.history_pixels()
        self.wait.until(lambda _:self.history_pixels() != first)
        self.open_settings(); self.aspect("4:3"); self.close_settings()
        self.assertAlmostEqual(self.ratio("#history-image"), 4/3, delta=.01)
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        paused = self.history_pixels()
        self.driver.execute_async_script("const done=arguments[0];setTimeout(done,500)")
        self.assertEqual(self.history_pixels(), paused)
        self.element("#history-pause").click(); self.history_playing()
        self.assertEqual(next(iter(self.fixture.worker.playbacks.values()))["generation"], 2)
        self.wait.until(lambda _:self.history_pixels() != paused)
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[2].click()
        self.wait.until(lambda _:next(iter(self.fixture.worker.playbacks.values()))["generation"] == 3 and
            self.element("#history-player").get_attribute("data-state") == "paused" and
            self.driver.execute_script("return !document.getElementById('history-image').hidden"))
        self.element("#history-stop").click()
        self.wait.until(lambda _:not self.fixture.worker.playbacks)
        self.assertEqual(self.element("#history-player").get_attribute("data-state"), "idle")

    def test_history_slider_previews_locally_and_commits_one_seek(self):
        self.wait_live(); self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click(); self.history_playing()
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.element("#history-player").get_attribute("data-state") == "paused")
        before = len([cmd for cmd in self.fixture.worker.playback_commands if cmd.startswith("playback-start")])
        self.driver.execute_script("""
            const slider=document.getElementById('history-position');
            for(const value of [2200,2300,2400]) {slider.value=value;slider.dispatchEvent(new Event('input',{bubbles:true}));}
        """)
        self.assertEqual(len([cmd for cmd in self.fixture.worker.playback_commands if cmd.startswith("playback-start")]), before)
        self.driver.execute_script("document.getElementById('history-position').dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait.until(lambda _:next(iter(self.fixture.worker.playbacks.values()))["generation"] == 2)
        self.assertEqual(len([cmd for cmd in self.fixture.worker.playback_commands if cmd.startswith("playback-start")]), before + 1)

    def test_history_playback_preserves_another_live_tab(self):
        self.wait_live(); first = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url); self.wait_live()
        self.open_history(); self.wait_counts(1,8)
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click(); self.history_playing()
        self.assertEqual(len(self.fixture.worker.playbacks), 1)
        self.driver.switch_to.window(first); self.wait_live()
        pixels = self.pixels(); self.wait.until(lambda _:self.pixels() != pixels)
        self.assertTrue(all(count == 1 for count in self.fixture.worker.started.values()))
        self.driver.switch_to.window(self.driver.window_handles[1]); self.element("#live-tab").click(); self.wait_live()
        self.wait.until(lambda _:not self.fixture.worker.playbacks)
        self.wait_counts(2,8)

    def test_history_playback_positions_are_independent_between_tabs(self):
        self.wait_live(); self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click(); self.history_playing()
        first_tab = self.driver.current_window_handle
        first_id = next(iter(self.fixture.worker.playbacks))
        self.driver.switch_to.new_window("tab"); self.driver.get(self.fixture.url); self.open_history()
        Select(self.element("#history-camera")).select_by_value("camera-2"); self.history_ready()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[2].click(); self.history_playing()
        second_id = next(key for key in self.fixture.worker.playbacks if key != first_id)
        self.driver.switch_to.window(first_tab)
        self.element("#history-pause").click()
        self.wait.until(lambda _:self.fixture.worker.playbacks[first_id]["state"] == "paused")
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[1].click()
        self.wait.until(lambda _:self.fixture.worker.playbacks[first_id]["generation"] == 2)
        self.assertEqual(self.fixture.worker.playbacks[second_id]["generation"], 1)
        self.assertEqual(self.fixture.worker.playbacks[second_id]["state"], "playing")
        self.element("#history-stop").click()
        self.wait.until(lambda _:first_id not in self.fixture.worker.playbacks)
        self.driver.switch_to.window(self.driver.window_handles[1]); self.history_playing()
        before = self.history_pixels(); self.wait.until(lambda _:self.history_pixels() != before)

    def test_history_offline_camera_playback_uses_its_own_aspect_preference(self):
        self.wait_live(); self.open_settings(); self.aspect("4:3"); self.close_settings()
        self.open_history()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-events button")[0].click(); self.history_playing()
        self.assertAlmostEqual(self.ratio("#history-image"), 4/3, delta=.01)
        Select(self.element("#history-camera")).select_by_value("camera-9"); self.history_ready()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")[0].click(); self.history_playing()
        self.assertIn("Camera 9", self.element("#history-image").get_attribute("alt"))
        self.assertAlmostEqual(self.ratio("#history-image"), 16/9, delta=.01)
        self.open_settings(); self.aspect("original", channel=9); self.close_settings()
        self.wait.until(lambda _:abs(self.ratio("#history-image") - 352/288) < .01)

    def test_history_settings_work_before_live_discovery_finishes(self):
        self.element("#history-tab").click(); self.open_settings()
        self.fixture.worker.discovery_gate.set(); self.history_ready()
        self.wait.until(lambda _:len(self.driver.find_elements(By.CSS_SELECTOR,"#aspect-settings select")) == 9)
        self.aspect("4:3", channel=2); self.close_settings()
        Select(self.element("#history-camera")).select_by_value("camera-2"); self.history_ready()
        self.driver.find_elements(By.CSS_SELECTOR,"#history-recordings button")[0].click(); self.history_playing()
        self.assertAlmostEqual(self.ratio("#history-image"), 4/3, delta=.01)

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
        self.driver.find_element(By.ID,"history-tab").click()
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
