import json

import pytest
import requests

from copycheck.http import HttpClient


def resp(status, body=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body or {}).encode()
    r.headers.update(headers or {})
    r.url = "https://example.test/x"
    return r


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def client(responses, **kw):
    t = FakeTime()
    s = FakeSession(responses)
    return HttpClient(session=s, sleep=t.sleep, clock=t.clock, **kw), s, t


def test_returnerar_json():
    c, s, t = client([resp(200, {"ok": 1})])
    assert c.get_json("https://example.test/x", {"a": 1}) == {"ok": 1}
    assert s.calls == [("https://example.test/x", {"a": 1})]
    assert t.sleeps == []


def test_429_respekterar_retry_after():
    c, s, t = client([resp(429, headers={"Retry-After": "3"}), resp(200, {"ok": 1})])
    assert c.get_json("https://example.test/x") == {"ok": 1}
    assert t.sleeps == [3.0]


def test_5xx_och_natverksfel_ger_backoff():
    c, s, t = client([resp(503), requests.ConnectionError("nere"), resp(200, {"ok": 1})])
    assert c.get_json("https://example.test/x") == {"ok": 1}
    assert t.sleeps == [1.0, 2.0]


def test_ger_upp_efter_max_forsok():
    c, s, t = client([resp(500)] * 3, max_retries=2)
    with pytest.raises(requests.HTTPError):
        c.get_json("https://example.test/x")
    assert len(s.calls) == 3


def test_400_forsoks_inte_igen():
    c, s, t = client([resp(400), resp(200)])
    with pytest.raises(requests.HTTPError):
        c.get_json("https://example.test/x")
    assert len(s.calls) == 1


def test_takt_per_vard():
    c, s, t = client([resp(200)] * 3, min_interval={"external-api.kalshi.com": 0.2})
    c.get_json("https://external-api.kalshi.com/a")
    c.get_json("https://external-api.kalshi.com/b")
    c.get_json("https://data-api.polymarket.com/c")  # annan värd, ingen väntan
    assert t.sleeps == [pytest.approx(0.2)]
