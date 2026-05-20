"""HTTP client for the TrainingPeaks API.

Cookie -> OAuth Bearer token exchange + minimal throttling + retry on 401.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TP_API_BASE = "https://tpapi.trainingpeaks.com"
TOKEN_ENDPOINT = "/users/v3/token"
MIN_REQUEST_INTERVAL = 0.15  # seconds
TOKEN_REFRESH_BUFFER = 60  # refresh 60s before expiry
DEFAULT_TIMEOUT = 30.0


class TPAuthError(RuntimeError):
    pass


class TPApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class AthleteThresholds:
    """Athlete-level thresholds used to translate %-based targets to absolute values."""

    ftp: float | None = None  # watts
    threshold_hr: float | None = None  # bpm
    threshold_velocity_mps: float | None = None  # metres per second (run)
    swim_threshold_velocity_mps: float | None = None  # metres per second (swim)


class TPClient:
    def __init__(self, cookie: str, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._cookie = cookie
        self._client = httpx.Client(timeout=timeout, base_url=TP_API_BASE)
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._last_request_ts: float = 0.0
        self._athlete_id: int | None = None
        self._thresholds: AthleteThresholds | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TPClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - TOKEN_REFRESH_BUFFER:
            return self._token
        self._throttle()
        r = self._client.get(
            TOKEN_ENDPOINT,
            headers={
                "Cookie": f"Production_tpAuth={self._cookie}",
                "Accept": "application/json",
            },
        )
        if r.status_code == 401:
            raise TPAuthError(
                "TrainingPeaks cookie expired or invalid. "
                "Refresh TP_AUTH_COOKIE in .env (log out + back in at trainingpeaks.com)."
            )
        if r.status_code != 200:
            raise TPApiError(f"Token exchange failed: HTTP {r.status_code} - {r.text[:200]}")
        body = r.json()
        if not body.get("success") or "token" not in body:
            raise TPApiError(f"Unexpected token response: {body}")
        tok = body["token"]
        self._token = tok["access_token"]
        self._token_expires_at = time.time() + int(tok.get("expires_in", 3600))
        return self._token

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        _retried: bool = False,
    ) -> Any:
        token = self._ensure_token()
        self._throttle()
        r = self._client.request(
            method,
            endpoint,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        if r.status_code == 401 and not _retried:
            self._token = None
            return self._request(method, endpoint, params=params, _retried=True)
        if r.status_code == 401:
            raise TPAuthError("TP returned 401 after token refresh. Cookie may be revoked.")
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise TPApiError(f"TP {method} {endpoint} -> HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            return None

    def get(self, endpoint: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", endpoint, params=params)

    def athlete_id(self) -> int:
        if self._athlete_id is not None:
            return self._athlete_id
        data = self.get("/users/v3/user")
        user = data.get("user", data) if isinstance(data, dict) else None
        if not user:
            raise TPApiError("Could not fetch TrainingPeaks user info.")
        person_id = user.get("personId")
        athletes = user.get("athletes") or []
        # Default: my own athlete entry (matches lastName + coachedBy=self), else personId.
        chosen: int | None = None
        my_last = (user.get("lastName") or "").lower()
        for a in athletes:
            if (a.get("lastName") or "").lower() == my_last and a.get("coachedBy") == person_id:
                chosen = a.get("athleteId")
                break
        if chosen is None and athletes:
            chosen = athletes[0].get("athleteId")
        if chosen is None:
            chosen = person_id
        if chosen is None:
            raise TPApiError("Could not determine athleteId from TP user payload.")
        self._athlete_id = int(chosen)
        return self._athlete_id

    def thresholds(self) -> AthleteThresholds:
        """Fetch and cache athlete thresholds (FTP, threshold HR, threshold pace)."""
        if self._thresholds is not None:
            return self._thresholds
        athlete_id = self.athlete_id()
        data = self.get(f"/fitness/v1/athletes/{athlete_id}/settings")
        if not isinstance(data, dict):
            self._thresholds = AthleteThresholds()
            return self._thresholds

        ftp: float | None = None
        for zg in data.get("powerZones", []) or []:
            if zg.get("workoutTypeId") in (0, None):
                t = zg.get("threshold")
                if isinstance(t, (int, float)) and t > 0:
                    ftp = float(t)
                    break

        thr_hr: float | None = None
        for zg in data.get("heartRateZones", []) or []:
            if zg.get("workoutTypeId") in (0, None):
                t = zg.get("threshold")
                if isinstance(t, (int, float)) and t > 0:
                    thr_hr = float(t)
                    break

        run_thr: float | None = None
        swim_thr: float | None = None
        for zg in data.get("speedZones", []) or []:
            wt = zg.get("workoutTypeId")
            t = zg.get("threshold")
            if not isinstance(t, (int, float)) or t <= 0:
                continue
            # workoutTypeId 0 = run by TP convention; 1 = swim.
            if wt in (0, None) and run_thr is None:
                run_thr = float(t)
            if wt == 1 and swim_thr is None:
                swim_thr = float(t)

        self._thresholds = AthleteThresholds(
            ftp=ftp,
            threshold_hr=thr_hr,
            threshold_velocity_mps=run_thr,
            swim_threshold_velocity_mps=swim_thr,
        )
        return self._thresholds
