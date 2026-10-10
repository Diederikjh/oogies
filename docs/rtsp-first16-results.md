# RTSP test with the web form's 16-character password

Date: 10 October 2026. Result reported at **12:46:11 South Africa time**
(`10:46:11 UTC`). The user authorized the proposed single RTSP prefix test.

## Result

Using the first 16 ASCII characters of the current saved password got past
RTSP authentication and into **HEVC/H.265 stream parsing** on port 554,
channel 102 (the first camera's substream). The earlier full-password attempt
with this account stopped at OPTIONS with 401; the prefix attempt proceeded
to HEVC parser errors rather than authentication rejection.

This confirms that the saved full password and the effective web-form password
differ for the tested RTSP account. It does not establish that all Hikvision
firmware universally truncates passwords or that the SDK has now been tested
with the prefix. No SDK login was made in this turn.

The session was configured for up to 60 seconds of decoding and capture, but
ended after **5.24 seconds** with FFmpeg return code 1. HEVC diagnostics included
invalid VPS fields, missing SPS/PPS and NAL parsing errors. Resolution could not
be determined; the Matroska output header could not be written without valid
dimensions. The resulting capture file is **zero bytes**, and no valid decoded
frames were produced. This was not a successful 60-second video capture.

The configured stream encryption is a plausible explanation for the invalid
codec data. The result alone cannot distinguish encryption from malformed or
unsupported stream data. The verification/encryption code was not applied.

## Execution and checks

- Added an opt-in `--password-first-16` argument to the RTSP diagnostic.
  It substitutes the prefix in a copied in-memory credential dictionary and
  restricts this comparison to ASCII passwords and RTSP modes.
- A network-disabled mock-server check with dummy credentials verified the
  actual Digest response uses the first 16 characters and stops after one
  rejected credential submission. The dummy source dictionary stayed intact.
- One live FFmpeg RTSP/TCP session ran in the existing Docker image with a
  read-only credential mount, two CPUs and a 1 GiB memory limit.
- No extra channel, password variant, reconnecting probe or SDK login was run.
  Ordinary authenticated RTSP session requests are part of this one session.
- A before/after file-integrity comparison confirmed that
  `.local/nvr-credentials.json` is **unchanged**. No recorder settings changed.
- The test container exited. Results remain private under
  `.local/rtsp-first16-20261010T104508Z/`.

## Strategy reset: authentication now works; decoding is unproven

1. Goal: obtain and correctly decode one live camera stream.
2. Approach: one RTSP session with the effective web-form password, FFmpeg
   decoding and Matroska capture from that same session.
3. Evidence for: authentication passed, and HEVC stream processing was reached.
   Evidence against a plain decoding path: no valid codec parameters or frames;
   the capture container could not be initialized.
4. Unverified assumptions: how encryption is applied on this RTSP path, how the
   saved verification code maps to a decoder key, and SDK/player compatibility.
5. Alternatives: use the vendor SDK and playback/decryption library with the
   accepted password prefix; or collect raw encoded/RTP data in a separately
   authorized session for offline stream-format and encryption analysis. A
   controlled encryption-off comparison remains another option requiring an
   explicit instruction to change recorder settings.
6. Simplest next path: evaluate the SDK plus vendor playback library using the
   proven RTSP credential prefix and the existing encryption key. Prepare the
   decoder/key-handling path before the next bounded live attempt.
7. Verification: accepted SDK login, actual stream bytes and correctly rendered
   frames. A login, callback handle, or encoded byte count alone is insufficient.

The password-length check succeeded at authentication. Live-video decoding and
browser-viewing feasibility still require further verification.
