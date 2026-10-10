# Shared recorder credential loading

`tools/credentials.py` provides `load_credentials(path=None)`. By default it
reads `.local/nvr-credentials.json` relative to the project. Container callers
can supply their credential-file mount path explicitly.

The returned dictionary preserves the full login password, username and
verification/encryption code. The source file is never rewritten. SDK-specific
preparation belongs to the selected adapter rather than this file reader.
Missing, empty, non-string or control-containing login fields are rejected before
protocol use. The optional verification code must be a string when supplied.

```python
from sdk_adapters import get_sdk_adapter

credentials = get_sdk_adapter().load_credentials()
# Pass credentials["password"] to SDK or protocol-specific authentication.
# Apply RTSP URL percent encoding after loading, where needed.
```

The current `HcNetSdk61948` adapter calls the shared file reader, then uses the
**first 16 characters of the login password**. Its policy preserves the accepted
recorder web/RTSP/SDK behavior. We now assume normalization is SDK-dependent;
the original finding is verified only for this device/SDK combination. Other
implementations own their preparation rules. See the
[Python seam notes](sdk-adapter-seam.md) for contributor instructions.

All authenticated entry points now obtain prepared credentials from the adapter:

- `tools/probe_authenticated.py`: RTSP/FFmpeg and HTTP Digest inspection.
- `tools/probe_rtsp_once.py`: bounded raw RTSP Digest diagnostic.
- `tools/probe_web_session.py`: browser-compatible session login.
- `docker/hikvision-sdk/run_probe.py`: vendor SDK wrapper inside Docker.
- `docker/hikvision-sdk/grid_worker.py`: current persistent viewer worker launch.
- `docker/hikvision-sdk/browser_server.py`: preserved earlier diagnostic worker.

The SDK launchers mount the file reader at `/support/credentials.py` and the
adapter package at `/support/sdk_adapters`, both read-only, and expose them
via the container's `PYTHONPATH`.
The actual credential file remains a separate read-only mount. The offline
SDK check does not mount credentials.

With the SDK runner's `--decrypt` option, the full `verification_code` is
sent privately over stdin to PlayCtrl's key setter, with no hashing or
truncation. Empty, control-containing or greater-than-128-UTF-8-byte codes
are rejected before login. This is separate from the 16-character login
password rule. See [encrypted-stream investigation](encrypted-stream-investigation.md).

The old RTSP `--password-first-16` flag remains accepted for compatibility;
the current adapter's rule applies without needing the flag. The existing experimental
raw RTSP option that explicitly substitutes `verification_code` still uses that
separate value as supplied; ordinary login uses the adapter-prepared `password`.

Regression checks cover password lengths below, at and above the boundary,
preservation of a longer encryption key and username, unchanged source-file
bytes, and invalid credentials rejected before protocol use:

```sh
python3 -m unittest discover -s tests -v
```

Ten offline tests passed after the extraction. The real Docker SDK initialization,
decoder key setup and debug logging also passed through the adapter with
networking disabled and zero login calls. The earlier authenticated success
is recorded in [SDK investigation](sdk-docker-investigation.md); no live login
was repeated for this refactor.
