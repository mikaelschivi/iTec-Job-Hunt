import json

import pytest
import requests

from watcher import config, site
from watcher.site import FetchError


class FakeResp:
    def __init__(self, status=200, body=b"", chunk=1000):
        self.status_code = status
        self.body = body
        self.chunk = chunk
        self.closed = False
        self.encoding = None

    def iter_content(self, n):
        for i in range(0, len(self.body), self.chunk):
            yield self.body[i : i + self.chunk]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp = resp
        self.exc = exc
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc:
            raise self.exc
        return self.resp


def post(**over):
    d = {
        "id": 5,
        "type": "post",
        "status": "publish",
        "content": {"rendered": "<p>x</p>", "protected": False},
    }
    d.update(over)
    return json.dumps(d).encode()


def test_get_post_ok_and_call_args():
    s = FakeSession(FakeResp(body=post()))
    data = site.get_post(s, 5)
    assert data["id"] == 5
    url, kw = s.calls[0]
    assert url == "https://itecfurg.org/?rest_route=/wp/v2/posts/5"
    assert kw["allow_redirects"] is False
    assert kw["stream"] is True
    assert kw["timeout"] == (config.CONNECT_TIMEOUT, config.READ_TIMEOUT)
    assert s.resp.closed


@pytest.mark.parametrize(
    "resp",
    [
        FakeResp(404, b"{}"),
        FakeResp(301, b""),
        FakeResp(200, b"<html>blocked by waf</html>"),
        FakeResp(200, post(id=6)),
        FakeResp(200, post(type="page")),
        FakeResp(200, post(status="draft")),
        FakeResp(200, post(content={"rendered": 5})),
        FakeResp(200, post(content={"rendered": "x", "protected": True})),
        FakeResp(200, b"[1, 2]"),
        FakeResp(200, b"\xff\xfe"),
    ],
)
def test_get_post_rejects(resp):
    with pytest.raises(FetchError):
        site.get_post(FakeSession(resp), 5)


def test_request_exception_becomes_fetch_error():
    s = FakeSession(exc=requests.ConnectionError("boom"))
    with pytest.raises(FetchError):
        site.get_post(s, 5)


def test_body_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 1500)
    with pytest.raises(FetchError):
        site.get_post(FakeSession(FakeResp(body=b"a" * 3000)), 5)


def test_get_page_utf8():
    s = FakeSession(FakeResp(body="Olá – ok".encode("utf-8")))
    assert site.get_page(s) == "Olá – ok"
    assert s.calls[0][0] == config.PAGE_URL


def test_get_page_errors():
    with pytest.raises(FetchError):
        site.get_page(FakeSession(FakeResp(503, b"")))
    with pytest.raises(FetchError):
        site.get_page(FakeSession(FakeResp(200, b"\xff\xfe\xfa")))


def test_session_user_agent():
    assert site.session().headers["User-Agent"] == config.USER_AGENT
