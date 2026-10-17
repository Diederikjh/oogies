#!/usr/bin/env python3
"""Temporarily test two main streams on the local viewer, then restore config.

Restarts cam-browser-viewer; live tabs will need Resume afterwards. Refuses
active playback/exports. No SDK or credentials enter the diagnostic browser.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from urllib.request import urlopen

from run_live_reliability_check import ROOT, SERVICE, status


def machine():
    fields=Path('/proc/stat').read_text().splitlines()[0].split()[1:]
    ticks=list(map(int,fields[:8]))
    memory={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','MemTotal:'))}
    pressure=None
    pressure_path=Path('/proc/pressure/memory')
    if pressure_path.exists():
        full=next((line for line in pressure_path.read_text().splitlines() if line.startswith('full ')),None)
        if full:pressure=float(dict(field.split('=') for field in full.split()[1:])['avg10'])
    return dict(at=time.monotonic(),total=sum(ticks),idle=ticks[3]+ticks[4],
                available_memory_bytes=memory['MemAvailable'],memory_full_avg10=pressure)


def container_resources(name):
    result=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}',SERVICE,name],
        capture_output=True,text=True,timeout=10)
    # Docker can reject the entire multi-container request while the diagnostic
    # container is still being created (or has just exited). The service exists
    # throughout the measured phases; retain its statistics during that race.
    if result.returncode and not result.stdout.strip():
        result=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}',SERVICE],
            capture_output=True,text=True,check=True,timeout=10)
    values={}
    for line in result.stdout.splitlines():
        row=json.loads(line)
        values[row['Name']]=dict(cpu_percent=float(row['CPUPerc'].rstrip('%')),
            memory_percent=float(row['MemPerc'].rstrip('%')),memory=row['MemUsage'],
            pids=int(row['PIDs']),network=row['NetIO'])
    if SERVICE not in values:raise RuntimeError('Viewer resource statistics unavailable')
    return values


def phase(output):
    try:
        report=json.loads((output/'capacity-check.json').read_text())
        return report.get('current_stage','starting') if report.get('measuring') else 'transition'
    except FileNotFoundError:return 'starting'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dual-seconds',type=int,default=180)
    parser.add_argument('--cameras',nargs=2)
    args=parser.parse_args()
    if not 60<=args.dual_seconds<=600:parser.error('dual duration must be 60-600 seconds')
    initial=status()
    if initial['playback_sessions'] or initial['active_exports']:
        parser.error('wait for historical playback/exports to finish before reloading the viewer')
    os.umask(0o077)
    output=ROOT/'.local/live-capacity-check'/time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True,mode=0o700)
    browser_output=output/'browser'; browser_output.mkdir(mode=0o700)
    config_path=ROOT/'.local/nvr-config.json'
    original=config_path.read_bytes(); original_mode=config_path.stat().st_mode & 0o777
    config=json.loads(original); original_limit=config.get('max_high_quality_sources',1)
    (output/'nvr-config.original.json').write_bytes(original)
    config['max_high_quality_sources']=2
    temporary=(json.dumps(config,indent=2)+'\n').encode()
    name='oogies-capacity-'+uuid.uuid4().hex[:8]
    report=dict(passed=False,original_high_limit=original_limit,experiment_high_limit=2,resource_samples=[],orchestrator_pid=os.getpid())
    changed=False; service_stopped=False; process=None; hot={}; pressure_since=None
    def save(): (output/'resource-check.json').write_text(json.dumps(report,indent=2)+'\n')
    def launch(*arguments):
        subprocess.run([sys.executable,str(ROOT/'tools/run_browser_viewer.py'),*arguments],check=True,timeout=120)
    def http_ready():
        until=time.monotonic()+45
        while time.monotonic()<until:
            try:return status()
            except OSError:time.sleep(.25)
        raise RuntimeError('Viewer HTTP startup timed out')
    def interrupted(*_):raise KeyboardInterrupt('Capacity experiment interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    started=time.monotonic()
    try:
        launch('--stop'); service_stopped=True
        if config_path.read_bytes()!=original:raise RuntimeError('Owner config changed before experiment; left untouched')
        config_path.write_bytes(temporary); changed=True
        launch(); service_stopped=False; http_ready()
        # One explicit initialization, never a login retry loop.
        with urlopen('http://localhost:8088/api/cameras',timeout=40) as response:inventory=json.load(response)
        online=[c for c in inventory['cameras'] if c['online'] is not False]
        if len(online)<2 or len(online)+2>status()['source_limit']:
            raise RuntimeError('Need two online cameras and room for their main streams alongside the grid')
        if status()['sdk_login_calls']!=1:raise RuntimeError('Expected exactly one SDK login')
        report['online_cameras']=[c['id'] for c in online]
        command=['docker','run','--rm','--init','--name',name,'--network','container:'+SERVICE,
            '--read-only','--user',f'{os.getuid()}:{os.getgid()}','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--cpus=2','--memory=2g','--memory-swap=2g','--pids-limit=512',
            '--tmpfs','/tmp:rw,exec,nosuid,size=256m','--env','XDG_CONFIG_HOME=/tmp/config',
            '--env','XDG_CACHE_HOME=/tmp/cache','--mount',f'type=bind,source={ROOT}/tools,target=/support,readonly',
            '--mount',f'type=bind,source={browser_output},target=/output',
            'cam-hik-sdk-browser:local','python3','/support/check_live_capacity.py',
            '--output','/output','--dual-seconds',str(args.dual_seconds)]
        if args.cameras:command.extend(['--cameras',*args.cameras])
        report['initial_machine']=machine(); previous_machine=report['initial_machine']
        with (output/'browser.log').open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+args.dual_seconds+360
            while process.poll() is None:
                if time.monotonic()>deadline:raise RuntimeError('Capacity experiment deadline exceeded')
                before=phase(browser_output); resources=container_resources(name); current_machine=machine(); current=status()
                after=phase(browser_output)
                elapsed=current_machine['total']-previous_machine['total']
                host_cpu=None if not elapsed else round(100*(1-(current_machine['idle']-previous_machine['idle'])/elapsed),2)
                previous_machine=current_machine
                sample=dict(seconds=round(time.monotonic()-started,2),stage=after if before==after else 'transition',
                    service=resources[SERVICE],browser=resources.get(name),host_cpu_percent=host_cpu,
                    host_available_memory_bytes=current_machine['available_memory_bytes'],host_memory_full_avg10=current_machine['memory_full_avg10'],
                    occupied_source_slots=current['occupied_source_slots'])
                report['resource_samples'].append(sample); save()
                for key,value in resources.items():
                    if value['memory_percent']>75 or value['pids']>450:raise RuntimeError('Container resource headroom exhausted')
                    hot[key]=(hot.get(key) or time.monotonic()) if value['cpu_percent']>180 else None
                    if hot[key] and time.monotonic()-hot[key]>30:raise RuntimeError('Sustained container CPU pressure')
                if current_machine['available_memory_bytes']<1024**3:raise RuntimeError('Host available memory below 1 GiB')
                pressure_since=(pressure_since or time.monotonic()) if (current_machine['memory_full_avg10'] or 0)>1 else None
                if pressure_since and time.monotonic()-pressure_since>10:raise RuntimeError('Host memory pressure')
                if current['sdk_login_calls']!=1:raise RuntimeError('Unexpected SDK login')
                if current['sources_by_quality']['high']>2 or current['occupied_source_slots']>current['source_limit']:
                    raise RuntimeError('Stream budget exceeded')
                time.sleep(5)
            if process.returncode:raise RuntimeError('Browser capacity check failed; inspect private browser.log')
        browser=json.loads((browser_output/'capacity-check.json').read_text())
        if not browser['passed']:raise RuntimeError('Browser capacity report did not pass')
        final=status()
        if any(final[k] for k in ('viewer_sessions','playback_sessions','active_media_feeds','occupied_source_slots')):
            raise RuntimeError('Experiment resources did not return to idle')
        report.update(passed=True,experiment_final_status=final,total_seconds=round(time.monotonic()-started,2))
    except BaseException as error:
        report['error']=str(error)
        raise
    finally:
        try:
            if process is not None and process.poll() is None:
                try:
                    subprocess.run(['docker','stop','--timeout','15',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=25)
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    report['browser_cleanup_error']='Diagnostic stop timed out; removing only the check-owned container'
                    subprocess.run(['docker','rm','--force',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
                    process.wait(timeout=5)
            if changed:
                # Restore the file even if the subsequent service stop fails.
                if config_path.read_bytes()!=temporary:
                    report['restoration_error']='Config changed during experiment; left untouched'
                else:
                    config_path.write_bytes(original); config_path.chmod(original_mode)
                    report['config_restored_exactly']=True
                launch('--stop'); service_stopped=True
            if service_stopped:
                launch(); service_stopped=False
                restored=http_ready()
                report['restored_high_limit']=restored['high_quality_limit']
                report['service_restarted']=True
        finally:
            save(); print('Private evidence: '+str(output.relative_to(ROOT)),flush=True)
    if not report.get('config_restored_exactly'):raise RuntimeError('Config restoration requires review; see private report')
    print(json.dumps(dict(passed=report['passed'],original_high_limit=original_limit,
        restored_high_limit=report['restored_high_limit'],total_seconds=report['total_seconds'])))


if __name__=='__main__':main()
