# Shared recorder credential loading

`tools/credentials.py` provides `load_credentials(path=None)`. By default it
reads `.local/nvr-credentials.json` relative to the project. Container callers
can supply their credential-file mount path explicitly.

The returned dictionary uses only the **first 16 characters of the login
password**, matching the accepted recorder web/RTSP/SDK credential. The username
and verification/encryption code are unchanged. The source file is never rewritten.
Missing, empty, non-string or control-containing login fields are rejected before
protocol use. The optional verification code must be a string when supplied.

```python
from credentials import load_credentials

credentials = load_credentials()
# Pass credentials["password"] to SDK or protocol-specific authentication.
# Apply RTSP URL percent encoding after loading, where needed.
```

All authenticated entry points now use this loader:

- `tools/probe_authenticated.py`: RTSP/FFmpeg and HTTP Digest inspection.
- `tools/probe_rtsp_once.py`: bounded raw RTSP Digest diagnostic.
- `tools/probe_web_session.py`: browser-compatible session login.
- `docker/hikvision-sdk/run_probe.py`: vendor SDK wrapper inside Docker.

The SDK launcher mounts this one helper file read-only at
`/support/credentials.py` and exposes it via the container's `PYTHONPATH`.
The actual credential file remains a separate read-only mount. The offline
SDK check does not mount credentials.

The old RTSP `--password-first-16` flag remains accepted for compatibility;
the rule now always applies, without needing the flag. The existing experimental
raw RTSP option that explicitly substitutes `verification_code` still uses that
separate value as supplied; ordinary login always uses the limited `password`.

Regression checks cover password lengths below, at and above the boundary,
preservation of a longer encryption key and username, unchanged source-file
bytes, and invalid credentials rejected before protocol use:

```sh
python3 -m unittest discover -s tests -v
```

Both test groups passed. SDK import, initialization and debug logging also
passed with networking disabled. Then the user-authorized single SDK login
succeeded using this loader; see `docs/sdk-docker-investigation.md`.
