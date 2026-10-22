import os
import re
from dataclasses import dataclass

PAGE_URL = "https://itecfurg.org/?page_id=2695"
REST_URL_TEMPLATE = "https://itecfurg.org/?rest_route=/wp/v2/posts/{id}"
LISTING_URL_TEMPLATE = "https://itecfurg.org/?p={id}"
SITE_HOSTS = ("itecfurg.org", "www.itecfurg.org")

USER_AGENT = "itec-watcher/1.0"
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
MAX_BODY_BYTES = 5 * 1024 * 1024

INTERVAL_SECONDS = 300
JITTER_SECONDS = 15

STATE_PATH = "/data/state.json"
HEARTBEAT_PATH = "/data/heartbeat"

SEED_MIN_LISTINGS = 5
BULK_THRESHOLD = 10
RECENCY_DAYS = 30
FETCH_FAILS_BEFORE_MINIMAL = 3
MAX_SENDS_PER_CYCLE = 5
MAX_FETCHES_PER_CYCLE = 5
SEND_DELAY_SECONDS = 1
ALERT_AFTER_FAILED_CYCLES = 6

TELEGRAM_MAX_CHARS = 4000
TELEGRAM_RETRY_AFTER_MAX = 60

CAP_TITLE = 200
CAP_FIELD = 120
CAP_ITEM = 120
CAP_ITEMS = 6
CAP_INTRO = 300

# status -> (title emoji, label shown in messages)
STATUS = {
    "open": ("\U0001F7E9", "\U0001F7E9 Inscrições abertas"),
    "closed": ("\U0001F7E6", "\U0001F7E6 Inscrições finalizadas / em andamento"),
    "done": ("\U0001F7EA", "\U0001F7EA Resultado disponível"),
}
UNKNOWN_LABEL = "Status desconhecido"

TOKEN_RE = re.compile(r"^\d+:[\w-]{30,}$")
CHAT_ID_RE = re.compile(r"^(-?\d+|@\w{5,})$")
ADMIN_CHAT_ID_RE = re.compile(r"^-?\d+$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Secrets:
    token: str
    chat_id: str
    admin_chat_id: str | None


def load_secrets(env=None):
    if env is None:
        env = os.environ
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = env.get("TELEGRAM_CHAT_ID", "").strip()
    admin = env.get("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if not TOKEN_RE.match(token):
        raise ConfigError("TELEGRAM_BOT_TOKEN is missing or has an invalid format")
    if not CHAT_ID_RE.match(chat_id):
        raise ConfigError("TELEGRAM_CHAT_ID is missing or has an invalid format")
    if admin and not ADMIN_CHAT_ID_RE.match(admin):
        raise ConfigError("TELEGRAM_ADMIN_CHAT_ID has an invalid format")
    return Secrets(token=token, chat_id=chat_id, admin_chat_id=admin or None)
