"""Python integration for the currently verified Linux64 HCNetSDK bundle.

This is one concrete implementation, not a universal recorder interface.
The 16-character login policy belongs here under the current design assumption;
its cause has not been established independently across SDK/device versions.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess

from credentials import load_credentials


@dataclass
class NativeInvocation:
    """A prepared native launch; credentials travel only through private stdin."""

    command: list
    stdin: str = field(repr=False)
    cwd: str
    env: dict


class HcNetSdk61948:
    sdk_id = "hcnet-6.1.9.48-linux64"
    runtime_image = "cam-hik-sdk-runtime:local"
    login_password_max_chars = 16

    def load_credentials(self, path=None):
        """Read validated credentials and apply this implementation's policy."""
        credentials = load_credentials(path)
        credentials["password"] = credentials["password"][:self.login_password_max_chars]
        return credentials

    def compile_bridge(self):
        """Compile only against this bundle's known header/library locations."""
        headers = (Path("/sdk/incEn/HCNetSDK.h"),
                   Path("/sdk/QtDemo/includeCn/LinuxPlayM4.h"))
        libraries = (Path("/sdk/lib/libhcnetsdk.so"), Path("/sdk/lib/libPlayCtrl.so"))
        if not all(path.is_file() for path in headers + libraries):
            raise ValueError("current SDK bundle is missing its expected headers or libraries")
        binary = "/tmp/cam-sdk-probe"
        command = ["g++", "-std=c++17", "-D_LINUX_", "-I", str(headers[0].parent),
                   "-I", str(headers[1].parent), "/probe/probe.cpp", "-L/sdk/lib",
                   "-Wl,-rpath,/sdk/lib", "-lhcnetsdk", "-lPlayCtrl", "-lpthread",
                   "-ldl", "-o", binary]
        subprocess.run(command, capture_output=True, text=True, timeout=45, check=True)
        return binary

    def invocation(self, binary, *, credentials=None, host=None, port=None,
                   seconds=0, check=False, decrypt=False, historical=False,
                   skip_search=False, browser_frames=False, capture_dir=None,
                   log_dir=None):
        """Prepare the existing bridge protocol without starting a process.

        Call load_credentials first for authenticated launches. Addresses are
        supplied by the caller, independently of the selected SDK version.
        """
        command = [str(binary)]
        if check:
            command.append("check")
        for enabled, flag in ((decrypt, "--decrypt"), (historical, "--historical"),
                              (skip_search, "--skip-search"), (browser_frames, "--browser-frames")):
            if enabled:
                command.append(flag)
        stdin = ""
        if not check:
            if credentials is None or host is None or port is None:
                raise ValueError("credentials and recorder address/port are required")
            key = credentials.get("verification_code", "") if decrypt else ""
            if decrypt and (not key or len(key.encode("utf-8")) > 128
                            or any(ord(c) < 32 or ord(c) == 127 for c in key)):
                raise ValueError("decryption requires a nonempty verification_code of at most 128 UTF-8 bytes without controls")
            stdin = "\n".join((host, str(port), credentials["username"],
                               credentials["password"], str(seconds), key)) + "\n"
        env = dict(os.environ, LD_LIBRARY_PATH="/sdk/lib:/sdk/lib/HCNetSDKCom")
        if capture_dir is not None:
            env["CAM_SDK_CAPTURE_DIR"] = str(capture_dir)
        if log_dir is not None:
            env["CAM_SDK_LOG_DIR"] = str(log_dir) + "/"
        return NativeInvocation(command, stdin, "/sdk/lib", env)
