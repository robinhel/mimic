"""Gemensam HTTP-klient. Alla anrop mot API:erna går härifrån."""

import logging
import time
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

# Sekunder mellan anrop per värd. Kalshi: max ~5 anrop/s (CLAUDE.md).
DEFAULT_MIN_INTERVAL = {
    "external-api.kalshi.com": 0.2,
    "api.elections.kalshi.com": 0.2,
    "data-api.polymarket.com": 0.1,  # gräns okänd, var snälla
    "clob.polymarket.com": 0.1,
}
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BACKOFF = 60.0


class HttpClient:
    def __init__(
        self,
        session=None,
        max_retries=5,
        min_interval=None,
        timeout=30,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = "copycheck/0.1"
        self.session = session
        self.max_retries = max_retries
        self.min_interval = DEFAULT_MIN_INTERVAL if min_interval is None else min_interval
        self.timeout = timeout
        self._sleep = sleep
        self._clock = clock
        self._last = {}

    def get_json(self, url, params=None):
        for attempt in range(self.max_retries + 1):
            self._throttle(url)
            last_try = attempt == self.max_retries
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                if last_try:
                    raise
                self._wait(None, attempt, f"{type(e).__name__}", url)
                continue
            if r.status_code in RETRY_STATUS and not last_try:
                self._wait(r.headers.get("Retry-After"), attempt, r.status_code, url)
                continue
            r.raise_for_status()
            return r.json()

    def _throttle(self, url):
        host = urlsplit(url).hostname
        gap = self.min_interval.get(host)
        if gap is None:
            return
        last = self._last.get(host)
        if last is not None:
            wait = gap - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()

    def _wait(self, retry_after, attempt, reason, url):
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            delay = min(2.0**attempt, MAX_BACKOFF)
        log.warning("%s på %s, väntar %.1f s (försök %d)", reason, url, delay, attempt + 1)
        self._sleep(delay)
