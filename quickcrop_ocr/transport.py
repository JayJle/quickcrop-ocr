from __future__ import annotations

import ssl
import threading
import urllib.request
from urllib.parse import urlsplit

import httpx


KEEPALIVE_SECONDS = 60.0


class QwenTransport:
    """One serial OCR connection pool; closing never races an active request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None
        self._route: tuple[str, str | None] | None = None
        self._active = False
        self._closed = False

    def post(self, request: urllib.request.Request, *, timeout: float) -> tuple[int, str, str | None]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Qwen transport is closed")
            if self._active:
                raise RuntimeError("Qwen transport already has an active request")
            self._active = True
        try:
            host = urlsplit(request.full_url).hostname
            proxy = None if urllib.request.proxy_bypass(host) else urllib.request.getproxies().get("https")
            route = (urlsplit(request.full_url).netloc, proxy)
            if self._client is None or route != self._route:
                if self._client is not None:
                    self._client.close()
                    self._client = None
                # Preserve Windows/system proxy discovery and the existing TLS trust store.
                self._client = httpx.Client(
                    proxy=proxy, trust_env=False, verify=ssl.create_default_context(),
                    follow_redirects=False, http2=False,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=1,
                                       keepalive_expiry=KEEPALIVE_SECONDS),
                )
                self._route = route
            with self._lock:
                if self._closed:
                    raise RuntimeError("Qwen transport is closed")
            # Credentials belong to this request, never the persistent client's defaults.
            with self._client.stream(
                "POST", request.full_url, content=request.data,
                headers=dict(request.header_items()), timeout=timeout,
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
                return response.status_code, body, response.headers.get("Retry-After")
        finally:
            client = None
            with self._lock:
                self._active = False
                if self._closed:
                    client, self._client = self._client, None
            if client is not None:
                client.close()

    def close(self) -> None:
        client = None
        with self._lock:
            self._closed = True
            if not self._active:
                client, self._client = self._client, None
        if client is not None:
            client.close()

    def __enter__(self) -> QwenTransport:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
