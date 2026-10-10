#!/usr/bin/env python3
"""Read-only recorder inspection and bounded RTSP decoding; redact credentials."""

import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from credentials import load_credentials

ROOT = Path(__file__).resolve().parents[1]
HOST = "192.0.2.10"


class BoundedDigestAuthHandler(urllib.request.HTTPDigestAuthHandler):
    """Submit one Digest response per challenge; do not retry rejected logins."""

    def http_error_auth_reqed(self, auth_header, host, req, headers):
        if self.retried >= 1:
            return None
        return super().http_error_auth_reqed(auth_header, host, req, headers)


def tag(element):
    return element.tag.rsplit("}", 1)[-1]


def redact(text, credentials):
    text = re.sub(r"rtsp://[^\s]+", "rtsp://[redacted]", text)
    for key in ("password", "verification_code", "username"):
        value = credentials.get(key, "")
        if value:
            text = text.replace(urllib.parse.quote(value, safe=""), "[redacted]")
            text = text.replace(value, "[redacted]")
    return text


def inspect(credentials):
    base = f"http://{HOST}"
    manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(None, base, credentials["username"], credentials["password"])
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), BoundedDigestAuthHandler(manager)
    )
    results = []
    for path in ("/ISAPI/System/deviceInfo", "/ISAPI/Streaming/channels"):
        result = {"path": path}
        try:
            with opener.open(base + path, timeout=8) as response:
                result["status"] = response.status
                document = ET.fromstring(response.read(2_000_000))
            if path.endswith("deviceInfo"):
                allowed = {"model", "firmwareVersion", "firmwareReleasedDate", "deviceType"}
                result["device"] = {
                    tag(element): element.text
                    for element in document.iter() if tag(element) in allowed
                }
            else:
                allowed = {
                    "id", "enabled", "videoInputChannelID", "videoCodecType",
                    "videoResolutionWidth", "videoResolutionHeight", "maxFrameRate",
                    "GovLength", "H264Profile", "H265Profile", "fixedQuality",
                    "videoQualityControlType", "vbrUpperCap", "constantBitRate",
                    "audioCompressionType", "streamingTransport",
                }
                result["channels"] = []
                for channel in document.iter():
                    if tag(channel) != "StreamingChannel":
                        continue
                    fields = {}
                    for element in channel.iter():
                        if tag(element) in allowed:
                            # Preserve nesting to distinguish video/audio enablement.
                            if tag(element) != "enabled":
                                fields[tag(element)] = element.text
                        if tag(element) == "SmartCodec":
                            fields["SmartCodec"] = {
                                tag(child): child.text for child in element
                                if tag(child) == "enabled"
                            }
                    result["channels"].append(fields)
        except urllib.error.HTTPError as error:
            result["status"] = error.code
        except (OSError, urllib.error.URLError, ET.ParseError) as error:
            result["error"] = type(error).__name__
        results.append(result)
        if result.get("status") in (401, 403):
            break
    return results


def stream_url(credentials, channel, port=554):
    user = urllib.parse.quote(credentials["username"], safe="")
    password = urllib.parse.quote(credentials["password"], safe="")
    return f"rtsp://{user}:{password}@{HOST}:{port}/Streaming/channels/{channel}"


def media_test(credentials, channel, seconds, port=554, capture=False):
    url = stream_url(credentials, channel, port)
    result = {"channel": channel, "port": port, "transport": "RTSP/TCP", "verification_code_used": False}
    common = ["-rtsp_transport", "tcp", "-timeout", "8000000"]
    if seconds == 0:
        command = ["ffprobe", "-v", "error", *common, "-i", url,
                   "-show_streams", "-of", "json"]
        limit = 25
    else:
        command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
                   *common, "-i", url, "-t", str(seconds), "-map", "0:v:0",
                   "-an", "-sn", "-dn", "-progress", "pipe:1", "-nostats",
                   "-threads", "2", "-f", "null", "-"]
        if capture:
            capture_path = ROOT / ".local/rtsp-view.mkv"
            if capture_path.exists():
                raise ValueError("capture already exists; use a fresh output directory")
            command.extend(["-t", str(seconds), "-map", "0:v:0", "-an", "-sn", "-dn",
                            "-c:v", "copy", "-f", "matroska", str(capture_path)])
            result["capture_file"] = capture_path.name
        limit = seconds + 25
    start = time.monotonic()
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=limit)
        result["returncode"] = process.returncode
        result["elapsed_seconds"] = round(time.monotonic() - start, 2)
        result["diagnostics"] = redact(process.stderr, credentials)[-8000:]
        if seconds == 0 and process.returncode == 0:
            allowed = {"index", "codec_name", "codec_type", "profile", "width", "height",
                       "pix_fmt", "level", "has_b_frames", "r_frame_rate", "avg_frame_rate",
                       "sample_rate", "channels", "bit_rate"}
            result["streams"] = [
                {key: value for key, value in stream.items() if key in allowed}
                for stream in json.loads(process.stdout).get("streams", [])
            ]
        elif seconds:
            progress = {}
            for line in process.stdout.splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    progress[key] = value
            result["requested_seconds"] = seconds
            result["progress"] = progress
    except subprocess.TimeoutExpired as error:
        result["error"] = "overall timeout"
        result["elapsed_seconds"] = round(time.monotonic() - start, 2)
        output = error.stderr or b""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        result["diagnostics"] = redact(output, credentials)[-8000:]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "probe", "decode"))
    parser.add_argument("--channel", type=int, default=102)
    parser.add_argument("--port", type=int, default=554)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--capture", action="store_true", help="Save encoded video during the same decode session")
    parser.add_argument("--password-first-16", action="store_true",
                        help="Compatibility flag: the shared loader now always limits the login password to 16 characters")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120 or not 101 <= args.channel <= 9999 or not 1 <= args.port <= 65535:
        parser.error("seconds must be 1–120, channel 101–9999 and port 1–65535")
    try:
        credentials = load_credentials()
    except ValueError as error:
        parser.error(str(error))
    if args.mode == "inspect":
        result = {"inspection": inspect(credentials)}
    else:
        result = media_test(credentials, args.channel, args.seconds if args.mode == "decode" else 0, args.port, args.capture)
        result["password_first_16"] = True
        if args.capture:
            capture_path = ROOT / ".local/rtsp-view.mkv"
            result["capture_created"] = capture_path.is_file()
            if capture_path.is_file():
                capture_path.chmod(0o600)
                result["capture_bytes"] = capture_path.stat().st_size
    result["timestamp_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    output = json.dumps(result, indent=2)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / f".local/{args.mode}-{args.channel}-{args.port}-{stamp}.json"
    output_path.write_text(output + "\n")
    output_path.chmod(0o600)
    print(output)


if __name__ == "__main__":
    main()
