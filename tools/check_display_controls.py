#!/usr/bin/env python3
"""Check display settings and expansion in Docker Chromium without a recorder."""

from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import threading
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from grid_server import Handler
from live_sessions import LiveSessions


def main():
    output = Path('/output')
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=352x288:rate=1','-frames:v','1','-threads','1','/tmp/test-frame.jpg'],check=True)
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=352x288:rate=5','-t','2','-threads','1','-pix_fmt','yuv420p','-c:v','libx264','-movflags','+faststart','/tmp/test-recording.mp4'],check=True)
    frame = Path('/tmp/test-frame.jpg').read_bytes()
    class FakeWorker:
        def __init__(self):
            self.condition = threading.Condition(threading.RLock())
            self.cameras = {
                'camera-1':dict(id='camera-1', channel=1, name='Driveway', online=True, aspect_ratio='16:9', live_qualities=['overview']),
                'camera-2':dict(id='camera-2', channel=2, name='Side door', online=False, aspect_ratio='16:9', live_qualities=['overview'])}
            self.sources = {}
            self.state, self.error = 'ready', None
            self.adapter = SimpleNamespace(sdk_id='ui-fixture')
            self.login_calls, self.tested_capacity = 0, 1
            self.started, self.stopped = [], []
        def ensure_ready(self): pass
        def start_source(self, key):
            self.started.append(key)
            self.sources[key] = dict(state='live', frame=frame, sequence=1, generation=len(self.started),
                width=352, height=288, received=1, last_frame=time.monotonic(),
                last_frame_received_at=datetime.now(timezone.utc).isoformat())
        def stop_source(self, key):
            self.stopped.append(key)
            self.sources[key].update(state='stopped', frame=None)

    worker=FakeWorker(); sessions=LiveSessions(worker)
    server=ThreadingHTTPServer(('127.0.0.1',0), Handler); server.daemon_threads=True
    server.allowed_hosts={f'127.0.0.1:{server.server_port}'}
    server.worker, server.sessions, server.feeds=worker, sessions, set()
    server.web, server.recording = Path('/web'), Path('/tmp/test-recording.mp4')
    server.recording_info={}
    threading.Thread(target=server.serve_forever,daemon=True).start()
    options=webdriver.ChromeOptions()
    for flag in ('--headless','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-background-networking','--disable-sync','--no-first-run','--user-data-dir=/tmp/display-controls-browser'):
        options.add_argument(flag)
    options.set_capability('goog:loggingPrefs',{'browser':'ALL'})
    driver=webdriver.Chrome(options=options); wait=WebDriverWait(driver,10)
    checks=[]
    try:
        driver.set_window_size(1280,960)
        driver.get(f'http://127.0.0.1:{server.server_port}/')
        image='.camera-tile[data-camera-id="camera-1"] img'
        view='.camera-tile[data-camera-id="camera-1"] .camera-view'
        def image_ready(): return driver.execute_script('return document.querySelector(arguments[0])?.naturalWidth > 0', image)
        def ratio(): return driver.execute_script('const r=document.querySelector(arguments[0]).getBoundingClientRect();return r.width/r.height;', image)
        def expanded(): return driver.find_element(By.CSS_SELECTOR,view).get_attribute('aria-expanded')=='true'
        wait.until(lambda _:image_ready())
        assert not driver.find_elements(By.CSS_SELECTOR,'#live-panel select, #recording-panel select')
        checks.append('view controls contain no aspect selectors')
        driver.find_element(By.CSS_SELECTOR,image).click(); wait.until(lambda _:expanded())
        driver.find_element(By.CSS_SELECTOR,image).click(); wait.until(lambda _:not expanded())
        driver.find_element(By.CSS_SELECTOR,view).send_keys(Keys.ENTER); wait.until(lambda _:expanded())
        driver.find_element(By.CSS_SELECTOR,view).send_keys(Keys.SPACE); wait.until(lambda _:not expanded())
        assert worker.started==['camera-1']
        checks.append('picture click and keyboard toggle without new source')
        driver.find_element(By.ID,'settings-open').click()
        wait.until(lambda _:driver.execute_script('return document.getElementById("display-settings").open'))
        assert len(driver.find_elements(By.CSS_SELECTOR,'#aspect-settings select'))==2
        assert driver.execute_script('return document.activeElement.id')=='settings-close'
        select='#aspect-settings select[data-camera-id="camera-1"]'
        Select(driver.find_element(By.CSS_SELECTOR,select)).select_by_value('4:3')
        driver.find_element(By.ID,'settings-close').click()
        wait.until(lambda _:abs(ratio()-4/3)<0.01)
        assert driver.execute_script('return document.activeElement.id')=='settings-open'
        checks.append('settings apply 4:3 and modal restores focus')
        driver.refresh(); wait.until(lambda _:image_ready() and abs(ratio()-4/3)<0.01)
        driver.find_element(By.ID,'settings-open').click()
        assert Select(driver.find_element(By.CSS_SELECTOR,select)).first_selected_option.get_attribute('value')=='4:3'
        assert Select(driver.find_element(By.CSS_SELECTOR,'#aspect-settings select[data-camera-id="camera-2"]')).first_selected_option.get_attribute('value')=='16:9'
        checks.append('per-camera preference survives refresh')
        Select(driver.find_element(By.CSS_SELECTOR,select)).select_by_value('original')
        driver.find_element(By.ID,'settings-close').send_keys(Keys.ESCAPE)
        wait.until(lambda _:not driver.execute_script('return document.getElementById("display-settings").open'))
        wait.until(lambda _:abs(ratio()-352/288)<0.01)
        checks.append('Original preserves raster and Escape closes settings')
        driver.set_window_size(390,844)
        driver.find_element(By.ID,'settings-open').click()
        assert driver.execute_script('const r=document.querySelector("dialog").getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;')
        Select(driver.find_element(By.CSS_SELECTOR,select)).select_by_value('16:9')
        driver.save_screenshot('/output/settings-mobile.png')
        driver.find_element(By.ID,'settings-close').click()
        driver.find_element(By.CSS_SELECTOR,image).click(); wait.until(lambda _:expanded())
        wait.until(lambda _:abs(ratio()-16/9)<0.01)
        assert driver.execute_script('const i=document.querySelector(arguments[0]).getBoundingClientRect(),v=document.querySelector(arguments[1]).getBoundingClientRect();return i.left>=v.left && i.right<=v.right+1 && i.top>=v.top && i.bottom<=v.bottom+1;',image,view)
        driver.save_screenshot('/output/expanded-mobile.png')
        checks.append('mobile settings and expanded picture fit viewport')
        driver.find_element(By.CSS_SELECTOR,image).click()
        driver.find_element(By.ID,'recording-tab').click()
        wait.until(lambda _:not driver.find_element(By.ID,'recording-panel').get_attribute('hidden'))
        driver.find_element(By.ID,'settings-open').click()
        Select(driver.find_element(By.CSS_SELECTOR,select)).select_by_value('4:3')
        driver.find_element(By.ID,'settings-close').click()
        assert driver.execute_script('const r=document.getElementById("recording").getBoundingClientRect();return Math.abs(r.width/r.height-4/3)<0.01;')
        checks.append('same camera preference applies to recorded view')
        errors=[e for e in driver.get_log('browser') if e['level']=='SEVERE' and 'favicon.ico' not in e['message']]
        assert not errors, errors
        report = {'checks':checks,'sdk_login_calls':worker.login_calls,'browser_errors':errors}
        Path('/output/display-controls.json').write_text(json.dumps(report,indent=2)+'\n')
        for path in Path('/output').iterdir():
            if path.is_file(): path.chmod(0o600)
        print(json.dumps(report,indent=2))
    finally:
        driver.quit(); sessions.close(); server.shutdown(); server.server_close()


if __name__ == "__main__":
    main()
