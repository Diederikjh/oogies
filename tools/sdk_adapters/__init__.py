"""Select the current SDK implementation at one Python boundary."""

from .hcnet_61948 import HcNetSdk61948

DEFAULT_SDK_ID = HcNetSdk61948.sdk_id


def get_sdk_adapter(sdk_id=DEFAULT_SDK_ID):
    """Return a known adapter; add selection here when a second SDK is verified."""
    if sdk_id != DEFAULT_SDK_ID:
        raise ValueError("unsupported SDK adapter")
    return HcNetSdk61948()
