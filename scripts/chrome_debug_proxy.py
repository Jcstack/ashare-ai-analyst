#!/usr/bin/env python3
"""CDP-aware reverse proxy: exposes Chrome's 127.0.0.1:9222 on 0.0.0.0:9223.

Chrome always binds its debug port to localhost on macOS. Docker containers
reach the host via host.docker.internal but can't hit 127.0.0.1.

This proxy handles TWO protocols:
1. HTTP — rewrites /json/* responses so WebSocket URLs point back through proxy
2. WebSocket — pure TCP pipe for the actual CDP session

Usage:
    python scripts/chrome_debug_proxy.py          # 0.0.0.0:9223 → 127.0.0.1:9222
    python scripts/chrome_debug_proxy.py 9224      # custom listen port
"""

import asyncio
import json
import sys
import urllib.request

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9223
CHROME_HOST = "127.0.0.1"
CHROME_PORT = 9222


def _rewrite_ws_urls(body: str, request_host: str) -> str:
    """Replace ws://127.0.0.1:9222 with ws://<request_host> in CDP JSON.

    ``request_host`` comes from the HTTP Host header so the rewritten
    WebSocket URL is routable from the caller's network.
    """
    return body.replace(
        f"ws://{CHROME_HOST}:{CHROME_PORT}",
        f"ws://{request_host}",
    ).replace(
        f"{CHROME_HOST}:{CHROME_PORT}",
        f"{request_host}",
    )


def _fetch_and_rewrite(path: str, request_host: str) -> bytes:
    """Fetch a /json/* path from Chrome and rewrite WebSocket URLs."""
    url = f"http://{CHROME_HOST}:{CHROME_PORT}{path}"
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        body = resp.read().decode()
        rewritten = _rewrite_ws_urls(body, request_host)
        return rewritten.encode()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
    """Route: HTTP /json/* → rewrite, WebSocket upgrade → TCP pipe."""
    try:
        # Peek at first bytes to decide HTTP vs WebSocket upgrade
        first_line = await asyncio.wait_for(client_r.readline(), timeout=10)
        if not first_line:
            client_w.close()
            return

        line = first_line.decode("utf-8", errors="replace").strip()

        # Check if this is an HTTP GET for /json/* endpoints
        if line.startswith("GET /json"):
            # Read rest of HTTP headers (until blank line)
            path = line.split(" ")[1] if " " in line else "/json/version"
            request_host = f"{LISTEN_HOST}:{LISTEN_PORT}"
            while True:
                header_line = await client_r.readline()
                if header_line in (b"\r\n", b"\n", b""):
                    break
                hdr = header_line.decode("utf-8", errors="replace").strip()
                if hdr.lower().startswith("host:"):
                    request_host = hdr.split(":", 1)[1].strip()

            # Fetch from Chrome and rewrite WS URLs to caller's host
            loop = asyncio.get_event_loop()
            body = await loop.run_in_executor(
                None, _fetch_and_rewrite, path, request_host
            )

            # Send HTTP response
            http_resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json; charset=UTF-8\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n"
                b"\r\n" + body
            )
            client_w.write(http_resp)
            await client_w.drain()
            client_w.close()
            return

        # For everything else (WebSocket upgrade, etc.), pipe to Chrome
        try:
            upstream_r, upstream_w = await asyncio.open_connection(
                CHROME_HOST, CHROME_PORT
            )
        except OSError as e:
            print(f"[proxy] Cannot reach Chrome at {CHROME_HOST}:{CHROME_PORT}: {e}")
            client_w.close()
            return

        # Forward the first line we already read
        upstream_w.write(first_line)
        await upstream_w.drain()

        # Pipe both directions
        await asyncio.gather(
            _pipe(client_r, upstream_w), _pipe(upstream_r, client_w)
        )

    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
        try:
            client_w.close()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(_handle, LISTEN_HOST, LISTEN_PORT)
    print(
        f"[chrome-debug-proxy] {LISTEN_HOST}:{LISTEN_PORT} → "
        f"{CHROME_HOST}:{CHROME_PORT} (CDP-aware rewrite)"
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[proxy] stopped")
