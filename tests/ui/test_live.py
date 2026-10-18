"""Live browser integration against the synthetic recorder."""

import hashlib
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from fixture import COLORS

from browser_support import BrowserTestCase


class LiveUITests(BrowserTestCase):
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
