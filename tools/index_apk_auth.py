#!/usr/bin/env python3
"""Find candidate SDK-login call sites in the supplied APK, without executing it.

Code-unit scanning identifies candidates, not a complete Dalvik disassembly.
Verify each candidate against decompiled instructions before drawing conclusions.
"""

import json
from pathlib import Path
import re
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APK = Path('/home/your-user/Downloads/Hik-Connect.apk')
METHODS = {'NET_DVR_Login_V30', 'NET_DVR_Login_V40'}


def uleb(data, offset):
    result = shift = 0
    for _ in range(5):
        value = data[offset]
        offset += 1
        result |= (value & 127) << shift
        if value < 128:
            return result, offset
        shift += 7
    raise ValueError('oversized ULEB128')


def inspect(data, name):
    def table(offset):
        return struct.unpack_from('<II', data, offset)
    string_count, string_offset = table(56)
    type_count, type_offset = table(64)
    method_count, method_offset = table(88)
    class_count, class_offset = table(96)
    strings = []
    for i in range(string_count):
        offset = struct.unpack_from('<I', data, string_offset + 4*i)[0]
        _, offset = uleb(data, offset)
        strings.append(data[offset:data.index(b'\0', offset)].decode('utf-8', 'replace'))
    types = [strings[struct.unpack_from('<I', data, type_offset+4*i)[0]]
             for i in range(type_count)]
    methods = []
    for i in range(method_count):
        owner, _, method = struct.unpack_from('<HHI', data, method_offset + 8*i)
        methods.append((types[owner], strings[method]))
    targets = {i: method for i, method in enumerate(methods) if method[1] in METHODS}
    if not targets:
        return []
    found = []
    for i in range(class_count):
        offset = struct.unpack_from('<I', data, class_offset + 32*i + 24)[0]
        if not offset:
            continue
        counts = []
        for _ in range(4):
            value, offset = uleb(data, offset)
            counts.append(value)
        for _ in range(counts[0] + counts[1]):
            _, offset = uleb(data, offset)
            _, offset = uleb(data, offset)
        for count in counts[2:]:
            method_index = 0
            for _ in range(count):
                delta, offset = uleb(data, offset)
                method_index += delta
                _, offset = uleb(data, offset)
                code_offset, offset = uleb(data, offset)
                if not code_offset:
                    continue
                size = struct.unpack_from('<I', data, code_offset + 12)[0]
                instructions = data[code_offset+16:code_offset+16+size*2]
                for pos in range(0, len(instructions)-5, 2):
                    if instructions[pos] not in (0x6e, 0x6f, 0x70, 0x71, 0x72, 0x74, 0x75, 0x76, 0x77, 0x78):
                        continue
                    callee = struct.unpack_from('<H', instructions, pos+2)[0]
                    if callee in targets:
                        found.append({'dex': name, 'caller': methods[method_index],
                                      'callee': targets[callee], 'code_unit': pos//2})
    return found


def main():
    output = ROOT / '.local/apk-auth'
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    found = []
    with zipfile.ZipFile(APK) as archive:
        for name in archive.namelist():
            if not re.fullmatch(r'classes\d*\.dex', name):
                continue
            data = archive.read(name)
            candidates = inspect(data, name)
            if candidates:
                (output / name).write_bytes(data)
                found.extend(candidates)
    (output / 'login-call-candidates.json').write_text(json.dumps(found, indent=2)+'\n')
    print(json.dumps(found, indent=2))


if __name__ == '__main__':
    main()
