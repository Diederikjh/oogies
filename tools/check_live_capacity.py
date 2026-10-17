#!/usr/bin/env python3
"""Explicit browser comparison of one versus two distinct main streams.

Run through run_live_capacity_check.py. Uses the real frontend and existing
worker login; all diagnostics/footage belong in private .local output.
"""
import argparse
import json
from pathlib import Path
import signal
import time
from urllib.request import urlopen

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default="http://localhost:8088")
    parser.add_argument("--output",default="/output")
    parser.add_argument("--dual-seconds",type=int,default=180)
    parser.add_argument("--cameras",nargs=2)
    args=parser.parse_args()
    if not 60<=args.dual_seconds<=600: parser.error("dual duration must be 60-600 seconds")
    output=Path(args.output); output.mkdir(parents=True,exist_ok=True,mode=0o700)
    def interrupted(*_): raise KeyboardInterrupt("Capacity check interrupted")
    signal.signal(signal.SIGTERM,interrupted)
    def get(path):
        with urlopen(args.url+path,timeout=10) as response:return json.load(response)
    inventory=get("/api/cameras")["cameras"]
    online=[c["id"] for c in sorted(inventory,key=lambda c:c["channel"]) if c["online"] is not False]
    pair=args.cameras or online[:2]
    if len(set(pair))!=2 or any(c not in online for c in pair): parser.error("choose two distinct online cameras")
    initial=get("/api/status")
    if initial["high_quality_limit"]!=2 or len(online)+2>initial["source_limit"]:
        parser.error("requires high cap two and room for every overview plus two main streams")
    report=dict(passed=False,online_cameras=online,high_cameras=pair,stages=[])
    def save():
        temporary=output/"capacity-check.tmp.json"
        temporary.write_text(json.dumps(report,indent=2)+"\n")
        temporary.replace(output/"capacity-check.json")
    options=webdriver.ChromeOptions()
    for flag in ("--headless","--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                 "--disable-background-networking","--disable-sync","--no-first-run","--user-data-dir=/tmp/capacity-browser"):
        options.add_argument(flag)
    options.set_capability("goog:loggingPrefs",{"browser":"ALL"})
    driver=webdriver.Chrome(options=options)
    wait=WebDriverWait(driver,25); render_wait=WebDriverWait(driver,3)
    def element(selector):return driver.find_element(By.CSS_SELECTOR,selector)
    def tile(key):return f'.camera-tile[data-camera-id="{key}"]'
    def selection(high):
        # Collapse first, then expand. Keyboard activation avoids measuring a
        # pointer click while another tile's focus animation moves its target.
        report.update(current_stage="preparing",measuring=False); save()
        for key in pair:
            view=element(tile(key)+" .camera-view")
            if view.get_attribute("aria-expanded")=="true" and key not in high:
                view.send_keys(Keys.ENTER)
                wait.until(lambda _:element(tile(key)).get_attribute("data-quality")=="overview")
        wait.until(lambda _:get("/api/status")["sources_by_quality"]["high"]<=len(high))
        for key in high:
            view=element(tile(key)+" .camera-view")
            if view.get_attribute("aria-expanded")!="true":view.send_keys(Keys.ENTER)
        wait.until(lambda _:all(element(tile(key)).get_attribute("data-quality")==("high" if key in high else "overview") for key in online))
    def pictures(_):
        value=driver.execute_async_script("""
            const done=arguments[1];Promise.all(arguments[0].map(async id=>{
              const tile=document.querySelector(`[data-camera-id="${id}"]`),img=tile.querySelector('img');
              if(tile.dataset.state!=='live'||img.hidden||!img.complete||!img.naturalWidth)throw new Error('Picture not decoded/fresh');
              const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;
              const x=c.getContext('2d');x.drawImage(img,0,0);
              const hash=await crypto.subtle.digest('SHA-256',x.getImageData(0,0,c.width,c.height).data);
              return {id,quality:tile.dataset.quality,generation:tile.dataset.sourceGeneration,width:c.width,height:c.height,
                hash:Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join('')};
            })).then(done,e=>done({error:String(e)}));
        """,online)
        return value if isinstance(value,list) else False
    def sample(name,seconds,high,history=False):
        report.update(current_stage=name,measuring=False); save()
        time.sleep(5)
        stage=dict(name=name,seconds=seconds,high_cameras=high,history=history,samples=[])
        report["stages"].append(stage); report["measuring"]=True; save()
        begin=time.monotonic(); previous=None; previous_bytes=None; previous_at=None; previous_history=None
        first=driver.current_window_handle
        while time.monotonic()-begin<seconds:
            image=render_wait.until(pictures)
            if previous:
                assert all(a["hash"]!=b["hash"] for a,b in zip(previous,image)),"Painted live pixels stopped changing"
                assert all(a["generation"]==b["generation"] for a,b in zip(previous,image)),"Unexpected native restart"
            assert all(c["quality"]==("high" if c["id"] in high else "overview") for c in image)
            previous=image
            current=get("/api/status")
            assert current["sdk_login_calls"]==initial["sdk_login_calls"]==1
            assert current["viewer_sessions"]==1 and current["playback_sessions"]==int(history)
            assert current["active_media_feeds"]==1+int(history)
            assert current["sources_by_quality"]==dict(overview=len(online),high=len(high))
            assert current["occupied_source_slots"]==len(online)+len(high)+int(history)
            assert current["upgrade_failures"]==current["upgrade_refusals"]==0
            assert all(s["state"]=="live" and s["frame_age_seconds"] is not None and s["frame_age_seconds"]<5 for s in current["live_source_metrics"])
            now=time.monotonic(); media_bytes=driver.execute_script("return mediaFault.bytes")
            delivery=None if previous_bytes is None else round((media_bytes-previous_bytes)/(now-previous_at))
            previous_bytes,previous_at=media_bytes,now
            playback=None
            if history:
                driver.switch_to.window(history_tab)
                path=driver.execute_script("return checkOwnedSessions.find(p=>p.startsWith('/api/playback/'))")
                playback=get(path)
                assert playback["state"]=="playing",playback.get("error") or "History stopped"
                if previous_history is not None:assert playback["frames"]>previous_history,"History frames stopped advancing"
                previous_history=playback["frames"]
                driver.switch_to.window(first)
            stage["samples"].append(dict(seconds=round(now-begin,2),pictures=image,
                live_source_metrics=current["live_source_metrics"],media_bytes_per_second=delivery,
                playback=None if playback is None else {k:playback[k] for k in ("frames","position","generation","rate")}))
            save(); print(f'{name}: {now-begin:.0f}/{seconds}s',flush=True); time.sleep(5)
        stage["measured_seconds"]=round(time.monotonic()-begin,2)
        report["measuring"]=False; save()
        driver.save_screenshot(str(output/(name+".png")))
    try:
        driver.set_window_size(1600,1100)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",{"source":Path(__file__).with_name("browser_feed_fault.js").read_text()})
        driver.get(args.url); wait.until(pictures)
        first_tab=driver.current_window_handle
        sample("overview_before",20,[])
        selection(pair[:1]); sample("one_high_before",45,pair[:1])
        selection(pair); sample("two_high",args.dual_seconds,pair)
        if len(online)+3<=initial["source_limit"]:
            driver.switch_to.new_window("tab"); history_tab=driver.current_window_handle
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",{"source":Path(__file__).with_name("browser_feed_fault.js").read_text()})
            driver.get(args.url); element("#history-tab").click()
            Select(element("#history-camera")).select_by_value(pair[0])
            wait.until(lambda _:element("#history-recordings").get_attribute("data-state")=="ready")
            driver.execute_script("const s=document.getElementById('history-position');s.value=Math.max(0,Number(s.max)-3600);s.dispatchEvent(new Event('change',{bubbles:true}))")
            wait.until(lambda _:element("#history-player").get_attribute("data-state")=="playing" and element("#history-image").get_attribute("src"))
            driver.switch_to.window(first_tab); sample("two_high_and_history",30,pair,history=True)
            driver.switch_to.window(history_tab); element("#history-stop").click()
            wait.until(lambda _:get("/api/status")["playback_sessions"]==0)
            driver.close(); driver.switch_to.window(first_tab)
        selection(pair[:1]); sample("one_high_after",45,pair[:1])
        selection([]); sample("overview_after",20,[])
        element("#stop").click()
        wait.until(lambda _:all(get("/api/status")[k]==0 for k in ("viewer_sessions","playback_sessions","active_media_feeds","occupied_source_slots")))
        errors=[e for e in driver.get_log("browser") if e["level"]=="SEVERE" and "favicon.ico" not in e["message"]]
        assert not errors,str(errors)
        report.update(passed=True,final_status=get("/api/status"),browser_errors=errors); save()
    except BaseException as error:
        report["error"]=str(error); save()
        try:driver.save_screenshot(str(output/"failure.png"))
        except Exception:pass
        raise
    finally:
        report["measuring"]=False; save()
        for tab in driver.window_handles:
            try:
                driver.switch_to.window(tab)
                driver.execute_async_script("const done=arguments[0];Promise.all((window.checkOwnedSessions||[]).map(p=>fetch(p,{method:'DELETE'}).catch(()=>{}))).then(()=>done())")
            except Exception:pass
        driver.quit()


if __name__=="__main__":main()
