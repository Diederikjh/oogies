"""Longer browser checks used only by the explicit real-recorder diagnostic."""
from pathlib import Path
import json
import time
from urllib.request import urlopen

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


def sustain(driver, wait, backend, online, url, output, seconds):
    first = driver.current_window_handle
    live_selector = '.camera-tile[data-camera-id="camera-1"]'
    report = dict(requested_seconds=seconds, samples=[])
    baseline = backend()
    assert baseline["high_quality_limit"] == 1, "Keep the high-quality cap at one for this check"
    assert len(online)+2 <= baseline["source_limit"], "No room for grid, high quality and History"
    login_calls = baseline["sdk_login_calls"]
    render_wait=WebDriverWait(driver,3)

    def element(selector): return driver.find_element(By.CSS_SELECTOR, selector)
    def live_ready():
        return driver.execute_script("""
            return arguments[0].every(id=>{const tile=document.querySelector(`[data-camera-id="${id}"]`);
              return tile?.dataset.state==='live' && !tile.querySelector('img').hidden && tile.querySelector('img').naturalWidth>0}) &&
              document.querySelector(arguments[1]).dataset.quality==='high';
        """, online, live_selector)

    def digests(selectors):
        # Hash painted pixels at native dimensions, without resizing/encoding.
        def snapshot(_):
            result = driver.execute_async_script("""
            const done=arguments[1];Promise.all(arguments[0].map(async selector=>{
              const img=document.querySelector(selector), canvas=document.createElement('canvas');
              canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
              const context=canvas.getContext('2d');context.drawImage(img,0,0);
              const bytes=context.getImageData(0,0,canvas.width,canvas.height).data;
              return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
            })).then(done,error=>done({error:String(error)}));
            """, selectors)
            return result if isinstance(result,list) else False
        # A visible history <img> briefly loses intrinsic dimensions when its
        # next Blob URL is assigned. Sample a decoded picture, not that instant.
        return render_wait.until(snapshot)

    def history_ready():
        return driver.execute_script("""
            const img=document.getElementById('history-image');
            return document.getElementById('history-player').dataset.state==='playing' && !img.hidden && img.complete && img.naturalWidth>0;
        """)

    def playback_status():
        path=driver.execute_script("return checkOwnedSessions.find(path=>path.startsWith('/api/playback/'))")
        if not path: raise RuntimeError("History did not create a playback session")
        with urlopen(url+path,timeout=5) as response: return json.load(response)

    driver.switch_to.new_window("tab")
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
        {"source":Path(__file__).with_name("browser_feed_fault.js").read_text()})
    driver.get(url)
    second = driver.current_window_handle
    wait.until(lambda _:backend()["viewer_sessions"]==2)
    element("#history-tab").click()
    wait.until(lambda _:element("#history-recordings").get_attribute("data-state")=="ready")
    driver.execute_script("""
        const slider=document.getElementById('history-position');
        slider.value=Math.max(0,Number(slider.max)-3600);
        slider.dispatchEvent(new Event('change',{bubbles:true}));
    """)
    wait.until(lambda _:history_ready())
    playback_baseline=playback_status()
    assert backend()["viewer_sessions"]==1 and backend()["playback_sessions"]==1
    driver.switch_to.window(first); wait.until(lambda _:live_ready())
    generation = element(live_selector).get_attribute("data-source-generation")
    started = time.monotonic(); previous = None; previous_traffic = None; previous_frames=None; faults = set()
    while time.monotonic()-started < seconds:
        elapsed = time.monotonic()-started
        if elapsed>=seconds/3 and "live" not in faults:
            attempts=driver.execute_script("return mediaFault.attempts")
            driver.execute_script("mediaFault.active('eof')")
            wait.until(lambda _:driver.execute_script("return mediaFault.attempts")>attempts and live_ready())
            assert element(live_selector).get_attribute("data-source-generation")==generation
            faults.add("live")
        live = digests([f'.camera-tile[data-camera-id="{key}"] img' for key in online])
        assert isinstance(live,list) and len(live)==len(online)
        assert live_ready(), "A live picture stopped being fresh"
        live_bytes=driver.execute_script("return mediaFault.bytes")
        driver.switch_to.window(second)
        if elapsed>=2*seconds/3 and "history" not in faults:
            attempts=driver.execute_script("return mediaFault.attempts")
            driver.execute_script("mediaFault.active('error')")
            wait.until(lambda _:driver.execute_script("return mediaFault.attempts")>attempts and history_ready())
            faults.add("history")
        render_wait.until(lambda _:history_ready())
        playback=playback_status()
        assert playback["state"]=="playing", playback.get("error") or "SDK History stopped playing"
        assert playback["id"]==playback_baseline["id"] and playback["generation"]==playback_baseline["generation"]
        if previous_frames is not None: assert playback["frames"]>previous_frames, "SDK History frames stopped advancing"
        previous_frames=playback["frames"]
        history_bytes=driver.execute_script("return mediaFault.bytes")
        history = digests(["#history-image"])
        assert isinstance(history,list)
        current = live+history
        if previous is not None: assert all(a!=b for a,b in zip(previous,current)), "A painted picture stopped changing"
        previous=current
        status=backend()
        assert status["sdk_login_calls"]==login_calls
        assert status["viewer_sessions"]==status["playback_sessions"]==1
        assert status["active_media_feeds"]==2
        assert status["sources_by_quality"]==dict(overview=len(online),high=1)
        assert status["occupied_source_slots"]==len(online)+2
        assert all(source["state"]=="live" and source["frame_age_seconds"] is not None and source["frame_age_seconds"]<5
                   for source in status["live_source_metrics"])
        traffic=dict(at=time.monotonic(),live_bytes=live_bytes,history_bytes=history_bytes)
        rates={} if previous_traffic is None else {key+"_per_second":round((traffic[key]-previous_traffic[key])/(traffic["at"]-previous_traffic["at"]))
            for key in ("live_bytes","history_bytes")}
        previous_traffic=traffic
        report["samples"].append(dict(seconds=round(elapsed,2), live_source_metrics=status["live_source_metrics"],
            occupied_source_slots=status["occupied_source_slots"], active_media_feeds=status["active_media_feeds"],
            sdk_login_calls=status["sdk_login_calls"],
            playback={key:playback[key] for key in ("state","frames","position","generation","rate")},**rates))
        (output/"reliability-check.json").write_text(json.dumps(report,indent=2)+"\n")
        driver.switch_to.window(first)
        print(f"Sustained moving grid/high/history: {elapsed:.0f}/{seconds}s",flush=True)
        time.sleep(5)
    report.update(measured_seconds=round(time.monotonic()-started,2), recovered_feeds=sorted(faults))
    driver.save_screenshot(str(output/"reliability-live.png"))
    driver.switch_to.window(second)
    element("#history-pause").click()
    wait.until(lambda _:element("#history-player").get_attribute("data-state")=="paused")
    attempts=driver.execute_script("return mediaFault.attempts")
    time.sleep(12)
    assert driver.execute_script("return mediaFault.attempts")==attempts, "Paused History was incorrectly reconnected"
    driver.execute_script("mediaFault.active('eof')")
    wait.until(lambda _:driver.execute_script("return mediaFault.attempts")>attempts and
        element("#history-player").get_attribute("data-state")=="paused" and
        not element("#history-pause").get_attribute("disabled"))
    assert backend()["active_media_feeds"]==2
    driver.save_screenshot(str(output/"reliability-history.png"))
    element("#history-stop").click()
    wait.until(lambda _:backend()["playback_sessions"]==0 and backend()["occupied_source_slots"]==len(online)+1)
    driver.close(); driver.switch_to.window(first)
    for _ in range(3):
        wait.until(lambda _:not driver.execute_script("return Boolean(document.querySelector('.camera-tile.is-animating'))"))
        element(live_selector+" .camera-view").click()
        wait.until(lambda _:backend()["sources_by_quality"]["high"]==0 and element(live_selector).get_attribute("data-quality")=="overview")
        wait.until(lambda _:not driver.execute_script("return Boolean(document.querySelector('.camera-tile.is-animating'))"))
        element(live_selector+" .camera-view").click()
        wait.until(lambda _:live_ready() and backend()["sources_by_quality"]["high"]==1)
    assert backend()["sdk_login_calls"]==login_calls
    report.update(repeated_upgrade_release_cycles=3, paused_history_no_reconnect=True,
        paused_history_disconnect_recovered=True, passed=True)
    (output/"reliability-check.json").write_text(json.dumps(report,indent=2)+"\n")
    return report
