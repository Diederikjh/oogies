"""Exports browser integration against the synthetic recorder."""

import struct
import subprocess
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from fixture import COLORS

from browser_support import BrowserTestCase


class ExportUITests(BrowserTestCase):
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
        self.wait.until(lambda _:not self.driver.find_elements(By.CSS_SELECTOR,".export-job"))
        self.assertFalse((self.fixture.server.exports.directory / job["id"]).exists())
        self.assertNotIn(job["id"], self.fixture.server.exports.jobs)

    def test_history_expired_clip_disappears_from_exports_on_poll(self):
        self.mark_clip(10); self.element("#clip-queue").click()
        self.wait.until(lambda _:"Export queued" in self.element("#clip-message").text)
        self.element("#exports-tab").click()
        self.wait.until(lambda _:self.driver.find_elements(By.CSS_SELECTOR,'.export-job[data-state="ready"]'))
        exports = self.fixture.server.exports
        job = exports.list()["jobs"][0]
        with exports.lock:
            exports.jobs[job["id"]]["expires_at"] = exports.clock() - 1
        # Routine polling must remove the entry without a page refresh.
        self.wait.until(lambda _:not self.driver.find_elements(By.CSS_SELECTOR,".export-job"))
        self.assertFalse((exports.directory / job["id"]).exists())
        self.assertNotIn(job["id"], exports.jobs)

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
