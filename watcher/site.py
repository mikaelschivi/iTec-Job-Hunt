import json

import requests

from watcher import config

CHUNK = 64 * 1024


class FetchError(Exception):
    pass


def session():
    s = requests.Session()
    s.headers["User-Agent"] = config.USER_AGENT
    return s


def _read_body(resp):
    chunks = []
    total = 0
    for chunk in resp.iter_content(CHUNK):
        total += len(chunk)
        if total > config.MAX_BODY_BYTES:
            raise FetchError("response body too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _get(sess, url, **kwargs):
    timeout = (config.CONNECT_TIMEOUT, config.READ_TIMEOUT)
    try:
        resp = sess.get(url, timeout=timeout, stream=True, **kwargs)
    except requests.RequestException as e:
        raise FetchError(f"request failed: {type(e).__name__}") from None
    try:
        if resp.status_code != 200:
            raise FetchError(f"HTTP {resp.status_code}")
        try:
            return _read_body(resp)
        except requests.RequestException as e:
            raise FetchError(f"read failed: {type(e).__name__}") from None
    finally:
        resp.close()


def get_page(sess):
    body = _get(sess, config.PAGE_URL)
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise FetchError("page is not valid UTF-8") from None


def get_post(sess, post_id):
    post_id = int(post_id)
    url = config.REST_URL_TEMPLATE.format(id=post_id)
    body = _get(sess, url, allow_redirects=False)
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise FetchError("post response is not valid JSON") from None
    if not isinstance(data, dict):
        raise FetchError("post JSON is not an object")
    if data.get("id") != post_id:
        raise FetchError("post id mismatch")
    if data.get("type") != "post":
        raise FetchError("not a post")
    if data.get("status") != "publish":
        raise FetchError("post not published")
    content = data.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("rendered"), str):
        raise FetchError("post has no rendered content")
    if content.get("protected") is True:
        raise FetchError("post is protected")
    return data
