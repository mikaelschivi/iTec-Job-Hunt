import logging
import random
import signal
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from watcher import config, format as fmt, site, state as state_mod, telegram
from watcher.extract import extract
from watcher.scrape import parse_listings

log = logging.getLogger("watcher")


@dataclass
class CycleResult:
    outcome: str
    sent: int = 0
    reason: str = ""


class RedactingFormatter(logging.Formatter):
    def __init__(self, token, pattern=None):
        super().__init__(pattern)
        self.token = token

    def format(self, record):
        text = super().format(record)
        if self.token:
            text = text.replace(self.token, "<redacted>")
        return text


def _write_heartbeat(path, now):
    with open(path, "w", encoding="utf-8") as f:
        f.write(now.isoformat())


def _deliver(send, html_text, plain_text, what):
    # True when the message was accepted, False when Telegram rejected it twice.
    try:
        send(html_text, True)
        return True
    except telegram.TelegramBadRequest as e:
        log.warning("telegram rejected HTML for %s (%s), retrying as plain text", what, e)
    try:
        send(plain_text, False)
        return True
    except telegram.TelegramBadRequest as e:
        log.error("telegram rejected plain text for %s: %s", what, e)
        return False


def run_cycle(
    fetch_page,
    fetch_post,
    send,
    state_path,
    heartbeat_path,
    now,
    fail_count,
    alert,
    stop,
    delay=config.SEND_DELAY_SECONDS,
):
    try:
        listings = parse_listings(fetch_page())
    except site.FetchError as e:
        log.warning("page fetch failed: %s", e)
        return CycleResult("skipped", reason=f"page fetch failed: {e}")
    if not listings:
        log.warning("page parsed to 0 listings")
        return CycleResult("skipped", reason="page has 0 listings")

    try:
        state = state_mod.load(state_path)
    except state_mod.StateError as e:
        log.error("state unreadable: %s", e)
        return CycleResult("failed", reason=f"state unreadable: {e}")

    stamp = now.isoformat()

    if state is None:
        if len(listings) < config.SEED_MIN_LISTINGS:
            log.warning("only %d listings parsed, not seeding", len(listings))
            return CycleResult("skipped", reason="too few listings to seed")
        state = state_mod.empty()
        for l in listings:
            state["listings"][str(l.id)] = state_mod.entry(l.title, l.status, stamp, None, "silent")
        state_mod.save(state_path, state)
        log.info("seeded %d listings: %s", len(listings), sorted(l.id for l in listings))
        alert(f"watcher iniciado, {len(listings)} vagas monitoradas")
        _write_heartbeat(heartbeat_path, now)
        return CycleResult("ok")

    known = state["listings"]
    by_id = {l.id: l for l in listings}
    sends_used = 0
    fetches_used = 0
    sent = 0
    halted = None

    silent = False
    for post_id, l in by_id.items():
        old = known.get(str(post_id))
        if old and old["status"] != l.status and "unknown" in (old["status"], l.status):
            log.info("status of %d changed %s -> %s silently", post_id, old["status"], l.status)
            old["status"] = l.status
            old["title"] = l.title
            silent = True
    if silent:
        state_mod.save(state_path, state)

    new_ids = sorted(i for i in by_id if str(i) not in known)
    if known and len(new_ids) > config.BULK_THRESHOLD:
        log.warning("%d new listings at once", len(new_ids))
        alert(f"⚠️ itec-watcher: {len(new_ids)} vagas novas de uma vez")

    def pause():
        if sends_used > 0:
            stop.wait(delay)

    def can_continue():
        return halted is None and not stop.is_set() and sends_used < config.MAX_SENDS_PER_CYCLE

    try:
        for post_id in new_ids:
            if not can_continue() or fetches_used >= config.MAX_FETCHES_PER_CYCLE:
                break
            l = by_id[post_id]
            fetches_used += 1
            try:
                post = fetch_post(post_id)
            except site.FetchError as e:
                fail_count[post_id] = fail_count.get(post_id, 0) + 1
                log.warning("detail fetch failed for %d (%d): %s", post_id, fail_count[post_id], e)
                if fail_count[post_id] < config.FETCH_FAILS_BEFORE_MINIMAL:
                    continue
                pause()
                sends_used += 1
                ok = _deliver(send, fmt.minimal(l), fmt.minimal(l, html=False), f"minimal {post_id}")
                sent += ok
                known[str(post_id)] = state_mod.entry(
                    l.title, l.status, stamp, stamp if ok else None, "minimal"
                )
                state_mod.save(state_path, state)
                del fail_count[post_id]
                continue

            fail_count.pop(post_id, None)
            summary = extract(post, l)
            cutoff = now - timedelta(days=config.RECENCY_DAYS)
            if summary.published is None or summary.published < cutoff:
                log.info("listing %d is old or undated, recorded silently", post_id)
                known[str(post_id)] = state_mod.entry(l.title, l.status, stamp, None, "silent")
                state_mod.save(state_path, state)
                continue

            pause()
            sends_used += 1
            ok = _deliver(
                send, fmt.new_listing(summary), fmt.new_listing(summary, html=False), f"listing {post_id}"
            )
            sent += ok
            known[str(post_id)] = state_mod.entry(
                l.title, l.status, stamp, stamp if ok else None, "full"
            )
            state_mod.save(state_path, state)

        for post_id in sorted(by_id):
            if not can_continue():
                break
            l = by_id[post_id]
            old = known.get(str(post_id))
            if old is None or old["status"] == l.status:
                continue
            pause()
            sends_used += 1
            ok = _deliver(
                send,
                fmt.status_change(l, old["status"], l.status),
                fmt.status_change(l, old["status"], l.status, html=False),
                f"status change {post_id}",
            )
            sent += ok
            old["status"] = l.status
            old["title"] = l.title
            state_mod.save(state_path, state)
    except telegram.TelegramTransient as e:
        halted = f"telegram unavailable: {e}"
        log.warning("%s", halted)
    except telegram.TelegramAuth as e:
        halted = f"telegram auth error: {e}"
        log.error("%s", halted)

    if halted:
        return CycleResult("failed", sent=sent, reason=halted)
    _write_heartbeat(heartbeat_path, now)
    return CycleResult("ok", sent=sent)


def loop(run_once, alert, stop, interval=None):
    if interval is None:
        interval = lambda: config.INTERVAL_SECONDS + random.uniform(
            -config.JITTER_SECONDS, config.JITTER_SECONDS
        )
    bad_cycles = 0
    alerted = False
    while not stop.is_set():
        try:
            result = run_once()
        except Exception:
            log.exception("cycle crashed")
            result = CycleResult("failed", reason="unexpected error")
        if result.outcome == "ok":
            log.info("cycle ok, %d sent", result.sent)
            if alerted:
                alert("✅ itec-watcher recuperado")
            bad_cycles = 0
            alerted = False
        else:
            bad_cycles += 1
            log.warning("cycle %s (%d in a row): %s", result.outcome, bad_cycles, result.reason)
            if bad_cycles == config.ALERT_AFTER_FAILED_CYCLES:
                alert(
                    f"⚠️ itec-watcher: {bad_cycles} ciclos falhos seguidos — {result.reason}"
                )
                alerted = True
        stop.wait(interval())


def make_alert(secrets):
    def alert(text):
        if not secrets.admin_chat_id:
            log.info("admin alert (no admin chat): %s", text)
            return
        try:
            telegram.send(secrets.token, secrets.admin_chat_id, text, html=False)
        except Exception as e:
            log.warning("admin alert failed: %s", type(e).__name__)

    return alert


def setup_logging(token):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter(token, "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def main():
    try:
        secrets = config.load_secrets()
    except config.ConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    setup_logging(secrets.token)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    sess = site.session()
    fail_count = {}
    alert = make_alert(secrets)

    def send(text, html=True):
        telegram.send(secrets.token, secrets.chat_id, text, html=html)

    def run_once():
        return run_cycle(
            lambda: site.get_page(sess),
            lambda post_id: site.get_post(sess, post_id),
            send,
            config.STATE_PATH,
            config.HEARTBEAT_PATH,
            datetime.now(timezone.utc),
            fail_count,
            alert,
            stop,
        )

    log.info("watcher started")
    loop(run_once, alert, stop)
    log.info("watcher stopped")


if __name__ == "__main__":
    main()
