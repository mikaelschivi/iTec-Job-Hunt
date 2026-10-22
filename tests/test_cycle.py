import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from watcher import main, state, telegram
from watcher.site import FetchError

NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
OPEN, CLOSED, DONE = "🟩 ", "🟦 ", "🟪 "


def page_html(items):
    out = []
    for post_id, prefix, title in items:
        out.append(
            f'<article id="post-{post_id}"><h4 class="entry-title">'
            f'<a href="https://itecfurg.org/?p={post_id}">{prefix}{title}</a></h4></article>'
        )
    return "<html><body>" + "".join(out) + "</body></html>"


def base_items(n=6, prefix=CLOSED):
    return [(i, prefix, f"Edital {i}") for i in range(1, n + 1)]


def post_json(post_id, date=NOW - timedelta(days=1)):
    return {
        "id": post_id,
        "date_gmt": date.strftime("%Y-%m-%dT%H:%M:%S"),
        "content": {
            "rendered": f"<p>2 vagas - Inscrições até 01/12/2026</p><p>Edital {post_id}</p>"
        },
    }


class Env:
    def __init__(self, tmp_path):
        self.state_path = str(tmp_path / "state.json")
        self.heartbeat = str(tmp_path / "heartbeat")
        self.items = base_items()
        self.page_error = None
        self.post_errors = set()
        self.post_dates = {}
        self.send_errors = []
        self.sent = []
        self.alerts = []
        self.fetched = []
        self.fail_count = {}
        self.stop = threading.Event()
        self.on_send = None

    def fetch_page(self):
        if self.page_error:
            raise FetchError(self.page_error)
        return page_html(self.items)

    def fetch_post(self, post_id):
        self.fetched.append(post_id)
        if post_id in self.post_errors:
            raise FetchError("boom")
        return post_json(post_id, self.post_dates.get(post_id, NOW - timedelta(days=1)))

    def send(self, text, html=True):
        if self.send_errors:
            err = self.send_errors.pop(0)
            if err is not None:
                raise err
        self.sent.append((text, html))
        if self.on_send:
            self.on_send()

    def run(self):
        return main.run_cycle(
            self.fetch_page,
            self.fetch_post,
            self.send,
            self.state_path,
            self.heartbeat,
            NOW,
            self.fail_count,
            self.alerts.append,
            self.stop,
            delay=0,
        )

    def seed(self):
        r = self.run()
        assert r.outcome == "ok"
        self.sent.clear()
        self.alerts.clear()

    def load(self):
        return state.load(self.state_path)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_seed_sends_nothing_to_channel(env):
    r = env.run()
    assert r.outcome == "ok" and r.sent == 0
    assert env.sent == []
    s = env.load()
    assert len(s["listings"]) == 6
    assert all(e["detail"] == "silent" and e["notified_at"] is None for e in s["listings"].values())
    assert env.alerts == ["watcher iniciado, 6 vagas monitoradas"]
    assert (env.heartbeat and open(env.heartbeat).read()) == NOW.isoformat()


def test_e4_page_failure_and_zero_listings(env):
    env.page_error = "HTTP 503"
    assert env.run().outcome == "skipped"
    env.page_error = None
    env.items = []
    assert env.run().outcome == "skipped"
    assert env.load() is None


def test_e4_state_untouched_when_page_fails(env):
    env.seed()
    before = open(env.state_path).read()
    env.page_error = "HTTP 500"
    assert env.run().outcome == "skipped"
    assert open(env.state_path).read() == before


def test_e17_degraded_first_fetch_not_seeded(env):
    env.items = base_items(4)
    assert env.run().outcome == "skipped"
    assert env.load() is None


def test_e10_corrupt_state_fails_without_reseed(env):
    open(env.state_path, "w").write("{broken")
    r = env.run()
    assert r.outcome == "failed"
    assert open(env.state_path).read() == "{broken"
    assert env.sent == []


def test_new_listing_sent_and_committed(env):
    env.seed()
    env.items.append((10, OPEN, "Edital 10"))
    r = env.run()
    assert r.outcome == "ok" and r.sent == 1
    text, html = env.sent[0]
    assert html and "Edital 10" in text and "2 vagas" in text
    e = env.load()["listings"]["10"]
    assert e["detail"] == "full" and e["notified_at"] == NOW.isoformat() and e["status"] == "open"
    env.run()
    assert len(env.sent) == 1


def test_e5_transient_leaves_state_and_retries(env):
    env.seed()
    env.items += [(10, OPEN, "A"), (11, OPEN, "B")]
    env.send_errors = [telegram.TelegramTransient("down")]
    r = env.run()
    assert r.outcome == "failed" and env.sent == []
    assert "10" not in env.load()["listings"] and "11" not in env.load()["listings"]
    r = env.run()
    assert r.outcome == "ok" and r.sent == 2
    assert "10" in env.load()["listings"]


def test_e16_auth_fails_cycle(env, caplog):
    env.seed()
    env.items.append((10, OPEN, "A"))
    env.send_errors = [telegram.TelegramAuth("HTTP 403")]
    with caplog.at_level("ERROR"):
        r = env.run()
    assert r.outcome == "failed"
    assert any(rec.levelname == "ERROR" for rec in caplog.records)
    assert "10" not in env.load()["listings"]


def test_e15_bad_request_plain_retry(env):
    env.seed()
    env.items.append((10, OPEN, "A"))
    env.send_errors = [telegram.TelegramBadRequest("can't parse")]
    r = env.run()
    assert r.outcome == "ok" and r.sent == 1
    assert [h for _, h in env.sent] == [False]
    assert "<b>" not in env.sent[0][0]
    assert env.load()["listings"]["10"]["notified_at"] == NOW.isoformat()


def test_e15_two_bad_requests_commit_and_never_loop(env):
    env.seed()
    env.items.append((10, OPEN, "A"))
    env.send_errors = [telegram.TelegramBadRequest("x"), telegram.TelegramBadRequest("y")]
    r = env.run()
    assert r.outcome == "ok" and r.sent == 0
    e = env.load()["listings"]["10"]
    assert e["notified_at"] is None and e["detail"] == "full"
    env.run()
    assert env.sent == []


def test_e6_fetch_failures_then_minimal(env):
    env.seed()
    env.items.append((10, OPEN, "A"))
    env.post_errors = {10}
    for _ in range(2):
        r = env.run()
        assert r.outcome == "ok" and env.sent == []
        assert "10" not in env.load()["listings"]
    assert env.fail_count == {10: 2}
    r = env.run()
    assert r.sent == 1
    assert "(detalhes indisponíveis)" in env.sent[0][0]
    assert env.load()["listings"]["10"]["detail"] == "minimal"
    assert env.fail_count == {}


def test_fetch_success_resets_counter(env):
    env.seed()
    env.items.append((10, OPEN, "A"))
    env.post_errors = {10}
    env.run()
    env.post_errors = set()
    env.run()
    assert env.fail_count == {}
    assert len(env.sent) == 1


def test_e18_old_post_recorded_silently(env):
    env.seed()
    env.items.append((10, OPEN, "A"))
    env.post_dates[10] = NOW - timedelta(days=45)
    r = env.run()
    assert r.sent == 0 and env.sent == []
    e = env.load()["listings"]["10"]
    assert e["detail"] == "silent" and e["notified_at"] is None


def test_status_change_message(env):
    env.seed()
    env.items[0] = (1, OPEN, "Edital 1")
    r = env.run()
    assert r.sent == 1
    text, html = env.sent[0]
    assert text.startswith("🔄") and "→" in text and html
    assert env.load()["listings"]["1"]["status"] == "open"
    env.run()
    assert len(env.sent) == 1


def test_e11_known_to_unknown_silent(env):
    env.seed()
    env.items[0] = (1, "", "Edital 1")
    r = env.run()
    assert r.outcome == "ok" and env.sent == []
    assert env.load()["listings"]["1"]["status"] == "unknown"


def test_e12_unknown_to_known_silent(env):
    env.items[0] = (1, "", "Edital 1")
    env.seed()
    env.items[0] = (1, DONE, "Edital 1")
    r = env.run()
    assert r.outcome == "ok" and env.sent == []
    assert env.load()["listings"]["1"]["status"] == "done"


def test_silent_update_saved_even_when_halted(env):
    env.seed()
    env.items[0] = (1, "", "Edital 1")
    env.items.append((10, OPEN, "A"))
    env.send_errors = [telegram.TelegramTransient("down")]
    assert env.run().outcome == "failed"
    assert env.load()["listings"]["1"]["status"] == "unknown"


def test_e19_bulk_alert_and_recency(env):
    env.seed()
    for i in range(20, 32):
        env.items.append((i, OPEN, f"N{i}"))
    for i in (20, 21):
        env.post_dates[i] = NOW - timedelta(days=90)
    r = env.run()
    assert any("12 vagas novas" in a for a in env.alerts)
    assert len([a for a in env.alerts if "novas" in a]) == 1
    assert r.sent == 3
    assert len(env.fetched) == 5
    s = env.load()["listings"]
    assert s["20"]["detail"] == "silent" and s["21"]["detail"] == "silent"


def test_e26_send_cap_five(env):
    env.seed()
    for i in range(20, 28):
        env.items.append((i, OPEN, f"N{i}"))
    r = env.run()
    assert r.sent == 5 and len(env.sent) == 5
    assert len(env.load()["listings"]) == 6 + 5
    r = env.run()
    assert r.sent == 3
    assert len(env.load()["listings"]) == 6 + 8


def test_e26_fetch_cap_five(env):
    env.seed()
    for i in range(20, 28):
        env.items.append((i, OPEN, f"N{i}"))
        env.post_dates[i] = NOW - timedelta(days=90)
    env.run()
    assert env.fetched == [20, 21, 22, 23, 24]
    env.fetched.clear()
    env.run()
    assert env.fetched == [25, 26, 27]


def test_e26_status_changes_share_send_budget(env):
    env.seed()
    env.items = [(i, OPEN, f"Edital {i}") for i in range(1, 7)]
    env.items += [(20, OPEN, "N"), (21, OPEN, "N")]
    r = env.run()
    assert r.sent == 5
    assert len(env.load()["listings"]) == 8
    r = env.run()
    assert r.sent == 3


def test_e24_stop_after_current_listing(env):
    env.seed()
    for i in range(20, 24):
        env.items.append((i, OPEN, f"N{i}"))
    env.on_send = env.stop.set
    r = env.run()
    assert r.sent == 1
    assert "20" in env.load()["listings"] and "21" not in env.load()["listings"]


def test_new_ids_sent_ascending(env):
    env.seed()
    env.items += [(30, OPEN, "C"), (12, OPEN, "A"), (21, OPEN, "B")]
    env.run()
    order = [t.split("\n")[1] for t, _ in env.sent]
    assert order == ["<b>A</b>", "<b>B</b>", "<b>C</b>"]


def test_empty_state_is_not_seed(env):
    state.save(env.state_path, state.empty())
    r = env.run()
    assert r.outcome == "ok" and r.sent == 5
