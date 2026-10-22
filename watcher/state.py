import json
import os

VERSION = 1
STATUSES = {"open", "closed", "done", "unknown"}
DETAILS = {"full", "minimal", "silent"}


class StateError(Exception):
    pass


def empty():
    return {"version": VERSION, "listings": {}}


def entry(title, status, first_seen, notified_at, detail):
    return {
        "title": title,
        "status": status,
        "first_seen": first_seen,
        "notified_at": notified_at,
        "detail": detail,
    }


def _valid_entry(key, value):
    if not (isinstance(key, str) and key.isdigit()):
        return False
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("title"), str):
        return False
    if value.get("status") not in STATUSES:
        return False
    if not isinstance(value.get("first_seen"), str):
        return False
    notified = value.get("notified_at")
    if notified is not None and not isinstance(notified, str):
        return False
    return value.get("detail") in DETAILS


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise StateError(f"cannot read state: {type(e).__name__}") from None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise StateError("state has wrong shape or version")
    listings = data.get("listings")
    if not isinstance(listings, dict):
        raise StateError("state listings is not an object")
    for key, value in listings.items():
        if not _valid_entry(key, value):
            raise StateError(f"state entry {key!r} is invalid")
    return data


def save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
