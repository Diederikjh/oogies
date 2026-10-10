"""Private owner settings, independent of SDK credential preparation."""

import ipaddress
import json
from pathlib import Path

from sdk_adapters import DEFAULT_SDK_ID, get_sdk_adapter

DEFAULT_CONFIG_FILE = Path(__file__).resolve().parents[1] / ".local/nvr-config.json"


def load_config(path=None):
    source = Path(path) if path is not None else DEFAULT_CONFIG_FILE
    try:
        value = json.loads(source.read_text())
    except json.JSONDecodeError:
        raise ValueError("recorder configuration must contain valid JSON") from None
    allowed = {"host", "sdk_port", "timezone", "sdk_profile", "max_live_sources", "lease_seconds", "camera_overrides"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("invalid or unknown recorder configuration fields")
    config = dict(sdk_port=8000, timezone="Africa/Johannesburg", sdk_profile=DEFAULT_SDK_ID,
                  max_live_sources=8, lease_seconds=90, camera_overrides={})
    config.update(value)
    if not isinstance(config.get("host"), str):
        raise ValueError("recorder IP is required")
    ipaddress.ip_address(config["host"])
    for name, lower, upper in (("sdk_port", 1, 65535), ("max_live_sources", 1, 16), ("lease_seconds", 10, 300)):
        if type(config[name]) is not int or not lower <= config[name] <= upper:
            raise ValueError(f"invalid {name}")
    if not isinstance(config["timezone"], str) or not config["timezone"] or any(ord(c) < 32 for c in config["timezone"]):
        raise ValueError("invalid recorder timezone")
    get_sdk_adapter(config["sdk_profile"])
    if not isinstance(config["camera_overrides"], dict):
        raise ValueError("camera_overrides must be an object")
    for channel, override in config["camera_overrides"].items():
        if not channel.isdecimal() or not 1 <= int(channel) <= 512 or not isinstance(override, dict):
            raise ValueError("invalid camera override")
        if set(override) - {"name", "aspect_ratio", "enabled"}:
            raise ValueError("unknown camera override field")
        if "name" in override and (not isinstance(override["name"], str) or not 1 <= len(override["name"]) <= 100):
            raise ValueError("invalid camera name")
        if override.get("aspect_ratio", "16:9") not in ("16:9", "4:3", "original"):
            raise ValueError("invalid display aspect")
        if "enabled" in override and type(override["enabled"]) is not bool:
            raise ValueError("invalid camera enabled flag")
    return config
