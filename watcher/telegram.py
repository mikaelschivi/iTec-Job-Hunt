import time

import requests

from watcher import config

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(Exception):
    pass


class TelegramTransient(TelegramError):
    pass


class TelegramBadRequest(TelegramError):
    pass


class TelegramAuth(TelegramError):
    pass


def _post(sess, token, payload):
    url = API_URL.format(token=token)
    try:
        resp = sess.post(
            url,
            json=payload,
            timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT),
        )
        status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            body = {}
    except requests.RequestException as e:
        raise TelegramTransient(type(e).__name__) from None
    if not isinstance(body, dict):
        body = {}
    return status, body


def _description(body):
    desc = body.get("description")
    return desc if isinstance(desc, str) else "no description"


def send(token, chat_id, text, html=True, session=None, sleep=time.sleep):
    sess = session if session is not None else requests
    payload = {
        "chat_id": chat_id,
        "text": text,
        "link_preview_options": {"is_disabled": True},
    }
    if html:
        payload["parse_mode"] = "HTML"

    status, body = _post(sess, token, payload)
    if status == 429:
        params = body.get("parameters")
        wait = params.get("retry_after") if isinstance(params, dict) else None
        if not isinstance(wait, (int, float)) or wait < 0:
            wait = 1
        sleep(min(wait, config.TELEGRAM_RETRY_AFTER_MAX))
        status, body = _post(sess, token, payload)

    if status == 200 and body.get("ok") is True:
        return
    if status == 400:
        params = body.get("parameters")
        if isinstance(params, dict) and "migrate_to_chat_id" in params:
            raise TelegramAuth(f"chat migrated to {params['migrate_to_chat_id']}, update TELEGRAM_CHAT_ID")
        raise TelegramBadRequest(_description(body))
    if status in (401, 403, 404):
        raise TelegramAuth(f"HTTP {status}: {_description(body)}")
    raise TelegramTransient(f"HTTP {status}: {_description(body)}")
