#!/usr/bin/env python3
"""One web-UI-compatible login, followed by read-only device inspection."""

import hashlib
import http.cookiejar
import json
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from probe_authenticated import HOST, ROOT, tag
from sdk_adapters import get_sdk_adapter


def values(document):
    return {tag(element): element.text or "" for element in document.iter()}


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main():
    credentials = get_sdk_adapter().load_credentials()
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookies)
    )
    base = f"http://{HOST}"
    report = {"method": "web session login", "verification_code_used": False,
              "password_first_16": True}
    query = urllib.parse.urlencode({
        "username": credentials["username"], "random": secrets.randbelow(90000000) + 10000000
    })
    try:
        with opener.open(base + "/ISAPI/Security/sessionLogin/capabilities?" + query, timeout=8) as response:
            capabilities = values(ET.fromstring(response.read(100000)))
        iterations = int(capabilities["iterations"])
        if not 2 <= iterations <= 100000:
            raise ValueError("unsupported iteration count")
        if capabilities.get("isIrreversible") == "true":
            encoded = digest(credentials["username"] + capabilities["salt"] + credentials["password"])
            encoded = digest(encoded + capabilities["challenge"])
            start = 2
        else:
            encoded = digest(credentials["password"]) + capabilities["challenge"]
            start = 1
        for _ in range(start, iterations):
            encoded = digest(encoded)
        login = ET.Element("SessionLogin")
        for key, value in (
            ("userName", credentials["username"]), ("password", encoded),
            ("sessionID", capabilities["sessionID"]),
            ("isSessionIDValidLongTerm", capabilities.get("isSessionIDValidLongTerm", "false")),
            ("sessionIDVersion", capabilities.get("sessionIDVersion", "2")),
        ):
            ET.SubElement(login, key).text = value
        if capabilities.get("isSupportSessionTag") == "true":
            ET.SubElement(login, "isNeedSessionTag").text = "true"
        request = urllib.request.Request(
            base + f"/ISAPI/Security/sessionLogin?timeStamp={int(time.time() * 1000)}",
            data=ET.tostring(login), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        )
        with opener.open(request, timeout=8) as response:
            login_result = values(ET.fromstring(response.read(100000)))
            report["login_http_status"] = response.status
        allowed = {"statusValue", "statusCode", "statusString", "subStatusCode", "lockStatus", "retryLoginTime", "unlockTime"}
        report["login_result"] = {key: value for key, value in login_result.items() if key in allowed}
        report["session_cookie_present"] = bool(list(cookies))
        report["inspection"] = []
        for path in ("/ISAPI/System/deviceInfo", "/ISAPI/Streaming/channels"):
            item = {"path": path}
            with opener.open(base + path, timeout=8) as response:
                document = ET.fromstring(response.read(2_000_000))
                item["status"] = response.status
            if path.endswith("deviceInfo"):
                permitted = {"model", "firmwareVersion", "firmwareReleasedDate", "deviceType"}
                item["device"] = {tag(e): e.text for e in document.iter() if tag(e) in permitted}
            else:
                permitted = {"id", "videoCodecType", "videoResolutionWidth", "videoResolutionHeight", "maxFrameRate", "H264Profile", "H265Profile", "GovLength", "audioCompressionType"}
                item["channels"] = [
                    {tag(e): e.text for e in channel.iter() if tag(e) in permitted}
                    for channel in document.iter() if tag(channel) == "StreamingChannel"
                ]
            report["inspection"].append(item)
    except urllib.error.HTTPError as error:
        report["http_error"] = error.code
        try:
            fields = values(ET.fromstring(error.read(100000)))
            permitted = {"statusValue", "statusCode", "statusString", "subStatusCode", "lockStatus", "retryLoginTime", "unlockTime"}
            report["error_details"] = {key: value for key, value in fields.items() if key in permitted}
        except ET.ParseError:
            pass
    except (OSError, urllib.error.URLError, ET.ParseError, ValueError, KeyError) as error:
        report["error"] = type(error).__name__
    output = json.dumps(report, indent=2)
    path = ROOT / ".local/web-session-probe.json"
    path.write_text(output + "\n")
    path.chmod(0o600)
    print(output)


if __name__ == "__main__":
    main()
