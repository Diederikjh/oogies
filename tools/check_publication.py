#!/usr/bin/env python3
"""Check publishable files/history; findings never include matched values."""

import argparse
import base64
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IPV4 = re.compile(rb'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
IPV6 = re.compile(rb'(?<![\w])(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(?![\w])')
HOME = re.compile(rb'/home/([\w.-]+)')
PRIVATE_RANGES = [ipaddress.ip_network((number, bits)) for number, bits in
                  ((0x0a000000, 8), (0xac100000, 12), (0xc0a80000, 16))]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def private_ipv4(value):
    try:
        address = ipaddress.ip_address(value.decode())
    except ValueError:
        return False
    return any(address in network for network in PRIVATE_RANGES)


def private_ipv6(value):
    try:
        address = ipaddress.IPv6Address(value.decode())
    except ValueError:
        return False
    return int(address) >> 121 == 0x7e or int(address) >> 118 in (0x3fa, 0x3fb)


def known_patterns(root=ROOT):
    patterns = {}
    path = root / '.local/nvr-credentials.json'
    if path.is_file():
        credentials = json.loads(path.read_text())
        for field in ('password', 'verification_code'):
            value = credentials.get(field, '')
            if not isinstance(value, str) or not value:
                continue
            values = {value}
            if field == 'password': values.add(value[:16])
            for item in values:
                for variant in (item.encode(), item.encode('utf-16-le'), quote(item, safe='').encode(),
                                base64.b64encode(item.encode()), json.dumps(item)[1:-1].encode()):
                    if len(variant) >= 5: patterns[variant] = field
        username, password = credentials.get('username',''), credentials.get('password','')
        if username and password:
            for item in (password, password[:16]):
                patterns[base64.b64encode(f'{username}:{item}'.encode())] = 'basic-auth'
    config = root / '.local/nvr-config.json'
    if config.is_file():
        host = json.loads(config.read_text()).get('host')
        if isinstance(host, str) and host:
            patterns[host.encode()] = 'configured-recorder-address'
            patterns[host.encode('utf-16-le')] = 'configured-recorder-address'
    return patterns


def inspect_bytes(data, patterns):
    findings = []
    for pattern, field in patterns.items():
        if pattern in data:
            findings.append({'kind':'known-private-value', 'field':field})
    if b'\x00' not in data:
        for number, line in enumerate(data.splitlines(), 1):
            if any(private_ipv4(match.group()) for match in IPV4.finditer(line)) or any(private_ipv6(match.group()) for match in IPV6.finditer(line)):
                findings.append({'kind':'private-network-address', 'line':number})
            if any(match[1] not in (b'your-user', b'runner') for match in HOME.finditer(line)):
                findings.append({'kind':'personal-home-path', 'line':number})
    return findings


def file_findings(path, root, patterns):
    relative = path.relative_to(root).as_posix()
    private_names = {'.local', '.aws', '.codex', '.agents'}
    if private_names.intersection(path.relative_to(root).parts) or path.name in ('nvr-credentials.json','nvr-config.json'):
        return [{'path':relative, 'kind':'private-file'}]
    findings = []
    if zipfile.is_zipfile(path):
        # Vendor samples may contain example addresses; check for this owner's
        # exact private values in all ZIP entries, including binary strings.
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir(): continue
                data = archive.read(entry)
                for pattern, field in patterns.items():
                    if pattern in data:
                        findings.append({'path':relative, 'kind':'archive-private-value', 'field':field})
    else:
        findings.extend(dict(path=relative, **finding) for finding in inspect_bytes(path.read_bytes(), patterns))
    return findings


def audit(history=False, push_updates=None):
    patterns = known_patterns()
    findings = []
    names = set(git('ls-files','--cached','--others','--exclude-standard','-z').split(b'\x00')) - {b''}
    for name in sorted(names):
        path = ROOT / name.decode()
        if path.is_file(): findings.extend(file_findings(path, ROOT, patterns))
    if history:
        revisions = ['HEAD', '--branches', '--tags']
        if push_updates:
            for row in Path(push_updates).read_text().splitlines():
                local_ref, local_oid, _, _ = row.split()
                if set(local_oid) == {'0'}:
                    continue  # Deleting a ref uploads no objects.
                if not local_ref.startswith(('refs/heads/','refs/tags/')):
                    findings.append({'kind':'non-public-reference', 'path':'(only branches and tags may be pushed)'})
                else:
                    revisions.append(local_oid)
        objects = {}
        for row in git('rev-list','--objects',*revisions).decode().splitlines():
            oid, _, name = row.partition(' ')
            objects[oid] = name
        process = subprocess.Popen(['git','cat-file','--batch'], cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for oid, name in objects.items():
                process.stdin.write((oid+'\n').encode()); process.stdin.flush()
                header = process.stdout.readline().split()
                data = process.stdout.read(int(header[2])); process.stdout.read(1)
                # Commit metadata/messages can expose an address too.
                if header[1] in (b'blob', b'commit'):
                    for finding in inspect_bytes(data, patterns):
                        findings.append(dict(path=name or '(commit metadata)', object=oid, **finding))
                if header[1] == b'blob' and name and any(part in {'.local','.aws','.codex','.agents'} for part in Path(name).parts):
                    findings.append(dict(path=name, object=oid, kind='private-file-history'))
        finally:
            process.stdin.close(); process.stdout.close(); process.wait()
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='Also scan branch/tag history intended for publication')
    parser.add_argument('--push-updates', help='Git pre-push ref updates; reject non-branch/tag refs')
    args = parser.parse_args()
    try:
        findings = audit(args.history, args.push_updates)
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile):
        print('Publication scan could not complete; check Git and private-file format.', file=sys.stderr)
        return 2
    if findings:
        print(json.dumps({'findings':findings},indent=2))
        return 1
    print('Publication checks passed: no private addresses, home paths or known private values found.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
