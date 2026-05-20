"""HTTP client for intervals.icu (Basic Auth)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ICU_API_BASE = "https://intervals.icu/api/v1"
MIN_REQUEST_INTERVAL = 0.2  # be polite
DEFAULT_TIMEOUT = 30.0


class IcuAuthError(RuntimeError):
    pass


class IcuApiError(RuntimeError):
    pass


class IcuClient:
    def __init__(self, api_key: str, athlete_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._athlete = athlete_id
        self._client = httpx.Client(
            timeout=timeout,
            base_url=ICU_API_BASE,
            auth=httpx.BasicAuth("API_KEY", api_key),
        )
        self._last_request_ts: float = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "IcuClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def athlete_id(self) -> str:
        return self._athlete

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        self._throttle()
        r = self._client.request(method, path, params=params, json=json)
        if r.status_code == 401:
            raise IcuAuthError("intervals.icu auth failed (HTTP 401). Check ICU_API_KEY.")
        if r.status_code == 403:
            raise IcuAuthError(
                f"intervals.icu denied access (HTTP 403). Check athlete id {self._athlete}."
            )
        if r.status_code == 429:
            time.sleep(30)
            r = self._client.request(method, path, params=params, json=json)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise IcuApiError(f"icu {method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, *, json: Any = None) -> Any:
        return self._request("POST", path, json=json)

    def put(self, path: str, *, json: Any = None) -> Any:
        return self._request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)
