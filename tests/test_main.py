import logging
import threading

from watcher import config, main, telegram

TOKEN = "123456789:" + "A" * 35


def test_e14_redacting_formatter_msg_and_traceback():
    fmt = main.RedactingFormatter(TOKEN, "%(levelname)s %(message)s")
    try:
        raise RuntimeError(f"https://api.telegram.org/bot{TOKEN}/sendMessage failed")
    except RuntimeError:
        import sys

        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "t", logging.ERROR, __file__, 1, "oops %s", (TOKEN,), exc_info
    )
    out = fmt.format(record)
    assert TOKEN not in out
    assert "<redacted>" in out
    assert "RuntimeError" in out


def test_redacting_formatter_stack_info():
    fmt = main.RedactingFormatter(TOKEN)
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "m", None, None)
    record.stack_info = f"stack {TOKEN}"
    assert TOKEN not in fmt.format(record)


def run_loop(outcomes, alert):
    stop = threading.Event()
    queue = list(outcomes)

    def run_once():
        item = queue.pop(0)
        if not queue:
            stop.set()
        if isinstance(item, Exception):
            raise item
        return item

    main.loop(run_once, alert, stop, interval=lambda: 0)


def bad(reason="why"):
    return main.CycleResult("failed", reason=reason)


def ok():
    return main.CycleResult("ok")


def test_e25_alert_once_then_recovery():
    alerts = []
    run_loop([bad("r%d" % i) for i in range(8)] + [ok(), ok()], alerts.append)
    assert len(alerts) == 2
    assert alerts[0].startswith("⚠️ itec-watcher: 6 ciclos falhos seguidos")
    assert alerts[0].endswith("r5")
    assert alerts[1] == "✅ itec-watcher recuperado"


def test_no_alert_below_threshold():
    alerts = []
    run_loop([bad()] * 5 + [ok()], alerts.append)
    assert alerts == []


def test_skipped_counts_and_streak_resets():
    alerts = []
    skipped = main.CycleResult("skipped", reason="s")
    run_loop([skipped] * 3 + [ok()] + [skipped] * 5 + [ok()], alerts.append)
    assert alerts == []


def test_loop_survives_exception():
    alerts = []
    run_loop([RuntimeError("x")] * 6 + [ok()], alerts.append)
    assert len(alerts) == 2


def test_make_alert_without_admin_never_sends(monkeypatch):
    called = []
    monkeypatch.setattr(telegram, "send", lambda *a, **k: called.append(a))
    main.make_alert(config.Secrets(TOKEN, "-1001", None))("hi")
    assert called == []


def test_make_alert_swallows_errors(monkeypatch):
    def boom(*a, **k):
        raise telegram.TelegramTransient("down")

    monkeypatch.setattr(telegram, "send", boom)
    main.make_alert(config.Secrets(TOKEN, "-1001", "-5"))("hi")


def test_make_alert_sends_plain(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "send", lambda *a, **k: calls.append((a, k)))
    main.make_alert(config.Secrets(TOKEN, "-1001", "-5"))("hi")
    assert calls[0][0] == (TOKEN, "-5", "hi")
    assert calls[0][1] == {"html": False}
