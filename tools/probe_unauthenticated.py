#!/usr/bin/env python3
"""Read-only, credential-free checks of this project's home recorder."""

import concurrent.futures
import http.client
import json
import socket

HOST = "192.0.2.10"
TIMEOUT = 4


def port_check(port):
    try:
        with socket.create_connection((HOST, port), timeout=TIMEOUT):
            return {"port": port, "reachable": True}
    except OSError as error:
        return {"port": port, "reachable": False, "error": str(error)}


def http_get(path):
    connection = http.client.HTTPConnection(HOST, 80, timeout=TIMEOUT)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return {
            "path": path,
            "status": response.status,
            "headers": dict(response.getheaders()),
            "body_excerpt": response.read(2048).decode("utf-8", errors="replace"),
        }
    except OSError as error:
        return {"path": path, "error": str(error)}
    finally:
        connection.close()


def rtsp_request(method, path):
    uri = f"rtsp://{HOST}:554{path}"
    request = (
        f"{method} {uri} RTSP/1.0\r\n"
        "CSeq: 1\r\nUser-Agent: cam-visualiser-probe\r\n"
        "Accept: application/sdp\r\n\r\n"
    )
    try:
        with socket.create_connection((HOST, 554), timeout=TIMEOUT) as connection:
            connection.sendall(request.encode("ascii"))
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                data += chunk
            header, _, body = data.partition(b"\r\n\r\n")
            lines = header.decode("utf-8", errors="replace").split("\r\n")
            headers = {}
            for line in lines[1:]:
                key, separator, value = line.partition(":")
                if separator:
                    headers[key.lower()] = value.strip()
            length = min(int(headers.get("content-length", "0")), 65536)
            while len(body) < length:
                chunk = connection.recv(min(4096, length - len(body)))
                if not chunk:
                    break
                body += chunk
            return {
                "method": method,
                "uri": uri,
                "status": lines[0],
                "headers": headers,
                "body_excerpt": body[:4096].decode("utf-8", errors="replace"),
            }
    except (OSError, ValueError) as error:
        return {"method": method, "uri": uri, "error": str(error)}


def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        ports = list(pool.map(port_check, (80, 443, 554, 8000)))
    results = {"host": HOST, "ports": ports, "http": [], "rtsp": []}
    reachable = {result["port"] for result in ports if result["reachable"]}
    if 80 in reachable:
        for path in ("/", "/ISAPI/System/deviceInfo", "/ISAPI/Streaming/channels"):
            results["http"].append(http_get(path))
    if 554 in reachable:
        results["rtsp"].append(rtsp_request("OPTIONS", "/"))
        for channel in (102, 101):
            results["rtsp"].append(
                rtsp_request("DESCRIBE", f"/Streaming/channels/{channel}")
            )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
