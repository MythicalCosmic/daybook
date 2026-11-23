"""The Daybook device API (contract §5), over httpx.

- Every call except ``pair/`` sends ``Authorization: Bearer koz_…``.
- Network errors, 5xx and 429 are retried with exponential backoff and jitter (``retries`` tries
  in all), then raise ``OfflineError``; the caller keeps what it could not send.
- Other 4xx raise ``DaybookError`` at once.
- A 401 means the token is wrong or revoked: ``RevokedError``, and from then on one try every
  ``revoked_retry_s`` (10 minutes); calls in between fail without touching the network.
"""

from __future__ import annotations

import json
import logging
import random
from urllib.parse import quote

import httpx

from . import __version__
from .clock import Clock, SystemClock

log = logging.getLogger(__name__)

API_PATH = "/api/v1/devices/koz/"


class DaybookError(Exception):
    def __init__(self, status: int, code: str | None = None, detail: str | None = None) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(f"{status} {code or ''} {detail or ''}".strip())


class RevokedError(DaybookError):
    pass


class OfflineError(DaybookError):
    pass


def _error_of(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        body = response.json()
    except ValueError:
        return None, response.text[:200] or None
    if isinstance(body, dict):
        return body.get("code"), body.get("detail")
    return None, None


class DaybookClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        clock: Clock | None = None,
        transport: httpx.BaseTransport | None = None,
        retries: int = 3,
        backoff_base_s: float = 0.5,
        backoff_cap_s: float = 8.0,
        revoked_retry_s: float = 600.0,
        rng: random.Random | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.clock = clock or SystemClock()
        self.retries = max(1, retries)
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.revoked_retry_s = revoked_retry_s
        self.rng = rng or random.Random()
        self.revoked_at: float | None = None
        self.last_ok_at: float | None = None
        self.last_error: str | None = None
        self.calls = 0
        self._http = httpx.Client(
            base_url=self.base_url + API_PATH,
            transport=transport,
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"User-Agent": f"koz-agent/{__version__}"},
        )

    def close(self) -> None:
        self._http.close()

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def backoff(self, attempt: int) -> float:
        """The pause before retry number ``attempt + 1``: exponential, capped, ±50 % jitter."""
        delay = min(self.backoff_cap_s, self.backoff_base_s * (2**attempt))
        return delay * (0.5 + self.rng.random())

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        json_body: object = None,
        data: dict | None = None,
        files: dict | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> httpx.Response:
        if auth:
            if not self.token:
                raise RevokedError(401, "not_paired", "this box is not paired")
            if self.revoked_at is not None:
                wait = self.revoked_retry_s - (self.clock.time() - self.revoked_at)
                if wait > 0:
                    raise RevokedError(401, "revoked", f"next try in {int(wait)} s")
        headers = {"Authorization": f"Bearer {self.token}"} if auth else {}
        kwargs: dict = {"headers": headers}
        if json_body is not None:
            kwargs["json"] = json_body
        if data is not None:
            kwargs["data"] = data
        if files is not None:
            kwargs["files"] = files
        if timeout is not None:
            kwargs["timeout"] = timeout

        for attempt in range(self.retries):
            last = attempt + 1 >= self.retries
            self.calls += 1
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                if last:
                    raise OfflineError(0, "offline", self.last_error) from exc
                self.clock.sleep(self.backoff(attempt))
                continue
            status = response.status_code
            if status == 401 and auth:
                code, detail = _error_of(response)
                self.revoked_at = self.clock.time()
                self.last_error = f"401 {code or 'revoked'}"
                log.warning("Daybook refused the token (%s); trying again in 10 minutes", code)
                raise RevokedError(401, code or "revoked", detail)
            if status >= 500 or status == 429:
                self.last_error = f"HTTP {status}"
                if last:
                    raise OfflineError(status, "server_error", f"HTTP {status}")
                self.clock.sleep(self.backoff(attempt))
                continue
            if status >= 400:
                code, detail = _error_of(response)
                self.last_error = f"HTTP {status} {code or ''}".strip()
                raise DaybookError(status, code, detail)
            if auth:
                self.revoked_at = None
            self.last_ok_at = self.clock.time()
            self.last_error = None
            return response
        raise OfflineError(0, "offline", "no try left")  # not reached

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        if response.status_code == 204 or not response.content:
            return {}
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    # --- the endpoints (contract §5.1–5.10) -----------------------------------------------

    def pair(self, code: str, host: dict) -> dict:
        response = self._request(
            "POST", "pair/", auth=False, json_body={"code": code, "host": host}
        )
        return self._json(response)

    def config(self) -> dict:
        return self._json(self._request("GET", "config/"))

    def cameras(self, cameras: list[dict]) -> dict:
        return self._json(self._request("POST", "cameras/", json_body={"cameras": cameras}))

    def snapshot(self, key: str, jpeg: bytes) -> None:
        self._request(
            "POST",
            f"cameras/{quote(key, safe=':')}/snapshot/",
            files={"image": ("snapshot.jpg", jpeg, "image/jpeg")},
        )

    def live(self, payload: dict) -> dict:
        return self._json(self._request("POST", "live/", json_body=payload))

    def frame(self, key: str, jpeg: bytes, meta: dict) -> None:
        self._request(
            "POST",
            f"frames/{quote(key, safe=':')}/",
            data={"meta": json.dumps(meta, separators=(",", ":"))},
            files={"image": ("frame.jpg", jpeg, "image/jpeg")},
        )

    def stats(self, minutes: list[dict]) -> dict:
        return self._json(self._request("POST", "stats/", json_body={"minutes": minutes}))

    def event(self, event: dict, image: bytes | None = None) -> dict:
        # always multipart (contract §5.8), even without a photo: a part with no file name
        files: dict = {"event": (None, json.dumps(event, separators=(",", ":")))}
        if image:
            files["image"] = ("alert.jpg", image, "image/jpeg")
        return self._json(self._request("POST", "events/", files=files))

    def jobs(self) -> dict:
        return self._json(self._request("GET", "jobs/"))

    def clip(self, clip_id: int, video: bytes, poster: bytes, meta: dict) -> None:
        self._request(
            "POST",
            f"clips/{int(clip_id)}/",
            data={"meta": json.dumps(meta, separators=(",", ":"))},
            files={
                "video": ("clip.mp4", video, "video/mp4"),
                "poster": ("poster.jpg", poster, "image/jpeg"),
            },
            timeout=httpx.Timeout(120.0, connect=5.0),
        )

    def clip_failed(self, clip_id: int, reason: str, detail: str = "") -> None:
        self._request(
            "POST", f"clips/{int(clip_id)}/", json_body={"failed": reason, "detail": detail[:500]}
        )
