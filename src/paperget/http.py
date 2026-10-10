from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

from .errors import PaperGetError


class HttpClient:
    """A small, polite HTTP client shared by metadata and PDF providers."""

    def __init__(self, session: requests.Session | None = None, min_interval: float = 1.0):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "PaperGet/0.2 (+https://github.com/Godwu155/sci-hub-tool)"
        self.min_interval = min_interval
        self._last_request: dict[str, float] = {}

    def get(self, url: str, *, params=None, headers=None, stream=False, retries=3):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise PaperGetError("invalid_url", f"Unsupported URL: {url}")
        host = parsed.hostname.lower()
        for attempt in range(retries + 1):
            elapsed = time.monotonic() - self._last_request.get(host, 0.0)
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request[host] = time.monotonic()
            try:
                response = self.session.get(
                    url, params=params, headers=headers, stream=stream, timeout=(10, 30)
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == retries:
                    code = "timeout" if isinstance(exc, requests.Timeout) else "connection_error"
                    raise PaperGetError(code, str(exc)) from exc
                time.sleep(min(2**attempt + random.random(), 30))
                continue
            except requests.RequestException as exc:
                raise PaperGetError("connection_error", str(exc)) from exc

            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == retries:
                    code = "rate_limited" if response.status_code == 429 else "server_error"
                    response.close()
                    raise PaperGetError(code, f"HTTP {response.status_code} from {host}")
                wait = self._retry_after(response.headers.get("Retry-After"))
                response.close()
                time.sleep(wait if wait is not None else min(2**attempt + random.random(), 30))
                continue
            if response.status_code == 403:
                response.close()
                raise PaperGetError("forbidden", f"HTTP 403 from {host}")
            if response.status_code >= 400 and response.status_code != 404:
                code = response.status_code
                response.close()
                raise PaperGetError("http_error", f"HTTP {code} from {host}")
            return response
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return min(max(float(value), 0.0), 300.0)
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                return min(max((date - datetime.now(timezone.utc)).total_seconds(), 0.0), 300.0)
            except (TypeError, ValueError, OverflowError):
                return None
