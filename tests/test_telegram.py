import traceback

import pytest
import requests

from watcher import telegram
from watcher.telegram import TelegramAuth, TelegramBadRequest, TelegramTransient

TOKEN = "123456:FAKE_TOKEN_abcdefghijklmnopqrstuvwxyz"


class Resp:
    def __init__(self, status=200, body=None, bad_json=False):
        self.status_code = status
        self.body = body if body is not None else {}
        self.bad_json = bad_json

    def json(self):
        if self.bad_json:
            raise ValueError("no json")
        return self.body


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def send(session, **kw):
    sleeps = []
    telegram.send(TOKEN, "-1001", "hi", session=session, sleep=sleeps.append, **kw)
    return sleeps


def test_ok_payload_html():
    s = Session(Resp(200, {"ok": True}))
    send(s)
    url, kw = s.calls[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert kw["json"]["parse_mode"] == "HTML"
    assert kw["json"]["link_preview_options"] == {"is_disabled": True}
    assert kw["json"]["chat_id"] == "-1001"


def test_plain_has_no_parse_mode():
    s = Session(Resp(200, {"ok": True}))
    send(s, html=False)
    assert "parse_mode" not in s.calls[0][1]["json"]


def test_400():
    with pytest.raises(TelegramBadRequest) as e:
        send(Session(Resp(400, {"description": "can't parse entities"})))
    assert "can't parse entities" in str(e.value)


@pytest.mark.parametrize("code", [401, 403])
def test_auth(code):
    with pytest.raises(TelegramAuth):
        send(Session(Resp(code, {"description": "Forbidden"})))


@pytest.mark.parametrize("code", [500, 502, 503])
def test_5xx(code):
    with pytest.raises(TelegramTransient):
        send(Session(Resp(code)))


def test_429_retry_then_ok():
    s = Session(Resp(429, {"parameters": {"retry_after": 3}}), Resp(200, {"ok": True}))
    assert send(s) == [3]
    assert len(s.calls) == 2


def test_429_sleep_capped_and_second_429_transient():
    s = Session(Resp(429, {"parameters": {"retry_after": 500}}), Resp(429, {}))
    sleeps = []
    with pytest.raises(TelegramTransient):
        telegram.send(TOKEN, "-1001", "hi", session=s, sleep=sleeps.append)
    assert sleeps == [60]
    assert len(s.calls) == 2


def test_bad_json_body_transient():
    with pytest.raises(TelegramTransient):
        send(Session(Resp(502, bad_json=True)))


def test_connection_error_transient():
    with pytest.raises(TelegramTransient):
        send(Session(requests.ConnectionError("x")))


def test_e14_token_not_leaked_from_exception():
    leaky = requests.ConnectionError(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    )
    with pytest.raises(TelegramTransient) as info:
        send(Session(leaky))
    exc = info.value
    assert TOKEN not in str(exc)
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True
    assert TOKEN not in "".join(traceback.format_exception(exc))


def test_400_chat_migrated_is_auth_error():
    body = {"description": "Bad Request: group chat was upgraded to a supergroup chat",
            "parameters": {"migrate_to_chat_id": -1009876543210}}
    with pytest.raises(TelegramAuth) as e:
        send(Session(Resp(400, body)))
    assert "-1009876543210" in str(e.value)
