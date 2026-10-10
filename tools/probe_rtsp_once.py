#!/usr/bin/env python3
"""One RTSP DESCRIBE probe, with at most one Digest authentication submission."""

from datetime import datetime, timezone
import argparse
import hashlib
import json
import secrets
import socket
import urllib.request

from probe_authenticated import HOST, ROOT
from sdk_adapters import get_sdk_adapter


def read_response(reader):
    status = reader.readline(8192).decode("utf-8", errors="replace").strip()
    headers = {}
    for _ in range(100):
        line = reader.readline(8192)
        if line in (b"\r\n", b"\n", b""):
            break
        key, separator, value = line.decode("utf-8", errors="replace").partition(":")
        if separator:
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if not 0 <= length <= 65536:
        raise ValueError("response body too large")
    return status, headers, reader.read(length).decode("utf-8", errors="replace")


def quote_header(value):
    if any(ord(character) < 32 for character in value):
        raise ValueError("control character in Digest field")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def authorization(challenge, credentials, uri):
    scheme, _, parameters = challenge.partition(" ")
    if scheme.lower() != "digest":
        raise ValueError("unsupported authentication scheme")
    fields = urllib.request.parse_keqv_list(urllib.request.parse_http_list(parameters))
    algorithm = fields.get("algorithm", "MD5").upper()
    if algorithm == "MD5":
        factory = hashlib.md5
    elif algorithm in ("SHA-256", "SHA256"):
        factory = hashlib.sha256
    else:
        raise ValueError("unsupported Digest algorithm")
    def digest(value):
        return factory(value.encode("utf-8")).hexdigest()
    realm, nonce = fields["realm"], fields["nonce"]
    ha1 = digest(f"{credentials['username']}:{realm}:{credentials['password']}")
    ha2 = digest(f"DESCRIBE:{uri}")
    result = {
        "username": credentials["username"], "realm": realm,
        "nonce": nonce, "uri": uri, "algorithm": fields.get("algorithm", "MD5"),
    }
    if fields.get("qop"):
        if "auth" not in [value.strip() for value in fields["qop"].split(",")]:
            raise ValueError("unsupported Digest qop")
        cnonce = secrets.token_hex(16)
        result.update({"qop": "auth", "nc": "00000001", "cnonce": cnonce})
        response = digest(f"{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}")
    else:
        response = digest(f"{ha1}:{nonce}:{ha2}")
    result["response"] = response
    if "opaque" in fields:
        result["opaque"] = fields["opaque"]
    return "Digest " + ", ".join(
        key + "=" + (value if key in ("qop", "nc", "algorithm") else quote_header(value))
        for key, value in result.items()
    ), algorithm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--password-field", choices=("password", "verification_code"), default="password",
        help="Credential-file field to use as the RTSP authentication password",
    )
    args = parser.parse_args()
    credentials = get_sdk_adapter().load_credentials()
    # Substitute in memory only; leave the user's credential file unchanged.
    credentials["password"] = credentials.get(args.password_field, "")
    report = {
        "host": HOST, "port": 554, "channel": 102, "method": "DESCRIBE",
        "authenticated_submissions": 0,
        "verification_code_used": args.password_field == "verification_code",
        "authentication_password_source": args.password_field,
        "password_first_16": args.password_field == "password",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    uri = f"rtsp://{HOST}:554/Streaming/channels/102"
    try:
        if not credentials.get("username") or not credentials.get("password"):
            raise ValueError("missing credentials")
        with socket.create_connection((HOST, 554), timeout=8) as connection:
            with connection.makefile("rb") as reader:
                prefix = f"DESCRIBE {uri} RTSP/1.0\r\n"
                suffix = "Accept: application/sdp\r\nUser-Agent: cam-visualiser-once\r\n\r\n"
                connection.sendall((prefix + "CSeq: 1\r\n" + suffix).encode("utf-8"))
                status, headers, body = read_response(reader)
                report["initial_status"] = status
                if status.startswith("RTSP/1.0 401"):
                    auth, algorithm = authorization(headers["www-authenticate"], credentials, uri)
                    report["digest_algorithm"] = algorithm
                    request = prefix + "CSeq: 2\r\nAuthorization: " + auth + "\r\n" + suffix
                    report["authenticated_submissions"] = 1
                    connection.sendall(request.encode("utf-8"))
                    status, _, body = read_response(reader)
                report["final_status"] = status
                if status.startswith("RTSP/1.0 200"):
                    report["sdp_media_and_codecs"] = [
                        line for line in body.splitlines()
                        if line.startswith(("m=", "a=rtpmap:"))
                    ]
    except (OSError, ValueError, KeyError) as error:
        report["error"] = type(error).__name__
    output = json.dumps(report, indent=2)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / f".local/rtsp-once-{stamp}.json"
    path.write_text(output + "\n")
    path.chmod(0o600)
    print(output)


if __name__ == "__main__":
    main()
