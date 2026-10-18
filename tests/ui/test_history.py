"""History browser integration against the synthetic recorder."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait

from browser_support import BrowserTestCase


class HistoryUITests(BrowserTestCase):
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
